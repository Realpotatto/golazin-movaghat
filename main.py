import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import (
    auth_router, panel_router, pb_router, fb_router,
    user_router, payment_router, discount_router, referral_router,
    base_router,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=AiohttpSession(proxy="http://127.0.0.1:10809"),
    )
    storage = MemoryStorage()
    dp      = Dispatcher(storage=storage)

    # Order matters: admin auth first, then specific handlers, base last
    dp.include_router(auth_router)
    dp.include_router(panel_router)
    dp.include_router(pb_router)
    dp.include_router(fb_router)
    dp.include_router(user_router)
    dp.include_router(payment_router)
    dp.include_router(discount_router)
    dp.include_router(referral_router)
    dp.include_router(base_router)

    logger.info("IrForge bot starting…")
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
