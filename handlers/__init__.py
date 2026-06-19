from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from handlers.admin_auth    import router as auth_router
from handlers.admin_panel   import router as panel_router
from handlers.panel_builder import router as pb_router
from handlers.form_builder  import router as fb_router
from handlers.user          import router as user_router
from handlers.payment       import router as payment_router
from handlers.discount      import router as discount_router
from handlers.referral      import router as referral_router

base_router = Router(name="base")


@base_router.message(CommandStart())
async def cmd_start_fallback(message: Message):
    await message.answer("برای شروع /start را بزنید.")


__all__ = [
    "base_router",
    "auth_router",
    "panel_router",
    "pb_router",
    "fb_router",
    "user_router",
    "payment_router",
    "discount_router",
    "referral_router",
]
