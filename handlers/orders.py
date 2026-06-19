import json
import random
import string
import os
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

router = Router()

ORDERS_FILE = "orders.json"
CONFIG_FILE = "config.json"


def load_orders() -> dict:
    if not os.path.exists(ORDERS_FILE):
        return {}
    with open(ORDERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_orders(orders: dict):
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_order_code() -> str:
    orders = load_orders()
    while True:
        letters = random.choices(string.ascii_uppercase, k=2)
        digits = random.choices(string.digits, k=4)
        end_letters = random.choices(string.ascii_uppercase, k=2)
        code = letters[0] + "".join(digits) + "".join(end_letters)
        if code not in orders:
            return code


def get_admin_group() -> int | None:
    config = load_config()
    return config.get("admin_group_id") or config.get("admin_channel_id")


def get_message_templates() -> dict:
    config = load_config()
    return config.get("order_messages", {
        "accepted": "✅ سفارش شما با کد {code} تایید شد.",
        "rejected": "❌ سفارش شما با کد {code} رد شد.\nدلیل: {reason}",
        "tracking": "📦 کد رهگیری سفارش {code}:\n{tracking_code}"
    })


def save_message_templates(templates: dict):
    config = load_config()
    config["order_messages"] = templates
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


class ReceiptState(StatesGroup):
    waiting_receipt = State()


class TemplateEditState(StatesGroup):
    waiting_template_type = State()
    waiting_template_text = State()


async def create_order(
    bot: Bot,
    user_id: int,
    username: str | None,
    phone: str | None,
    fields: dict,
    receipt_file_id: str | None = None
) -> str:
    orders = load_orders()
    code = generate_order_code()
    now = datetime.now().isoformat()

    orders[code] = {
        "user_id": str(user_id),
        "username": username or "",
        "phone": phone or "",
        "fields": fields,
        "receipt": receipt_file_id or "",
        "status": "pending",
        "created_at": now,
        "group_message_id": ""
    }

    save_orders(orders)

    admin_group = get_admin_group()
    if admin_group:
        text = build_order_text(code, orders[code])
        try:
            if receipt_file_id:
                msg = await bot.send_photo(
                    chat_id=admin_group,
                    photo=receipt_file_id,
                    caption=text
                )
            else:
                msg = await bot.send_message(
                    chat_id=admin_group,
                    text=text
                )
            orders[code]["group_message_id"] = str(msg.message_id)
            save_orders(orders)
        except Exception:
            pass

    return code


def build_order_text(code: str, order: dict) -> str:
    status_map = {
        "pending": "🟡 در انتظار بررسی",
        "accepted": "✅ تایید شده",
        "rejected": "❌ رد شده",
        "waiting_receipt": "⏳ در انتظار تایید رسید"
    }
    status = status_map.get(order.get("status", "pending"), order.get("status", "pending"))
    fields_text = ""
    for k, v in (order.get("fields") or {}).items():
        fields_text += f"  • {k}: {v}\n"

    text = (
        f"🛒 سفارش جدید\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔑 کد سفارش: <code>{code}</code>\n"
        f"👤 یوزر: @{order.get('username') or 'ندارد'}\n"
        f"🆔 آیدی: <code>{order.get('user_id', '')}</code>\n"
        f"📞 شماره: {order.get('phone') or 'ثبت نشده'}\n"
        f"📅 تاریخ: {order.get('created_at', '')[:19].replace('T', ' ')}\n"
        f"📊 وضعیت: {status}\n"
    )
    if fields_text:
        text += f"📋 جزئیات:\n{fields_text}"
    text += (
        f"━━━━━━━━━━━━━━━\n"
        f"دستورات:\n"
        f"/ACPT {code} — تایید\n"
        f"/RJCT {code} دلیل — رد\n"
        f"/code {code} TRACKING — ارسال کد رهگیری"
    )
    return text


@router.message(Command("ACPT"))
async def accept_order(message: Message, bot: Bot):
    admin_group = get_admin_group()
    if not admin_group or message.chat.id != admin_group:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ فرمت: /ACPT CODE")
        return

    code = args[1].strip().upper()
    orders = load_orders()

    if code not in orders:
        await message.reply(f"❌ سفارش {code} یافت نشد.")
        return

    order = orders[code]
    if order["status"] == "accepted":
        await message.reply(f"⚠️ سفارش {code} قبلاً تایید شده.")
        return

    orders[code]["status"] = "accepted"
    save_orders(orders)

    templates = get_message_templates()
    user_text = templates["accepted"].format(code=code)

    try:
        await bot.send_message(chat_id=int(order["user_id"]), text=user_text)
    except Exception:
        pass

    await message.reply(f"✅ سفارش {code} تایید شد و به کاربر اطلاع داده شد.")

    if order.get("group_message_id"):
        try:
            await bot.edit_message_caption(
                chat_id=admin_group,
                message_id=int(order["group_message_id"]),
                caption=build_order_text(code, orders[code])
            )
        except Exception:
            try:
                await bot.edit_message_text(
                    chat_id=admin_group,
                    message_id=int(order["group_message_id"]),
                    text=build_order_text(code, orders[code])
                )
            except Exception:
                pass


@router.message(Command("RJCT"))
async def reject_order(message: Message, bot: Bot):
    admin_group = get_admin_group()
    if not admin_group or message.chat.id != admin_group:
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("❌ فرمت: /RJCT CODE دلیل رد")
        return

    code = args[1].strip().upper()
    reason = args[2].strip()
    orders = load_orders()

    if code not in orders:
        await message.reply(f"❌ سفارش {code} یافت نشد.")
        return

    order = orders[code]
    if order["status"] == "rejected":
        await message.reply(f"⚠️ سفارش {code} قبلاً رد شده.")
        return

    orders[code]["status"] = "rejected"
    orders[code]["reject_reason"] = reason
    save_orders(orders)

    templates = get_message_templates()
    user_text = templates["rejected"].format(code=code, reason=reason)

    try:
        await bot.send_message(chat_id=int(order["user_id"]), text=user_text)
    except Exception:
        pass

    await message.reply(f"❌ سفارش {code} رد شد و به کاربر اطلاع داده شد.")

    if order.get("group_message_id"):
        try:
            await bot.edit_message_caption(
                chat_id=admin_group,
                message_id=int(order["group_message_id"]),
                caption=build_order_text(code, orders[code])
            )
        except Exception:
            try:
                await bot.edit_message_text(
                    chat_id=admin_group,
                    message_id=int(order["group_message_id"]),
                    text=build_order_text(code, orders[code])
                )
            except Exception:
                pass


@router.message(Command("code"))
async def send_tracking_code(message: Message, bot: Bot):
    admin_group = get_admin_group()
    if not admin_group or message.chat.id != admin_group:
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("❌ فرمت: /code ORDER_CODE TRACKING_CODE")
        return

    code = args[1].strip().upper()
    tracking_code = args[2].strip()
    orders = load_orders()

    if code not in orders:
        await message.reply(f"❌ سفارش {code} یافت نشد.")
        return

    order = orders[code]
    orders[code]["tracking_code"] = tracking_code
    save_orders(orders)

    templates = get_message_templates()
    user_text = templates["tracking"].format(code=code, tracking_code=tracking_code)

    try:
        await bot.send_message(chat_id=int(order["user_id"]), text=user_text)
        await message.reply(f"📦 کد رهگیری برای سفارش {code} ارسال شد.")
    except Exception as e:
        await message.reply(f"❌ خطا در ارسال: {e}")


@router.message(Command("order_status"))
async def order_status(message: Message):
    admin_group = get_admin_group()
    if not admin_group or message.chat.id != admin_group:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ فرمت: /order_status CODE")
        return

    code = args[1].strip().upper()
    orders = load_orders()

    if code not in orders:
        await message.reply(f"❌ سفارش {code} یافت نشد.")
        return

    text = build_order_text(code, orders[code])
    await message.reply(text)


@router.message(Command("orders"))
async def user_orders(message: Message):
    if message.chat.type != "private":
        return

    orders = load_orders()
    user_id = str(message.from_user.id)

    user_orders_list = [
        (code, order)
        for code, order in orders.items()
        if order.get("user_id") == user_id
    ]

    if not user_orders_list:
        await message.answer("📭 شما هیچ سفارشی ندارید.")
        return

    status_map = {
        "pending": "🟡 در انتظار",
        "accepted": "✅ تایید شده",
        "rejected": "❌ رد شده",
        "waiting_receipt": "⏳ در انتظار تایید رسید"
    }

    text = "📦 سفارشات شما:\n━━━━━━━━━━━━━━━\n"
    for code, order in sorted(user_orders_list, key=lambda x: x[1].get("created_at", ""), reverse=True):
        status = status_map.get(order.get("status", "pending"), order.get("status", ""))
        date = order.get("created_at", "")[:10]
        text += f"🔑 <code>{code}</code> | {status} | {date}\n"
        if order.get("tracking_code"):
            text += f"  📦 رهگیری: {order['tracking_code']}\n"
        if order.get("reject_reason"):
            text += f"  💬 دلیل رد: {order['reject_reason']}\n"

    await message.answer(text)


@router.message(Command("set_template"))
async def set_template(message: Message, state: FSMContext):
    admin_group = get_admin_group()
    if not admin_group or message.chat.id != admin_group:
        return

    await message.reply(
        "✏️ کدام قالب را می‌خواهید ویرایش کنید?\n"
        "1 - قالب تایید (accepted)\n"
        "2 - قالب رد (rejected)\n"
        "3 - قالب رهگیری (tracking)\n\n"
        "متغیرها: {code}, {reason}, {tracking_code}"
    )
    await state.set_state(TemplateEditState.waiting_template_type)


@router.message(TemplateEditState.waiting_template_type)
async def receive_template_type(message: Message, state: FSMContext):
    choice = message.text.strip()
    type_map = {"1": "accepted", "2": "rejected", "3": "tracking"}
    if choice not in type_map:
        await message.reply("❌ عدد 1، 2 یا 3 وارد کنید.")
        return

    await state.update_data(template_type=type_map[choice])
    templates = get_message_templates()
    current = templates.get(type_map[choice], "")
    await message.reply(f"✏️ متن جدید را وارد کنید:\n\nفعلی:\n{current}")
    await state.set_state(TemplateEditState.waiting_template_text)


@router.message(TemplateEditState.waiting_template_text)
async def receive_template_text(message: Message, state: FSMContext):
    data = await state.get_data()
    template_type = data.get("template_type")
    templates = get_message_templates()
    templates[template_type] = message.text.strip()
    save_message_templates(templates)
    await message.reply(f"✅ قالب '{template_type}' با موفقیت ذخیره شد.")
    await state.clear()


async def submit_receipt(message: Message, bot: Bot, order_code: str):
    """Call this from other handlers when user sends a receipt photo."""
    if not message.photo:
        await message.reply("❌ لطفاً عکس رسید را ارسال کنید.")
        return

    file_id = message.photo[-1].file_id
    orders = load_orders()

    if order_code not in orders:
        await message.reply("❌ سفارش یافت نشد.")
        return

    order = orders[order_code]
    if order["user_id"] != str(message.from_user.id):
        await message.reply("❌ این سفارش متعلق به شما نیست.")
        return

    orders[order_code]["receipt"] = file_id
    orders[order_code]["status"] = "waiting_receipt"
    save_orders(orders)

    admin_group = get_admin_group()
    if admin_group:
        caption = (
            f"📎 رسید پرداخت دریافت شد\n"
            f"🔑 کد سفارش: <code>{order_code}</code>\n"
            f"👤 یوزر: @{order.get('username') or 'ندارد'}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"/ACPT {order_code} — تایید\n"
            f"/RJCT {order_code} دلیل — رد"
        )
        try:
            msg = await bot.send_photo(
                chat_id=admin_group,
                photo=file_id,
                caption=caption
            )
            orders[order_code]["group_message_id"] = str(msg.message_id)
            save_orders(orders)
        except Exception:
            pass

    await message.reply(
        f"✅ رسید شما برای سفارش <code>{order_code}</code> دریافت شد.\n"
        f"⏳ در انتظار تایید ادمین..."
    )