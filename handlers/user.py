"""
handlers/user.py
تمام کامندها و middleware کاربر — IrForge فاز ۴
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

from models import User, BotSettings
from utils.db import users_db, settings_db, panels_db
from utils.mdv2 import esc, bold, italic, code

logger = logging.getLogger(__name__)
router = Router(name="user")

# ══════════════════════════════════════════════════════════════════════
#  STATES
# ══════════════════════════════════════════════════════════════════════

class UserStates(StatesGroup):
    edit_first_name  = State()
    edit_last_name   = State()
    edit_phone       = State()
    panel_password   = State()   # باگ ۵: state اختصاصی برای رمز پنل
    sell_receipt     = State()   # انتظار رسید از کاربر در پنل فروش


# ══════════════════════════════════════════════════════════════════════
#  SETTINGS LOADER
# ══════════════════════════════════════════════════════════════════════

def _load_settings() -> BotSettings:
    raw = settings_db.read()
    return BotSettings.from_dict(raw) if raw else BotSettings()


# ══════════════════════════════════════════════════════════════════════
#  USER REGISTRY
# ══════════════════════════════════════════════════════════════════════

def _get_user(uid: str) -> Optional[dict]:
    return users_db.get(uid)


def save_form_fields_to_profile(uid: str, fields: dict) -> None:
    """
    فیلدهای فرم را در profile_data کاربر ذخیره می‌کند.
    از form_builder هنگام submit فراخوانی می‌شود.
    """
    user = users_db.get(uid)
    if not user:
        return
    pd = user.get("profile_data", {})
    pd.update({str(k): str(v) for k, v in fields.items() if v})
    users_db.update(uid, {"profile_data": pd})


def _upsert_user(message: Message) -> tuple[dict, bool]:
    """Returns (user_dict, is_new)."""
    uid      = str(message.from_user.id)
    username = message.from_user.username or ""
    existing = users_db.get(uid)
    now      = datetime.utcnow().isoformat()

    if existing:
        # Update mutable fields silently
        updates: dict = {"last_seen": now}
        if username and existing.get("username") != username:
            updates["username"] = username
        if message.from_user.first_name and existing.get("first_name") != message.from_user.first_name:
            updates["first_name"] = message.from_user.first_name
        users_db.update(uid, updates)
        return users_db.get(uid), False

    user = User(
        user_id=uid,
        username=username,
        first_name=message.from_user.first_name or "",
        last_name=message.from_user.last_name or "",
        joined_at=now,
        last_seen=now,
    )
    users_db.set(uid, user.to_dict())
    return user.to_dict(), True


# ══════════════════════════════════════════════════════════════════════
#  ANTI-FLOOD
# ══════════════════════════════════════════════════════════════════════

def _check_flood(uid: str, bs: BotSettings) -> bool:
    """Returns True if user is flooding (should be blocked)."""
    af = bs.anti_flood
    if not af.get("enabled", True):
        return False

    max_msgs = af.get("max_messages", 5)
    interval = af.get("interval_seconds", 5)
    now      = datetime.utcnow()
    cutoff   = (now - timedelta(seconds=interval)).isoformat()

    user = users_db.get(uid)
    if not user:
        return False

    timestamps: list[str] = user.get("flood_timestamps", [])
    # Keep only recent ones
    timestamps = [t for t in timestamps if t >= cutoff]
    timestamps.append(now.isoformat())
    users_db.update(uid, {"flood_timestamps": timestamps})

    return len(timestamps) > max_msgs


# ══════════════════════════════════════════════════════════════════════
#  WORKING HOURS CHECK
# ══════════════════════════════════════════════════════════════════════

def _is_working_hours(bs: BotSettings) -> bool:
    wh = bs.working_hours
    if not wh.get("enabled", False):
        return True

    now     = datetime.utcnow()
    weekday = now.weekday()  # 0=Monday
    days    = wh.get("days", [0, 1, 2, 3, 4])
    if weekday not in days:
        return False

    try:
        open_h,  open_m  = map(int, wh.get("open_time",  "09:00").split(":"))
        close_h, close_m = map(int, wh.get("close_time", "21:00").split(":"))
    except ValueError:
        return True

    current = now.hour * 60 + now.minute
    open_t  = open_h  * 60 + open_m
    close_t = close_h * 60 + close_m
    return open_t <= current < close_t


# ══════════════════════════════════════════════════════════════════════
#  FORCE-JOIN CHECK
# ══════════════════════════════════════════════════════════════════════

async def _check_force_join(bot: Bot, uid: int, bs: BotSettings) -> list[str]:
    """Returns list of channels user is NOT a member of."""
    channels = bs.force_join_channels
    if not channels:
        return []

    not_joined = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, uid)
            if member.status in ("left", "kicked"):
                not_joined.append(ch)
            elif member.status == "restricted" and not getattr(member, "can_send_messages", True):
                not_joined.append(ch)
            # اگر status == "member", "creator", "administrator" یعنی عضو هست — اضافه نکن
        except Exception as e:
            # باگ ۲: فقط خطای "chat not found" یا خطای واقعی — نه هر Exception
            err_str = str(e).lower()
            if "chat not found" in err_str or "user not found" in err_str:
                # کانال وجود ندارد یا ربات عضو کانال نیست — نادیده بگیریم
                not_joined.append(ch)
            elif "bot is not a member" in err_str or "kicked" in err_str or "not enough rights" in err_str:
                # ربات دسترسی ندارد — به جای ارور به کاربر، آرام بگیریم (کانال را از لیست حذف کن)
                pass
            else:
                # خطای ناشناخته — احتیاط کنیم و نادیده بگیریم
                not_joined.append(ch)
    return not_joined


def _force_join_kb(channels: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        ch_clean = ch.lstrip("@")
        if ch.startswith("-"):
            # کانال private — numeric ID به عنوان URL معتبر نیست؛ ادمین باید invite link بدهد
            rows.append([InlineKeyboardButton(text=f"📢 عضویت در کانال", url=f"https://t.me/joinchat/{ch_clean}")])
        else:
            rows.append([InlineKeyboardButton(text=f"📢 @{ch_clean}", url=f"https://t.me/{ch_clean}")])
    rows.append([InlineKeyboardButton(text="✅ عضو شدم", callback_data="user:check_join")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ══════════════════════════════════════════════════════════════════════
#  WELCOME MESSAGE BUILDER
# ══════════════════════════════════════════════════════════════════════

def _build_welcome(user: dict, is_new: bool, bs: BotSettings) -> str:
    uname    = user.get("username", "")
    fname    = user.get("first_name", "")
    # یوزرنیم اولویت دارد — اگر نداشت از نام استفاده می‌شود
    if uname:
        name_esc = esc("@" + uname)
    else:
        name_esc = esc(fname or "کاربر")

    if is_new:
        greeting = f"سلام {name_esc} عزیز\\! به ربات خوش آمدید 👋"
    else:
        greeting = f"خوش برگشتی {name_esc}\\! 🙌"

    base_msg = esc(bs.welcome_msg)

    # Support line
    support = ""
    if bs.support_username:
        support = (
            f"\n\n🆘 {esc(bs.support_message.format(support='@' + bs.support_username))}"
        )

    return f"{greeting}\n\n{base_msg}{support}"


# ══════════════════════════════════════════════════════════════════════
#  GATE: shared pre-check for all user-facing messages
#  Returns True if message should be blocked, False if it can proceed.
# ══════════════════════════════════════════════════════════════════════

async def _gate(message: Message, skip_flood: bool = False) -> bool:
    """
    Runs ban / maintenance / working-hours / flood checks.
    Returns True → blocked (handler must return early).
    Returns False → OK, proceed.
    """
    uid  = str(message.from_user.id)
    bs   = _load_settings()
    user = users_db.get(uid)

    # 1. Banned
    if user and user.get("is_banned"):
        reason = user.get("ban_reason", "")
        text   = esc(bs.banned_msg)
        if reason:
            text += f"\n\n📌 {italic('دلیل: ' + reason)}"
        await message.answer(text, parse_mode="MarkdownV2")
        return True

    # 2. Maintenance (admins bypass)
    from handlers.admin_auth import _is_admin
    if bs.maintenance and not _is_admin(uid):
        await message.answer(esc(bs.maintenance_msg), parse_mode="MarkdownV2")
        return True

    # 3. Working hours (admins bypass)
    if not _is_working_hours(bs) and not _is_admin(uid):
        wh  = bs.working_hours
        msg = esc(wh.get("closed_message", "ربات در حال حاضر بسته است\\."))
        open_t  = esc(wh.get("open_time",  "09:00"))
        close_t = esc(wh.get("close_time", "21:00"))
        await message.answer(
            f"{msg}\n\n⏰ ساعت کاری: {open_t} — {close_t}",
            parse_mode="MarkdownV2",
        )
        return True

    # 4. Anti-flood (admins bypass)
    if not skip_flood and not _is_admin(uid):
        if _check_flood(uid, bs):
            af       = bs.anti_flood
            warn_msg = esc(af.get("warn_message", "⚠️ لطفاً کمی صبر کنید\\."))
            ban_dur  = af.get("ban_duration_seconds", 60)
            await message.answer(
                f"{warn_msg}\n\n_مسدود برای {esc(str(ban_dur))} ثانیه_",
                parse_mode="MarkdownV2",
            )
            return True

    return False


# ══════════════════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════════════════

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    uid      = str(message.from_user.id)
    bs       = _load_settings()

    user, is_new = _upsert_user(message)

    # Ban check (before anything)
    if user.get("is_banned"):
        reason = user.get("ban_reason", "")
        text   = esc(bs.banned_msg)
        if reason:
            text += f"\n\n📌 {italic('دلیل: ' + reason)}"
        await message.answer(text, parse_mode="MarkdownV2")
        return

    # Maintenance (admins bypass)
    from handlers.admin_auth import _is_admin
    if bs.maintenance and not _is_admin(uid):
        await message.answer(esc(bs.maintenance_msg), parse_mode="MarkdownV2")
        return

    # Force-join
    not_joined = await _check_force_join(bot, message.from_user.id, bs)
    if not_joined:
        await message.answer(
            f"{bold('📢 عضویت اجباری')}\n\n{esc(bs.force_join_message)}",
            parse_mode="MarkdownV2",
            reply_markup=_force_join_kb(not_joined),
        )
        return

    await state.clear()

    # Send welcome
    welcome_text = _build_welcome(user, is_new, bs)
    await message.answer(welcome_text, parse_mode="MarkdownV2")

    # Navigate to home panel if set
    home_pid = bs.home_panel_id
    if home_pid and panels_db.exists(home_pid):
        await _render_panel(message, home_pid)
    else:
        # Minimal help hint if no panel configured yet
        hint = (
            f"\n\n{italic('برای مشاهده دستورات از /help استفاده کنید\\.')}"
        )
        await message.answer(hint, parse_mode="MarkdownV2")


@router.callback_query(F.data == "user:check_join")
async def cb_check_join(call: CallbackQuery, state: FSMContext, bot: Bot):
    bs         = _load_settings()
    not_joined = await _check_force_join(bot, call.from_user.id, bs)
    if not_joined:
        await call.answer("❌ هنوز در همه کانال‌ها عضو نشده‌اید!", show_alert=True)
        return
    await call.message.delete()
    # Re-trigger start
    await call.answer("✅ عضویت تأیید شد")
    uid      = str(call.from_user.id)
    # یوزرنیم را از اطلاعات لحظه‌ای تلگرام به‌روز می‌کنیم
    uname_live = call.from_user.username or ""
    if uname_live:
        users_db.update(uid, {"username": uname_live})
    user     = users_db.get(uid) or {}
    welcome  = _build_welcome(user, False, bs)
    await call.message.answer(welcome, parse_mode="MarkdownV2")
    home_pid = bs.home_panel_id
    if home_pid and panels_db.exists(home_pid):
        await _render_panel(call.message, home_pid)


# ══════════════════════════════════════════════════════════════════════
#  /rs — restart with session keep
# ══════════════════════════════════════════════════════════════════════

@router.message(Command("rs"))
async def cmd_rs(message: Message, state: FSMContext, bot: Bot):
    if await _gate(message, skip_flood=True):
        return
    # Clear FSM but keep user data intact
    await state.clear()
    uid  = str(message.from_user.id)
    bs   = _load_settings()
    user = users_db.get(uid) or {}

    await message.answer(
        f"🔄 {bold('ریستارت شد')}\\!\n\n{esc(bs.welcome_msg)}",
        parse_mode="MarkdownV2",
    )
    home_pid = bs.home_panel_id
    if home_pid and panels_db.exists(home_pid):
        await _render_panel(message, home_pid)


# ══════════════════════════════════════════════════════════════════════
#  /cancel
# ══════════════════════════════════════════════════════════════════════

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    await state.clear()
    if current:
        await message.answer(
            "❌ عملیات لغو شد\\.",
            parse_mode="MarkdownV2",
        )
    else:
        await message.answer(
            italic("هیچ عملیات فعالی برای لغو وجود ندارد\\."),
            parse_mode="MarkdownV2",
        )


# ══════════════════════════════════════════════════════════════════════
#  /help
# ══════════════════════════════════════════════════════════════════════

@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext):
    if await _gate(message):
        return
    uid = str(message.from_user.id)
    bs  = _load_settings()

    lines = [
        bold("📖 راهنمای دستورات"),
        "",
        bold("👤 دستورات کاربر:"),
        f"• /start — شروع \\/ صفحه اصلی",
        f"• /rs — ریستارت ربات",
        f"• /profile — پروفایل و سفارشات",
        f"• /id — نمایش آیدی تلگرام شما",
        f"• /cancel — لغو عملیات جاری",
        f"• /help — این راهنما",
    ]

    if bs.support_username:
        lines += [
            "",
            f"🆘 پشتیبانی: {esc('@' + bs.support_username)}",
        ]

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")


# ══════════════════════════════════════════════════════════════════════
#  /id
# ══════════════════════════════════════════════════════════════════════

@router.message(Command("id"))
async def cmd_id(message: Message):
    uid   = str(message.from_user.id)
    uname = message.from_user.username or ""
    text  = (
        f"{bold('🆔 اطلاعات شناسه')}\n\n"
        f"• آیدی عددی: {code(uid)}\n"
        f"• یوزرنیم: {esc('@' + uname) if uname else italic('ندارد')}"
    )
    await message.answer(text, parse_mode="MarkdownV2")


# ══════════════════════════════════════════════════════════════════════
#  /profile
# ══════════════════════════════════════════════════════════════════════

def _profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ ویرایش نام",     callback_data="user:edit_name"),
         InlineKeyboardButton(text="📞 ویرایش تلفن",    callback_data="user:edit_phone")],
        [InlineKeyboardButton(text="📦 سفارشات من",     callback_data="user:orders")],
    ])


def _build_profile_text(user: dict) -> str:
    uid      = user.get("user_id", "")
    uname    = user.get("username", "")
    fname    = user.get("first_name", "")
    lname    = user.get("last_name", "")
    joined   = user.get("joined_at", "")[:10]
    last     = user.get("last_seen", "")[:16].replace("T", " ")
    orders_n = len(user.get("orders", []))
    pd       = user.get("profile_data", {})
    phone    = pd.get("phone", "")

    lines = [
        bold("👤 پروفایل شما"),
        "",
        f"👤 نام: {bold(esc((fname + ' ' + lname).strip() or '—'))}",
        f"🔖 یوزرنیم: {esc('@' + uname) if uname else italic('ندارد')}",
        f"📞 تلفن: {esc(phone) if phone else italic('ثبت نشده')}",
        f"📅 عضویت: {esc(joined)}",
        f"🕐 آخرین فعالیت: {esc(last)}",
        f"📦 سفارشات: {bold(str(orders_n))}",
    ]

    # اطلاعات اضافی از فیلدهای فرم (به‌جز phone که بالا نمایش داده شد)
    extra = {k: v for k, v in pd.items() if k != "phone" and v}
    if extra:
        lines.append("")
        lines.append(bold("📋 اطلاعات تکمیلی:"))
        for k, v in list(extra.items())[:8]:
            lines.append(f"• {esc(str(k))}: {esc(str(v))}")

    return "\n".join(lines)


@router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    if await _gate(message):
        return
    uid  = str(message.from_user.id)
    user = _upsert_user(message)[0]
    await message.answer(
        _build_profile_text(user),
        parse_mode="MarkdownV2",
        reply_markup=_profile_kb(),
    )


@router.callback_query(F.data == "user:profile")
async def cb_profile(call: CallbackQuery, state: FSMContext):
    uid  = str(call.from_user.id)
    user = users_db.get(uid) or {}
    await call.message.edit_text(
        _build_profile_text(user),
        parse_mode="MarkdownV2",
        reply_markup=_profile_kb(),
    )
    await call.answer()


# — edit name ————————————————————————————————————————————————

@router.callback_query(F.data == "user:edit_name")
async def cb_edit_name(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.edit_first_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="user:cancel_edit")]
    ])
    await call.message.edit_text(
        f"{bold('✏️ ویرایش نام')}\n\nنام جدید خود را وارد کنید:",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(UserStates.edit_first_name)
async def fsm_edit_first_name(message: Message, state: FSMContext):
    parts = message.text.strip().split(None, 1)
    fname = parts[0] if parts else ""
    lname = parts[1] if len(parts) > 1 else ""
    uid   = str(message.from_user.id)
    users_db.update(uid, {"first_name": fname, "last_name": lname})
    await state.clear()
    user = users_db.get(uid) or {}
    await message.answer(
        f"✅ نام به {bold(esc((fname + ' ' + lname).strip()))} تغییر یافت\\.",
        parse_mode="MarkdownV2",
        reply_markup=_profile_kb(),
    )


# — edit phone ————————————————————————————————————————————————

@router.callback_query(F.data == "user:edit_phone")
async def cb_edit_phone(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.edit_phone)
    # ارسال دکمه share contact (فقط در ReplyKeyboard کار می‌کند)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📲 اشتراک‌گذاری شماره", request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await call.message.answer(
        f"{bold('📞 ویرایش شماره تلفن')}\n\n"
        "دکمه زیر را بزنید تا شماره‌تان ثبت شود،\n"
        "یا شماره را به صورت دستی وارد کنید:\n"
        "مثال: `09123456789`",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
    await call.answer()


@router.message(UserStates.edit_phone)
async def fsm_edit_phone(message: Message, state: FSMContext):
    uid  = str(message.from_user.id)
    user = users_db.get(uid) or {}
    pd   = user.get("profile_data", {})

    # باگ ۱: پشتیبانی از contact share و ورود دستی
    if message.contact:
        phone = message.contact.phone_number or ""
        if not phone.startswith("+"):
            phone = "+" + phone
    else:
        phone = (message.text or "").strip()

    if not phone:
        await message.answer(
            "❌ شماره معتبر نیست\\. دوباره وارد کنید:",
            parse_mode="MarkdownV2",
        ); return

    pd["phone"] = phone
    users_db.update(uid, {"profile_data": pd})
    await state.clear()
    await message.answer(
        f"✅ شماره {code(esc(phone))} ثبت شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        _build_profile_text(users_db.get(uid) or {}),
        parse_mode="MarkdownV2",
        reply_markup=_profile_kb(),
    )


@router.callback_query(F.data == "user:cancel_edit")
async def cb_cancel_edit(call: CallbackQuery, state: FSMContext):
    await state.clear()
    uid  = str(call.from_user.id)
    user = users_db.get(uid) or {}
    await call.message.edit_text(
        _build_profile_text(user),
        parse_mode="MarkdownV2",
        reply_markup=_profile_kb(),
    )
    await call.answer()


# — panel password handlers ——————————————————————————————————————————————
# باگ ۵: handler اختصاصی برای رمز پنل

@router.callback_query(F.data == "user:cancel_panel_pass")
async def cb_cancel_panel_pass(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        italic("انصراف دادید."),
        parse_mode="MarkdownV2",
    )
    await call.answer()


@router.message(UserStates.panel_password)
async def fsm_panel_password(message: Message, state: FSMContext):
    data        = await state.get_data()
    panel_id    = data.get("_locked_panel", "")
    correct_pass = data.get("_locked_panel_pass", "")

    if message.text.strip() == correct_pass:
        await state.clear()
        await _render_panel(message, panel_id)
    else:
        await message.answer(
            f"❌ {bold('رمز اشتباه است.')}\\n\\nدوباره تلاش کنید:",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ انصراف", callback_data="user:cancel_panel_pass")
            ]]),
        )


# — orders ————————————————————————————————————————————————————

@router.callback_query(F.data == "user:orders")
async def cb_orders(call: CallbackQuery, state: FSMContext):
    uid    = str(call.from_user.id)
    user   = users_db.get(uid) or {}
    orders = user.get("orders", [])

    if not orders:
        text = f"{bold('📦 سفارشات شما')}\n\n{italic('هنوز سفارشی ثبت نشده\\.')}"
    else:
        lines = [bold("📦 تاریخچه سفارشات"), ""]
        for i, order in enumerate(reversed(orders[-20:]), 1):
            title   = esc(order.get("form_title", "سفارش"))
            date    = esc(order.get("submitted_at", "")[:10])
            receipt = " 🧾" if order.get("has_receipt") else ""
            line    = f"{esc(str(i))}\\. {bold(title)} — {date}{esc(receipt)}"
            # نمایش فیلدهای فرم ذخیره‌شده در این سفارش
            fields: dict = order.get("fields", {})
            if fields:
                field_parts = []
                for k, v in list(fields.items())[:4]:   # حداکثر ۴ فیلد نمایش داده می‌شود
                    field_parts.append(f"  • {esc(str(k))}: {esc(str(v))}")
                line += "\n" + "\n".join(field_parts)
            lines.append(line)
        text = "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت به پروفایل", callback_data="user:profile")]
    ])
    await call.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await call.answer()



# ══════════════════════════════════════════════════════════════════════
#  PANEL RENDERER  (used by /start and /rs)
# ══════════════════════════════════════════════════════════════════════

async def _render_panel(message: Message, panel_id: str):
    """Render a panel to the user (text + inline buttons)."""
    from models import Panel, Button

    raw = panels_db.get(panel_id)
    if not raw:
        return

    panel = Panel.from_dict(raw)
    if not panel.is_active:
        bs = _load_settings()
        await message.answer(esc(bs.panel_inactive_msg), parse_mode="MarkdownV2")
        return

    # Capacity check
    cap = panel.settings.get("capacity", 0)
    if cap:
        used = panel.settings.get("capacity_used", 0)
        if used >= cap:
            bs = _load_settings()
            await message.answer(esc(bs.not_found_msg), parse_mode="MarkdownV2")
            return
        panels_db.update(panel_id, {"settings": {**panel.settings, "capacity_used": used + 1}})

    # Build inline keyboard from panel.buttons
    btn_rows: dict[int, list[InlineKeyboardButton]] = {}
    for b in panel.buttons:
        row = b.get("row", 0)
        action = b.get("action", "callback")
        label  = b.get("label", "دکمه")
        value  = b.get("value", "")

        # style فقط یک متادیتای پنل‌ساز است و پارامتر معتبری برای InlineKeyboardButton نیست
        # باگ ۴ رفع شد: استفاده از style= که در Bot API 9.4 اضافه شد
        style = b.get("style")  # "success" | "danger" | "primary" | None

        if action == "url":
            ib = InlineKeyboardButton(text=label, url=value, style=style)
        elif action == "panel":
            ib = InlineKeyboardButton(text=label, callback_data=f"nav:{value}", style=style)
        elif action == "form":
            ib = InlineKeyboardButton(text=label, callback_data=f"openform:{value}", style=style)
        elif action == "phone":
            # دکمه share contact → هدایت به همان فلوی edit_phone که RequestContact دارد
            ib = InlineKeyboardButton(text=label, callback_data="user:edit_phone", style=style)
        else:
            ib = InlineKeyboardButton(text=label, callback_data=value or "noop", style=style)

        btn_rows.setdefault(row, []).append(ib)

    kb_rows = [btn_rows[r] for r in sorted(btn_rows.keys())]
    # Add back button if panel has a parent
    if panel.parent_id:
        kb_rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"nav:{panel.parent_id}")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None

    # Add watermark if enabled
    bs = _load_settings()
    content = panel.content or ""
    if bs.watermark_enabled and bs.watermark:
        content = content + ("\n\n" if content else "") + f"_{esc(bs.watermark)}_"

    # ─── helper: ارسال با MarkdownV2، fallback به plain text اگه parse fail شد ───
    async def _send(fn, *args, **kwargs):
        try:
            await fn(*args, parse_mode="MarkdownV2", **kwargs)
        except Exception as md_err:
            if "can't parse" in str(md_err).lower() or "bad request" in str(md_err).lower():
                # content ادمین شامل کاراکتر escape‌نشده است — plain text بفرست
                kwargs.pop("parse_mode", None)
                await fn(*args, parse_mode=None, **kwargs)
            else:
                raise

    # Send by type
    try:
        if panel.type == "sell":
            # Show product info + receipt upload button
            s     = panel.settings
            name  = esc(s.get("product_name", panel.title))
            desc  = s.get("product_desc", "")
            price = s.get("product_price", "")
            bs2   = _load_settings()
            lines = [f"{bold('🛒 ' + s.get('product_name', panel.title))}"]
            if desc:
                lines += ["", esc(desc)]
            if price:
                lines += ["", f"💰 قیمت: {bold(esc(price))} {esc(bs2.currency)}"]
            if bs2.payment_info:
                lines += ["", f"💳 اطلاعات پرداخت:", esc(bs2.payment_info)]
            lines += ["", italic("پس از پرداخت، رسید خود را ارسال کنید\\. \\(تصویر، فوروارد یا متن\\)")]
            sell_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📤 ارسال رسید", callback_data=f"sell:receipt:{panel_id}")],
            ])
            if panel.parent_id:
                sell_kb.inline_keyboard.append(
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"nav:{panel.parent_id}")]
                )
            await _send(message.answer, "\n".join(lines), reply_markup=sell_kb)
            return
        elif panel.type == "text" or not panel.media_file_id:
            await _send(message.answer,
                content or esc(panel.title),
                reply_markup=kb,
            )
        elif panel.type == "photo":
            await _send(message.answer_photo,
                panel.media_file_id,
                caption=content,
                reply_markup=kb,
            )
        elif panel.type == "video":
            await _send(message.answer_video,
                panel.media_file_id,
                caption=content,
                reply_markup=kb,
            )
        elif panel.type == "audio":
            await _send(message.answer_audio,
                panel.media_file_id,
                caption=content,
                reply_markup=kb,
            )
        elif panel.type == "document":
            await _send(message.answer_document,
                panel.media_file_id,
                caption=content,
                reply_markup=kb,
            )
        elif panel.type == "carousel":
            ids = panel.settings.get("carousel_ids", [panel.media_file_id])
            from aiogram.types import InputMediaPhoto
            if len(ids) == 1:
                await _send(message.answer_photo, ids[0], caption=content, reply_markup=kb)
            else:
                # برای media_group هم fallback plain text
                caption_md   = content
                caption_plain = content
                parse_mode_mg = "MarkdownV2"
                try:
                    media_group = [InputMediaPhoto(media=fid) for fid in ids]
                    if content:
                        media_group[-1] = InputMediaPhoto(
                            media=ids[-1], caption=caption_md, parse_mode="MarkdownV2"
                        )
                    await message.answer_media_group(media_group)
                except Exception as mg_err:
                    if "can't parse" in str(mg_err).lower() or "bad request" in str(mg_err).lower():
                        media_group = [InputMediaPhoto(media=fid) for fid in ids]
                        if content:
                            media_group[-1] = InputMediaPhoto(
                                media=ids[-1], caption=caption_plain, parse_mode=None
                            )
                        await message.answer_media_group(media_group)
                    else:
                        raise
                if kb:
                    await message.answer("⬆️", reply_markup=kb)
    except Exception as e:
        logger.error("Panel render error [%s]: %s", panel_id, e)
        bs2 = _load_settings()
        await message.answer(esc(bs2.error_msg), parse_mode="MarkdownV2")


# ══════════════════════════════════════════════════════════════════════
#  PANEL NAVIGATION CALLBACK
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("nav:"))
async def cb_nav_panel(call: CallbackQuery, state: FSMContext, bot: Bot):
    uid = str(call.from_user.id)
    bs  = _load_settings()

    user = users_db.get(uid)
    if user and user.get("is_banned"):
        await call.answer("⛔ دسترسی محدود", show_alert=True); return

    from handlers.admin_auth import _is_admin
    if bs.maintenance and not _is_admin(uid):
        await call.answer(esc(bs.maintenance_msg)[:200], show_alert=True); return

    panel_id = call.data.split(":", 1)[1]
    raw      = panels_db.get(panel_id)
    if not raw:
        await call.answer("❌ پنل یافت نشد", show_alert=True); return

    panel = __import__("models").Panel.from_dict(raw)

    # Inactive panel — show admin-configurable message
    if not panel.is_active:
        bs = _load_settings()
        await call.answer(bs.panel_inactive_msg[:200], show_alert=True); return

    # Password-locked panel — باگ ۵ رفع شد: state اختصاصی
    password = panel.settings.get("password")
    if password:
        await state.update_data(_locked_panel=panel_id, _locked_panel_pass=password)
        await state.set_state(UserStates.panel_password)
        await call.message.answer(
            f"{bold('🔒 این بخش رمز دارد')}\\n\\nرمز را وارد کنید:",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ انصراف", callback_data="user:cancel_panel_pass")
            ]]),
        )
        await call.answer(); return

    await _render_panel(call.message, panel_id)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  SELL PANEL — RECEIPT SUBMISSION
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sell:receipt:"))
async def cb_sell_receipt_start(call: CallbackQuery, state: FSMContext):
    panel_id = call.data.split(":", 2)[2]
    raw = panels_db.get(panel_id)
    if not raw:
        await call.answer("❌ پنل یافت نشد", show_alert=True); return
    from models import Panel as _Panel
    panel = _Panel.from_dict(raw)
    if not panel.is_active:
        bs = _load_settings()
        await call.answer(bs.panel_inactive_msg[:200], show_alert=True); return
    await state.update_data(_sell_panel_id=panel_id)
    await state.set_state(UserStates.sell_receipt)
    await call.message.answer(
        f"{bold('📤 ارسال رسید')}\n\n"
        "رسید پرداخت خود را ارسال کنید\\.\n"
        "_می‌توانید تصویر، متن یا پیام فوروارد‌شده ارسال کنید\\._",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ انصراف", callback_data="sell:cancel")
        ]]),
    )
    await call.answer()


@router.callback_query(F.data == "sell:cancel")
async def cb_sell_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ ارسال رسید لغو شد\\.", parse_mode="MarkdownV2")
    await call.answer()


@router.message(UserStates.sell_receipt)
async def fsm_sell_receipt(message: Message, state: FSMContext, bot: Bot):
    data      = await state.get_data()
    panel_id  = data.get("_sell_panel_id", "")
    await state.clear()

    raw = panels_db.get(panel_id)
    if not raw:
        await message.answer("❌ پنل یافت نشد\\.", parse_mode="MarkdownV2"); return

    from models import Panel as _Panel
    panel      = _Panel.from_dict(raw)
    target_gid = panel.settings.get("target_group", "")

    if not target_gid:
        await message.answer(
            "❌ این پنل هنوز گروه مقصدی ندارد\\. با ادمین تماس بگیرید\\.",
            parse_mode="MarkdownV2"
        ); return

    uid      = str(message.from_user.id)
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {uid}"
    name     = message.from_user.full_name or uid

    # Build product info header to prepend
    s           = panel.settings
    product_name = s.get("product_name", panel.title)
    product_price = s.get("product_price", "")
    bs           = _load_settings()
    header = (
        f"🛒 <b>رسید فروش — {product_name}</b>\n"
        f"👤 خریدار: {name} ({username})\n"
        + (f"💰 قیمت: {product_price} {bs.currency}\n" if product_price else "")
        + f"🕐 زمان: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n"
        f"🆔 آیدی: <code>{uid}</code>\n"
        "──────────────────\n"
    )

    try:
        # Send header to group
        await bot.send_message(int(target_gid), header, parse_mode="HTML")
        # Forward or copy the receipt
        if message.forward_origin or message.forward_from or message.forward_from_chat:
            await message.forward(int(target_gid))
        else:
            await message.copy_to(int(target_gid))

        # ثبت has_receipt در آخرین سفارش کاربر (قابلیت جدید)
        user_raw = users_db.get(uid) or {}
        orders   = user_raw.get("orders", [])
        if orders:
            orders[-1]["has_receipt"] = True
            users_db.update(uid, {"orders": orders})

        await message.answer(
            f"✅ {bold('رسید شما با موفقیت ارسال شد\\!')}\n\n"
            "ادمین در اسرع وقت بررسی می‌کند\\.",
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        logger.error("sell receipt forward error panel=%s gid=%s: %s", panel_id, target_gid, e)
        await message.answer(
            "❌ خطا در ارسال رسید\\. لطفاً مستقیماً با پشتیبانی تماس بگیرید\\.",
            parse_mode="MarkdownV2"
        )


# ══════════════════════════════════════════════════════════════════════
#  OPEN FORM CALLBACK
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("openform:"))
async def cb_open_form(call: CallbackQuery, state: FSMContext, bot: Bot):
    uid = str(call.from_user.id)
    bs  = _load_settings()

    user = users_db.get(uid)
    if user and user.get("is_banned"):
        await call.answer("⛔", show_alert=True); return
    if bs.maintenance:
        from handlers.admin_auth import _is_admin
        if not _is_admin(uid):
            await call.answer(esc(bs.maintenance_msg)[:200], show_alert=True); return

    form_id = call.data.split(":", 1)[1]
    from handlers.form_builder import start_form_for_user
    await start_form_for_user(call.message, state, form_id, bot)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  CATCH-ALL FLOOD / GATE for regular messages
# ══════════════════════════════════════════════════════════════════════

@router.message(F.text & ~F.text.startswith("/"))
async def catch_all_text(message: Message, state: FSMContext):
    """
    Runs gate checks on every non-command text message
    that wasn't caught by a more specific handler.
    """
    current_state = await state.get_state()
    # Don't interfere with active FSM flows
    if current_state:
        return

    blocked = await _gate(message)
    if blocked:
        return

    # If user sends random text without an active flow, show hint
    await message.answer(
        italic("برای مشاهده منو /start را بزنید\\."),
        parse_mode="MarkdownV2",
    )