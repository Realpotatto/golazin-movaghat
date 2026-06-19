import logging
import traceback
from datetime import datetime
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from config import Config

_std_logger = logging.getLogger(__name__)


def escape_md(text: str) -> str:
    chars = r"\_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text


async def log_error(
    bot: Bot,
    config: Config,
    error: Exception,
    context: Optional[str] = None,
    user_id: Optional[int] = None,
    extra: Optional[dict] = None,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    error_type = escape_md(type(error).__name__)
    error_msg = escape_md(str(error))
    safe_context = escape_md(context) if context else "نامشخص"
    safe_now = escape_md(now)

    tb = traceback.format_exc()
    tb_lines = tb.strip().splitlines()
    short_tb = "\n".join(tb_lines[-6:]) if len(tb_lines) > 6 else tb.strip()
    safe_tb = escape_md(short_tb)

    user_line = f"\n👤 یوزر: `{user_id}`" if user_id else ""

    extra_lines = ""
    if extra:
        for k, v in extra.items():
            sk = escape_md(str(k))
            sv = escape_md(str(v))
            extra_lines += f"\n▫️ *{sk}*: `{sv}`"

    text = (
        "🚨 *خطا ثبت شد*\n\n"
        f"🕐 زمان: `{safe_now}`\n"
        f"⚠️ نوع خطا: `{error_type}`\n"
        f"📌 متن خطا: `{error_msg}`\n"
        f"📍 کانتکست: {safe_context}"
        f"{user_line}"
        f"{extra_lines}\n\n"
        f"📋 *Traceback:*\n"
        f"```\n{safe_tb}\n```"
    )

    _std_logger.error(
        f"[{now}] {type(error).__name__}: {error} | context={context} | user={user_id}"
    )

    try:
        target = getattr(config, "LOG_GROUP_ID", None) or config.ADMIN_ID
        await bot.send_message(
            chat_id=target,
            text=text,
            parse_mode="MarkdownV2",
        )
    except TelegramBadRequest as e:
        _std_logger.error(f"log_error TelegramBadRequest: {e}")
    except Exception as e:
        _std_logger.error(f"log_error failed to send: {e}")


async def log_warning(
    bot: Bot,
    config: Config,
    message: str,
    context: Optional[str] = None,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_now = escape_md(now)
    safe_msg = escape_md(message)
    safe_ctx = escape_md(context) if context else "نامشخص"

    text = (
        "⚠️ *هشدار سیستم*\n\n"
        f"🕐 زمان: `{safe_now}`\n"
        f"📝 پیام: {safe_msg}\n"
        f"📍 کانتکست: {safe_ctx}"
    )

    _std_logger.warning(f"[{now}] WARNING: {message} | context={context}")

    try:
        target = getattr(config, "LOG_GROUP_ID", None) or config.ADMIN_ID
        await bot.send_message(
            chat_id=target,
            text=text,
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        _std_logger.error(f"log_warning failed to send: {e}")


async def log_info(
    bot: Bot,
    config: Config,
    message: str,
    context: Optional[str] = None,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_now = escape_md(now)
    safe_msg = escape_md(message)
    safe_ctx = escape_md(context) if context else "نامشخص"

    text = (
        "ℹ️ *لاگ سیستم*\n\n"
        f"🕐 زمان: `{safe_now}`\n"
        f"📝 پیام: {safe_msg}\n"
        f"📍 کانتکست: {safe_ctx}"
    )

    _std_logger.info(f"[{now}] INFO: {message} | context={context}")

    try:
        target = getattr(config, "LOG_GROUP_ID", None) or config.ADMIN_ID
        await bot.send_message(
            chat_id=target,
            text=text,
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        _std_logger.error(f"log_info failed to send: {e}")
