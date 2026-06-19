"""
handlers/discount.py  —  IrForge فاز ۵
ساخت / مدیریت / اعمال کدهای تخفیف
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from models import Discount, BotSettings
from utils.db import discounts_db, settings_db, admins_db
from utils.mdv2 import esc, bold, italic, code

logger = logging.getLogger(__name__)
router = Router(name="discount")

# ══════════════════════════════════════════════════════════════════════
#  STATES
# ══════════════════════════════════════════════════════════════════════

class DiscountStates(StatesGroup):
    # Admin create
    dc_code        = State()
    dc_type        = State()
    dc_value       = State()
    dc_min_order   = State()
    dc_capacity    = State()
    dc_expiry      = State()
    dc_description = State()
    # User apply
    user_apply     = State()


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════

def _require_admin(uid: str) -> bool:
    from handlers.admin_auth import _is_admin
    return _is_admin(uid)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _tog(v: bool) -> str:
    return "✅" if v else "❌"


def _home_back(back: str = "dc:menu") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=back),
        InlineKeyboardButton(text="🏠 خانه",   callback_data="ap:home"),
    ]


def _load_settings() -> BotSettings:
    raw = settings_db.read()
    return BotSettings.from_dict(raw) if raw else BotSettings()


def _expiry_str(d: Discount) -> str:
    if not d.expiry:
        return italic("بدون انقضا")
    try:
        dt  = datetime.fromisoformat(d.expiry)
        now = datetime.utcnow()
        if dt < now:
            return italic("منقضی شده")
        days = (dt - now).days
        return esc(f"{d.expiry[:10]} ({days} روز مانده)")
    except ValueError:
        return esc(d.expiry[:10])


def _disc_summary(d: Discount) -> str:
    unit = "٪" if d.type == "percent" else _load_settings().currency
    val  = f"{d.value:g} {unit}"
    cap  = f"{d.used}/{d.capacity}" if d.capacity else f"{d.used}/∞"
    act  = _tog(d.is_active and d.is_valid())
    return (
        f"{act} {code(esc(d.code))} — "
        f"{bold(esc(val))} — "
        f"ظرفیت: {esc(cap)}"
    )


async def _notify_admins_expiry(bot: Bot, disc: Discount):
    """Notify admins when a discount code is fully used or expired."""
    text = (
        f"⚠️ {bold('کد تخفیف تمام شد')}\n\n"
        f"کد: {code(esc(disc.code))}\n"
        f"استفاده شده: {bold(str(disc.used))} بار\n"
        f"وضعیت: {esc('منقضی' if not disc.is_valid() else 'تمام ظرفیت')}"
    )
    for admin_id, adm in admins_db.all_items():
        if "all" in adm.get("permissions", []) or "discounts" in adm.get("permissions", []):
            try:
                await bot.send_message(int(admin_id), text, parse_mode="MarkdownV2")
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  MENU
# ══════════════════════════════════════════════════════════════════════

async def send_discount_menu(target, edit: bool = True):
    count  = discounts_db.count()
    active = sum(1 for d in discounts_db.all_values()
                 if Discount.from_dict(d).is_valid())
    text = (
        f"{bold('🎟 مدیریت کدهای تخفیف')}\n\n"
        f"کل کدها: {bold(str(count))}\n"
        f"فعال: {bold(str(active))}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ کد جدید",        "dc:new"),
         _btn("📋 لیست کدها",      "dc:list")],
        [_btn("📊 آمار تخفیف‌ها",  "dc:stats"),
         _btn("🗑 حذف منقضی‌ها",   "dc:purge_expired")],
        _home_back("ap:home"),
    ])
    if edit:
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data == "dc:menu")
async def cb_dc_menu(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.clear()
    await send_discount_menu(call.message)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  CREATE
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "dc:new")
async def cb_dc_new(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.clear()
    await state.set_state(DiscountStates.dc_code)
    await call.message.edit_text(
        f"{bold('➕ کد تخفیف جدید')}\n\n"
        "کد تخفیف دلخواه را وارد کنید \\(حروف بزرگ انگلیسی/عدد\\):\n"
        "مثال: `SUMMER20`",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔀 تولید خودکار", "dc:auto_code")],
            _home_back(),
        ]),
    )
    await call.answer()


@router.callback_query(F.data == "dc:auto_code")
async def cb_auto_code(call: CallbackQuery, state: FSMContext):
    import random, string
    auto = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    await state.update_data(dc_code=auto)
    await state.set_state(DiscountStates.dc_type)
    await _ask_type(call.message, auto, edit=True)
    await call.answer()


@router.message(DiscountStates.dc_code)
async def fsm_dc_code(message: Message, state: FSMContext):
    raw_code = message.text.strip().upper()
    if not raw_code.replace("_", "").replace("-", "").isalnum():
        await message.answer(
            "❌ کد فقط می‌تواند حروف انگلیسی، اعداد، خط تیره یا زیرخط داشته باشد:",
            parse_mode="MarkdownV2",
        ); return
    if discounts_db.find("code", raw_code):
        await message.answer(
            f"❌ کد {code(esc(raw_code))} قبلاً وجود دارد\\. کد دیگری انتخاب کنید:",
            parse_mode="MarkdownV2",
        ); return
    await state.update_data(dc_code=raw_code)
    await state.set_state(DiscountStates.dc_type)
    await _ask_type(message, raw_code)


async def _ask_type(target, code_str: str, edit: bool = False):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 درصدی (٪)",    "dc:type:percent"),
         _btn("💵 مبلغ ثابت",   "dc:type:fixed")],
        _home_back(),
    ])
    txt = f"{bold('نوع تخفیف را انتخاب کنید:')}\n\nکد: {code(esc(code_str))}"
    if edit:
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data.startswith("dc:type:"))
async def cb_dc_type(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    dtype = call.data.split(":")[2]
    await state.update_data(dc_type=dtype)
    await state.set_state(DiscountStates.dc_value)
    bs   = _load_settings()
    hint = (
        "مقدار درصد را وارد کنید \\(مثال: `20` \\= ۲۰٪\\):"
        if dtype == "percent" else
        f"مقدار تخفیف را به {esc(bs.currency)} وارد کنید:"
    )
    text = f"{bold('💰 مقدار تخفیف')}\n\n{hint}"
    kb   = InlineKeyboardMarkup(inline_keyboard=[_home_back()])
    await call.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)


@router.message(DiscountStates.dc_value)
async def fsm_dc_value(message: Message, state: FSMContext):
    txt = message.text.replace(",", "").strip()
    if not txt.replace(".", "").isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2"); return
    val = float(txt)
    data = await state.get_data()
    if data.get("dc_type") == "percent" and val > 100:
        await message.answer("❌ درصد تخفیف نمی‌تواند بیشتر از ۱۰۰ باشد:", parse_mode="MarkdownV2"); return
    await state.update_data(dc_value=val)
    await state.set_state(DiscountStates.dc_min_order)
    await message.answer(
        f"{bold('💵 حداقل مبلغ سفارش')}\n\nحداقل مبلغ سفارش برای استفاده از این کد را وارد کنید:\n"
        "\\(عدد ۰ = بدون محدودیت\\)",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("⏭ بدون محدودیت", "dc:skip_min")]
        ]),
    )


@router.callback_query(F.data == "dc:skip_min")
async def cb_skip_min(call: CallbackQuery, state: FSMContext):
    await state.update_data(dc_min_order=0.0)
    await _ask_capacity(call.message, state, edit=True)
    await call.answer()


@router.message(DiscountStates.dc_min_order)
async def fsm_dc_min_order(message: Message, state: FSMContext):
    txt = message.text.replace(",", "").strip()
    if not txt.replace(".", "").isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2"); return
    await state.update_data(dc_min_order=float(txt))
    await _ask_capacity(message, state)


async def _ask_capacity(target, state: FSMContext, edit: bool = False):
    await state.set_state(DiscountStates.dc_capacity)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("∞ نامحدود", "dc:cap_unlimited")],
        _home_back(),
    ])
    txt = (
        f"{bold('👥 ظرفیت کد تخفیف')}\n\n"
        "حداکثر تعداد دفعات استفاده را وارد کنید:\n"
        "\\(عدد ۰ = نامحدود\\)"
    )
    if edit:
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data == "dc:cap_unlimited")
async def cb_cap_unlimited(call: CallbackQuery, state: FSMContext):
    await state.update_data(dc_capacity=0)
    await _ask_expiry(call.message, state, edit=True)
    await call.answer()


@router.message(DiscountStates.dc_capacity)
async def fsm_dc_capacity(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2"); return
    await state.update_data(dc_capacity=int(message.text))
    await _ask_expiry(message, state)


async def _ask_expiry(target, state: FSMContext, edit: bool = False):
    await state.set_state(DiscountStates.dc_expiry)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("1️⃣ یک روز",    "dc:exp:1"),
         _btn("7️⃣ یک هفته",  "dc:exp:7")],
        [_btn("3️⃣0️⃣ یک ماه",  "dc:exp:30"),
         _btn("∞ بدون انقضا", "dc:exp:0")],
        _home_back(),
    ])
    txt = (
        f"{bold('📅 تاریخ انقضا')}\n\n"
        "تاریخ انقضا را انتخاب یا به صورت `YYYY-MM-DD` وارد کنید:"
    )
    if edit:
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data.startswith("dc:exp:"))
async def cb_dc_exp(call: CallbackQuery, state: FSMContext):
    days = int(call.data.split(":")[2])
    if days == 0:
        expiry = None
    else:
        expiry = (datetime.utcnow() + timedelta(days=days)).isoformat()
    await state.update_data(dc_expiry=expiry)
    await state.set_state(DiscountStates.dc_description)
    await call.message.edit_text(
        f"{bold('📝 توضیحات \\(اختیاری\\)')}\n\nتوضیحی برای این کد وارد کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("⏭ بدون توضیحات", "dc:skip_desc")],
            _home_back(),
        ]),
    )
    await call.answer()


@router.message(DiscountStates.dc_expiry)
async def fsm_dc_expiry_manual(message: Message, state: FSMContext):
    txt = message.text.strip()
    try:
        dt = datetime.strptime(txt, "%Y-%m-%d")
        expiry = dt.isoformat()
    except ValueError:
        await message.answer(
            "❌ فرمت اشتباه\\. مثال: `2025-12-31`", parse_mode="MarkdownV2"
        ); return
    await state.update_data(dc_expiry=expiry)
    await state.set_state(DiscountStates.dc_description)
    await message.answer(
        f"{bold('📝 توضیحات \\(اختیاری\\)')}\n\nتوضیحی برای این کد وارد کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("⏭ بدون توضیحات", "dc:skip_desc")]
        ]),
    )


@router.callback_query(F.data == "dc:skip_desc")
async def cb_skip_desc(call: CallbackQuery, state: FSMContext):
    await state.update_data(dc_description="")
    await _finalize_discount(call, state)
    await call.answer()


@router.message(DiscountStates.dc_description)
async def fsm_dc_description(message: Message, state: FSMContext):
    await state.update_data(dc_description=message.text.strip())
    await _finalize_discount(message, state, is_msg=True)


async def _finalize_discount(target, state: FSMContext, is_msg: bool = False):
    data = await state.get_data()
    disc = Discount(
        code=data.get("dc_code", ""),
        type=data.get("dc_type", "percent"),
        value=data.get("dc_value", 0.0),
        min_order_amount=data.get("dc_min_order", 0.0),
        capacity=data.get("dc_capacity", 0),
        expiry=data.get("dc_expiry"),
        description=data.get("dc_description", ""),
    )
    discounts_db.set(disc.id, disc.to_dict())
    await state.clear()

    bs   = _load_settings()
    unit = "٪" if disc.type == "percent" else esc(bs.currency)
    text = (
        f"✅ {bold('کد تخفیف ساخته شد\\!')}\n\n"
        f"🎟 کد: {code(esc(disc.code))}\n"
        f"💰 مقدار: {bold(esc(f'{disc.value:g}'))} {unit}\n"
        f"👥 ظرفیت: {bold(str(disc.capacity) if disc.capacity else 'نامحدود')}\n"
        f"📅 انقضا: {_expiry_str(disc)}\n"
        f"💵 حداقل خرید: {esc(f'{disc.min_order_amount:g}') if disc.min_order_amount else italic('ندارد')}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ کد جدید",      "dc:new"),
         _btn("📋 لیست کدها",    "dc:list")],
        _home_back(),
    ])
    if is_msg:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  LIST
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "dc:list")
async def cb_dc_list(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    all_discs = discounts_db.all_items()
    if not all_discs:
        await call.message.edit_text(
            "📭 هیچ کد تخفیفی ثبت نشده\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [_btn("➕ کد جدید", "dc:new")], _home_back()
            ]),
        )
        await call.answer(); return

    rows = []
    for did, raw in all_discs[:20]:
        d = Discount.from_dict(raw)
        status_icon = "✅" if d.is_valid() else "⛔"
        rows.append([_btn(f"{status_icon} {d.code} — {d.value:g}{'٪' if d.type=='percent' else ''}",
                          f"dc:detail:{did}")])
    rows.append(_home_back())
    await call.message.edit_text(
        f"{bold(f'🎟 کدهای تخفیف ({len(all_discs)})')}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  DETAIL
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("dc:detail:"))
async def cb_dc_detail(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    did  = call.data.split(":", 2)[2]
    raw  = discounts_db.get(did)
    if not raw: await call.answer("یافت نشد", show_alert=True); return
    d    = Discount.from_dict(raw)
    bs   = _load_settings()
    unit = "٪" if d.type == "percent" else esc(bs.currency)
    text = (
        f"{bold('🎟 جزئیات کد تخفیف')}\n\n"
        f"🔤 کد: {code(esc(d.code))}\n"
        f"💰 مقدار: {bold(esc(f'{d.value:g}'))} {unit}\n"
        f"💵 حداقل خرید: {esc(f'{d.min_order_amount:g}') if d.min_order_amount else italic('ندارد')}\n"
        f"👥 ظرفیت: {esc(str(d.capacity)) if d.capacity else italic('نامحدود')}\n"
        f"✅ استفاده شده: {bold(str(d.used))} بار\n"
        f"📅 انقضا: {_expiry_str(d)}\n"
        f"🔄 فعال: {_tog(d.is_active)}\n"
        f"✅ معتبر: {_tog(d.is_valid())}\n"
        + (f"📝 توضیح: {esc(d.description)}\n" if d.description else "")
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"{'⛔ غیرفعال' if d.is_active else '✅ فعال'}", f"dc:toggle:{did}"),
         _btn("🗑 حذف", f"dc:delete:{did}")],
        _home_back("dc:list"),
    ])
    await call.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("dc:toggle:"))
async def cb_dc_toggle(call: CallbackQuery, state: FSMContext):
    did = call.data.split(":", 2)[2]
    raw = discounts_db.get(did)
    if not raw: await call.answer("یافت نشد", show_alert=True); return
    d = Discount.from_dict(raw)
    d.is_active = not d.is_active
    discounts_db.set(did, d.to_dict())
    await call.answer(f"{'✅ فعال' if d.is_active else '⛔ غیرفعال'} شد")
    call.data = f"dc:detail:{did}"
    await cb_dc_detail(call, state)


@router.callback_query(F.data.startswith("dc:delete:"))
async def cb_dc_delete(call: CallbackQuery, state: FSMContext):
    did = call.data.split(":", 2)[2]
    raw = discounts_db.get(did)
    if not raw: await call.answer("یافت نشد", show_alert=True); return
    d = Discount.from_dict(raw)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🗑 بله، حذف شود",  f"dc:del_yes:{did}"),
         _btn("❌ انصراف",         f"dc:detail:{did}")],
    ])
    await call.message.edit_text(
        f"⚠️ آیا از حذف کد {code(esc(d.code))} مطمئنید؟",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data.startswith("dc:del_yes:"))
async def cb_dc_del_yes(call: CallbackQuery, state: FSMContext):
    did = call.data.split(":", 2)[2]
    discounts_db.delete(did)
    await call.message.edit_text(
        "🗑 کد تخفیف حذف شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("📋 لیست کدها", "dc:list"), _btn("🏠 خانه", "ap:home")]
        ]),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  STATS
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "dc:stats")
async def cb_dc_stats(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    all_discs = discounts_db.all_values()
    total     = len(all_discs)
    active    = sum(1 for d in all_discs if Discount.from_dict(d).is_valid())
    expired   = sum(1 for d in all_discs if not Discount.from_dict(d).is_valid())
    total_uses = sum(d.get("used", 0) for d in all_discs)
    top_used  = sorted(all_discs, key=lambda d: d.get("used", 0), reverse=True)[:5]

    lines = [
        bold("📊 آمار کدهای تخفیف"), "",
        f"🎟 کل کدها: {bold(str(total))}",
        f"✅ فعال: {bold(str(active))}",
        f"⛔ منقضی/غیرفعال: {bold(str(expired))}",
        f"🔢 کل استفاده: {bold(str(total_uses))}",
        "",
        bold("🏆 پرمصرف‌ترین کدها:"),
    ]
    for d_raw in top_used:
        d = Discount.from_dict(d_raw)
        lines.append(f"• {code(esc(d.code))} — {bold(str(d.used))} بار")

    await call.message.edit_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  PURGE EXPIRED
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "dc:purge_expired")
async def cb_purge_expired(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    deleted = 0
    for did, raw in discounts_db.all_items():
        d = Discount.from_dict(raw)
        if not d.is_valid() and d.used > 0:
            discounts_db.delete(did)
            deleted += 1
    await call.answer(f"🗑 {deleted} کد منقضی حذف شد", show_alert=True)
    await send_discount_menu(call.message)


# ══════════════════════════════════════════════════════════════════════
#  USER  —  APPLY DISCOUNT  (/discount command)
# ══════════════════════════════════════════════════════════════════════

@router.message(Command("discount"))
async def cmd_discount(message: Message, state: FSMContext):
    await state.set_state(DiscountStates.user_apply)
    await message.answer(
        f"{bold('🎟 اعمال کد تخفیف')}\n\nکد تخفیف خود را وارد کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ انصراف", callback_data="dc:user_cancel")]
        ]),
    )


@router.message(DiscountStates.user_apply)
async def fsm_user_apply(message: Message, state: FSMContext, bot: Bot):
    code_str = message.text.strip().upper()
    uid      = str(message.from_user.id)
    result   = discounts_db.find("code", code_str)

    if not result:
        await message.answer(
            f"❌ کد {code(esc(code_str))} معتبر نیست\\.",
            parse_mode="MarkdownV2",
        )
        await state.clear(); return

    disc_id, raw_disc = result
    d  = Discount.from_dict(raw_disc)
    bs = _load_settings()

    if not d.is_valid():
        # Check if just expired or capacity full — notify admins
        await _notify_admins_expiry(bot, d)
        await message.answer(
            f"❌ کد {code(esc(code_str))} منقضی یا تمام‌شده است\\.",
            parse_mode="MarkdownV2",
        )
        await state.clear(); return

    if uid in d.used_by:
        await message.answer(
            "❌ شما قبلاً از این کد استفاده کرده‌اید\\.",
            parse_mode="MarkdownV2",
        )
        await state.clear(); return

    unit = "٪" if d.type == "percent" else esc(bs.currency)
    remaining = (d.capacity - d.used) if d.capacity else None

    await state.clear()
    await message.answer(
        f"✅ {bold('کد تخفیف معتبر است\\!')}\n\n"
        f"🎟 کد: {code(esc(d.code))}\n"
        f"💰 تخفیف: {bold(esc(f'{d.value:g}'))} {unit}\n"
        + (f"💵 حداقل خرید: {esc(f'{d.min_order_amount:g}')} {esc(bs.currency)}\n"
           if d.min_order_amount else "")
        + (f"👥 ظرفیت باقی: {bold(str(remaining))}\n" if remaining is not None else "")
        + f"\n_این کد را هنگام پرداخت در بخش کد تخفیف وارد کنید\\._",
        parse_mode="MarkdownV2",
    )


@router.callback_query(F.data == "dc:user_cancel")

async def cb_dc_user_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ لغو شد\\.", parse_mode="MarkdownV2")
    await call.answer()

#  COMMAND
# ══════════════════════════════════════════════════════════════════════

@router.message(Command("discounts"))
async def cmd_discounts(message: Message, state: FSMContext):
    if not _require_admin(str(message.from_user.id)):
        return
    await send_discount_menu(message, edit=False)