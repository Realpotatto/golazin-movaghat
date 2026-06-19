import asyncio
import logging
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


class PingService:
    def __init__(
        self,
        bot: Bot,
        config: Config,
        interval_minutes: int = 5,
    ):
        self.bot = bot
        self.config = config
        self.interval = interval_minutes * 60
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._consecutive_failures = 0
        self._max_failures = 3

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        _std_logger.info("PingService started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _std_logger.info("PingService stopped")

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.interval)
            await self.ping_once()

    async def ping_once(self) -> bool:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            me = await self.bot.get_me()
            self._consecutive_failures = 0
            _std_logger.info(f"[{now}] Ping OK — @{me.username}")
            return True
        except Exception as e:
            self._consecutive_failures += 1
            _std_logger.error(
                f"[{now}] Ping FAILED ({self._consecutive_failures}): {e}"
            )
            await self._send_failure_alert(e, now)
            return False

    async def _send_failure_alert(self, error: Exception, now: str) -> None:
        safe_now = escape_md(now)
        error_type = escape_md(type(error).__name__)
        error_msg = escape_md(str(error))
        failures = self._consecutive_failures

        text = (
            "🔴 *هشدار: بات پاسخ نمی‌دهد\\!*\n\n"
            f"🕐 زمان: `{safe_now}`\n"
            f"⚠️ نوع خطا: `{error_type}`\n"
            f"📝 پیام: `{error_msg}`\n"
            f"🔁 تعداد خطاهای متوالی: `{failures}`"
        )

        if failures >= self._max_failures:
            text += (
                "\n\n🚨 *بیش از حد مجاز خطا\\!*\n"
                "لطفاً هرچه سریع‌تر بررسی کنید\\."
            )

        try:
            target = getattr(self.config, "LOG_GROUP_ID", None) or self.config.ADMIN_ID
            await self.bot.send_message(
                chat_id=target,
                text=text,
                parse_mode="MarkdownV2",
            )
        except TelegramBadRequest as e:
            _std_logger.error(f"ping alert TelegramBadRequest: {e}")
        except Exception as e:
            _std_logger.error(f"ping alert send failed: {e}")

    async def send_status_report(self) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_now = escape_md(now)

        try:
            me = await self.bot.get_me()
            safe_username = escape_md(f"@{me.username}")
            safe_name = escape_md(me.full_name)
            status_icon = "🟢"
            status_text = "آنلاین"
        except Exception as e:
            safe_username = "نامشخص"
            safe_name = "نامشخص"
            status_icon = "🔴"
            status_text = escape_md(f"آفلاین — {e}")

        text = (
            f"{status_icon} *وضعیت بات*\n\n"
            f"🤖 نام: {safe_name}\n"
            f"📛 یوزرنیم: {safe_username}\n"
            f"📶 وضعیت: {status_text}\n"
            f"🕐 زمان بررسی: `{safe_now}`\n"
            f"⏱ فاصله پینگ: `{self.interval // 60}` دقیقه"
        )

        try:
            target = getattr(self.config, "LOG_GROUP_ID", None) or self.config.ADMIN_ID
            await self.bot.send_message(
                chat_id=target,
                text=text,
                parse_mode="MarkdownV2",
            )
        except Exception as e:
            _std_logger.error(f"status_report send failed: {e}")
