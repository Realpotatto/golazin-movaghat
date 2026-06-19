import asyncio
import logging
from datetime import datetime
from typing import Optional, Union

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.types import Message

from json_manager import JsonManager
from config import Config

logger = logging.getLogger(__name__)


def escape_md(text: str) -> str:
    chars = r"\_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text


async def broadcast_now(
    bot: Bot,
    text: str,
    json_manager: JsonManager,
    parse_mode: str = "MarkdownV2",
    delay: float = 0.05,
) -> dict:
    users = await json_manager.get_all_users()
    total = len(users)
    success = 0
    failed = 0
    blocked = []

    for user in users:
        uid = user.get("user_id") or user.get("id")
        if not uid:
            continue
        try:
            await bot.send_message(chat_id=uid, text=text, parse_mode=parse_mode)
            success += 1
        except TelegramForbiddenError:
            blocked.append(uid)
            failed += 1
        except TelegramBadRequest as e:
            logger.warning(f"BadRequest for {uid}: {e}")
            failed += 1
        except Exception as e:
            logger.error(f"Broadcast error for {uid}: {e}")
            failed += 1
        await asyncio.sleep(delay)

    if blocked:
        await _remove_blocked_users(json_manager, blocked)

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "blocked_removed": len(blocked),
    }


async def broadcast_scheduled(
    bot: Bot,
    text: str,
    json_manager: JsonManager,
    send_at: datetime,
    parse_mode: str = "MarkdownV2",
) -> None:
    now = datetime.now()
    delta = (send_at - now).total_seconds()
    if delta > 0:
        await asyncio.sleep(delta)
    result = await broadcast_now(bot, text, json_manager, parse_mode)
    logger.info(f"Scheduled broadcast done: {result}")


async def _remove_blocked_users(json_manager: JsonManager, blocked_ids: list) -> None:
    for uid in blocked_ids:
        try:
            await json_manager.remove_user(uid)
            logger.info(f"Removed blocked user: {uid}")
        except Exception as e:
            logger.error(f"Failed to remove blocked user {uid}: {e}")


async def send_broadcast_report(
    bot: Bot,
    admin_id: int,
    result: dict,
) -> None:
    text = (
        "📢 *گزارش برودکست*\n\n"
        f"👥 کل کاربران: `{result['total']}`\n"
        f"✅ موفق: `{result['success']}`\n"
        f"❌ ناموفق: `{result['failed']}`\n"
        f"🚫 حذف‌شده \\(بلاک\\): `{result['blocked_removed']}`"
    )
    await bot.send_message(chat_id=admin_id, text=text, parse_mode="MarkdownV2")
