"""
handlers/admin_panel.py  —  IrForge
پنل مدیریت: تنظیمات / ادمین‌ها / کانال‌ها / آمار / بک‌آپ

باگ‌فیکس‌ها:
  1. send_settings_menu — کاراکتر '.' در MarkdownV2 حالا escape می‌شه
  2. متن فورس‌جوین قابل ویرایش از تنظیمات
  3. اد/حذف ادمین با یوزرنیم — بات خودش آیدی رو با getChat fetch می‌کنه

قابلیت‌های جدید:
  1. بک‌آپ restore — ارسال ZIP → جایگزینی خودکار
  2. ساخت کد تخفیف مستقیم از پنل ادمین
  3. چند زبان: fa / en / tr / ar / ru
  4. ارسال نتایج فرم به گروه دلخواه (destination_group per-form)
"""

import json
import io
import logging
import zipfile
from datetime import datetime, timedelta

from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    Document,
)

import config
from models import BotSettings, WorkingHours, AntiFlood, Admin, Discount
from utils.db import users_db, admins_db, settings_db, panels_db, forms_db, discounts_db
from utils.mdv2 import esc, bold, italic, code

logger = logging.getLogger(__name__)
router = Router(name="admin_panel")

# ══════════════════════════════════════════════════════════
#  STATES
# ══════════════════════════════════════════════════════════

class AdminStates(StatesGroup):
    # Settings text fields
    edit_welcome         = State()
    edit_error           = State()
    edit_watermark       = State()
    edit_maintenance_msg = State()
    edit_open_time       = State()
    edit_close_time      = State()
    edit_flood_max       = State()
    edit_flood_interval  = State()
    edit_flood_ban       = State()
    edit_support         = State()
    edit_payment         = State()
    # Bug fix 2: force-join message editable
    edit_force_join_msg  = State()
    edit_panel_inactive_msg = State()
    # Bug fix 3: admin by username
    add_admin_username    = State()
    add_admin_perm        = State()
    remove_admin_username = State()
    # Channel management
    add_channel          = State()
    remove_channel       = State()
    # Password change
    change_password         = State()
    change_password_confirm = State()
    # New feature 1: backup restore
    restore_backup       = State()
    # New feature 2: quick discount
    disc_code     = State()
    disc_type     = State()
    disc_value    = State()
    disc_capacity = State()
    disc_expiry   = State()
    # New feature 4: form destination group
    edit_form_dest = State()
    # قابلیت جدید: متن‌های سفارش قابل تغییر
    edit_order_confirm_msg = State()
    edit_order_reject_msg  = State()
    edit_order_track_msg   = State()


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

def _require_admin(uid: str) -> bool:
    from handlers.admin_auth import _is_admin
    return _is_admin(uid)


def _load_settings() -> BotSettings:
    raw = settings_db.read()
    if not raw:
        bs = BotSettings()
        settings_db.write(bs.to_dict())
        return bs
    return BotSettings.from_dict(raw)


def _save_settings(bs: BotSettings):
    bs.updated_at = datetime.utcnow().isoformat()
    settings_db.write(bs.to_dict())


def _tog(val: bool) -> str:
    return "✅" if val else "❌"


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _home_back_row() -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="ap:back"),
        InlineKeyboardButton(text="🏠 خانه",   callback_data="ap:home"),
    ]


def _settings_back_row() -> list[InlineKeyboardButton]:
    """Back row that returns to settings menu instead of main menu."""
    return [
        InlineKeyboardButton(text="🔙 بازگشت به تنظیمات", callback_data="ap:settings"),
        InlineKeyboardButton(text="🏠 خانه",               callback_data="ap:home"),
    ]


# ══════════════════════════════════════════════════════════
#  MAIN MENU
# ══════════════════════════════════════════════════════════

def _main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🗂 مدیریت پنل‌ها",       "pb:menu"),
         _btn("⚙️ تنظیمات ربات",       "ap:settings")],
        [_btn("👥 مدیریت ادمین‌ها",     "ap:admins"),
         _btn("📢 کانال‌ها و گروه‌ها",  "ap:channels")],
        [_btn("📊 آمار",                "ap:stats"),
         _btn("🔑 تغییر رمز پنل",      "ap:change_pass")],
        [_btn("💾 بک‌آپ JSON",          "ap:backup"),
         _btn("📥 بازیابی بک‌آپ",      "ap:restore")],
        [_btn("🎟 کد تخفیف جدید",       "ap:disc_new"),
         _btn("📣 پیام همگانی",         "ap:broadcast")],
        [_btn("📝 ساخت فرم جدید",       "fb:menu"),
         _btn("📋 مقصد فرم‌ها",         "ap:formdests")],
    ])


async def send_main_menu(message: Message, edit: bool = False):
    bs    = _load_settings()
    maint = _tog(bs.maintenance)
    wh    = _tog(bs.working_hours.get("enabled", False))
    flood = _tog(bs.anti_flood.get("enabled", True))
    wm    = _tog(bs.watermark_enabled)

    text = (
        f"{bold('🎛 پنل مدیریت IrForge')}\n\n"
        f"🔧 حالت تعمیر: {maint}\n"
        f"⏰ ساعت کاری: {wh}\n"
        f"🛡 آنتی‌فلاد: {flood}\n"
        f"💧 واترمارک: {wm}\n\n"
        f"_آخرین بروزرسانی: {esc(bs.updated_at[:16].replace('T', ' '))}_"
    )
    kb = _main_menu_kb()
    if edit:
        await message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════
#  SETTINGS MENU
# ══════════════════════════════════════════════════════════

def _settings_kb(bs: BotSettings) -> InlineKeyboardMarkup:
    wh_enabled    = bs.working_hours.get("enabled", False)
    flood_enabled = bs.anti_flood.get("enabled", True)
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✏️ پیام خوش‌آمد",          "ap:s:welcome"),
         _btn("✏️ پیام خطا",              "ap:s:error")],
        [_btn("✏️ پیام تعمیر",            "ap:s:maint_msg"),
         _btn("✏️ پشتیبانی",              "ap:s:support")],
        [_btn("✏️ اطلاعات پرداخت",        "ap:s:payment"),
         _btn("✏️ واترمارک",              "ap:s:watermark")],
        # Bug fix 2: force-join message now editable via FSM
        [_btn("✏️ پیام فورس‌جوین",        "ap:s:force_join_msg"),
         _btn(f"💧 واترمارک: {_tog(bs.watermark_enabled)}", "ap:s:toggle_wm")],
        [_btn(f"🔧 تعمیر: {_tog(bs.maintenance)}",         "ap:s:toggle_maint"),
         _btn(f"⏰ ساعت کاری: {_tog(wh_enabled)}",         "ap:s:toggle_wh")],
        [_btn("🕐 تنظیم ساعت",                             "ap:s:wh_times"),
         _btn(f"🛡 آنتی‌فلاد: {_tog(flood_enabled)}",      "ap:s:toggle_flood")],
        [_btn("⚡ تنظیم فلاد",                             "ap:s:flood_cfg"),
         _btn("✏️ پیام غیرفعال بودن پنل",                 "ap:s:panel_inactive_msg")],
        [_btn("✏️ متن تایید سفارش",                       "ap:s:order_confirm_msg"),
         _btn("✏️ متن رد سفارش",                          "ap:s:order_reject_msg")],
        [_btn("✏️ متن رهگیری سفارش",                      "ap:s:order_track_msg")],
        _home_back_row(),
    ])


async def send_settings_menu(target, edit: bool = True):
    bs = _load_settings()
    wh = bs.working_hours
    af = bs.anti_flood

    open_t  = wh.get("open_time",  "09:00")
    close_t = wh.get("close_time", "21:00")
    wm_text = bs.watermark[:30] + "…" if len(bs.watermark) > 30 else bs.watermark
    fj_prev = bs.force_join_message[:40] + "…" \
              if len(bs.force_join_message) > 40 else bs.force_join_message

    # Bug fix 1: all special chars (including '.') properly escaped via esc()
    # Literal '-' between times escaped with '\\-'
    text = (
        f"{bold('⚙️ تنظیمات ربات')}\n\n"
        f"💧 واترمارک: {esc(wm_text) if wm_text else italic('تنظیم نشده')}\n"
        f"⏰ ساعت کاری: {esc(open_t)} \\- {esc(close_t)}\n"
        f"🛡 فلاد: حداکثر {esc(str(af.get('max_messages', 5)))} پیام در "
        f"{esc(str(af.get('interval_seconds', 5)))} ثانیه\n"
        f"👤 پشتیبانی: {esc('@' + bs.support_username) if bs.support_username else italic('تنظیم نشده')}\n"
        f"📢 فورس‌جوین: {esc(fj_prev) if fj_prev else italic('تنظیم نشده')}\n"
    )
    kb = _settings_kb(bs)
    if edit:
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════
#  ADMINS MENU
# ══════════════════════════════════════════════════════════

def _admins_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ افزودن ادمین",    "ap:adm:add"),
         _btn("➖ حذف ادمین",       "ap:adm:remove")],
        [_btn("📋 لیست ادمین‌ها",   "ap:adm:list")],
        _home_back_row(),
    ])


async def send_admins_menu(target, edit: bool = True):
    count = admins_db.count()
    text  = (
        f"{bold('👥 مدیریت ادمین‌ها')}\n\n"
        f"تعداد ادمین‌های فعال: {bold(str(count))}\n\n"
        "از دکمه‌های زیر برای مدیریت ادمین‌ها استفاده کنید:"
    )
    if edit:
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=_admins_kb())
    else:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=_admins_kb())


# ══════════════════════════════════════════════════════════
#  CHANNELS MENU
# ══════════════════════════════════════════════════════════

def _channels_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ افزودن کانال/گروه",   "ap:ch:add"),
         _btn("➖ حذف کانال/گروه",      "ap:ch:remove")],
        [_btn("📋 لیست کانال‌ها",       "ap:ch:list")],
        _home_back_row(),
    ])


async def send_channels_menu(target, edit: bool = True):
    bs       = _load_settings()
    channels = bs.force_join_channels
    ch_list  = "\n".join(f"• {esc(c)}" for c in channels) if channels else italic("بدون کانال")
    text = (
        f"{bold('📢 کانال‌ها و گروه‌های فورس‌جوین')}\n\n"
        f"{ch_list}\n\n"
        "کاربران باید در این کانال‌ها عضو باشند:"
    )
    if edit:
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=_channels_kb())
    else:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=_channels_kb())


# ══════════════════════════════════════════════════════════
#  STATS
# ══════════════════════════════════════════════════════════

async def send_stats(target, edit: bool = True):
    all_users    = users_db.all_values()
    total        = len(all_users)
    banned       = sum(1 for u in all_users if u.get("is_banned"))
    admins_count = admins_db.count()
    panels_count = panels_db.count()
    forms_count  = forms_db.count()
    disc_count   = discounts_db.count()
    # Bug fix 1: esc() wraps the whole timestamp — handles '-', ':', ' ' safely
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    text = (
        f"{bold('📊 آمار ربات')}\n\n"
        f"👤 کل کاربران: {bold(str(total))}\n"
        f"🚫 بن‌شده: {bold(str(banned))}\n"
        f"🛡 ادمین‌ها: {bold(str(admins_count))}\n"
        f"📋 پنل‌ها: {bold(str(panels_count))}\n"
        f"📝 فرم‌ها: {bold(str(forms_count))}\n"
        f"🎟 کدهای تخفیف: {bold(str(disc_count))}\n\n"
        f"🕐 زمان: {esc(now_str)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back_row()])
    if edit:
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════
#  BACKUP
# ══════════════════════════════════════════════════════════

async def send_backup(message: Message):
    buf = io.BytesIO()
    db_map = {
        "users.json":     users_db,
        "admins.json":    admins_db,
        "settings.json":  settings_db,
        "panels.json":    panels_db,
        "forms.json":     forms_db,
        "discounts.json": discounts_db,
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, db in db_map.items():
            zf.writestr(fname, json.dumps(db.read(), ensure_ascii=False, indent=2))
    buf.seek(0)
    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file = BufferedInputFile(buf.read(), filename=f"IrForge_backup_{ts}.zip")
    await message.answer_document(
        file,
        caption=f"💾 *بک\\-آپ IrForge*\n_{esc(ts)}_",
        parse_mode="MarkdownV2",
    )


# ══════════════════════════════════════════════════════════
#  BACKUP RESTORE  (New feature 1)
# ══════════════════════════════════════════════════════════

_RESTORE_MAP = {
    "users.json":     users_db,
    "admins.json":    admins_db,
    "settings.json":  settings_db,
    "panels.json":    panels_db,
    "forms.json":     forms_db,
    "discounts.json": discounts_db,
}


async def _do_restore(message: Message, state: FSMContext, bot: Bot):
    """Download ZIP sent by admin, overwrite each JSON database from it."""
    doc: Document = message.document
    if not doc or not doc.file_name.endswith(".zip"):
        await message.answer(
            "❌ لطفاً یک فایل ZIP معتبر ارسال کنید\\.",
            parse_mode="MarkdownV2",
        )
        return

    file_info = await bot.get_file(doc.file_id)
    buf       = io.BytesIO()
    await bot.download_file(file_info.file_path, buf)
    buf.seek(0)

    restored = []
    errors   = []

    try:
        with zipfile.ZipFile(buf, "r") as zf:
            for fname, db in _RESTORE_MAP.items():
                if fname in zf.namelist():
                    try:
                        data = json.loads(zf.read(fname).decode("utf-8"))
                        db.write(data)
                        restored.append(fname)
                    except Exception as e:
                        errors.append(f"{fname}: {e}")
                else:
                    errors.append(f"{fname}: یافت نشد در ZIP")
    except zipfile.BadZipFile:
        await message.answer("❌ فایل ZIP معتبر نیست\\.", parse_mode="MarkdownV2")
        await state.clear()
        return

    await state.clear()

    r_txt = "\n".join(f"✅ {esc(f)}" for f in restored) or italic("هیچ")
    e_txt = "\n".join(f"⚠️ {esc(e)}" for e in errors)   or italic("بدون خطا")

    await message.answer(
        f"{bold('📥 نتیجه بازیابی بک‌آپ')}\n\n"
        f"*بازیابی شد:*\n{r_txt}\n\n"
        f"*خطاها:*\n{e_txt}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🏠 خانه", "ap:home")],
        ]),
    )


# ══════════════════════════════════════════════════════════
#  FORM DESTINATION MENU  (New feature 4)
# ══════════════════════════════════════════════════════════

async def send_form_dest_menu(target, edit: bool = True):
    all_forms = forms_db.all_items()
    if not all_forms:
        kb  = InlineKeyboardMarkup(inline_keyboard=[_home_back_row()])
        txt = f"{bold('📋 مقصد فرم‌ها')}\n\n{italic('هنوز فرمی ساخته نشده')}"
        if edit:
            await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
        else:
            await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)
        return

    rows = []
    for fid, raw in all_forms[:15]:
        title = raw.get("title", "بی‌نام")
        dest  = raw.get("destination_group", "")
        label = f"📋 {title[:20]}" + (f" ← {dest[:12]}" if dest else " ← ❌")
        rows.append([_btn(label, f"ap:formdest:{fid}")])
    rows.append(_home_back_row())

    txt = (
        f"{bold('📋 مقصد ارسال فرم‌ها')}\n\n"
        "یک فرم انتخاب کنید تا گروه مقصد آن را تنظیم کنید:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if edit:
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════════════════

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not _require_admin(str(message.from_user.id)):
        return
    await send_stats(message, edit=False)


@router.message(Command("backup"))
async def cmd_backup(message: Message):
    if not _require_admin(str(message.from_user.id)):
        return
    await send_backup(message)


# ══════════════════════════════════════════════════════════
#  CALLBACK ROUTER
# ══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ap:"))
async def admin_panel_cb(call: CallbackQuery, state: FSMContext):
    uid = str(call.from_user.id)
    if not _require_admin(uid):
        await call.answer("⛔ دسترسی ندارید", show_alert=True)
        return

    data = call.data

    # ── navigation ──
    if data == "ap:home":
        await state.clear()
        await send_main_menu(call.message, edit=True)

    elif data == "ap:back":
        await state.clear()
        await send_main_menu(call.message, edit=True)

    elif data == "ap:settings":
        await send_settings_menu(call.message)

    elif data == "ap:admins":
        await send_admins_menu(call.message)

    elif data == "ap:channels":
        await send_channels_menu(call.message)

    elif data == "ap:stats":
        await send_stats(call.message)

    elif data == "ap:backup":
        await call.answer("در حال تهیه بک‌آپ…")
        await send_backup(call.message)

    # New feature 1: restore
    elif data == "ap:restore":
        await state.set_state(AdminStates.restore_backup)
        kb = InlineKeyboardMarkup(inline_keyboard=[_home_back_row()])
        await call.message.edit_text(
            f"{bold('📥 بازیابی بک‌آپ')}\n\n"
            "فایل ZIP بک‌آپ را ارسال کنید\\.\n"
            "⚠️ _تمام داده‌های فعلی جایگزین خواهند شد\\._",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )

    elif data == "ap:change_pass":
        await state.set_state(AdminStates.change_password)
        kb = InlineKeyboardMarkup(inline_keyboard=[_home_back_row()])
        await call.message.edit_text(
            f"{bold('🔑 تغییر رمز پنل')}\n\nرمز جدید را وارد کنید:",
            parse_mode="MarkdownV2", reply_markup=kb
        )

    # New feature 2: quick discount
    elif data == "ap:disc_new":
        await state.set_state(AdminStates.disc_code)
        kb  = InlineKeyboardMarkup(inline_keyboard=[_home_back_row()])
        await call.message.edit_text(
            f"{bold('🎟 کد تخفیف جدید')}\n\nکد تخفیف را وارد کنید \\(حروف انگلیسی/اعداد\\):",
            parse_mode="MarkdownV2", reply_markup=kb,
        )

    # broadcast — هدایت به handler اختصاصی
    elif data == "ap:broadcast":
        from handlers.broadcast import start_broadcast
        await start_broadcast(call, state)

    # New feature 4: form destination
    elif data == "ap:formdests":
        await send_form_dest_menu(call.message)

    elif data.startswith("ap:formdest:"):
        fid = data.split(":")[2]
        raw = forms_db.get(fid)
        if not raw:
            await call.answer("فرم یافت نشد", show_alert=True)
        else:
            await state.update_data(formdest_fid=fid)
            await state.set_state(AdminStates.edit_form_dest)
            cur = raw.get("destination_group", "")
            kb  = InlineKeyboardMarkup(inline_keyboard=[_home_back_row()])
            await call.message.edit_text(
                f"{bold('📋 گروه مقصد فرم')}\n\n"
                f"فرم: {bold(esc(raw.get('title', 'بی‌نام')))}\n"
                f"مقصد فعلی: {code(cur) if cur else italic('تنظیم نشده')}\n\n"
                "آیدی گروه جدید را وارد کنید \\(مثال: `\\-100xxxxxxx`\\)\\.\n"
                "برای پاک کردن، `0` ارسال کنید:",
                parse_mode="MarkdownV2",
                reply_markup=kb,
            )

    # ── settings toggles ──
    elif data == "ap:s:toggle_wm":
        bs = _load_settings()
        bs.watermark_enabled = not bs.watermark_enabled
        _save_settings(bs)
        await send_settings_menu(call.message)

    elif data == "ap:s:toggle_maint":
        bs = _load_settings()
        bs.maintenance = not bs.maintenance
        _save_settings(bs)
        await send_settings_menu(call.message)

    elif data == "ap:s:toggle_wh":
        bs  = _load_settings()
        wh  = bs.working_hours.copy()
        wh["enabled"] = not wh.get("enabled", False)
        bs.working_hours = wh
        _save_settings(bs)
        await send_settings_menu(call.message)

    elif data == "ap:s:toggle_flood":
        bs  = _load_settings()
        af  = bs.anti_flood.copy()
        af["enabled"] = not af.get("enabled", True)
        bs.anti_flood = af
        _save_settings(bs)
        await send_settings_menu(call.message)

    # ── settings edit prompts ──
    elif data == "ap:s:welcome":
        await state.set_state(AdminStates.edit_welcome)
        await _prompt_edit(call, "پیام خوش‌آمدگویی جدید را وارد کنید:")

    elif data == "ap:s:error":
        await state.set_state(AdminStates.edit_error)
        await _prompt_edit(call, "پیام خطای جدید را وارد کنید:")

    elif data == "ap:s:maint_msg":
        await state.set_state(AdminStates.edit_maintenance_msg)
        await _prompt_edit(call, "پیام حالت تعمیر را وارد کنید:")

    elif data == "ap:s:watermark":
        await state.set_state(AdminStates.edit_watermark)
        await _prompt_edit(call, "متن واترمارک جدید را وارد کنید:")

    elif data == "ap:s:support":
        await state.set_state(AdminStates.edit_support)
        await _prompt_edit(call, "یوزرنیم پشتیبانی را وارد کنید \\(بدون @\\):")

    elif data == "ap:s:payment":
        await state.set_state(AdminStates.edit_payment)
        await _prompt_edit(call, "اطلاعات پرداخت را وارد کنید:")

    elif data == "ap:s:wh_times":
        await state.set_state(AdminStates.edit_open_time)
        await _prompt_edit(call, "ساعت شروع کار را وارد کنید \\(مثال: 09:00\\):")

    elif data == "ap:s:flood_cfg":
        await state.set_state(AdminStates.edit_flood_max)
        await _prompt_edit(call, "حداکثر تعداد پیام در بازه را وارد کنید \\(عدد\\):")

    # Bug fix 2: force-join message now triggers an FSM state instead of just showing
    elif data == "ap:s:force_join_msg":
        bs = _load_settings()
        await state.set_state(AdminStates.edit_force_join_msg)
        kb = InlineKeyboardMarkup(inline_keyboard=[_settings_back_row()])
        await call.message.edit_text(
            f"{bold('📢 پیام فورس‌جوین')}\n\n"
            f"متن فعلی:\n{esc(bs.force_join_message)}\n\n"
            "متن جدید را وارد کنید:",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )

    elif data == "ap:s:panel_inactive_msg":
        bs = _load_settings()
        await state.set_state(AdminStates.edit_panel_inactive_msg)
        kb = InlineKeyboardMarkup(inline_keyboard=[_settings_back_row()])
        await call.message.edit_text(
            f"{bold('🚫 پیام غیرفعال بودن پنل')}\n\n"
            f"متن فعلی:\n{esc(bs.panel_inactive_msg)}\n\n"
            "متن جدید را وارد کنید:",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )

    elif data == "ap:s:order_confirm_msg":
        bs = _load_settings()
        cur = bs.order_confirm_msg if hasattr(bs, "order_confirm_msg") else ""
        await state.set_state(AdminStates.edit_order_confirm_msg)
        kb = InlineKeyboardMarkup(inline_keyboard=[_settings_back_row()])
        await call.message.edit_text(
            f"{bold('✅ متن تایید سفارش')}\n\n"
            f"متن فعلی:\n{esc(cur) if cur else italic('تنظیم نشده')}\n\n"
            "متن جدید را وارد کنید:\n"
            "_می‌توانید از \\{order\\_id\\} برای شماره سفارش استفاده کنید\\._",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )

    elif data == "ap:s:order_reject_msg":
        bs = _load_settings()
        cur = bs.order_reject_msg if hasattr(bs, "order_reject_msg") else ""
        await state.set_state(AdminStates.edit_order_reject_msg)
        kb = InlineKeyboardMarkup(inline_keyboard=[_settings_back_row()])
        await call.message.edit_text(
            f"{bold('❌ متن رد سفارش')}\n\n"
            f"متن فعلی:\n{esc(cur) if cur else italic('تنظیم نشده')}\n\n"
            "متن جدید را وارد کنید:\n"
            "_می‌توانید از \\{order\\_id\\} و \\{reason\\} استفاده کنید\\._",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )

    elif data == "ap:s:order_track_msg":
        bs = _load_settings()
        cur = bs.order_track_msg if hasattr(bs, "order_track_msg") else ""
        await state.set_state(AdminStates.edit_order_track_msg)
        kb = InlineKeyboardMarkup(inline_keyboard=[_settings_back_row()])
        await call.message.edit_text(
            f"{bold('🔍 متن رهگیری سفارش')}\n\n"
            f"متن فعلی:\n{esc(cur) if cur else italic('تنظیم نشده')}\n\n"
            "متن جدید را وارد کنید:\n"
            "_می‌توانید از \\{order\\_id\\} و \\{status\\} استفاده کنید\\._",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )

    # ── admin management ──
    elif data == "ap:adm:list":
        items = admins_db.all_items()
        if not items:
            lines = [italic("هیچ ادمینی ثبت نشده")]
        else:
            lines = []
            for aid, adm in items:
                uname = adm.get("username", "")
                perms = ", ".join(adm.get("permissions", []))
                lines.append(
                    f"• {esc('@' + uname) if uname else code(aid)} — {esc(perms)}"
                )
        text = f"{bold('📋 لیست ادمین‌ها')}\n\n" + "\n".join(lines)
        kb   = InlineKeyboardMarkup(inline_keyboard=[_home_back_row()])
        await call.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)

    # Bug fix 3: add by username
    elif data == "ap:adm:add":
        await state.set_state(AdminStates.add_admin_username)
        await _prompt_edit(call, "یوزرنیم تلگرام ادمین جدید را وارد کنید \\(بدون @\\):")

    # Bug fix 3: remove by username
    elif data == "ap:adm:remove":
        await state.set_state(AdminStates.remove_admin_username)
        await _prompt_edit(call, "یوزرنیم ادمینی که باید حذف شود را وارد کنید \\(بدون @\\):")

    # ── channel management ──
    elif data == "ap:ch:list":
        bs  = _load_settings()
        chs = bs.force_join_channels
        lst = "\n".join(f"• {esc(c)}" for c in chs) if chs else italic("بدون کانال")
        kb  = InlineKeyboardMarkup(inline_keyboard=[_home_back_row()])
        await call.message.edit_text(
            f"{bold('📢 کانال‌های فورس‌جوین')}\n\n{lst}",
            parse_mode="MarkdownV2", reply_markup=kb
        )

    elif data == "ap:ch:add":
        await state.set_state(AdminStates.add_channel)
        await _prompt_edit(call,
            "آیدی یا یوزرنیم کانال را وارد کنید \\(مثال: @mychannel یا \\-100xxxxxxx\\):"
        )

    elif data == "ap:ch:remove":
        await state.set_state(AdminStates.remove_channel)
        await _prompt_edit(call,
            "آیدی یا یوزرنیم کانالی که باید حذف شود را وارد کنید:"
        )

    await call.answer()


# ══════════════════════════════════════════════════════════
#  FSM — helpers
# ══════════════════════════════════════════════════════════

async def _prompt_edit(call: CallbackQuery, prompt: str):
    kb = InlineKeyboardMarkup(inline_keyboard=[_settings_back_row()])
    await call.message.edit_text(
        f"{bold('✏️ ویرایش')}\n\n{prompt}",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )


async def _done_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ بازگشت به تنظیمات", "ap:settings")],
        _home_back_row(),
    ])


# ══════════════════════════════════════════════════════════
#  FSM — settings text fields
# ══════════════════════════════════════════════════════════

@router.message(AdminStates.edit_welcome)
async def fsm_welcome(message: Message, state: FSMContext):
    bs = _load_settings()
    bs.welcome_msg = message.text
    _save_settings(bs)
    await state.clear()
    await message.answer("✅ پیام خوش‌آمد بروزرسانی شد\\.",
                         parse_mode="MarkdownV2", reply_markup=await _done_kb())


@router.message(AdminStates.edit_error)
async def fsm_error(message: Message, state: FSMContext):
    bs = _load_settings()
    bs.error_msg = message.text
    _save_settings(bs)
    await state.clear()
    await message.answer("✅ پیام خطا بروزرسانی شد\\.",
                         parse_mode="MarkdownV2", reply_markup=await _done_kb())


@router.message(AdminStates.edit_maintenance_msg)
async def fsm_maint_msg(message: Message, state: FSMContext):
    bs = _load_settings()
    bs.maintenance_msg = message.text
    _save_settings(bs)
    await state.clear()
    await message.answer("✅ پیام تعمیر بروزرسانی شد\\.",
                         parse_mode="MarkdownV2", reply_markup=await _done_kb())


@router.message(AdminStates.edit_watermark)
async def fsm_watermark(message: Message, state: FSMContext):
    bs = _load_settings()
    bs.watermark = message.text
    _save_settings(bs)
    await state.clear()
    await message.answer(
        f"✅ واترمارک بروزرسانی شد: {code(message.text)}",
        parse_mode="MarkdownV2", reply_markup=await _done_kb(),
    )


@router.message(AdminStates.edit_support)
async def fsm_support(message: Message, state: FSMContext):
    username = message.text.lstrip("@").strip()
    bs = _load_settings()
    bs.support_username = username
    _save_settings(bs)
    await state.clear()
    await message.answer(
        f"✅ پشتیبانی تنظیم شد: {esc('@' + username)}",
        parse_mode="MarkdownV2", reply_markup=await _done_kb(),
    )


@router.message(AdminStates.edit_payment)
async def fsm_payment(message: Message, state: FSMContext):
    bs = _load_settings()
    bs.payment_info = message.text
    _save_settings(bs)
    await state.clear()
    await message.answer("✅ اطلاعات پرداخت بروزرسانی شد\\.",
                         parse_mode="MarkdownV2", reply_markup=await _done_kb())


# Bug fix 2: handler for editable force-join message
@router.message(AdminStates.edit_force_join_msg)
async def fsm_force_join_msg(message: Message, state: FSMContext):
    bs = _load_settings()
    bs.force_join_message = message.text
    _save_settings(bs)
    await state.clear()
    await message.answer("✅ پیام فورس‌جوین بروزرسانی شد\\.",
                         parse_mode="MarkdownV2", reply_markup=await _done_kb())


@router.message(AdminStates.edit_panel_inactive_msg)
async def fsm_panel_inactive_msg(message: Message, state: FSMContext):
    bs = _load_settings()
    bs.panel_inactive_msg = message.text.strip()
    _save_settings(bs)
    await state.clear()
    await message.answer("✅ پیام غیرفعال بودن پنل بروزرسانی شد\\.",
                         parse_mode="MarkdownV2", reply_markup=await _done_kb())


@router.message(AdminStates.edit_order_confirm_msg)
async def fsm_order_confirm_msg(message: Message, state: FSMContext):
    bs = _load_settings()
    if hasattr(bs, "order_confirm_msg"):
        bs.order_confirm_msg = message.text.strip()
    else:
        bs.__dict__["order_confirm_msg"] = message.text.strip()
    _save_settings(bs)
    await state.clear()
    await message.answer("✅ متن تایید سفارش بروزرسانی شد\\.",
                         parse_mode="MarkdownV2", reply_markup=await _done_kb())


@router.message(AdminStates.edit_order_reject_msg)
async def fsm_order_reject_msg(message: Message, state: FSMContext):
    bs = _load_settings()
    if hasattr(bs, "order_reject_msg"):
        bs.order_reject_msg = message.text.strip()
    else:
        bs.__dict__["order_reject_msg"] = message.text.strip()
    _save_settings(bs)
    await state.clear()
    await message.answer("✅ متن رد سفارش بروزرسانی شد\\.",
                         parse_mode="MarkdownV2", reply_markup=await _done_kb())


@router.message(AdminStates.edit_order_track_msg)
async def fsm_order_track_msg(message: Message, state: FSMContext):
    bs = _load_settings()
    if hasattr(bs, "order_track_msg"):
        bs.order_track_msg = message.text.strip()
    else:
        bs.__dict__["order_track_msg"] = message.text.strip()
    _save_settings(bs)
    await state.clear()
    await message.answer("✅ متن رهگیری سفارش بروزرسانی شد\\.",
                         parse_mode="MarkdownV2", reply_markup=await _done_kb())


@router.message(AdminStates.edit_open_time)
async def fsm_open_time(message: Message, state: FSMContext):
    t = message.text.strip()
    if len(t) != 5 or ":" not in t:
        await message.answer("❌ فرمت اشتباه\\. مثال: `09:00`", parse_mode="MarkdownV2")
        return
    bs = _load_settings()
    wh = bs.working_hours.copy()
    wh["open_time"] = t
    bs.working_hours = wh
    _save_settings(bs)
    await state.set_state(AdminStates.edit_close_time)
    await message.answer(
        f"✅ ساعت شروع: {code(t)}\n\nحالا ساعت پایان را وارد کنید \\(مثال: `21:00`\\):",
        parse_mode="MarkdownV2",
    )


@router.message(AdminStates.edit_close_time)
async def fsm_close_time(message: Message, state: FSMContext):
    t = message.text.strip()
    if len(t) != 5 or ":" not in t:
        await message.answer("❌ فرمت اشتباه\\. مثال: `21:00`", parse_mode="MarkdownV2")
        return
    bs = _load_settings()
    wh = bs.working_hours.copy()
    wh["close_time"] = t
    bs.working_hours = wh
    _save_settings(bs)
    await state.clear()
    open_t = wh.get("open_time", "?")
    await message.answer(
        f"✅ ساعت کاری تنظیم شد: {code(open_t + ' - ' + t)}",
        parse_mode="MarkdownV2", reply_markup=await _done_kb(),
    )


@router.message(AdminStates.edit_flood_max)
async def fsm_flood_max(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2")
        return
    bs = _load_settings()
    af = bs.anti_flood.copy()
    af["max_messages"] = int(message.text)
    bs.anti_flood = af
    _save_settings(bs)
    await state.set_state(AdminStates.edit_flood_interval)
    await message.answer(
        f"✅ حداکثر پیام: {code(message.text)}\n\nحالا بازه زمانی را \\(ثانیه\\) وارد کنید:",
        parse_mode="MarkdownV2",
    )


@router.message(AdminStates.edit_flood_interval)
async def fsm_flood_interval(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2")
        return
    bs = _load_settings()
    af = bs.anti_flood.copy()
    af["interval_seconds"] = int(message.text)
    bs.anti_flood = af
    _save_settings(bs)
    await state.set_state(AdminStates.edit_flood_ban)
    await message.answer(
        f"✅ بازه: {code(message.text + 's')}\n\nمدت بن فلاد را \\(ثانیه\\) وارد کنید:",
        parse_mode="MarkdownV2",
    )


@router.message(AdminStates.edit_flood_ban)
async def fsm_flood_ban(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2")
        return
    bs = _load_settings()
    af = bs.anti_flood.copy()
    af["ban_duration_seconds"] = int(message.text)
    bs.anti_flood = af
    _save_settings(bs)
    await state.clear()
    await message.answer("✅ تنظیمات آنتی‌فلاد ذخیره شد\\.",
                         parse_mode="MarkdownV2", reply_markup=await _done_kb())


# ══════════════════════════════════════════════════════════
#  FSM — admin management  (Bug fix 3: by username + getChat)
# ══════════════════════════════════════════════════════════

@router.message(AdminStates.add_admin_username)
async def fsm_add_admin_username(message: Message, state: FSMContext, bot: Bot):
    """Receive username, resolve numeric ID via getChat, then proceed to perm selection."""
    username = message.text.lstrip("@").strip()
    if not username:
        await message.answer("❌ یوزرنیم نمی‌تواند خالی باشد\\.", parse_mode="MarkdownV2")
        return

    try:
        chat = await bot.get_chat(f"@{username}")
        uid  = str(chat.id)
    except Exception as e:
        await message.answer(
            f"❌ کاربر {esc('@' + username)} پیدا نشد\\.\nخطا: {esc(str(e))}",
            parse_mode="MarkdownV2",
        )
        return

    await state.update_data(new_admin_id=uid, new_admin_username=username)
    await state.set_state(AdminStates.add_admin_perm)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("👑 همه دسترسی‌ها",  f"ap:adm:perm:all:{uid}"),
         _btn("⚙️ تنظیمات",        f"ap:adm:perm:settings:{uid}")],
        [_btn("👥 کاربران",         f"ap:adm:perm:users:{uid}"),
         _btn("📊 آمار",            f"ap:adm:perm:stats:{uid}")],
        [_btn("📋 پنل‌ها",          f"ap:adm:perm:panels:{uid}"),
         _btn("🎟 تخفیف",          f"ap:adm:perm:discounts:{uid}")],
        _home_back_row(),
    ])
    await message.answer(
        f"یوزرنیم: {esc('@' + username)}\nآیدی: {code(uid)}\n\nسطح دسترسی را انتخاب کنید:",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("ap:adm:perm:"))
async def cb_add_admin_perm(call: CallbackQuery, state: FSMContext):
    parts    = call.data.split(":")
    perm     = parts[3]
    uid      = parts[4]
    fsm_data = await state.get_data()
    username = fsm_data.get("new_admin_username", "")

    existing = admins_db.get(uid)
    if existing:
        perms = existing.get("permissions", [])
        if perm not in perms:
            perms.append(perm)
        admins_db.update(uid, {"permissions": perms, "username": username})
    else:
        admin = Admin(
            user_id=uid,
            username=username,
            permissions=[perm],
            added_by=str(call.from_user.id),
        )
        admins_db.set(uid, admin.to_dict())

    users_db.update(uid, {"is_admin": True})
    await state.clear()
    await call.message.edit_text(
        f"✅ ادمین {esc('@' + username) if username else code(uid)} "
        f"با دسترسی {code(perm)} اضافه شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 مدیریت ادمین‌ها", "ap:admins")],
        ]),
    )
    await call.answer()


@router.message(AdminStates.remove_admin_username)
async def fsm_remove_admin(message: Message, state: FSMContext, bot: Bot):
    """Resolve username → numeric id via getChat (fallback: search admins_db)."""
    username = message.text.lstrip("@").strip()
    uid: str | None = None

    try:
        chat = await bot.get_chat(f"@{username}")
        uid  = str(chat.id)
    except Exception:
        # Fallback: linear search by stored username field
        for aid, adm in admins_db.all_items():
            if adm.get("username", "").lower() == username.lower():
                uid = aid
                break

    if uid is None:
        await message.answer(
            f"❌ ادمینی با یوزرنیم {esc('@' + username)} یافت نشد\\.",
            parse_mode="MarkdownV2",
        )
        await state.clear()
        return

    removed = admins_db.delete(uid)
    users_db.update(uid, {"is_admin": False})
    await state.clear()

    txt = (
        f"✅ ادمین {esc('@' + username)} \\({code(uid)}\\) حذف شد\\."
        if removed else
        f"❌ ادمینی با آیدی {code(uid)} در دیتابیس یافت نشد\\."
    )
    await message.answer(
        txt,
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔙 مدیریت ادمین‌ها", "ap:admins")],
        ]),
    )


# ══════════════════════════════════════════════════════════
#  FSM — channel management
# ══════════════════════════════════════════════════════════

@router.message(AdminStates.add_channel)
async def fsm_add_channel(message: Message, state: FSMContext):
    ch = message.text.strip()
    bs = _load_settings()
    if ch not in bs.force_join_channels:
        bs.force_join_channels.append(ch)
        _save_settings(bs)
        txt = f"✅ کانال {esc(ch)} اضافه شد\\."
    else:
        txt = f"⚠️ کانال {esc(ch)} قبلاً وجود دارد\\."
    await state.clear()
    await message.answer(txt, parse_mode="MarkdownV2",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [_btn("🔙 مدیریت کانال‌ها", "ap:channels")],
                         ]))


@router.message(AdminStates.remove_channel)
async def fsm_remove_channel(message: Message, state: FSMContext):
    ch = message.text.strip()
    bs = _load_settings()
    if ch in bs.force_join_channels:
        bs.force_join_channels.remove(ch)
        _save_settings(bs)
        txt = f"✅ کانال {esc(ch)} حذف شد\\."
    else:
        txt = f"❌ کانال {esc(ch)} پیدا نشد\\."
    await state.clear()
    await message.answer(txt, parse_mode="MarkdownV2",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [_btn("🔙 مدیریت کانال‌ها", "ap:channels")],
                         ]))


# ══════════════════════════════════════════════════════════
#  FSM — password change
# ══════════════════════════════════════════════════════════

@router.message(AdminStates.change_password)
async def fsm_change_pass(message: Message, state: FSMContext):
    await message.delete()
    await state.update_data(new_pass=message.text)
    await state.set_state(AdminStates.change_password_confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back_row()])
    await message.answer("رمز جدید را مجدداً وارد کنید تا تأیید شود:",
                         parse_mode="MarkdownV2", reply_markup=kb)


@router.message(AdminStates.change_password_confirm)
async def fsm_change_pass_confirm(message: Message, state: FSMContext):
    await message.delete()
    data     = await state.get_data()
    new_pass = data.get("new_pass", "")
    if message.text == new_pass:
        config.ADMIN_PASSWORD = new_pass
        await state.clear()
        await message.answer(
            "✅ رمز پنل با موفقیت تغییر کرد\\.\n\n"
            "⚠️ برای ماندگاری، متغیر محیطی `ADMIN_PASSWORD` را هم تغییر دهید\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [_btn("🏠 خانه", "ap:home")]
            ]),
        )
    else:
        await state.clear()
        await message.answer(
            "❌ رمزها مطابقت ندارند\\. دوباره از /admin امتحان کنید\\.",
            parse_mode="MarkdownV2",
        )


# ══════════════════════════════════════════════════════════
#  FSM — backup restore  (New feature 1)
# ══════════════════════════════════════════════════════════

@router.message(AdminStates.restore_backup, F.document)
async def fsm_restore_backup(message: Message, state: FSMContext, bot: Bot):
    await _do_restore(message, state, bot)


# ══════════════════════════════════════════════════════════
#  FSM — quick discount creation  (New feature 2)
# ══════════════════════════════════════════════════════════

@router.message(AdminStates.disc_code)
async def fsm_disc_code(message: Message, state: FSMContext):
    code_val = message.text.strip().upper()
    if not code_val.isalnum():
        await message.answer(
            "❌ کد تخفیف فقط می‌تواند شامل حروف انگلیسی و اعداد باشد\\.",
            parse_mode="MarkdownV2",
        )
        return
    if discounts_db.get(code_val):
        await message.answer(f"❌ کد {code(code_val)} قبلاً وجود دارد\\.",
                             parse_mode="MarkdownV2")
        return
    await state.update_data(disc_code=code_val)
    await state.set_state(AdminStates.disc_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📉 درصدی \\(مثال: 20%\\)", "ap:dtype:percent"),
         _btn("💵 مبلغ ثابت",              "ap:dtype:fixed")],
        _home_back_row(),
    ])
    await message.answer(
        f"کد: {code(code_val)}\n\nنوع تخفیف را انتخاب کنید:",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


@router.callback_query(F.data.startswith("ap:dtype:"))
async def cb_disc_type(call: CallbackQuery, state: FSMContext):
    dtype = call.data.split(":")[2]
    await state.update_data(disc_type=dtype)
    await state.set_state(AdminStates.disc_value)
    hint = ("درصد تخفیف را وارد کنید \\(مثال: 20\\):"
            if dtype == "percent"
            else "مبلغ تخفیف را وارد کنید \\(تومان\\):")
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back_row()])
    await call.message.edit_text(
        f"{bold('🎟 مقدار تخفیف')}\n\n{hint}",
        parse_mode="MarkdownV2", reply_markup=kb,
    )
    await call.answer()


@router.message(AdminStates.disc_value)
async def fsm_disc_value(message: Message, state: FSMContext):
    try:
        val = float(message.text.strip())
    except ValueError:
        await message.answer("❌ لطفاً یک عدد معتبر وارد کنید:", parse_mode="MarkdownV2")
        return
    await state.update_data(disc_value=val)
    await state.set_state(AdminStates.disc_capacity)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("∞ نامحدود", "ap:dcap:0")],
        _home_back_row(),
    ])
    await message.answer(
        f"مقدار: {code(str(val))}\n\nظرفیت استفاده را وارد کنید \\(0 \\= نامحدود\\):",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


@router.callback_query(F.data == "ap:dcap:0")
async def cb_disc_cap_unlimited(call: CallbackQuery, state: FSMContext):
    await state.update_data(disc_capacity=0)
    await _disc_ask_expiry(call.message, state)
    await call.answer()


@router.message(AdminStates.disc_capacity)
async def fsm_disc_capacity(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2")
        return
    await state.update_data(disc_capacity=int(message.text))
    await _disc_ask_expiry(message, state)


async def _disc_ask_expiry(target, state: FSMContext):
    await state.set_state(AdminStates.disc_expiry)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📅 ۷ روز",        "ap:dexp:7"),
         _btn("📅 ۳۰ روز",       "ap:dexp:30"),
         _btn("♾ بدون انقضا",   "ap:dexp:0")],
        _home_back_row(),
    ])
    txt = f"{bold('📅 تاریخ انقضا')}\n\nتعداد روز وارد کنید یا دکمه انتخاب کنید:"
    if hasattr(target, "edit_text"):
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data.startswith("ap:dexp:"))
async def cb_disc_expiry(call: CallbackQuery, state: FSMContext):
    days   = int(call.data.split(":")[2])
    expiry = (datetime.utcnow() + timedelta(days=days)).isoformat() if days > 0 else None
    await state.update_data(disc_expiry=expiry)
    await _disc_save(call.message, state)
    await call.answer()


@router.message(AdminStates.disc_expiry)
async def fsm_disc_expiry(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ تعداد روز را به صورت عدد وارد کنید:", parse_mode="MarkdownV2")
        return
    days   = int(message.text)
    expiry = (datetime.utcnow() + timedelta(days=days)).isoformat() if days > 0 else None
    await state.update_data(disc_expiry=expiry)
    await _disc_save(message, state)


async def _disc_save(target, state: FSMContext):
    data     = await state.get_data()
    code_val = data.get("disc_code", "")
    dtype    = data.get("disc_type", "percent")
    val      = data.get("disc_value", 0.0)
    cap      = data.get("disc_capacity", 0)
    expiry   = data.get("disc_expiry")

    discount = Discount(
        code=code_val, type=dtype, value=val,
        capacity=cap, expiry=expiry, is_active=True,
    )
    discounts_db.set(code_val, discount.to_dict())
    await state.clear()

    exp_txt  = esc(expiry[:10]) if expiry else italic("بدون انقضا")
    type_txt = "درصدی" if dtype == "percent" else "مبلغ ثابت"

    txt = (
        f"{bold('✅ کد تخفیف ایجاد شد')}\n\n"
        f"🎟 کد: {code(code_val)}\n"
        f"📉 نوع: {esc(type_txt)}\n"
        f"💰 مقدار: {code(str(val))}\n"
        f"👥 ظرفیت: {code(str(cap)) if cap else italic('نامحدود')}\n"
        f"📅 انقضا: {exp_txt}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🎟 کد جدید", "ap:disc_new"), _btn("🏠 خانه", "ap:home")],
    ])
    if hasattr(target, "edit_text"):
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════
#  FSM — form destination group  (New feature 4)
# ══════════════════════════════════════════════════════════

@router.message(AdminStates.edit_form_dest)
async def fsm_edit_form_dest(message: Message, state: FSMContext):
    data  = await state.get_data()
    fid   = data.get("formdest_fid", "")
    group = message.text.strip()
    if group == "0":
        group = ""

    raw = forms_db.get(fid)
    if not raw:
        await message.answer("❌ فرم یافت نشد\\.", parse_mode="MarkdownV2")
        await state.clear()
        return

    forms_db.update(fid, {"destination_group": group})
    await state.clear()

    form_title = raw.get("title", "بی‌نام")
    if group:
        txt = (f"✅ گروه مقصد فرم {bold(esc(form_title))} تنظیم شد:\n"
               f"{code(group)}")
    else:
        txt = f"✅ گروه مقصد فرم {bold(esc(form_title))} پاک شد\\."

    await message.answer(
        txt,
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("📋 مقصد فرم‌ها", "ap:formdests"),
             _btn("🏠 خانه",        "ap:home")],
        ]),
    )