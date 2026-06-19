import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

import config
from models import User, Admin
from utils.db import users_db, admins_db
from utils.mdv2 import esc, bold

logger = logging.getLogger(__name__)
router = Router(name="admin_auth")


# ─────────────────────── States ───────────────────────

class AuthStates(StatesGroup):
    waiting_password = State()


# ─────────────────────── Helpers ──────────────────────

def _get_or_create_user(message: Message) -> dict:
    uid = str(message.from_user.id)
    existing = users_db.get(uid)
    if existing:
        users_db.update(uid, {"last_seen": datetime.utcnow().isoformat()})
        return users_db.get(uid)
    user = User(
        user_id=uid,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
        last_name=message.from_user.last_name or "",
    )
    users_db.set(uid, user.to_dict())
    return user.to_dict()


def _is_admin(user_id: str) -> bool:
    user = users_db.get(user_id)
    if user and user.get("is_admin"):
        return True
    if admins_db.exists(user_id):
        return True
    try:
        if int(user_id) in config.ADMIN_IDS:
            return True
    except (ValueError, TypeError):
        pass
    return False


def _promote_to_admin(message: Message):
    uid = str(message.from_user.id)
    username = message.from_user.username or ""
    users_db.update(uid, {"is_admin": True})
    if not admins_db.exists(uid):
        admin = Admin(
            user_id=uid,
            username=username,
            permissions=["all"],
            added_by="self",
        )
        admins_db.set(uid, admin.to_dict())


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="auth_cancel")]
    ])


def _admin_welcome_text(first_name: str) -> str:
    name = esc(first_name)
    lines = [
        bold("🔐 پنل مدیریت IrForge"),
        "",
        f"سلام {name}\\! با موفقیت وارد پنل ادمین شدی\\.",
        "",
        bold("📋 دستورات اصلی:"),
        f"• /admin — باز کردن پنل ادمین",
        f"• /stats — آمار سریع ربات",
        f"• /backup — دریافت بک‌آپ JSON",
        "",
        bold("📌 راهنمای سریع:"),
        f"• از منوی ادمین میتونی تمام تنظیمات رو مدیریت کنی",
        f"• برای اضافه کردن ادمین جدید به بخش مدیریت ادمین‌ها برو",
        f"• تنظیمات ربات از بخش تنظیمات قابل تغییره",
        "",
        f"_نسخه IrForge v2\\.0_",
    ]
    return "\n".join(lines)


# ─────────────────────── Handlers ─────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    _get_or_create_user(message)
    uid = str(message.from_user.id)

    if _is_admin(uid):
        from handlers.admin_panel import send_main_menu
        await send_main_menu(message)
        return

    await state.set_state(AuthStates.waiting_password)
    await message.answer(
        f"{bold('🔐 احراز هویت ادمین')}\n\n"
        f"رمز پنل ادمین را وارد کنید:",
        parse_mode="MarkdownV2",
        reply_markup=_cancel_kb(),
    )


@router.message(AuthStates.waiting_password)
async def process_password(message: Message, state: FSMContext):
    await message.delete()
    uid = str(message.from_user.id)

    if message.text and message.text.strip() == config.ADMIN_PASSWORD:
        _get_or_create_user(message)
        _promote_to_admin(message)
        await state.clear()

        logger.info("New admin authenticated: %s (%s)", message.from_user.username, uid)

        await message.answer(
            _admin_welcome_text(message.from_user.first_name or "ادمین"),
            parse_mode="MarkdownV2",
        )

        from handlers.admin_panel import send_main_menu
        await send_main_menu(message)
    else:
        await message.answer(
            f"{bold('❌ رمز اشتباه است\\!')}\n\nدوباره تلاش کنید:",
            parse_mode="MarkdownV2",
            reply_markup=_cancel_kb(),
        )


@router.callback_query(F.data == "auth_cancel")
async def cb_auth_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        esc("❌ احراز هویت لغو شد."),
        parse_mode="MarkdownV2",
    )
    await call.answer()
