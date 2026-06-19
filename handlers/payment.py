"""
handlers/payment.py  —  IrForge فاز ۵
کارت‌به‌کارت  |  درگاه آنلاین  |  مدیریت پرداخت ادمین
"""

import logging
import uuid
from datetime import datetime

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

from models import BotSettings
from utils.db import users_db, settings_db, payments_db, admins_db
from utils.mdv2 import esc, bold, italic, code

logger = logging.getLogger(__name__)
router = Router(name="payment")

# ══════════════════════════════════════════════════════════════════════
#  PAYMENT SETTINGS KEYS  (stored inside BotSettings.payment_info as JSON)
#  We keep a separate flat dict under settings_db key "payment_cfg"
# ══════════════════════════════════════════════════════════════════════

def _load_pay_cfg() -> dict:
    raw = settings_db.read()
    return raw.get("payment_cfg", {
        "card_enabled":    False,
        "card_number":     "",
        "card_owner":      "",
        "gateway_enabled": False,
        "gateway_url":     "",
        "gateway_label":   "💳 پرداخت آنلاین",
        "order_group":     "",
        "verify_required": True,
    })


def _save_pay_cfg(cfg: dict):
    raw = settings_db.read() or {}
    raw["payment_cfg"] = cfg
    settings_db.write(raw)


def _load_settings() -> BotSettings:
    raw = settings_db.read()
    return BotSettings.from_dict(raw) if raw else BotSettings()


def _require_admin(uid: str) -> bool:
    from handlers.admin_auth import _is_admin
    return _is_admin(uid)


# ══════════════════════════════════════════════════════════════════════
#  STATES
# ══════════════════════════════════════════════════════════════════════

class PaymentStates(StatesGroup):
    # Admin config
    set_card_number  = State()
    set_card_owner   = State()
    set_gateway_url  = State()
    set_gateway_label = State()
    set_order_group  = State()
    # User flow
    enter_amount     = State()
    apply_discount   = State()
    upload_receipt   = State()
    # Admin verify
    verify_note      = State()


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════

def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def _tog(v: bool) -> str:
    return "✅" if v else "❌"


def _home_back(back: str = "pay:admin_menu") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=back),
        InlineKeyboardButton(text="🏠 خانه",   callback_data="ap:home"),
    ]


def _new_order_id() -> str:
    return uuid.uuid4().hex[:10].upper()


def _fmt_amount(amount: float, currency: str) -> str:
    return f"{esc(f'{amount:,.0f}')} {esc(currency)}"


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  PAYMENT SETTINGS MENU
# ══════════════════════════════════════════════════════════════════════

async def send_payment_admin_menu(target, edit: bool = True):
    cfg = _load_pay_cfg()
    bs  = _load_settings()
    text = (
        f"{bold('💳 تنظیمات پرداخت')}\n\n"
        f"💳 کارت‌به‌کارت: {_tog(cfg['card_enabled'])}\n"
        f"🏦 شماره کارت: {code(cfg['card_number']) if cfg['card_number'] else italic('تنظیم نشده')}\n"
        f"👤 صاحب کارت: {esc(cfg['card_owner']) if cfg['card_owner'] else italic('تنظیم نشده')}\n\n"
        f"🌐 درگاه آنلاین: {_tog(cfg['gateway_enabled'])}\n"
        f"🔗 آدرس درگاه: {italic(cfg['gateway_url'][:40]) if cfg['gateway_url'] else italic('تنظیم نشده')}\n"
        f"🏷 لیبل دکمه: {esc(cfg['gateway_label'])}\n\n"
        f"📤 گروه سفارشات: {code(cfg['order_group']) if cfg['order_group'] else italic('تنظیم نشده')}\n"
        f"✅ تأیید دستی: {_tog(cfg['verify_required'])}\n"
        f"💰 واحد پول: {esc(bs.currency)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"💳 کارت: {_tog(cfg['card_enabled'])}",    "pay:toggle_card"),
         _btn(f"🌐 درگاه: {_tog(cfg['gateway_enabled'])}", "pay:toggle_gw")],
        [_btn("🔢 شماره کارت",   "pay:set_card_num"),
         _btn("👤 صاحب کارت",   "pay:set_card_owner")],
        [_btn("🔗 آدرس درگاه",  "pay:set_gw_url"),
         _btn("🏷 لیبل درگاه",  "pay:set_gw_label")],
        [_btn("📤 گروه سفارشات", "pay:set_order_group"),
         _btn(f"✅ تأیید دستی: {_tog(cfg['verify_required'])}", "pay:toggle_verify")],
        [_btn("📋 لیست سفارشات", "pay:order_list"),
         _btn("📊 آمار پرداخت",  "pay:pay_stats")],
        _home_back("ap:home"),
    ])
    if edit:
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data == "pay:admin_menu")
async def cb_pay_admin_menu(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.clear()
    await send_payment_admin_menu(call.message)
    await call.answer()


# toggles
@router.callback_query(F.data.in_({"pay:toggle_card", "pay:toggle_gw", "pay:toggle_verify"}))
async def cb_pay_toggles(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    cfg = _load_pay_cfg()
    key = {"pay:toggle_card": "card_enabled",
           "pay:toggle_gw":   "gateway_enabled",
           "pay:toggle_verify": "verify_required"}[call.data]
    cfg[key] = not cfg[key]
    _save_pay_cfg(cfg)
    await send_payment_admin_menu(call.message)
    await call.answer()


# set card number
@router.callback_query(F.data == "pay:set_card_num")
async def cb_set_card_num(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(PaymentStates.set_card_number)
    await call.message.edit_text(
        f"{bold('🔢 شماره کارت جدید')}\n\nشماره ۱۶ رقمی کارت را وارد کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


@router.message(PaymentStates.set_card_number)
async def fsm_set_card_num(message: Message, state: FSMContext):
    num = message.text.replace("-", "").replace(" ", "").strip()
    if not num.isdigit() or len(num) not in (16, 19):
        await message.answer(
            "❌ شماره کارت باید ۱۶ رقم باشد\\.",
            parse_mode="MarkdownV2"
        ); return
    cfg = _load_pay_cfg()
    cfg["card_number"] = num
    _save_pay_cfg(cfg)
    await state.clear()
    await message.answer(
        f"✅ شماره کارت ثبت شد: {code(num)}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 بازگشت به تنظیمات", "pay:admin_menu")]
        ]),
    )


# set card owner
@router.callback_query(F.data == "pay:set_card_owner")
async def cb_set_card_owner(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(PaymentStates.set_card_owner)
    await call.message.edit_text(
        f"{bold('👤 نام صاحب کارت')}\n\nنام دارنده کارت را وارد کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


@router.message(PaymentStates.set_card_owner)
async def fsm_set_card_owner(message: Message, state: FSMContext):
    cfg = _load_pay_cfg()
    cfg["card_owner"] = message.text.strip()
    _save_pay_cfg(cfg)
    await state.clear()
    await message.answer(
        f"✅ نام صاحب کارت ثبت شد: {bold(esc(cfg['card_owner']))}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 بازگشت به تنظیمات", "pay:admin_menu")]
        ]),
    )


# set gateway url
@router.callback_query(F.data == "pay:set_gw_url")
async def cb_set_gw_url(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(PaymentStates.set_gateway_url)
    await call.message.edit_text(
        f"{bold('🔗 آدرس درگاه')}\n\nآدرس URL درگاه پرداخت را وارد کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


@router.message(PaymentStates.set_gateway_url)
async def fsm_set_gw_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if not url.startswith("http"):
        await message.answer("❌ آدرس باید با http شروع شود\\.", parse_mode="MarkdownV2")
        return
    cfg = _load_pay_cfg()
    cfg["gateway_url"] = url
    _save_pay_cfg(cfg)
    await state.clear()
    await message.answer(
        f"✅ آدرس درگاه ثبت شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 بازگشت به تنظیمات", "pay:admin_menu")]
        ]),
    )


# set gateway label
@router.callback_query(F.data == "pay:set_gw_label")
async def cb_set_gw_label(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(PaymentStates.set_gateway_label)
    await call.message.edit_text(
        f"{bold('🏷 لیبل دکمه درگاه')}\n\nمتن دکمه پرداخت آنلاین را وارد کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


@router.message(PaymentStates.set_gateway_label)
async def fsm_set_gw_label(message: Message, state: FSMContext):
    cfg = _load_pay_cfg()
    cfg["gateway_label"] = message.text.strip()
    _save_pay_cfg(cfg)
    await state.clear()
    await message.answer(
        f"✅ لیبل ثبت شد: {bold(esc(cfg['gateway_label']))}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 بازگشت به تنظیمات", "pay:admin_menu")]
        ]),
    )


# set order group
@router.callback_query(F.data == "pay:set_order_group")
async def cb_set_order_group(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(PaymentStates.set_order_group)
    await call.message.edit_text(
        f"{bold('📤 گروه سفارشات')}\n\n"
        "آیدی گروهی که سفارشات به آن ارسال می‌شود را وارد کنید:\n"
        "مثال: `\\-100xxxxxxx`",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


@router.message(PaymentStates.set_order_group)
async def fsm_set_order_group(message: Message, state: FSMContext):
    gid = message.text.strip()
    cfg = _load_pay_cfg()
    cfg["order_group"] = gid
    _save_pay_cfg(cfg)
    await state.clear()
    await message.answer(
        f"✅ گروه سفارشات: {code(gid)}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 بازگشت به تنظیمات", "pay:admin_menu")]
        ]),
    )


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  ORDER LIST
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pay:order_list")
async def cb_order_list(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    all_orders = payments_db.all_items()
    if not all_orders:
        await call.message.edit_text(
            f"{bold('📋 سفارشات')}\n\n{italic('هیچ سفارشی ثبت نشده\\.')}",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
        )
        await call.answer(); return

    rows = []
    for oid, order in list(reversed(all_orders))[:20]:
        status_icon = {"pending": "⏳", "verified": "✅", "rejected": "❌"}.get(
            order.get("status", "pending"), "❓"
        )
        label = f"{status_icon} {order.get('order_id','?')[:8]} — {order.get('amount','?')}"
        rows.append([_btn(label, f"pay:order_detail:{oid}")])
    rows.append(_home_back())
    await call.message.edit_text(
        f"{bold(f'📋 سفارشات ({len(all_orders)})')}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pay:order_detail:"))
async def cb_order_detail(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    oid   = call.data.split(":", 2)[2]
    order = payments_db.get(oid)
    if not order:
        await call.answer("سفارش یافت نشد", show_alert=True); return

    bs     = _load_settings()
    status = order.get("status", "pending")
    status_label = {"pending": "⏳ در انتظار", "verified": "✅ تأیید شده", "rejected": "❌ رد شده"}
    text = (
        f"{bold('📦 جزئیات سفارش')}\n\n"
        f"🆔 شماره سفارش: {code(order.get('order_id',''))}\n"
        f"👤 کاربر: {esc(order.get('username',''))}\n"
        f"💰 مبلغ: {esc('{:,.0f}'.format(order.get('amount', 0)))} {esc(bs.currency)}\n"
        f"🎟 تخفیف: {esc(order.get('discount_code','—'))}\n"
        f"💳 روش: {esc(order.get('method','—'))}\n"
        f"📅 تاریخ: {esc(order.get('created_at','')[:16].replace('T',' '))}\n"
        f"📊 وضعیت: {status_label.get(status,'?')}\n"
    )
    if order.get("note"):
        text += f"\n📝 یادداشت: {esc(order['note'])}\n"

    rows = []
    if status == "pending":
        rows.append([
            _btn("✅ تأیید",    f"pay:verify:{oid}"),
            _btn("❌ رد کردن", f"pay:reject:{oid}"),
        ])
    rows.append([_btn("🔙 بازگشت", "pay:order_list")])

    await call.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pay:verify:"))
async def cb_verify_order(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    oid   = call.data.split(":", 2)[2]
    order = payments_db.get(oid)
    if not order: await call.answer("یافت نشد", show_alert=True); return
    payments_db.update(oid, {
        "status": "verified",
        "verified_by": str(call.from_user.id),
        "verified_at": datetime.utcnow().isoformat(),
    })
    uid = order.get("user_id", "")
    bs  = _load_settings()
    try:
        await bot.send_message(
            int(uid),
            f"✅ {bold('پرداخت شما تأیید شد\\!')}\n\n"
            f"🆔 شماره سفارش: {code(order.get('order_id',''))}\n"
            f"💰 مبلغ: {esc('{:,.0f}'.format(order.get('amount', 0)))} {esc(bs.currency)}",
            parse_mode="MarkdownV2",
        )
    except Exception:
        pass
    await call.answer("✅ سفارش تأیید شد", show_alert=True)
    call.data = f"pay:order_detail:{oid}"
    await cb_order_detail(call, state)


@router.callback_query(F.data.startswith("pay:reject:"))
async def cb_reject_order(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    oid   = call.data.split(":", 2)[2]
    order = payments_db.get(oid)
    if not order: await call.answer("یافت نشد", show_alert=True); return
    payments_db.update(oid, {
        "status": "rejected",
        "rejected_by": str(call.from_user.id),
        "rejected_at": datetime.utcnow().isoformat(),
    })
    uid = order.get("user_id", "")
    bs  = _load_settings()
    try:
        await bot.send_message(
            int(uid),
            f"❌ {bold('پرداخت شما رد شد\\.')}\n\n"
            f"🆔 شماره سفارش: {code(order.get('order_id',''))}\n"
            "در صورت نیاز با پشتیبانی تماس بگیرید\\.",
            parse_mode="MarkdownV2",
        )
    except Exception:
        pass
    await call.answer("❌ سفارش رد شد", show_alert=True)
    call.data = f"pay:order_detail:{oid}"
    await cb_order_detail(call, state)


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  STATS
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pay:pay_stats")
async def cb_pay_stats(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    all_orders = payments_db.all_values()
    total      = len(all_orders)
    verified   = sum(1 for o in all_orders if o.get("status") == "verified")
    pending    = sum(1 for o in all_orders if o.get("status") == "pending")
    rejected   = sum(1 for o in all_orders if o.get("status") == "rejected")
    total_amount = sum(float(o.get("amount", 0)) for o in all_orders if o.get("status") == "verified")
    bs = _load_settings()
    text = (
        f"{bold('📊 آمار پرداخت')}\n\n"
        f"📦 کل سفارشات: {bold(str(total))}\n"
        f"✅ تأیید شده: {bold(str(verified))}\n"
        f"⏳ در انتظار: {bold(str(pending))}\n"
        f"❌ رد شده: {bold(str(rejected))}\n\n"
        f"💰 مجموع تأیید شده: {bold(esc(f'{total_amount:,.0f}'))} {esc(bs.currency)}"
    )
    await call.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  USER  —  START PAYMENT FLOW
# ══════════════════════════════════════════════════════════════════════

async def start_payment(
    message: Message,
    state: FSMContext,
    amount: float = 0.0,
    description: str = "",
    form_data: dict | None = None,
):
    """Entry point called from order/form submit."""
    cfg = _load_pay_cfg()
    bs  = _load_settings()

    if not cfg["card_enabled"] and not cfg["gateway_enabled"]:
        await message.answer(
            f"❌ {bold('درگاه پرداخت فعال نیست\\.')}\n\nلطفاً با پشتیبانی تماس بگیرید\\.",
            parse_mode="MarkdownV2",
        )
        return

    await state.update_data(
        pay_amount=amount,
        pay_description=description,
        pay_form_data=form_data or {},
        pay_discount_code="",
        pay_final_amount=amount,
    )
    await state.set_state(PaymentStates.enter_amount)

    if amount == 0.0:
        # Ask user for amount
        await message.answer(
            f"{bold('💰 مبلغ پرداختی را وارد کنید')} \\({esc(bs.currency)}\\):",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [_btn("❌ انصراف", "pay:cancel")]
            ]),
        )
    else:
        await _show_payment_options(message, state, amount)


async def _show_payment_options(
    target: Message,
    state: FSMContext,
    amount: float,
    edit: bool = False,
):
    cfg  = _load_pay_cfg()
    bs   = _load_settings()
    data = await state.get_data()
    final_amount = data.get("pay_final_amount", amount)
    disc_code    = data.get("pay_discount_code", "")

    amount_str = _fmt_amount(final_amount, bs.currency)
    discount_line = (
        f"\n🎟 تخفیف اعمال شده: {code(esc(disc_code))}\n"
        f"💵 مبلغ اصلی: {_fmt_amount(amount, bs.currency)}\n"
        f"✂️ مبلغ نهایی: {bold(amount_str)}"
        if disc_code else
        f"\n💰 مبلغ: {bold(amount_str)}"
    )

    text = (
        f"{bold('💳 انتخاب روش پرداخت')}\n"
        f"{discount_line}\n\n"
        "روش پرداخت را انتخاب کنید:"
    )

    rows = []
    if cfg["card_enabled"]:
        rows.append([_btn("💳 کارت‌به‌کارت", "pay:method:card")])
    if cfg["gateway_enabled"] and cfg["gateway_url"]:
        rows.append([_url_btn(cfg["gateway_label"], cfg["gateway_url"])])
        rows.append([_btn("✅ پرداخت آنلاین انجام دادم", "pay:method:gateway_done")])
    rows.append([_btn("🎟 کد تخفیف دارم", "pay:use_discount")])
    rows.append([_btn("❌ انصراف", "pay:cancel")])

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if edit:
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


@router.message(PaymentStates.enter_amount)
async def fsm_enter_amount(message: Message, state: FSMContext):
    txt = message.text.replace(",", "").replace("٬", "").strip()
    if not txt.replace(".", "").isdigit():
        await message.answer("❌ مبلغ را به عدد وارد کنید:", parse_mode="MarkdownV2")
        return
    amount = float(txt)
    await state.update_data(pay_amount=amount, pay_final_amount=amount)
    await _show_payment_options(message, state, amount)


# ══════════════════════════════════════════════════════════════════════
#  USER  —  DISCOUNT IN PAYMENT
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pay:use_discount")
async def cb_pay_use_discount(call: CallbackQuery, state: FSMContext):
    await state.set_state(PaymentStates.apply_discount)
    await call.message.edit_text(
        f"{bold('🎟 کد تخفیف')}\n\nکد تخفیف خود را وارد کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("⏭ ادامه بدون تخفیف", "pay:skip_discount")]
        ]),
    )
    await call.answer()


@router.message(PaymentStates.apply_discount)
async def fsm_apply_discount(message: Message, state: FSMContext):
    from models import Discount
    from utils.db import discounts_db

    code_str = message.text.strip().upper()
    result   = discounts_db.find("code", code_str)
    data     = await state.get_data()
    amount   = data.get("pay_amount", 0.0)
    uid      = str(message.from_user.id)

    if not result:
        await message.answer(
            f"❌ کد تخفیف {code(esc(code_str))} معتبر نیست\\.",
            parse_mode="MarkdownV2",
        )
        await _show_payment_options(message, state, amount)
        return

    disc_id, raw_disc = result
    disc = Discount.from_dict(raw_disc)

    if not disc.is_valid():
        await message.answer(
            f"❌ کد تخفیف {code(esc(code_str))} منقضی یا تمام‌شده است\\.",
            parse_mode="MarkdownV2",
        )
        await _show_payment_options(message, state, amount)
        return

    if uid in disc.used_by:
        await message.answer(
            f"❌ شما قبلاً از این کد استفاده کرده‌اید\\.",
            parse_mode="MarkdownV2",
        )
        await _show_payment_options(message, state, amount)
        return

    bs    = _load_settings()

    # باگ ۱ رفع شد: بررسی حداقل مبلغ سفارش قبل از اعمال تخفیف
    if disc.min_order_amount > 0 and amount < disc.min_order_amount:
        await message.answer(
            f"❌ برای استفاده از این کد، حداقل مبلغ سفارش باید "
            f"{bold(_fmt_amount(disc.min_order_amount, bs.currency))} باشد\\.",
            parse_mode="MarkdownV2",
        )
        await _show_payment_options(message, state, amount)
        return

    final = disc.calculate(amount)
    saved = amount - final

    await state.update_data(
        pay_discount_code=code_str,
        pay_discount_id=disc_id,
        pay_final_amount=final,
    )
    await state.set_state(None)

    await message.answer(
        f"✅ کد تخفیف اعمال شد\\!\n\n"
        f"💵 مبلغ اصلی: {_fmt_amount(amount, bs.currency)}\n"
        f"✂️ تخفیف: {_fmt_amount(saved, bs.currency)}\n"
        f"💰 مبلغ نهایی: {bold(_fmt_amount(final, bs.currency))}",
        parse_mode="MarkdownV2",
    )
    await _show_payment_options(message, state, amount)


@router.callback_query(F.data == "pay:skip_discount")
async def cb_skip_discount(call: CallbackQuery, state: FSMContext):
    data   = await state.get_data()
    amount = data.get("pay_amount", 0.0)
    await state.set_state(None)
    await _show_payment_options(call.message, state, amount, edit=True)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  USER  —  CARD-TO-CARD FLOW
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pay:method:card")
async def cb_method_card(call: CallbackQuery, state: FSMContext):
    cfg  = _load_pay_cfg()
    bs   = _load_settings()
    data = await state.get_data()
    final_amount = data.get("pay_final_amount", 0.0)

    card_fmt = " ".join(
        cfg["card_number"][i:i+4] for i in range(0, len(cfg["card_number"]), 4)
    )
    await state.set_state(PaymentStates.upload_receipt)
    await state.update_data(pay_method="card")

    text = (
        f"{bold('💳 کارت‌به‌کارت')}\n\n"
        f"💰 مبلغ: {bold(_fmt_amount(final_amount, bs.currency))}\n\n"
        f"شماره کارت:\n{bold(esc(card_fmt))}\n"
        f"به نام: {bold(esc(cfg['card_owner']))}\n\n"
        f"_پس از واریز، تصویر رسید را ارسال کنید\\._"
    )
    await call.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("❌ انصراف", "pay:cancel")]
        ]),
    )
    await call.answer()


@router.callback_query(F.data == "pay:method:gateway_done")
async def cb_method_gw_done(call: CallbackQuery, state: FSMContext):
    await state.update_data(pay_method="gateway")
    await state.set_state(PaymentStates.upload_receipt)
    await call.message.edit_text(
        f"{bold('✅ پرداخت آنلاین')}\n\n"
        "تصویر یا کد رهگیری پرداخت را ارسال کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("❌ انصراف", "pay:cancel")]
        ]),
    )
    await call.answer()


@router.message(PaymentStates.upload_receipt, F.photo | F.document | F.text)
async def fsm_upload_receipt(message: Message, state: FSMContext, bot: Bot):
    data         = await state.get_data()
    uid          = str(message.from_user.id)
    user         = users_db.get(uid) or {}
    uname        = user.get("username", "") or uid
    amount       = data.get("pay_amount", 0.0)
    final_amount = data.get("pay_final_amount", 0.0)
    disc_code    = data.get("pay_discount_code", "")
    disc_id      = data.get("pay_discount_id", "")
    method       = data.get("pay_method", "card")
    form_data    = data.get("pay_form_data", {})
    description  = data.get("pay_description", "")
    bs           = _load_settings()
    cfg          = _load_pay_cfg()

    # Determine receipt info
    receipt_file_id  = ""
    receipt_text     = ""
    if message.photo:
        receipt_file_id = message.photo[-1].file_id
    elif message.document:
        receipt_file_id = message.document.file_id
    elif message.text:
        receipt_text = message.text

    order_id = _new_order_id()
    now      = datetime.utcnow().isoformat()

    order = {
        "order_id":        order_id,
        "user_id":         uid,
        "username":        "@" + uname if uname else uid,
        "amount":          amount,
        "final_amount":    final_amount,
        "discount_code":   disc_code,
        "method":          method,
        "receipt_file_id": receipt_file_id,
        "receipt_text":    receipt_text,
        "form_data":       form_data,
        "description":     description,
        "status":          "pending",
        "created_at":      now,
    }
    payments_db.set(order_id, order)

    # Mark discount as used
    if disc_id:
        from utils.db import discounts_db
        from models import Discount
        raw_d = discounts_db.get(disc_id)
        if raw_d:
            d = Discount.from_dict(raw_d)
            d.used += 1
            if uid not in d.used_by:
                d.used_by.append(uid)
            discounts_db.set(disc_id, d.to_dict())

    # Save to user orders
    users_db.append_to_list(uid, "orders", {
        "order_id":   order_id,
        "amount":     final_amount,
        "method":     method,
        "status":     "pending",
        "created_at": now,
    })

    # Ack user
    await state.clear()
    await message.answer(
        f"✅ {bold('رسید دریافت شد\\!')}\n\n"
        f"🆔 شماره سفارش: {code(order_id)}\n"
        f"💰 مبلغ: {_fmt_amount(final_amount, bs.currency)}\n"
        f"⏳ وضعیت: در انتظار تأیید",
        parse_mode="MarkdownV2",
    )

    # Send to order group
    order_group = cfg.get("order_group", "")
    if order_group:
        await _send_order_to_group(bot, order_group, order, bs, message, receipt_file_id)

    # Notify admins if no order group
    if not order_group:
        for admin_id, adm in admins_db.all_items():
            if "all" in adm.get("permissions", []) or "orders" in adm.get("permissions", []):
                try:
                    await _send_order_notification(bot, int(admin_id), order, bs)
                except Exception:
                    pass


async def _send_order_to_group(
    bot: Bot, group_id: str, order: dict, bs: BotSettings,
    user_message: Message, receipt_file_id: str,
):
    text = _build_order_report(order, bs)
    try:
        if receipt_file_id:
            await bot.send_photo(
                group_id,
                receipt_file_id,
                caption=text,
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ تأیید",    callback_data=f"pay:verify:{order['order_id']}"),
                     InlineKeyboardButton(text="❌ رد کردن", callback_data=f"pay:reject:{order['order_id']}")],
                ]),
            )
        else:
            if order.get("receipt_text"):
                text += f"\n\n📝 کد رهگیری: {code(esc(order['receipt_text']))}"
            await bot.send_message(
                group_id, text, parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ تأیید",    callback_data=f"pay:verify:{order['order_id']}"),
                     InlineKeyboardButton(text="❌ رد کردن", callback_data=f"pay:reject:{order['order_id']}")],
                ]),
            )
    except Exception as e:
        logger.error("Failed sending order to group %s: %s", group_id, e)


async def _send_order_notification(bot: Bot, admin_id: int, order: dict, bs: BotSettings):
    text = _build_order_report(order, bs)
    await bot.send_message(admin_id, text, parse_mode="MarkdownV2")


def _build_order_report(order: dict, bs: BotSettings) -> str:
    amount_fmt = esc(f"{float(order.get('amount', 0)):,.0f}")
    final_fmt  = esc(f"{float(order.get('final_amount', 0)):,.0f}")
    cur        = esc(bs.currency)
    method_map = {"card": "💳 کارت‌به‌کارت", "gateway": "🌐 درگاه آنلاین"}
    form_lines = ""
    for k, v in order.get("form_data", {}).items():
        if isinstance(v, dict):
            form_lines += f"• {bold(esc(v.get('label', k)))}: {esc(str(v.get('value', '—')))}\n"

    return (
        f"{bold('📦 سفارش جدید')}\n\n"
        f"🆔 شماره: {code(order.get('order_id', ''))}\n"
        f"👤 کاربر: {esc(order.get('username', ''))}\n"
        f"💰 مبلغ: {amount_fmt} {cur}\n"
        f"✂️ نهایی: {bold(final_fmt)} {cur}\n"
        f"🎟 تخفیف: {esc(order.get('discount_code', '—'))}\n"
        f"💳 روش: {esc(method_map.get(order.get('method',''), order.get('method','')))}\n"
        f"📅 تاریخ: {esc(order.get('created_at','')[:16].replace('T',' '))}\n"
        + (f"\n{bold('اطلاعات فرم:')}\n{form_lines}" if form_lines else "")
    )


# ══════════════════════════════════════════════════════════════════════
#  CANCEL
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pay:cancel")
async def cb_pay_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "❌ پرداخت لغو شد\\.",
        parse_mode="MarkdownV2",
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  /pay COMMAND  (shortcut)
# ══════════════════════════════════════════════════════════════════════

@router.message(Command("pay"))
async def cmd_pay(message: Message, state: FSMContext, bot: Bot):
    await start_payment(message, state)
