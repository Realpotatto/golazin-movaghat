import logging
from datetime import datetime
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from config import Config

logger = logging.getLogger(__name__)


def escape_md(text: str) -> str:
    chars = r"\_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text


async def notify_new_user(
    bot: Bot,
    config: Config,
    user_id: int,
    username: Optional[str],
    full_name: str,
    total_users: int,
) -> None:
    safe_name = escape_md(full_name)
    safe_username = escape_md(f"@{username}") if username else "ندارد"
    joined_at = escape_md(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    text = (
        "👤 *کاربر جدید ثبت شد*\n\n"
        f"🆔 آیدی: `{user_id}`\n"
        f"👤 نام: {safe_name}\n"
        f"📛 یوزرنیم: {safe_username}\n"
        f"🕐 زمان عضویت: `{joined_at}`\n"
        f"📊 کل کاربران: `{total_users}`"
    )

    try:
        await bot.send_message(
            chat_id=config.ADMIN_ID,
            text=text,
            parse_mode="MarkdownV2",
        )
    except TelegramBadRequest as e:
        logger.error(f"notify_new_user TelegramBadRequest: {e}")
    except Exception as e:
        logger.error(f"notify_new_user error: {e}")


async def notify_new_order(
    bot: Bot,
    config: Config,
    order_id: str,
    user_id: int,
    username: Optional[str],
    full_name: str,
    details: dict,
) -> None:
    safe_name = escape_md(full_name)
    safe_username = escape_md(f"@{username}") if username else "ندارد"
    safe_order_id = escape_md(order_id)
    submitted_at = escape_md(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    fields = ""
    for key, val in details.items():
        safe_key = escape_md(str(key))
        safe_val = escape_md(str(val))
        fields += f"▫️ *{safe_key}*: {safe_val}\n"

    text = (
        "🛒 *سفارش \\/ فرم جدید*\n\n"
        f"🔖 شناسه: `{safe_order_id}`\n"
        f"👤 کاربر: {safe_name}\n"
        f"📛 یوزرنیم: {safe_username}\n"
        f"🆔 آیدی: `{user_id}`\n"
        f"🕐 زمان: `{submitted_at}`\n\n"
        f"📋 *جزئیات:*\n{fields}"
    )

    try:
        await bot.send_message(
            chat_id=config.ADMIN_ID,
            text=text,
            parse_mode="MarkdownV2",
        )
    except TelegramBadRequest as e:
        logger.error(f"notify_new_order TelegramBadRequest: {e}")
    except Exception as e:
        logger.error(f"notify_new_order error: {e}")


async def notify_new_receipt(
    bot: Bot,
    config: Config,
    receipt_id: str,
    user_id: int,
    username: Optional[str],
    full_name: str,
    amount: Optional[str] = None,
    file_id: Optional[str] = None,
    description: Optional[str] = None,
) -> None:
    safe_name = escape_md(full_name)
    safe_username = escape_md(f"@{username}") if username else "ندارد"
    safe_receipt_id = escape_md(receipt_id)
    submitted_at = escape_md(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    safe_amount = escape_md(str(amount)) if amount else "نامشخص"
    safe_desc = escape_md(description) if description else "ندارد"

    text = (
        "🧾 *رسید جدید دریافت شد*\n\n"
        f"🔖 شناسه رسید: `{safe_receipt_id}`\n"
        f"👤 کاربر: {safe_name}\n"
        f"📛 یوزرنیم: {safe_username}\n"
        f"🆔 آیدی: `{user_id}`\n"
        f"💰 مبلغ: `{safe_amount}`\n"
        f"📝 توضیحات: {safe_desc}\n"
        f"🕐 زمان: `{submitted_at}`"
    )

    try:
        if file_id:
            await bot.send_photo(
                chat_id=config.ADMIN_ID,
                photo=file_id,
                caption=text,
                parse_mode="MarkdownV2",
            )
        else:
            await bot.send_message(
                chat_id=config.ADMIN_ID,
                text=text,
                parse_mode="MarkdownV2",
            )
    except TelegramBadRequest as e:
        logger.error(f"notify_new_receipt TelegramBadRequest: {e}")
    except Exception as e:
        logger.error(f"notify_new_receipt error: {e}")
