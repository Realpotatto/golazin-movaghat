"""
handlers/referral.py  —  IrForge فاز ۵
سیستم رفرال: لینک اختصاصی + آمار ادمین + روشن/خاموش
"""

import logging
from datetime import datetime

from aiogram import Bot, Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from models import BotSettings, User
from utils.db import users_db, settings_db, referrals_db
from utils.mdv2 import esc, bold, italic, code

logger = logging.getLogger(__name__)
router = Router(name="referral")

# ══════════════════════════════════════════════════════════════════════
#  REFERRAL CONFIG — stored under settings_db["referral_cfg"]
# ══════════════════════════════════════════════════════════════════════

def _load_ref_cfg() -> dict:
    raw = settings_db.read()
    return raw.get("referral_cfg", {
        "enabled": False,
        "reward_referrer": 0,       # reward points/amount for referrer (0 = disabled)
        "reward_new_user": 0,       # reward for newly referred user
        "reward_currency": "امتیاز",
    })


def _save_ref_cfg(cfg: dict):
    raw = settings_db.read() or {}
    raw["referral_cfg"] = cfg
    settings_db.write(raw)


def _load_settings() -> BotSettings:
    raw = settings_db.read()
    return BotSettings.from_dict(raw) if raw else BotSettings()


def _require_admin(uid: str) -> bool:
    from handlers.admin_auth import _is_admin
    return _is_admin(uid)


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════

def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _tog(v: bool) -> str:
    return "✅" if v else "❌"


def _home_back(back: str = "ref:admin_menu") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=back),
        InlineKeyboardButton(text="🏠 خانه",   callback_data="ap:home"),
    ]


def _ref_link(bot_username: str, uid: str) -> str:
    return f"https://t.me/{bot_username}?start=ref_{uid}"


def _get_referral_stats(uid: str) -> dict:
    """Return referral stats for a given user."""
    raw = referrals_db.get(uid)
    return raw or {"uid": uid, "referrals": [], "total": 0, "reward_given": 0}


# ══════════════════════════════════════════════════════════════════════
#  /start DEEP LINK HANDLER  (ref_XXXX)
# This is called from user.py's cmd_start when payload starts with ref_
# ══════════════════════════════════════════════════════════════════════

async def handle_referral_start(
    message: Message,
    new_uid: str,
    referrer_uid: str,
    bot: Bot,
):
    """Called when a new user joins via referral link."""
    cfg = _load_ref_cfg()
    if not cfg.get("enabled", False):
        return

    if new_uid == referrer_uid:
        return  # can't refer yourself

    # Check if already referred
    user = users_db.get(new_uid)
    if user and user.get("referral_by"):
        return  # already has a referrer

    # Mark referral_by on new user
    users_db.update(new_uid, {
        "referral_by": referrer_uid,
        "referral_at": datetime.utcnow().isoformat(),
    })

    # Update referrer stats
    ref_stats = _get_referral_stats(referrer_uid)
    if new_uid not in ref_stats["referrals"]:
        ref_stats["referrals"].append(new_uid)
        ref_stats["total"] = len(ref_stats["referrals"])
    referrals_db.set(referrer_uid, ref_stats)

    # Notify referrer
    referrer = users_db.get(referrer_uid)
    if referrer:
        new_user = users_db.get(new_uid)
        new_name = new_user.get("first_name", new_uid) if new_user else new_uid
        total    = ref_stats["total"]
        try:
            await bot.send_message(
                int(referrer_uid),
                f"🎉 {bold('کاربر جدید از طریق لینک شما وارد شد\\!')}\n\n"
                f"👤 کاربر: {bold(esc(new_name))}\n"
                f"👥 مجموع دعوت‌شده‌های شما: {bold(str(total))}",
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass

    # Give reward if configured
    reward = cfg.get("reward_referrer", 0)
    if reward:
        cur      = esc(cfg.get("reward_currency", "امتیاز"))
        ref_data = referrals_db.get(referrer_uid) or {}
        ref_data["reward_given"] = ref_data.get("reward_given", 0) + reward
        referrals_db.set(referrer_uid, ref_data)
        try:
            await bot.send_message(
                int(referrer_uid),
                f"🎁 {bold(esc(str(reward)))} {cur} به حساب شما اضافه شد\\!",
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass

    # Reward new user
    reward_new = cfg.get("reward_new_user", 0)
    if reward_new:
        cur = esc(cfg.get("reward_currency", "امتیاز"))
        try:
            await bot.send_message(
                int(new_uid),
                f"🎁 چون از لینک دعوت وارد شدی، {bold(esc(str(reward_new)))} {cur} هدیه گرفتی\\!",
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
#  USER  —  MY REFERRAL LINK
# ══════════════════════════════════════════════════════════════════════

@router.message(Command("referral"))
@router.message(Command("invite"))
async def cmd_referral(message: Message, state: FSMContext, bot: Bot):
    cfg = _load_ref_cfg()
    uid = str(message.from_user.id)

    if not cfg.get("enabled", False):
        await message.answer(
            "❌ سیستم دعوت در حال حاضر فعال نیست\\.",
            parse_mode="MarkdownV2",
        )
        return

    me         = await bot.get_me()
    link       = _ref_link(me.username, uid)
    stats      = _get_referral_stats(uid)
    total      = stats.get("total", 0)
    reward     = cfg.get("reward_referrer", 0)
    cur        = esc(cfg.get("reward_currency", "امتیاز"))

    reward_line = (
        f"\n🎁 پاداش هر دعوت: {bold(esc(str(reward)))} {cur}"
        if reward else ""
    )

    text = (
        f"{bold('🔗 لینک دعوت اختصاصی شما')}\n\n"
        f"`{esc(link)}`\n\n"
        f"👥 تعداد دعوت‌شده‌ها: {bold(str(total))}"
        f"{reward_line}\n\n"
        "_این لینک را با دوستان خود به اشتراک بگذارید\\._"
    )
    await message.answer(
        text,
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 اشتراک‌گذاری", switch_inline_query=link)],
            [_btn("📊 آمار دعوت‌های من", "ref:my_stats")],
        ]),
    )


@router.callback_query(F.data == "ref:my_stats")
async def cb_my_stats(call: CallbackQuery, state: FSMContext, bot: Bot):
    uid    = str(call.from_user.id)
    cfg    = _load_ref_cfg()
    stats  = _get_referral_stats(uid)
    total  = stats.get("total", 0)
    reward = stats.get("reward_given", 0)
    cur    = esc(cfg.get("reward_currency", "امتیاز"))

    referral_list = stats.get("referrals", [])
    lines = [f"{bold('📊 آمار دعوت‌های من')}", ""]
    lines.append(f"👥 کل دعوت‌شده: {bold(str(total))}")
    if reward:
        lines.append(f"🎁 پاداش دریافت‌شده: {bold(esc(str(reward)))} {cur}")

    if referral_list:
        lines.append("")
        lines.append(bold("آخرین ۵ نفر:"))
        for ruid in referral_list[-5:]:
            ruser = users_db.get(ruid)
            if ruser:
                rname = ruser.get("first_name", "") or ruser.get("username", ruid)
                lines.append(f"• {esc(rname)}")

    await call.message.edit_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 بازگشت", "ref:back_to_link")]
        ]),
    )
    await call.answer()


@router.callback_query(F.data == "ref:back_to_link")
async def cb_ref_back_to_link(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.message.delete()
    await cmd_referral(call.message, state, bot)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  REFERRAL SETTINGS MENU
# ══════════════════════════════════════════════════════════════════════

async def send_referral_admin_menu(target, edit: bool = True):
    cfg = _load_ref_cfg()
    text = (
        f"{bold('🔗 تنظیمات سیستم دعوت')}\n\n"
        f"📢 فعال: {_tog(cfg['enabled'])}\n"
        f"🎁 پاداش دعوت‌کننده: {bold(esc(str(cfg['reward_referrer'])))} {esc(cfg['reward_currency'])}\n"
        f"🎁 پاداش کاربر جدید: {bold(esc(str(cfg['reward_new_user'])))} {esc(cfg['reward_currency'])}\n"
        f"💱 واحد پاداش: {esc(cfg['reward_currency'])}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"📢 فعال: {_tog(cfg['enabled'])}",         "ref:toggle"),
         _btn("🎁 پاداش دعوت‌کننده",                      "ref:set_reward_ref")],
        [_btn("🎁 پاداش کاربر جدید",                      "ref:set_reward_new"),
         _btn("💱 واحد پاداش",                            "ref:set_currency")],
        [_btn("📊 آمار کلی دعوت‌ها",                      "ref:global_stats"),
         _btn("🏆 برترین دعوت‌کنندگان",                   "ref:top_referrers")],
        [_btn("📋 لیست رفرال‌ها",                          "ref:all_list")],
        _home_back("ap:home"),
    ])
    if edit:
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data == "ref:admin_menu")
async def cb_ref_admin_menu(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await send_referral_admin_menu(call.message)
    await call.answer()


@router.callback_query(F.data == "ref:toggle")
async def cb_ref_toggle(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    cfg = _load_ref_cfg()
    cfg["enabled"] = not cfg["enabled"]
    _save_ref_cfg(cfg)
    await send_referral_admin_menu(call.message)
    await call.answer(f"{'✅ فعال' if cfg['enabled'] else '❌ غیرفعال'} شد")


# ── reward settings (reuse a simple FSM state via state.update_data) ──

class _RefStates:
    class Set:
        reward_ref  = "ref:set_reward_ref"
        reward_new  = "ref:set_reward_new"
        currency    = "ref:set_currency"


from aiogram.fsm.state import StatesGroup as _SG, State as _S

class RefAdminStates(_SG):
    set_reward_ref = _S()
    set_reward_new = _S()
    set_currency   = _S()


@router.callback_query(F.data == "ref:set_reward_ref")
async def cb_set_reward_ref(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(RefAdminStates.set_reward_ref)
    await call.message.edit_text(
        f"{bold('🎁 پاداش دعوت‌کننده')}\n\nمقدار پاداش برای هر دعوت موفق را وارد کنید \\(0 = غیرفعال\\):",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


@router.message(RefAdminStates.set_reward_ref)
async def fsm_set_reward_ref(message: Message, state: FSMContext):
    if not message.text.replace(".", "").isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2"); return
    cfg = _load_ref_cfg()
    cfg["reward_referrer"] = float(message.text)
    _save_ref_cfg(cfg)
    await state.clear()
    await message.answer(
        f"✅ پاداش دعوت‌کننده: {bold(esc(message.text))} {esc(cfg['reward_currency'])}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 بازگشت به تنظیمات", "ref:admin_menu")]
        ]),
    )


@router.callback_query(F.data == "ref:set_reward_new")
async def cb_set_reward_new(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(RefAdminStates.set_reward_new)
    await call.message.edit_text(
        f"{bold('🎁 پاداش کاربر جدید')}\n\nمقدار پاداش برای کاربر تازه‌وارد را وارد کنید \\(0 = غیرفعال\\):",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


@router.message(RefAdminStates.set_reward_new)
async def fsm_set_reward_new(message: Message, state: FSMContext):
    if not message.text.replace(".", "").isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2"); return
    cfg = _load_ref_cfg()
    cfg["reward_new_user"] = float(message.text)
    _save_ref_cfg(cfg)
    await state.clear()
    await message.answer(
        f"✅ پاداش کاربر جدید: {bold(esc(message.text))} {esc(cfg['reward_currency'])}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 بازگشت به تنظیمات", "ref:admin_menu")]
        ]),
    )


@router.callback_query(F.data == "ref:set_currency")
async def cb_set_currency(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(RefAdminStates.set_currency)
    await call.message.edit_text(
        f"{bold('💱 واحد پاداش')}\n\nواحد پاداش را وارد کنید:\nمثال: `امتیاز` یا `تومان`",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


@router.message(RefAdminStates.set_currency)
async def fsm_set_currency(message: Message, state: FSMContext):
    cfg = _load_ref_cfg()
    cfg["reward_currency"] = message.text.strip()
    _save_ref_cfg(cfg)
    await state.clear()
    await message.answer(
        f"✅ واحد پاداش: {bold(esc(cfg['reward_currency']))}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 بازگشت به تنظیمات", "ref:admin_menu")]
        ]),
    )


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  GLOBAL STATS
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "ref:global_stats")
async def cb_global_stats(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return

    all_ref    = referrals_db.all_values()
    total_refs = sum(r.get("total", 0) for r in all_ref)
    active_ref = len([r for r in all_ref if r.get("total", 0) > 0])
    cfg        = _load_ref_cfg()

    # Users who were referred
    all_users    = users_db.all_values()
    referred_cnt = sum(1 for u in all_users if u.get("referral_by"))

    text = (
        f"{bold('📊 آمار کلی سیستم دعوت')}\n\n"
        f"👤 کاربران دعوت‌کننده: {bold(str(active_ref))}\n"
        f"👥 کاربران دعوت‌شده: {bold(str(referred_cnt))}\n"
        f"🔗 کل دعوت‌های ثبت‌شده: {bold(str(total_refs))}\n"
        f"📢 وضعیت سیستم: {_tog(cfg['enabled'])}"
    )
    await call.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  TOP REFERRERS
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "ref:top_referrers")
async def cb_top_referrers(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return

    all_ref = referrals_db.all_items()
    sorted_ref = sorted(all_ref, key=lambda x: x[1].get("total", 0), reverse=True)[:10]

    if not sorted_ref:
        await call.answer("هنوز رفرالی ثبت نشده", show_alert=True); return

    lines = [bold("🏆 برترین دعوت‌کنندگان"), ""]
    for rank, (uid, ref_data) in enumerate(sorted_ref, 1):
        user  = users_db.get(uid)
        uname = ""
        if user:
            uname = user.get("username") or user.get("first_name") or uid
        total = ref_data.get("total", 0)
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}\\.")
        lines.append(f"{medal} {esc(uname)} — {bold(str(total))} نفر")

    await call.message.edit_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()]),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  ADMIN  —  ALL REFERRAL LIST
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "ref:all_list")
async def cb_all_list(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return

    all_ref = referrals_db.all_items()
    if not all_ref:
        await call.answer("هیچ رفرالی ثبت نشده", show_alert=True); return

    rows = []
    for uid, ref_data in sorted(all_ref, key=lambda x: x[1].get("total", 0), reverse=True)[:20]:
        user  = users_db.get(uid)
        uname = (user.get("username") or user.get("first_name") or uid) if user else uid
        total = ref_data.get("total", 0)
        rows.append([_btn(f"👤 {uname[:25]} — {total} نفر", f"ref:user_detail:{uid}")])

    rows.append(_home_back())
    await call.message.edit_text(
        f"{bold('📋 لیست رفرال‌ها')}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


@router.callback_query(F.data.startswith("ref:user_detail:"))
async def cb_ref_user_detail(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return

    uid      = call.data.split(":", 2)[2]
    user     = users_db.get(uid)
    ref_data = referrals_db.get(uid) or {}
    cfg      = _load_ref_cfg()

    uname  = ""
    if user:
        uname = "@" + user.get("username") if user.get("username") else user.get("first_name", uid)
    total   = ref_data.get("total", 0)
    reward  = ref_data.get("reward_given", 0)
    cur     = esc(cfg.get("reward_currency", "امتیاز"))

    referral_uids = ref_data.get("referrals", [])
    ref_lines = []
    for ruid in referral_uids[-10:]:
        ru = users_db.get(ruid)
        if ru:
            rn = ru.get("first_name") or ru.get("username") or ruid
            rd = ru.get("referral_at", "")[:10]
            ref_lines.append(f"• {esc(rn)} — {esc(rd)}")

    text = (
        f"{bold('👤 جزئیات رفرال')}\n\n"
        f"کاربر: {bold(esc(uname))}\n"
        f"👥 کل دعوت: {bold(str(total))}\n"
        f"🎁 پاداش داده‌شده: {bold(esc(str(reward)))} {cur}\n"
        + (f"\n{bold('آخرین دعوت‌شده‌ها:')}\n" + "\n".join(ref_lines) if ref_lines else "")
    )
    await call.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back("ref:all_list")]),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  COMMAND
# ══════════════════════════════════════════════════════════════════════

@router.message(Command("refstats"))
async def cmd_refstats(message: Message, state: FSMContext):
    if not _require_admin(str(message.from_user.id)):
        return
    await send_referral_admin_menu(message, edit=False)
