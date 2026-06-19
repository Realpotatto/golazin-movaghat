"""
handlers/panel_builder.py
پنل‌ساز کامل IrForge — ساخت / ویرایش / حذف / درخت بی‌نهایت
"""

import logging
from datetime import datetime
from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from models import Panel
from utils.db import panels_db, forms_db
from utils.mdv2 import esc, bold, italic, code

logger = logging.getLogger(__name__)
router = Router(name="panel_builder")

# ══════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════

PANEL_TYPES = {
    "text":     "📝 متنی",
    "photo":    "🖼 تصویر",
    "carousel": "🎠 کاروسل (چند تصویر)",
    "video":    "🎬 ویدیو",
    "audio":    "🎵 صوت",
    "document": "📎 فایل",
    "form":     "📋 فرم",
    "sell":     "🛒 فروش (ارسال رسید)",
}

BTN_ACTIONS = {
    "panel":    "🔗 لینک به پنل",
    "url":      "🌐 لینک خارجی (URL)",
    "form":     "📋 باز کردن فرم",
    "callback": "⚡ کال‌بک",
    "phone":    "📞 درخواست شماره",
}

# ══════════════════════════════════════════════════════════════════════
#  STATES
# ══════════════════════════════════════════════════════════════════════

class PanelStates(StatesGroup):
    # Create flow
    create_title         = State()
    create_type          = State()
    create_content       = State()
    create_media         = State()
    create_carousel_more = State()
    # Advanced settings
    adv_timer            = State()
    adv_password         = State()
    adv_capacity         = State()
    adv_forward_groups   = State()
    # Button builder
    btn_label            = State()
    btn_action           = State()
    btn_value            = State()
    btn_row              = State()
    btn_style            = State()
    # Edit flow
    edit_choose_field    = State()
    edit_title           = State()
    edit_content         = State()
    edit_media           = State()
    # Link panel to parent
    link_parent          = State()
    # Delete confirm
    delete_confirm       = State()
    # Password unlock (user side)
    unlock_password      = State()
    # Sell panel
    sell_product_name    = State()
    sell_product_desc    = State()
    sell_product_price   = State()
    sell_target_group    = State()


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════

def _require_admin(uid: str) -> bool:
    from handlers.admin_auth import _is_admin
    return _is_admin(uid)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def _home_back(back_cb: str = "pb:menu") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_cb),
        InlineKeyboardButton(text="🏠 خانه",   callback_data="pb:menu"),
    ]


def _load_panel(pid: str) -> Optional[Panel]:
    raw = panels_db.get(pid)
    return Panel.from_dict(raw) if raw else None


def _save_panel(panel: Panel):
    panel.updated_at = datetime.utcnow().isoformat()
    panels_db.set(panel.id, panel.to_dict())


def _tog(val: bool) -> str:
    return "✅" if val else "❌"


def _panel_short(p: Panel) -> str:
    typ  = PANEL_TYPES.get(p.type, p.type)
    home = " 🏠" if p.is_home else ""
    act  = "" if p.is_active else " ⛔"
    lock = " 🔒" if p.settings.get("password") else ""
    return f"{esc(p.title)}{home}{act}{lock} — {esc(typ)}"


def _panel_tree(pid: str, depth: int = 0, visited: Optional[set] = None) -> str:
    if visited is None:
        visited = set()
    if pid in visited or depth > 8:
        return ""
    visited.add(pid)
    raw = panels_db.get(pid)
    if not raw:
        return ""
    p = Panel.from_dict(raw)
    prefix = "　" * depth + ("├─ " if depth > 0 else "")
    line   = f"{prefix}{_panel_short(p)}\n"
    for child_id in p.children:
        line += _panel_tree(child_id, depth + 1, visited)
    return line


# ══════════════════════════════════════════════════════════════════════
#  MENU
# ══════════════════════════════════════════════════════════════════════

def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ پنل جدید",        "pb:new"),
         _btn("📋 لیست پنل‌ها",     "pb:list")],
        [_btn("🌳 درخت پنل‌ها",     "pb:tree"),
         _btn("🔗 لینک پنل‌ها",     "pb:link_menu")],
        [_btn("🏠 تنظیم پنل خانه",  "pb:set_home")],
        _home_back("ap:home"),
    ])


async def send_panel_menu(target, edit: bool = True):
    count = panels_db.count()
    text  = (
        f"{bold('🧱 پنل‌ساز IrForge')}\n\n"
        f"تعداد پنل‌ها: {bold(str(count))}\n\n"
        "از دکمه‌های زیر پنل‌های ربات را مدیریت کنید:"
    )
    kb = _menu_kb()
    if edit:
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════════════════
#  CREATE — step 1: title
# ══════════════════════════════════════════════════════════════════════

async def _ask_title(target, edit: bool = True):
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back()])
    txt = f"{bold('➕ ساخت پنل جدید')}\n\n✏️ عنوان پنل را وارد کنید:"
    if edit:
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data == "pb:new")
async def cb_new_panel(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.clear()
    await state.set_state(PanelStates.create_title)
    await _ask_title(call.message)
    await call.answer()


@router.message(PanelStates.create_title)
async def fsm_create_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if not title:
        await message.answer("❌ عنوان نمی‌تواند خالی باشد\\.", parse_mode="MarkdownV2")
        return
    await state.update_data(title=title, media_ids=[], buttons=[], settings={})
    await state.set_state(PanelStates.create_type)

    rows = []
    row  = []
    for i, (key, label) in enumerate(PANEL_TYPES.items()):
        row.append(_btn(label, f"pb:type:{key}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append(_home_back())

    await message.answer(
        f"{bold('📦 نوع پنل را انتخاب کنید:')}\n\nعنوان: {bold(esc(title))}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


# ══════════════════════════════════════════════════════════════════════
#  CREATE — step 2: type
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pb:type:"))
async def cb_panel_type(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    ptype = call.data.split(":")[2]
    await state.update_data(ptype=ptype)

    if ptype in ("photo", "video", "audio", "document"):
        await state.set_state(PanelStates.create_media)
        kb = InlineKeyboardMarkup(inline_keyboard=[_home_back()])
        await call.message.edit_text(
            f"{bold('📎 فایل را ارسال کنید')}\n\n"
            f"نوع: {esc(PANEL_TYPES[ptype])}\n"
            "فایل یا تصویر را مستقیم ارسال کنید:",
            parse_mode="MarkdownV2", reply_markup=kb
        )
    elif ptype == "carousel":
        await state.set_state(PanelStates.create_media)
        kb = InlineKeyboardMarkup(inline_keyboard=[_home_back()])
        await call.message.edit_text(
            f"{bold('🎠 کاروسل — تصاویر را ارسال کنید')}\n\n"
            "تصویر اول را ارسال کنید:",
            parse_mode="MarkdownV2", reply_markup=kb
        )
    elif ptype == "sell":
        await state.set_state(PanelStates.sell_product_name)
        kb = InlineKeyboardMarkup(inline_keyboard=[_home_back()])
        await call.message.edit_text(
            f"{bold('🛒 پنل فروش — مرحله ۱/۴')}\n\n"
            "نام محصول یا خدمت را وارد کنید:",
            parse_mode="MarkdownV2", reply_markup=kb
        )
    else:
        await state.set_state(PanelStates.create_content)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [_btn("⏭ بدون متن (فقط دکمه)", "pb:skip_content")],
            _home_back(),
        ])
        await call.message.edit_text(
            f"{bold('✏️ متن پنل را وارد کنید')}\n\n"
            "MarkdownV2 پشتیبانی می‌شود\\. مثال:\n"
            "`*بولد*` `_ایتالیک_` کد",
            parse_mode="MarkdownV2", reply_markup=kb
        )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  CREATE — step 3a: content (text/form)
# ══════════════════════════════════════════════════════════════════════

@router.message(PanelStates.create_content)
async def fsm_create_content(message: Message, state: FSMContext):
    await state.update_data(content=message.text or "")
    await _ask_advanced_or_buttons(message, state)


@router.callback_query(F.data == "pb:skip_content")
async def cb_skip_content(call: CallbackQuery, state: FSMContext):
    await state.update_data(content="")
    await _ask_advanced_or_buttons(call.message, state, edit=True)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  CREATE — step 3b: media upload
# ══════════════════════════════════════════════════════════════════════

@router.message(PanelStates.create_media, F.photo | F.video | F.audio | F.document)
async def fsm_create_media(message: Message, state: FSMContext):
    data  = await state.get_data()
    ptype = data.get("ptype", "photo")

    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.audio:
        file_id = message.audio.file_id
    elif message.document:
        file_id = message.document.file_id
    else:
        file_id = ""

    if ptype == "carousel":
        media_ids = data.get("media_ids", [])
        media_ids.append(file_id)
        await state.update_data(media_ids=media_ids)
        await state.set_state(PanelStates.create_carousel_more)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [_btn(f"✅ کافیه ({len(media_ids)} تصویر)", "pb:carousel_done")],
            _home_back(),
        ])
        await message.answer(
            f"✅ تصویر {esc(str(len(media_ids)))} اضافه شد\\.\nتصویر بعدی را ارسال کنید یا تأیید کنید:",
            parse_mode="MarkdownV2", reply_markup=kb
        )
    else:
        await state.update_data(media_ids=[file_id], content="")
        await _ask_advanced_or_buttons(message, state)


@router.message(PanelStates.create_carousel_more, F.photo)
async def fsm_carousel_more(message: Message, state: FSMContext):
    data      = await state.get_data()
    media_ids = data.get("media_ids", [])
    media_ids.append(message.photo[-1].file_id)
    await state.update_data(media_ids=media_ids)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"✅ کافیه ({len(media_ids)} تصویر)", "pb:carousel_done")],
        _home_back(),
    ])
    await message.answer(
        f"✅ تصویر {esc(str(len(media_ids)))} اضافه شد\\.",
        parse_mode="MarkdownV2", reply_markup=kb
    )


@router.callback_query(F.data == "pb:carousel_done")
async def cb_carousel_done(call: CallbackQuery, state: FSMContext):
    await _ask_advanced_or_buttons(call.message, state, edit=True)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  CREATE — SELL PANEL FLOW
# ══════════════════════════════════════════════════════════════════════

@router.message(PanelStates.sell_product_name)
async def fsm_sell_product_name(message: Message, state: FSMContext):
    await state.update_data(sell_product_name=message.text.strip())
    await state.set_state(PanelStates.sell_product_desc)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⏭ بدون توضیحات", "pb:sell_skip_desc")],
        _home_back(),
    ])
    await message.answer(
        f"{bold('🛒 پنل فروش — مرحله ۲/۴')}\n\n"
        "توضیحات محصول را وارد کنید:",
        parse_mode="MarkdownV2", reply_markup=kb
    )


@router.callback_query(F.data == "pb:sell_skip_desc")
async def cb_sell_skip_desc(call: CallbackQuery, state: FSMContext):
    await state.update_data(sell_product_desc="")
    await state.set_state(PanelStates.sell_product_price)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⏭ بدون قیمت", "pb:sell_skip_price")],
        _home_back(),
    ])
    await call.message.edit_text(
        f"{bold('🛒 پنل فروش — مرحله ۳/۴')}\n\n"
        "قیمت محصول را وارد کنید \\(عدد\\):",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(PanelStates.sell_product_desc)
async def fsm_sell_product_desc(message: Message, state: FSMContext):
    await state.update_data(sell_product_desc=message.text.strip())
    await state.set_state(PanelStates.sell_product_price)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⏭ بدون قیمت", "pb:sell_skip_price")],
        _home_back(),
    ])
    await message.answer(
        f"{bold('🛒 پنل فروش — مرحله ۳/۴')}\n\n"
        "قیمت محصول را وارد کنید \\(عدد\\):",
        parse_mode="MarkdownV2", reply_markup=kb
    )


@router.callback_query(F.data == "pb:sell_skip_price")
async def cb_sell_skip_price(call: CallbackQuery, state: FSMContext):
    await state.update_data(sell_product_price="")
    await _ask_sell_target_group(call.message, state, edit=True)
    await call.answer()


@router.message(PanelStates.sell_product_price)
async def fsm_sell_product_price(message: Message, state: FSMContext):
    txt = message.text.replace(",", "").strip()
    if txt and not txt.replace(".", "").isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2")
        return
    await state.update_data(sell_product_price=txt)
    await _ask_sell_target_group(message, state)


async def _ask_sell_target_group(target, state: FSMContext, edit: bool = False):
    await state.set_state(PanelStates.sell_target_group)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back()])
    txt = (
        f"{bold('🛒 پنل فروش — مرحله ۴/۴')}\n\n"
        "آیدی عددی گروه یا کانالی که رسیدها باید ارسال شوند را وارد کنید\\.\n"
        "مثال: `\\-100123456789`\n\n"
        "⚠️ ربات باید ادمین آن گروه\\/کانال باشد\\."
    )
    if edit:
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


@router.message(PanelStates.sell_target_group)
async def fsm_sell_target_group(message: Message, state: FSMContext):
    gid = message.text.strip()
    if not gid.lstrip("-").isdigit():
        await message.answer(
            "❌ آیدی گروه باید عددی باشد\\. مثال: `\\-100123456789`",
            parse_mode="MarkdownV2"
        )
        return
    data = await state.get_data()
    # Build sell settings
    sell_settings = {
        "product_name":  data.get("sell_product_name", ""),
        "product_desc":  data.get("sell_product_desc", ""),
        "product_price": data.get("sell_product_price", ""),
        "target_group":  gid,
    }
    await state.update_data(
        ptype="sell",
        content=data.get("sell_product_name", ""),
        settings={**data.get("settings", {}), **sell_settings},
    )
    await _ask_advanced_or_buttons(message, state)


# ══════════════════════════════════════════════════════════════════════
#  CREATE — step 4: advanced settings or buttons
# ══════════════════════════════════════════════════════════════════════

async def _ask_advanced_or_buttons(target, state: FSMContext, edit: bool = False,
                                    back_cb: str = "pb:menu"):
    data = await state.get_data()
    settings = data.get("settings", {})
    buttons  = data.get("buttons",  [])

    timer_set  = settings.get("timer_seconds")
    pass_set   = bool(settings.get("password"))
    cap_set    = settings.get("capacity", 0)
    fwd_groups = settings.get("forward_groups", [])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ افزودن دکمه",             "pb:btn_add"),
         _btn(f"📋 دکمه‌ها ({len(buttons)})", "pb:btn_list")],
        [_btn(f"⏱ تایمر: {'✅ ' + esc(str(timer_set)) + 's' if timer_set else '❌'}",
              "pb:adv:timer"),
         _btn(f"🔒 رمز: {_tog(pass_set)}",    "pb:adv:password")],
        [_btn(f"👥 ظرفیت: {esc(str(cap_set)) if cap_set else '∞'}",
              "pb:adv:capacity"),
         _btn(f"📤 فوروارد به {esc(str(len(fwd_groups)))} گروه",
              "pb:adv:forward")],
        [_btn("✅ ذخیره پنل",                "pb:save")],
        _home_back(back_cb),
    ])
    txt = f"{bold('🛠 تنظیمات پنل')}\n\nدکمه‌ها یا تنظیمات پیشرفته را اضافه کنید، سپس ذخیره کنید\\."
    if edit:
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════════════════
#  ADVANCED SETTINGS
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pb:adv:timer")
async def cb_adv_timer(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    await state.set_state(PanelStates.adv_timer)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("❌ بدون تایمر", "pb:adv:timer:clear")],
        _home_back("pb:save_prep"),
    ])
    await call.message.edit_text(
        f"{bold('⏱ تایمر خودکار')}\n\nمدت نمایش پنل را به ثانیه وارد کنید\\.\nمثال: `30`",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(PanelStates.adv_timer)
async def fsm_adv_timer(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2"); return
    data = await state.get_data()
    settings = data.get("settings", {})
    settings["timer_seconds"] = int(message.text)
    await state.update_data(settings=settings)
    await state.set_state(None)
    await _ask_advanced_or_buttons(message, state)


@router.callback_query(F.data == "pb:adv:timer:clear")
async def cb_adv_timer_clear(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    settings = data.get("settings", {})
    settings.pop("timer_seconds", None)
    await state.update_data(settings=settings)
    await state.set_state(None)
    await _ask_advanced_or_buttons(call.message, state, edit=True)
    await call.answer()


@router.callback_query(F.data == "pb:adv:password")
async def cb_adv_password(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    await state.set_state(PanelStates.adv_password)
    data = await state.get_data()
    cur  = data.get("settings", {}).get("password", "")
    kb   = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("❌ حذف رمز", "pb:adv:pass:clear")],
        _home_back("pb:save_prep"),
    ])
    await call.message.edit_text(
        f"{bold('🔒 رمز ورود پنل')}\n\n"
        f"رمز فعلی: {code(cur) if cur else italic('ندارد')}\n\nرمز جدید را وارد کنید:",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(PanelStates.adv_password)
async def fsm_adv_password(message: Message, state: FSMContext):
    await message.delete()
    data = await state.get_data()
    settings = data.get("settings", {})
    settings["password"] = message.text.strip()
    await state.update_data(settings=settings)
    await state.set_state(None)
    await _ask_advanced_or_buttons(message, state)


@router.callback_query(F.data == "pb:adv:pass:clear")
async def cb_adv_pass_clear(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    settings = data.get("settings", {})
    settings.pop("password", None)
    await state.update_data(settings=settings)
    await state.set_state(None)
    await _ask_advanced_or_buttons(call.message, state, edit=True)
    await call.answer()


@router.callback_query(F.data == "pb:adv:capacity")
async def cb_adv_capacity(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    await state.set_state(PanelStates.adv_capacity)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("∞ نامحدود", "pb:adv:cap:clear")],
        _home_back("pb:save_prep"),
    ])
    await call.message.edit_text(
        f"{bold('👥 ظرفیت پنل')}\n\nحداکثر تعداد بازدید را وارد کنید \\(0 \\= نامحدود\\):",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(PanelStates.adv_capacity)
async def fsm_adv_capacity(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ فقط عدد وارد کنید:", parse_mode="MarkdownV2"); return
    data = await state.get_data()
    settings = data.get("settings", {})
    settings["capacity"] = int(message.text)
    await state.update_data(settings=settings)
    await state.set_state(None)
    await _ask_advanced_or_buttons(message, state)


@router.callback_query(F.data == "pb:adv:cap:clear")
async def cb_adv_cap_clear(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    settings = data.get("settings", {})
    settings["capacity"] = 0
    await state.update_data(settings=settings)
    await state.set_state(None)
    await _ask_advanced_or_buttons(call.message, state, edit=True)
    await call.answer()


@router.callback_query(F.data == "pb:adv:forward")
async def cb_adv_forward(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    await state.set_state(PanelStates.adv_forward_groups)
    data   = await state.get_data()
    groups = data.get("settings", {}).get("forward_groups", [])
    cur    = "\n".join(f"• {esc(g)}" for g in groups) if groups else italic("هیچ گروهی")
    kb     = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🗑 پاک کردن همه", "pb:adv:fwd:clear")],
        _home_back("pb:save_prep"),
    ])
    await call.message.edit_text(
        f"{bold('📤 فوروارد به گروه')}\n\n"
        f"گروه‌های فعلی:\n{cur}\n\n"
        "آیدی گروه جدید را وارد کنید \\(مثال: `\\-100xxxxxxx`\\):",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(PanelStates.adv_forward_groups)
async def fsm_adv_forward(message: Message, state: FSMContext):
    gid = message.text.strip()
    data = await state.get_data()
    settings = data.get("settings", {})
    fwd = settings.get("forward_groups", [])
    if gid not in fwd:
        fwd.append(gid)
    settings["forward_groups"] = fwd
    await state.update_data(settings=settings)
    await state.set_state(None)
    await message.answer(
        f"✅ گروه {code(gid)} اضافه شد\\.",
        parse_mode="MarkdownV2",
    )
    await _ask_advanced_or_buttons(message, state)


@router.callback_query(F.data == "pb:adv:fwd:clear")
async def cb_adv_fwd_clear(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    settings = data.get("settings", {})
    settings["forward_groups"] = []
    await state.update_data(settings=settings)
    await state.set_state(None)
    await _ask_advanced_or_buttons(call.message, state, edit=True)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  BUTTON BUILDER
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pb:btn_add")
async def cb_btn_add(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    await state.set_state(PanelStates.btn_label)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back("pb:save_prep")])
    await call.message.edit_text(
        f"{bold('🔘 دکمه جدید')}\n\nعنوان دکمه را وارد کنید:",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(PanelStates.btn_label)
async def fsm_btn_label(message: Message, state: FSMContext):
    await state.update_data(btn_label=message.text.strip())
    await state.set_state(PanelStates.btn_action)
    rows = []
    row  = []
    for i, (key, label) in enumerate(BTN_ACTIONS.items()):
        row.append(_btn(label, f"pb:ba:{key}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append(_home_back("pb:save_prep"))
    await message.answer(
        f"{bold('نوع عملکرد دکمه را انتخاب کنید:')}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("pb:ba:"))
async def cb_btn_action(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    action = call.data.split(":")[2]
    await state.update_data(btn_action=action)

    if action == "phone":
        # no value needed
        await state.update_data(btn_value="request_contact")
        await _finalize_button(call, state)
        return

    if action == "panel":
        all_panels = panels_db.all_items()
        if not all_panels:
            await call.message.edit_text(
                "❌ هنوز هیچ پنلی ساخته نشده\\.",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back("pb:save_prep")])
            )
            await call.answer(); return
        rows = []
        for pid, raw in all_panels[:20]:
            p = Panel.from_dict(raw)
            rows.append([_btn(f"📋 {p.title}", f"pb:bv:panel:{pid}")])
        rows.append(_home_back("pb:save_prep"))
        await call.message.edit_text(
            f"{bold('پنل مقصد را انتخاب کنید:')}",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    elif action == "form":
        all_forms = forms_db.all_items()
        if not all_forms:
            await call.message.edit_text(
                "❌ هنوز هیچ فرمی ساخته نشده\\.",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back("pb:save_prep")])
            )
            await call.answer(); return
        rows = []
        for fid, raw in all_forms[:20]:
            rows.append([_btn(f"📋 {raw.get('title','بی‌نام')}", f"pb:bv:form:{fid}")])
        rows.append(_home_back("pb:save_prep"))
        await call.message.edit_text(
            f"{bold('فرم مقصد را انتخاب کنید:')}",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    else:
        await state.set_state(PanelStates.btn_value)
        hint = {
            "url":      "آدرس URL را وارد کنید \\(مثال: `https://example.com`\\):",
            "callback": "داده کال‌بک را وارد کنید:",
        }.get(action, "مقدار دکمه را وارد کنید:")
        kb = InlineKeyboardMarkup(inline_keyboard=[_home_back("pb:save_prep")])
        await call.message.edit_text(
            f"{bold('✏️ مقدار دکمه')}\n\n{hint}",
            parse_mode="MarkdownV2", reply_markup=kb
        )
    await call.answer()


async def _ask_btn_style_cb(call: CallbackQuery, state: FSMContext):
    """Ask for button style after inline value selection (panel/form)."""
    await state.set_state(PanelStates.btn_style)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 سبز",    callback_data="pb:bstyle:success"),
            InlineKeyboardButton(text="🔴 قرمز",   callback_data="pb:bstyle:danger"),
            InlineKeyboardButton(text="🔵 آبی",    callback_data="pb:bstyle:primary"),
        ],
        [InlineKeyboardButton(text="⬜ پیش‌فرض", callback_data="pb:bstyle:none")],
        _home_back("pb:save_prep"),
    ])
    await call.message.edit_text(
        f"{bold('🎨 رنگ دکمه را انتخاب کنید:')}",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("pb:bv:"))
async def cb_btn_value_inline(call: CallbackQuery, state: FSMContext):
    parts  = call.data.split(":")
    action = parts[2]
    value  = parts[3]
    await state.update_data(btn_value=value)
    # Bug 4 fix: ask for style even after inline panel/form selection
    await _ask_btn_style_cb(call, state)
    await call.answer()


@router.message(PanelStates.btn_value)
async def fsm_btn_value(message: Message, state: FSMContext):
    await state.update_data(btn_value=message.text.strip())
    await _ask_btn_style_msg(message, state)


async def _ask_btn_style_msg(message: Message, state: FSMContext):
    await state.set_state(PanelStates.btn_style)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 سبز", callback_data="pb:bstyle:success"),
            InlineKeyboardButton(text="🔴 قرمز", callback_data="pb:bstyle:danger"),
            InlineKeyboardButton(text="🔵 آبی", callback_data="pb:bstyle:primary"),
        ],
        [InlineKeyboardButton(text="⬜ پیش‌فرض", callback_data="pb:bstyle:none")],
        _home_back("pb:save_prep"),
    ])
    await message.answer(
        f"{bold('🎨 رنگ دکمه را انتخاب کنید:')}",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("pb:bstyle:"))
async def cb_btn_style(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    style = call.data.split(":")[2]
    await state.update_data(btn_style=style if style != "none" else None)
    await _finalize_button(call, state)
    await call.answer()


async def _finalize_button(call: CallbackQuery, state: FSMContext):
    data   = await state.get_data()
    label  = data.get("btn_label", "دکمه")
    action = data.get("btn_action", "callback")
    value  = data.get("btn_value", "")
    row    = len(data.get("buttons", [])) // 2

    style  = data.get("btn_style")
    btn    = {"label": label, "action": action, "value": value, "row": row, "col": 0, "style": style}
    buttons = data.get("buttons", [])
    buttons.append(btn)
    await state.update_data(buttons=buttons, btn_label=None, btn_action=None, btn_value=None, btn_style=None)
    await state.set_state(None)
    await call.message.edit_text(
        f"✅ دکمه *{esc(label)}* اضافه شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("➕ دکمه بعدی", "pb:btn_add"),
             _btn("✅ ادامه", "pb:save_prep")],
        ]),
    )


async def _finalize_button_msg(message: Message, state: FSMContext):
    data   = await state.get_data()
    label  = data.get("btn_label", "دکمه")
    action = data.get("btn_action", "callback")
    value  = data.get("btn_value", "")
    row    = len(data.get("buttons", [])) // 2

    style   = data.get("btn_style")
    btn     = {"label": label, "action": action, "value": value, "row": row, "col": 0, "style": style}
    buttons = data.get("buttons", [])
    buttons.append(btn)
    await state.update_data(buttons=buttons, btn_label=None, btn_action=None, btn_value=None, btn_style=None)
    await state.set_state(None)
    await message.answer(
        f"✅ دکمه *{esc(label)}* اضافه شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("➕ دکمه بعدی", "pb:btn_add"),
             _btn("✅ ادامه", "pb:save_prep")],
        ]),
    )


@router.callback_query(F.data == "pb:btn_list")
async def cb_btn_list(call: CallbackQuery, state: FSMContext):
    data    = await state.get_data()
    buttons = data.get("buttons", [])
    if not buttons:
        await call.answer("هنوز دکمه‌ای اضافه نشده", show_alert=True); return
    lines = [f"{i+1}\\. {esc(b['label'])} — {esc(b['action'])}" for i, b in enumerate(buttons)]
    rows  = [[_btn(f"🗑 حذف دکمه {i+1}", f"pb:btn_del:{i}") for i in range(len(buttons[:4]))]]
    rows.append([_btn("🗑 پاک کردن همه", "pb:btn_clear"), _btn("🔙 بازگشت", "pb:save_prep")])
    await call.message.edit_text(
        f"{bold('📋 دکمه‌های پنل')}\n\n" + "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pb:btn_del:"))
async def cb_btn_del(call: CallbackQuery, state: FSMContext):
    idx  = int(call.data.split(":")[2])
    data = await state.get_data()
    btns = data.get("buttons", [])
    if 0 <= idx < len(btns):
        btns.pop(idx)
        await state.update_data(buttons=btns)
    await _ask_advanced_or_buttons(call.message, state, edit=True)
    await call.answer()


@router.callback_query(F.data == "pb:btn_clear")
async def cb_btn_clear(call: CallbackQuery, state: FSMContext):
    await state.update_data(buttons=[])
    await _ask_advanced_or_buttons(call.message, state, edit=True)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  SAVE PANEL
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.in_({"pb:save", "pb:save_prep"}))
async def cb_save_panel(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    if call.data == "pb:save_prep":
        await _ask_advanced_or_buttons(call.message, state, edit=True)
        await call.answer(); return

    data      = await state.get_data()
    edit_id   = data.get("edit_panel_id")          # set only in edit flow
    title     = data.get("title", "پنل بدون عنوان")
    ptype     = data.get("ptype", "text")
    content   = data.get("content", "")
    media_ids = data.get("media_ids", [])
    buttons   = data.get("buttons",  [])
    settings  = data.get("settings", {})

    if edit_id:
        panel = _load_panel(edit_id) or Panel(id=edit_id)
        panel.title    = title
        panel.type     = ptype
        panel.content  = content
        panel.media_file_id = media_ids[0] if media_ids else ""
        if ptype == "carousel":
            settings["carousel_ids"] = media_ids
        panel.buttons  = buttons
        panel.settings = settings
    else:
        panel = Panel(
            title=title,
            type=ptype,
            content=content,
            media_file_id=media_ids[0] if media_ids else "",
            buttons=buttons,
            settings=settings,
        )
        if ptype == "carousel":
            panel.settings["carousel_ids"] = media_ids

    _save_panel(panel)
    await state.clear()

    verb = "بروزرسانی" if edit_id else "ایجاد"
    await call.message.edit_text(
        f"✅ پنل *{esc(title)}* با موفقیت {esc(verb)} شد\\!\n\n"
        f"🆔 شناسه: {code(panel.id)}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("✏️ ویرایش",       f"pb:edit:{panel.id}"),
             _btn("🔗 لینک به والد",  f"pb:link:{panel.id}")],
            [_btn("🧱 پنل جدید",     "pb:new"),
             _btn("📋 لیست پنل‌ها",  "pb:list")],
            _home_back("ap:home"),
        ]),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  LIST
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pb:list")
async def cb_panel_list(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    all_panels = panels_db.all_items()
    if not all_panels:
        await call.message.edit_text(
            "📭 هنوز پنلی ساخته نشده\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [_btn("➕ پنل جدید", "pb:new")], _home_back()
            ])
        )
        await call.answer(); return

    rows = []
    for pid, raw in all_panels[:15]:
        p = Panel.from_dict(raw)
        lbl = ("🏠 " if p.is_home else "") + p.title[:25]
        rows.append([_btn(lbl, f"pb:detail:{pid}")])
    rows.append(_home_back())

    await call.message.edit_text(
        f"{bold(f'📋 لیست پنل‌ها ({len(all_panels)})')}\n\nیک پنل انتخاب کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  PANEL DETAIL
# ══════════════════════════════════════════════════════════════════════

async def send_panel_detail(target, pid: str):
    """Render panel detail into a message (edit). Used by cb_panel_detail and cb_toggle."""
    panel = _load_panel(pid)
    if not panel:
        await target.edit_text("❌ پنل یافت نشد\\.", parse_mode="MarkdownV2")
        return

    settings  = panel.settings
    timer     = settings.get("timer_seconds")
    cap       = settings.get("capacity", 0)
    cap_used  = settings.get("capacity_used", 0)
    fwd       = settings.get("forward_groups", [])
    pass_set  = bool(settings.get("password"))

    text = (
        f"{bold('📋 جزئیات پنل')}\n\n"
        f"📌 عنوان: {bold(esc(panel.title))}\n"
        f"🆔 شناسه: {code(panel.id)}\n"
        f"📦 نوع: {esc(PANEL_TYPES.get(panel.type, panel.type))}\n"
        f"🔘 دکمه‌ها: {bold(str(len(panel.buttons)))}\n"
        f"👶 زیرپنل‌ها: {bold(str(len(panel.children)))}\n"
        f"⏱ تایمر: {esc(str(timer)+'s') if timer else italic('ندارد')}\n"
        f"🔒 رمز: {_tog(pass_set)}\n"
        f"👥 ظرفیت: {esc(str(cap_used)+'/'+str(cap)) if cap else italic('نامحدود')}\n"
        f"📤 فوروارد: {esc(str(len(fwd)))} گروه\n"
        f"✅ فعال: {_tog(panel.is_active)}\n"
        f"🏠 خانه: {_tog(panel.is_home)}\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✏️ ویرایش",             f"pb:edit:{pid}"),
         _btn(f"{'⛔ غیرفعال' if panel.is_active else '✅ فعال'}",
              f"pb:toggle:{pid}")],
        [_btn("🔗 لینک به والد",        f"pb:link:{pid}"),
         _btn("🗑 حذف پنل",            f"pb:delete:{pid}")],
        [_btn("📋 دکمه‌ها",            f"pb:editbtns:{pid}"),
         _btn("👶 زیرپنل‌ها",          f"pb:children:{pid}")],
        _home_back("pb:list"),
    ])

    await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data.startswith("pb:detail:"))
async def cb_panel_detail(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    pid = call.data.split(":")[2]
    panel = _load_panel(pid)
    if not panel:
        await call.answer("پنل یافت نشد", show_alert=True); return
    await send_panel_detail(call.message, pid)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  TOGGLE ACTIVE
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pb:toggle:"))
async def cb_toggle(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    pid   = call.data.split(":")[2]
    panel = _load_panel(pid)
    if not panel: await call.answer("یافت نشد", show_alert=True); return
    panel.is_active = not panel.is_active
    _save_panel(panel)
    await call.answer(f"{'✅ فعال' if panel.is_active else '⛔ غیرفعال'} شد")
    # refresh detail — call send_panel_detail directly instead of mutating frozen call.data
    await send_panel_detail(call.message, pid)


# ══════════════════════════════════════════════════════════════════════
#  SET HOME PANEL
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pb:set_home")
async def cb_set_home_list(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    all_panels = panels_db.all_items()
    rows = [[_btn(f"{'🏠 ' if Panel.from_dict(r).is_home else ''}{Panel.from_dict(r).title[:28]}",
                  f"pb:sethome:{pid}")] for pid, r in all_panels[:15]]
    rows.append(_home_back())
    await call.message.edit_text(
        f"{bold('🏠 انتخاب پنل خانه')}\n\nکدام پنل، پنل اصلی \\(خانه\\) باشد؟",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await call.answer()


@router.callback_query(F.data.startswith("pb:sethome:"))
async def cb_set_home(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    pid = call.data.split(":")[2]
    for existing_id, raw in panels_db.all_items():
        if raw.get("is_home"):
            panels_db.update(existing_id, {"is_home": False})
    panels_db.update(pid, {"is_home": True})

    from utils.db import settings_db
    raw = settings_db.read()
    raw["home_panel_id"] = pid
    settings_db.write(raw)

    panel = _load_panel(pid)
    await call.answer(f"🏠 پنل خانه: {panel.title if panel else pid}", show_alert=True)
    await send_panel_menu(call.message, edit=True)


# ══════════════════════════════════════════════════════════════════════
#  EDIT PANEL
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pb:edit:"))
async def cb_edit_panel(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    pid   = call.data.split(":")[2]
    panel = _load_panel(pid)
    if not panel: await call.answer("یافت نشد", show_alert=True); return

    await state.clear()
    await state.update_data(
        edit_panel_id=pid,
        title=panel.title,
        ptype=panel.type,
        content=panel.content,
        media_ids=[panel.media_file_id] if panel.media_file_id else
                  panel.settings.get("carousel_ids", []),
        buttons=panel.buttons,
        settings=panel.settings,
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✏️ عنوان",       "pb:ef:title"),
         _btn("📝 محتوا",       "pb:ef:content")],
        [_btn("🖼 مدیا",        "pb:ef:media"),
         _btn("🔘 دکمه‌ها",     "pb:btn_add")],
        [_btn("⚙️ تنظیمات پیشرفته", "pb:save_prep"),
         _btn("✅ ذخیره",        "pb:save")],
        _home_back(f"pb:detail:{pid}"),
    ])
    await call.message.edit_text(
        f"{bold('✏️ ویرایش پنل')} — {bold(esc(panel.title))}\n\nچه چیزی را ویرایش کنید؟",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data == "pb:ef:title")
async def cb_ef_title(call: CallbackQuery, state: FSMContext):
    await state.set_state(PanelStates.edit_title)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back("pb:save_prep")])
    await call.message.edit_text(
        "✏️ عنوان جدید را وارد کنید:", parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(PanelStates.edit_title)
async def fsm_edit_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(None)
    await message.answer(
        f"✅ عنوان بروزرسانی شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("✅ ذخیره", "pb:save"), _btn("⚙️ ادامه", "pb:save_prep")]
        ])
    )


@router.callback_query(F.data == "pb:ef:content")
async def cb_ef_content(call: CallbackQuery, state: FSMContext):
    await state.set_state(PanelStates.edit_content)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back("pb:save_prep")])
    await call.message.edit_text(
        "✏️ متن جدید را وارد کنید:", parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(PanelStates.edit_content)
async def fsm_edit_content(message: Message, state: FSMContext):
    await state.update_data(content=message.text or "")
    await state.set_state(None)
    await message.answer(
        "✅ محتوا بروزرسانی شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("✅ ذخیره", "pb:save"), _btn("⚙️ ادامه", "pb:save_prep")]
        ])
    )


@router.callback_query(F.data == "pb:ef:media")
async def cb_ef_media(call: CallbackQuery, state: FSMContext):
    await state.set_state(PanelStates.edit_media)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back("pb:save_prep")])
    await call.message.edit_text(
        "🖼 فایل یا تصویر جدید را ارسال کنید:", parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(PanelStates.edit_media, F.photo | F.video | F.audio | F.document)
async def fsm_edit_media(message: Message, state: FSMContext):
    if message.photo:
        fid = message.photo[-1].file_id
    elif message.video:
        fid = message.video.file_id
    elif message.audio:
        fid = message.audio.file_id
    else:
        fid = message.document.file_id
    await state.update_data(media_ids=[fid])
    await state.set_state(None)
    await message.answer(
        "✅ مدیا بروزرسانی شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("✅ ذخیره", "pb:save"), _btn("⚙️ ادامه", "pb:save_prep")]
        ])
    )


# ══════════════════════════════════════════════════════════════════════
#  EDIT BUTTONS on existing panel
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pb:editbtns:"))
async def cb_editbtns(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    pid   = call.data.split(":")[2]
    panel = _load_panel(pid)
    if not panel: await call.answer("یافت نشد", show_alert=True); return

    await state.update_data(
        edit_panel_id=pid,
        title=panel.title, ptype=panel.type,
        content=panel.content,
        media_ids=[panel.media_file_id] if panel.media_file_id else [],
        buttons=panel.buttons,
        settings=panel.settings,
    )
    rows = [[_btn(f"🗑 {b['label'][:20]}", f"pb:btn_del:{i}")]
            for i, b in enumerate(panel.buttons[:10])]
    rows.append([_btn("➕ دکمه جدید", "pb:btn_add"), _btn("✅ ذخیره", "pb:save")])
    rows.append(_home_back(f"pb:detail:{pid}"))
    await call.message.edit_text(
        f"{bold('🔘 دکمه‌های پنل')} — {esc(panel.title)}\n\nدکمه‌ای برای حذف انتخاب کنید یا دکمه جدید اضافه کنید:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  LINK PANEL TO PARENT
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pb:link_menu")
async def cb_link_menu(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    all_panels = panels_db.all_items()
    rows = [[_btn(f"🔗 {Panel.from_dict(r).title[:28]}", f"pb:link:{pid}")]
            for pid, r in all_panels[:15]]
    rows.append(_home_back())
    await call.message.edit_text(
        f"{bold('🔗 لینک پنل به والد')}\n\nکدام پنل را می‌خواهید به والد متصل کنید؟",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await call.answer()


@router.callback_query(F.data.startswith("pb:link:"))
async def cb_link_panel(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    child_id = call.data.split(":")[2]
    child    = _load_panel(child_id)
    if not child:
        await call.answer("پنل یافت نشد", show_alert=True); return

    all_panels = panels_db.all_items()
    # Bug 3 fix: store parent candidates in state indexed by int to keep
    # callback_data short (pb:linkto:{idx} <= 20 bytes, well under 64-byte limit).
    parent_map = {str(i): pid for i, (pid, _) in enumerate(all_panels) if pid != child_id}
    await state.update_data(link_child_id=child_id, link_parent_map=parent_map)
    await state.set_state(PanelStates.link_parent)

    rows = []
    for idx, (pid, r) in enumerate(all_panels[:15]):
        if pid == child_id:
            continue
        p = Panel.from_dict(r)
        style_label = "🏠 " if p.is_home else ""
        rows.append([_btn(f"📋 {style_label}{p.title[:26]}", f"pb:linkto:{idx}")])
    rows.append([_btn("❌ جدا کردن از والد", f"pb:unlink:{child_id}")])
    rows.append(_home_back())

    await call.message.edit_text(
        f"پنل {bold(esc(child.title))} را به کدام والد متصل کنید؟",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await call.answer()


@router.callback_query(F.data.startswith("pb:linkto:"))
async def cb_linkto(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    idx   = parts[2]
    data  = await state.get_data()
    child_id  = data.get("link_child_id", "")
    parent_id = data.get("link_parent_map", {}).get(idx, "")
    if not child_id or not parent_id:
        await call.answer("خطا: اطلاعات لینک یافت نشد", show_alert=True); return

    child  = _load_panel(child_id)
    parent = _load_panel(parent_id)
    if not child or not parent:
        await call.answer("پنل یافت نشد", show_alert=True); return

    old_parent_id = child.parent_id
    if old_parent_id and old_parent_id != parent_id:
        old_parent = _load_panel(old_parent_id)
        if old_parent and child_id in old_parent.children:
            old_parent.children.remove(child_id)
            _save_panel(old_parent)

    child.parent_id = parent_id
    _save_panel(child)

    if child_id not in parent.children:
        parent.children.append(child_id)
        _save_panel(parent)

    await state.clear()
    await call.answer(f"✅ {child.title} → {parent.title}", show_alert=True)
    await send_panel_menu(call.message, edit=True)


@router.callback_query(F.data.startswith("pb:unlink:"))
async def cb_unlink(call: CallbackQuery, state: FSMContext):
    child_id = call.data.split(":")[2]
    child    = _load_panel(child_id)
    if child and child.parent_id:
        parent = _load_panel(child.parent_id)
        if parent and child_id in parent.children:
            parent.children.remove(child_id)
            _save_panel(parent)
        child.parent_id = None
        _save_panel(child)
    await state.clear()
    await call.answer("✅ پنل از والد جدا شد", show_alert=True)
    await send_panel_menu(call.message, edit=True)


# ══════════════════════════════════════════════════════════════════════
#  TREE VIEW
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pb:tree")
async def cb_tree(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    roots = [
        pid for pid, raw in panels_db.all_items()
        if not raw.get("parent_id")
    ]
    if not roots:
        await call.message.edit_text(
            "📭 هنوز پنلی وجود ندارد\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[_home_back()])
        )
        await call.answer(); return

    tree = ""
    for rid in roots:
        tree += _panel_tree(rid)

    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back()])
    await call.message.edit_text(
        f"{bold('🌳 درخت پنل‌ها')}\n\n```\n{tree[:3500]}\n```",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  CHILDREN LIST
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pb:children:"))
async def cb_children(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    pid   = call.data.split(":")[2]
    panel = _load_panel(pid)
    if not panel: await call.answer("یافت نشد", show_alert=True); return

    if not panel.children:
        await call.answer("این پنل زیرپنل ندارد", show_alert=True); return

    rows = []
    for cid in panel.children[:15]:
        child = _load_panel(cid)
        if child:
            rows.append([_btn(f"📋 {child.title[:28]}", f"pb:detail:{cid}")])
    rows.append(_home_back(f"pb:detail:{pid}"))

    # Bug 6 fix: if no valid children loaded (stale IDs), show informative text
    if len(rows) == 1:
        await call.answer("زیرپنل‌ها پیدا نشدند", show_alert=True); return

    await call.message.edit_text(
        f"{bold('👶 زیرپنل‌های')} {bold(esc(panel.title))}\n\n"
        f"تعداد: {esc(str(len(rows) - 1))} زیرپنل",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  DELETE PANEL
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pb:delete:"))
async def cb_delete_confirm(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    pid   = call.data.split(":")[2]
    panel = _load_panel(pid)
    if not panel: await call.answer("یافت نشد", show_alert=True); return

    await state.set_state(PanelStates.delete_confirm)
    await state.update_data(delete_panel_id=pid)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🗑 بله، حذف شود", f"pb:del_yes:{pid}"),
         _btn("❌ انصراف",        f"pb:detail:{pid}")],
    ])
    await call.message.edit_text(
        f"⚠️ آیا از حذف پنل {bold(esc(panel.title))} مطمئنید؟\n\n"
        f"تعداد زیرپنل‌ها: {bold(str(len(panel.children)))}\n"
        "_این عمل قابل بازگشت نیست\\._",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data.startswith("pb:del_yes:"))
async def cb_delete_yes(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    pid   = call.data.split(":")[2]
    panel = _load_panel(pid)

    if panel and panel.parent_id:
        parent = _load_panel(panel.parent_id)
        if parent and pid in parent.children:
            parent.children.remove(pid)
            _save_panel(parent)

    panels_db.delete(pid)
    await state.clear()

    await call.message.edit_text(
        f"🗑 پنل با موفقیت حذف شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("📋 لیست پنل‌ها", "pb:list"),
             _btn("🏠 خانه",        "pb:menu")],
        ])
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  MAIN MENU CALLBACK + COMMAND
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "pb:menu")
async def cb_panel_menu(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    await state.clear()
    await send_panel_menu(call.message, edit=True)
    await call.answer()


@router.message(Command("panels"))
async def cmd_panels(message: Message, state: FSMContext):
    if not _require_admin(str(message.from_user.id)): return
    await send_panel_menu(message, edit=False)