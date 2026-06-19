import io
import json
import logging
import os
import zipfile
from datetime import datetime
from typing import List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile

from config import Config
from json_manager import JsonManager

_std_logger = logging.getLogger(__name__)


def escape_md(text: str) -> str:
    chars = r"\_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text


async def create_backup_zip(json_manager: JsonManager) -> tuple[bytes, int, List[str]]:
    data_map = await json_manager.export_all()
    zip_buffer = io.BytesIO()
    file_names = []

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename, content in data_map.items():
            if not filename.endswith(".json"):
                filename = f"{filename}.json"
            json_bytes = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr(filename, json_bytes)
            file_names.append(filename)
            _std_logger.info(f"Packed: {filename} ({len(json_bytes)} bytes)")

    zip_buffer.seek(0)
    raw = zip_buffer.read()
    return raw, len(raw), file_names


async def send_backup_to_admin(
    bot: Bot,
    config: Config,
    json_manager: JsonManager,
    requested_by: Optional[int] = None,
) -> None:
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    filename_ts = now.strftime("%Y%m%d_%H%M%S")
    zip_filename = f"irforge_backup_{filename_ts}.zip"

    safe_now = escape_md(now_str)
    safe_filename = escape_md(zip_filename)

    try:
        zip_bytes, zip_size, file_names = await create_backup_zip(json_manager)
    except Exception as e:
        _std_logger.error(f"create_backup_zip failed: {e}")
        await _send_backup_failure(bot, config, e, now_str)
        return

    size_kb = round(zip_size / 1024, 2)
    safe_size = escape_md(str(size_kb))
    safe_count = str(len(file_names))

    files_list = ""
    for f in file_names:
        files_list += f"▫️ `{escape_md(f)}`\n"

    requester_line = ""
    if requested_by:
        requester_line = f"\n👤 درخواست‌دهنده: `{requested_by}`"

    caption = (
        "📦 *بکاپ کامل IrForge*\n\n"
        f"🕐 زمان: `{safe_now}`\n"
        f"📁 نام فایل: `{safe_filename}`\n"
        f"📊 حجم: `{safe_size} KB`\n"
        f"🗂 تعداد فایل‌ها: `{safe_count}`"
        f"{requester_line}\n\n"
        f"📋 *فایل‌های بکاپ:*\n{files_list}"
    )

    try:
        file_input = BufferedInputFile(zip_bytes, filename=zip_filename)
        await bot.send_document(
            chat_id=config.ADMIN_ID,
            document=file_input,
            caption=caption,
            parse_mode="MarkdownV2",
        )
        _std_logger.info(f"Backup sent to admin: {zip_filename} ({size_kb} KB)")
    except TelegramBadRequest as e:
        _std_logger.error(f"send_backup TelegramBadRequest: {e}")
        await _send_backup_failure(bot, config, e, now_str)
    except Exception as e:
        _std_logger.error(f"send_backup failed: {e}")
        await _send_backup_failure(bot, config, e, now_str)


async def send_single_json(
    bot: Bot,
    config: Config,
    json_manager: JsonManager,
    key: str,
) -> None:
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    filename_ts = now.strftime("%Y%m%d_%H%M%S")
    filename = f"{key}_{filename_ts}.json"
    safe_now = escape_md(now_str)
    safe_key = escape_md(key)

    try:
        data = await json_manager.get_all(key)
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    except Exception as e:
        _std_logger.error(f"send_single_json read failed for {key}: {e}")
        await _send_backup_failure(bot, config, e, now_str)
        return

    caption = (
        "📄 *خروجی JSON*\n\n"
        f"🗝 کلید: `{safe_key}`\n"
        f"🕐 زمان: `{safe_now}`\n"
        f"📊 حجم: `{round(len(json_bytes)/1024, 2)} KB`"
    )

    try:
        file_input = BufferedInputFile(json_bytes, filename=filename)
        await bot.send_document(
            chat_id=config.ADMIN_ID,
            document=file_input,
            caption=caption,
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        _std_logger.error(f"send_single_json send failed: {e}")
        await _send_backup_failure(bot, config, e, now_str)


async def _send_backup_failure(
    bot: Bot,
    config: Config,
    error: Exception,
    now_str: str,
) -> None:
    safe_now = escape_md(now_str)
    error_type = escape_md(type(error).__name__)
    error_msg = escape_md(str(error))

    text = (
        "❌ *خطا در ارسال بکاپ*\n\n"
        f"🕐 زمان: `{safe_now}`\n"
        f"⚠️ نوع خطا: `{error_type}`\n"
        f"📝 پیام: `{error_msg}`"
    )

    try:
        await bot.send_message(
            chat_id=config.ADMIN_ID,
            text=text,
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        _std_logger.error(f"_send_backup_failure itself failed: {e}")
