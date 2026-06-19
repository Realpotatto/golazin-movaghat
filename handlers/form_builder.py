"""
handlers/form_builder.py
فرم‌ساز کامل IrForge
— ساخت / ویرایش / حذف فرم توسط ادمین
— پر کردن فرم توسط کاربر با timeout 15 دقیقه
— ارسال نتیجه به گروه با فرمت کامل
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

from models import Form, FormField
from utils.db import forms_db, users_db
from utils.mdv2 import esc, bold, italic, code

logger = logging.getLogger(__name__)
router = Router(name="form_builder")

FORM_TIMEOUT_MINUTES = 15
FIELD_TYPES = {
    "text":   "📝 متن آزاد",
    "number": "🔢 عدد",
    "phone":  "📞 شماره تلفن",
    "email":  "📧 ایمیل",
    "photo":  "🖼 تصویر",
    "select": "📋 انتخابی",
    "share_phone": "📱 اشتراک شماره (آخرین فیلد)",
}


# ══════════════════════════════════════════════════════════════════════
#  STATES
# ══════════════════════════════════════════════════════════════════════

class FormBuilderStates(StatesGroup):
    # Admin — create form
    fb_title            = State()
    fb_dest_group       = State()
    fb_thank_you        = State()
    # Admin — add field
    fb_field_label      = State()
    fb_field_type       = State()
    fb_field_options    = State()   # only for select
    fb_field_required   = State()
    # Admin — edit form
    fb_edit_title       = State()
    fb_edit_dest        = State()
    fb_edit_thanks      = State()


class FormFillStates(StatesGroup):
    # User — filling a form
    filling             = State()


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════

def _require_admin(uid: str) -> bool:
    from handlers.admin_auth import _is_admin
    return _is_admin(uid)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _home_back(back_cb: str = "fb:menu") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_cb),
        InlineKeyboardButton(text="🏠 خانه",   callback_data="fb:menu"),
    ]


def _tog(val: bool) -> str:
    return "✅" if val else "❌"


def _load_form(fid: str) -> Optional[Form]:
    raw = forms_db.get(fid)
    return Form.from_dict(raw) if raw else None


def _save_form(form: Form):
    forms_db.set(form.id, form.to_dict())


def _field_summary(f: dict, idx: int) -> str:
    req   = "✅" if f.get("required", True) else "⭕"
    ftype = FIELD_TYPES.get(f.get("type", "text"), f.get("type", ""))
    return f"{req} {esc(str(idx+1))}\\. {bold(esc(f.get('label','')))} — {esc(ftype)}"


# ══════════════════════════════════════════════════════════════════════
#  ADMIN MENU
# ══════════════════════════════════════════════════════════════════════

def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ فرم جدید",     "fb:new"),
         _btn("📋 لیست فرم‌ها",  "fb:list")],
        _home_back("ap:home"),
    ])


async def send_form_menu(target, edit: bool = True):
    count = forms_db.count()
    text  = (
        f"{bold('📋 فرم‌ساز IrForge')}\n\n"
        f"تعداد فرم‌ها: {bold(str(count))}\n\n"
        "فرم‌های ربات را از اینجا مدیریت کنید:"
    )
    if edit:
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=_menu_kb())
    else:
        await target.answer(text, parse_mode="MarkdownV2", reply_markup=_menu_kb())


# ══════════════════════════════════════════════════════════════════════
#  CREATE FORM — step 1: title
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "fb:new")
async def cb_new_form(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    await state.clear()
    await state.set_state(FormBuilderStates.fb_title)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back()])
    await call.message.edit_text(
        f"{bold('➕ فرم جدید')}\n\nعنوان فرم را وارد کنید:",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(FormBuilderStates.fb_title)
async def fsm_fb_title(message: Message, state: FSMContext):
    await state.update_data(fb_title=message.text.strip(), fb_fields=[])
    await state.set_state(FormBuilderStates.fb_dest_group)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⏭ بعداً تنظیم کنم", "fb:skip_dest")],
        _home_back(),
    ])
    await message.answer(
        f"{bold('📤 گروه مقصد')}\n\n"
        "آیدی گروهی که فرم‌ها به آن فوروارد می‌شود را وارد کنید\\.\n"
        "مثال: `\\-100xxxxxxx`",
        parse_mode="MarkdownV2", reply_markup=kb
    )


@router.message(FormBuilderStates.fb_dest_group)
async def fsm_fb_dest(message: Message, state: FSMContext):
    await state.update_data(fb_dest=message.text.strip())
    await _ask_thanks(message, state)


@router.callback_query(F.data == "fb:skip_dest")
async def cb_skip_dest(call: CallbackQuery, state: FSMContext):
    await state.update_data(fb_dest="")
    await _ask_thanks(call.message, state, edit=True)
    await call.answer()


async def _ask_thanks(target, state: FSMContext, edit: bool = False):
    await state.set_state(FormBuilderStates.fb_thank_you)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⏭ پیام پیش‌فرض", "fb:skip_thanks")],
        _home_back(),
    ])
    txt = (
        f"{bold('✅ پیام پایانی')}\n\n"
        "پیامی که بعد از تکمیل فرم به کاربر نشان داده می‌شود را وارد کنید:"
    )
    if edit:
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


@router.message(FormBuilderStates.fb_thank_you)
async def fsm_fb_thanks(message: Message, state: FSMContext):
    await state.update_data(fb_thanks=message.text)
    await _proceed_to_fields(message, state)


@router.callback_query(F.data == "fb:skip_thanks")
async def cb_skip_thanks(call: CallbackQuery, state: FSMContext):
    await state.update_data(fb_thanks="فرم شما با موفقیت ثبت شد\\. ✅")
    await _proceed_to_fields(call.message, state, edit=True)
    await call.answer()


async def _proceed_to_fields(target, state: FSMContext, edit: bool = False):
    data   = await state.get_data()
    fields = data.get("fb_fields", [])
    kb     = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ افزودن فیلد",          "fb:add_field"),
         _btn(f"📋 فیلدها ({len(fields)})", "fb:field_list")],
        [_btn("✅ ذخیره فرم",            "fb:save_form")],
        _home_back(),
    ])
    txt = (
        f"{bold('📋 فیلدهای فرم')}\n\n"
        f"تعداد فیلدهای فعلی: {bold(str(len(fields)))}\n\n"
        "فیلدهای دلخواه را اضافه کنید، سپس ذخیره کنید:"
    )
    if edit:
        await target.edit_text(txt, parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await target.answer(txt, parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════════════════
#  ADD FIELD
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "fb:add_field")
async def cb_add_field(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    await state.set_state(FormBuilderStates.fb_field_label)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back("fb:fields_menu")])
    await call.message.edit_text(
        f"{bold('➕ فیلد جدید')}\n\nمتن سوال یا لیبل این فیلد را وارد کنید:\n"
        f"مثال: _نام و نام خانوادگی_",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(FormBuilderStates.fb_field_label)
async def fsm_field_label(message: Message, state: FSMContext):
    await state.update_data(cur_field_label=message.text.strip())
    await state.set_state(FormBuilderStates.fb_field_type)

    data   = await state.get_data()
    fields = data.get("fb_fields", [])
    rows   = []
    row    = []
    for key, label in FIELD_TYPES.items():
        if key == "share_phone" and len(fields) == 0:
            continue  # only available as last field (need at least 1 field before)
        row.append(_btn(label, f"fb:ftype:{key}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append(_home_back("fb:fields_menu"))

    await message.answer(
        f"{bold('نوع فیلد را انتخاب کنید:')}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("fb:ftype:"))
async def cb_field_type(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    ftype = call.data.split(":")[2]
    await state.update_data(cur_field_type=ftype)

    if ftype == "select":
        await state.set_state(FormBuilderStates.fb_field_options)
        kb = InlineKeyboardMarkup(inline_keyboard=[_home_back("fb:fields_menu")])
        await call.message.edit_text(
            f"{bold('📋 گزینه‌های انتخابی')}\n\n"
            "گزینه‌ها را هر کدام در یک خط وارد کنید:\n"
            "مثال:\n`گزینه اول\nگزینه دوم\nگزینه سوم`",
            parse_mode="MarkdownV2", reply_markup=kb
        )
        await call.answer(); return

    if ftype == "share_phone":
        # share_phone: automatically required, no further questions
        await state.update_data(cur_field_required=True, cur_field_options=[])
        await _finalize_field(call, state)
        await call.answer(); return

    await state.set_state(FormBuilderStates.fb_field_required)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ الزامی",    "fb:freq:true"),
         _btn("⭕ اختیاری", "fb:freq:false")],
        _home_back("fb:fields_menu"),
    ])
    await call.message.edit_text(
        f"{bold('آیا این فیلد الزامی است؟')}",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(FormBuilderStates.fb_field_options)
async def fsm_field_options(message: Message, state: FSMContext):
    options = [o.strip() for o in message.text.split("\n") if o.strip()]
    await state.update_data(cur_field_options=options)
    await state.set_state(FormBuilderStates.fb_field_required)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ الزامی",    "fb:freq:true"),
         _btn("⭕ اختیاری", "fb:freq:false")],
        _home_back("fb:fields_menu"),
    ])
    await message.answer(
        f"✅ {esc(str(len(options)))} گزینه ثبت شد\\.\n\n{bold('آیا این فیلد الزامی است؟')}",
        parse_mode="MarkdownV2", reply_markup=kb
    )


@router.callback_query(F.data.startswith("fb:freq:"))
async def cb_field_required(call: CallbackQuery, state: FSMContext):
    required = call.data.split(":")[2] == "true"
    await state.update_data(cur_field_required=required)
    await _finalize_field(call, state)
    await call.answer()


async def _finalize_field(call: CallbackQuery, state: FSMContext):
    data    = await state.get_data()
    label   = data.get("cur_field_label", "فیلد")
    ftype   = data.get("cur_field_type", "text")
    options = data.get("cur_field_options", [])
    required = data.get("cur_field_required", True)
    fields  = data.get("fb_fields", [])

    field = FormField(
        name=f"field_{len(fields)+1}",
        label=label,
        type=ftype,
        required=required,
        options=options,
        order=len(fields),
    )
    fields.append(field.to_dict())
    await state.update_data(
        fb_fields=fields,
        cur_field_label=None, cur_field_type=None,
        cur_field_options=[], cur_field_required=True,
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ فیلد بعدی",     "fb:add_field"),
         _btn("✅ ذخیره فرم",     "fb:save_form")],
        _home_back("fb:fields_menu"),
    ])
    await call.message.edit_text(
        f"✅ فیلد {bold(esc(label))} اضافه شد\\!\n\n"
        f"نوع: {esc(FIELD_TYPES.get(ftype, ftype))}\n"
        f"الزامی: {_tog(required)}\n\n"
        f"تعداد فیلدهای کل: {bold(str(len(fields)))}",
        parse_mode="MarkdownV2", reply_markup=kb
    )


# ══════════════════════════════════════════════════════════════════════
#  FIELD LIST
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "fb:field_list")
async def cb_field_list(call: CallbackQuery, state: FSMContext):
    data   = await state.get_data()
    fields = data.get("fb_fields", [])

    if not fields:
        # بجای alert، صفحه‌ای با دکمه افزودن فیلد نشون بده
        await call.message.edit_text(
            f"{bold('📋 فیلدهای فرم')}\n\n{italic('هنوز فیلدی اضافه نشده\\.')}",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [_btn("➕ افزودن فیلد", "fb:add_field")],
                [_btn("🔙 بازگشت", "fb:fields_menu")],
            ]),
        )
        await call.answer(); return

    lines = [_field_summary(f, i) for i, f in enumerate(fields)]
    rows  = [[_btn(f"🗑 حذف فیلد {i+1}", f"fb:del_field:{i}")] for i in range(min(len(fields), 10))]
    # دکمه افزودن فیلد در بالای لیست
    rows.insert(0, [_btn("➕ افزودن فیلد جدید", "fb:add_field")])
    rows.append([_btn("🗑 پاک کردن همه", "fb:clear_fields"), _btn("🔙 بازگشت", "fb:fields_menu")])

    await call.message.edit_text(
        f"{bold('📋 فیلدهای فرم')} ({bold(str(len(fields)))})\n\n" + "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


@router.callback_query(F.data.startswith("fb:del_field:"))
async def cb_del_field(call: CallbackQuery, state: FSMContext):
    idx    = int(call.data.split(":")[2])
    data   = await state.get_data()
    fields = data.get("fb_fields", [])
    if 0 <= idx < len(fields):
        fields.pop(idx)
        for i, f in enumerate(fields):
            f["order"] = i
        await state.update_data(fb_fields=fields)
    await _proceed_to_fields(call.message, state, edit=True)
    await call.answer()


@router.callback_query(F.data == "fb:clear_fields")
async def cb_clear_fields(call: CallbackQuery, state: FSMContext):
    await state.update_data(fb_fields=[])
    await _proceed_to_fields(call.message, state, edit=True)
    await call.answer()


@router.callback_query(F.data == "fb:fields_menu")
async def cb_fields_menu(call: CallbackQuery, state: FSMContext):
    await _proceed_to_fields(call.message, state, edit=True)
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  SAVE FORM
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "fb:save_form")
async def cb_save_form(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    data    = await state.get_data()
    edit_id = data.get("edit_form_id")
    title   = data.get("fb_title",  "فرم بدون عنوان")
    dest    = data.get("fb_dest",   "")
    thanks  = data.get("fb_thanks", "فرم شما با موفقیت ثبت شد\\. ✅")
    fields  = data.get("fb_fields", [])

    if edit_id:
        form = _load_form(edit_id) or Form(id=edit_id)
        form.title              = title
        form.destination_group  = dest
        form.thank_you_message  = thanks
        form.fields             = fields
    else:
        form = Form(
            title=title,
            fields=fields,
            destination_group=dest,
            thank_you_message=thanks,
        )

    _save_form(form)
    await state.clear()

    verb = "بروزرسانی" if edit_id else "ایجاد"
    await call.message.edit_text(
        f"✅ فرم {bold(esc(title))} {esc(verb)} شد\\!\n\n"
        f"🆔 شناسه: {code(form.id)}\n"
        f"📋 تعداد فیلد: {bold(str(len(fields)))}\n"
        f"📤 گروه: {code(dest) if dest else italic('تنظیم نشده')}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("✏️ ویرایش",      f"fb:edit:{form.id}"),
             _btn("📋 لیست فرم‌ها", "fb:list")],
            _home_back("ap:home"),
        ]),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  LIST FORMS
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "fb:list")
async def cb_form_list(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    all_forms = forms_db.all_items()
    if not all_forms:
        await call.message.edit_text(
            "📭 هنوز فرمی ساخته نشده\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [_btn("➕ فرم جدید", "fb:new")], _home_back()
            ])
        )
        await call.answer(); return

    rows = [[_btn(f"📋 {raw.get('title','بی‌نام')[:30]}", f"fb:detail:{fid}")]
            for fid, raw in all_forms[:20]]
    rows.append(_home_back())

    await call.message.edit_text(
        f"{bold(f'📋 لیست فرم‌ها ({len(all_forms)})')}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  FORM DETAIL
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("fb:detail:"))
async def cb_form_detail(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    fid  = call.data.split(":")[2]
    form = _load_form(fid)
    if not form: await call.answer("یافت نشد", show_alert=True); return

    fields_txt = "\n".join(
        _field_summary(f, i) for i, f in enumerate(form.fields)
    ) or italic("بدون فیلد")

    text = (
        f"{bold('📋 جزئیات فرم')}\n\n"
        f"📌 عنوان: {bold(esc(form.title))}\n"
        f"🆔 شناسه: {code(form.id)}\n"
        f"📤 گروه: {code(form.destination_group) if form.destination_group else italic('تنظیم نشده')}\n"
        f"✅ فعال: {_tog(form.is_active)}\n"
        f"⏰ تایمر: {esc(str(FORM_TIMEOUT_MINUTES))} دقیقه\n\n"
        f"{bold('فیلدها:')}\n{fields_txt}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✏️ ویرایش",              f"fb:edit:{fid}"),
         _btn(f"{'⛔ غیرفعال' if form.is_active else '✅ فعال'}",
              f"fb:toggle:{fid}")],
        [_btn("🗑 حذف فرم",             f"fb:delete:{fid}"),
         _btn("📤 تنظیم گروه",          f"fb:editdest:{fid}")],
        _home_back("fb:list"),
    ])
    await call.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("fb:toggle:"))
async def cb_form_toggle(call: CallbackQuery, state: FSMContext):
    fid  = call.data.split(":")[2]
    form = _load_form(fid)
    if not form: await call.answer("یافت نشد", show_alert=True); return
    form.is_active = not form.is_active
    _save_form(form)
    await call.answer(f"{'✅ فعال' if form.is_active else '⛔ غیرفعال'} شد")
    call.data = f"fb:detail:{fid}"
    await cb_form_detail(call, state)


# ══════════════════════════════════════════════════════════════════════
#  EDIT FORM
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("fb:edit:"))
async def cb_edit_form(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    fid  = call.data.split(":")[2]
    form = _load_form(fid)
    if not form: await call.answer("یافت نشد", show_alert=True); return

    await state.clear()
    await state.update_data(
        edit_form_id=fid,
        fb_title=form.title,
        fb_dest=form.destination_group,
        fb_thanks=form.thank_you_message,
        fb_fields=form.fields,
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✏️ عنوان",         "fb:ef:title"),
         _btn("📤 گروه مقصد",    "fb:ef:dest")],
        [_btn("✅ پیام پایانی",   "fb:ef:thanks"),
         _btn("📋 فیلدها",       "fb:field_list")],
        [_btn("➕ افزودن فیلد",   "fb:add_field")],   # دکمه مستقیم ساخت فیلد
        [_btn("✅ ذخیره",         "fb:save_form")],
        _home_back(f"fb:detail:{fid}"),
    ])
    await call.message.edit_text(
        f"{bold('✏️ ویرایش فرم')} — {bold(esc(form.title))}",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data == "fb:ef:title")
async def cb_ef_title(call: CallbackQuery, state: FSMContext):
    await state.set_state(FormBuilderStates.fb_edit_title)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back("fb:fields_menu")])
    await call.message.edit_text("✏️ عنوان جدید را وارد کنید:", parse_mode="MarkdownV2", reply_markup=kb)
    await call.answer()


@router.message(FormBuilderStates.fb_edit_title)
async def fsm_ef_title(message: Message, state: FSMContext):
    await state.update_data(fb_title=message.text.strip())
    await state.set_state(None)
    await message.answer(
        "✅ عنوان بروزرسانی شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_btn("✅ ذخیره", "fb:save_form")]])
    )


@router.callback_query(F.data == "fb:ef:dest")
async def cb_ef_dest(call: CallbackQuery, state: FSMContext):
    await state.set_state(FormBuilderStates.fb_edit_dest)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back("fb:fields_menu")])
    await call.message.edit_text(
        "📤 آیدی گروه جدید را وارد کنید:", parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(FormBuilderStates.fb_edit_dest)
async def fsm_ef_dest(message: Message, state: FSMContext):
    await state.update_data(fb_dest=message.text.strip())
    await state.set_state(None)
    await message.answer(
        "✅ گروه مقصد بروزرسانی شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_btn("✅ ذخیره", "fb:save_form")]])
    )


@router.callback_query(F.data == "fb:ef:thanks")
async def cb_ef_thanks(call: CallbackQuery, state: FSMContext):
    await state.set_state(FormBuilderStates.fb_edit_thanks)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back("fb:fields_menu")])
    await call.message.edit_text(
        "✅ پیام پایانی جدید را وارد کنید:", parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.message(FormBuilderStates.fb_edit_thanks)
async def fsm_ef_thanks(message: Message, state: FSMContext):
    await state.update_data(fb_thanks=message.text)
    await state.set_state(None)
    await message.answer(
        "✅ پیام پایانی بروزرسانی شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_btn("✅ ذخیره", "fb:save_form")]])
    )


@router.callback_query(F.data.startswith("fb:editdest:"))
async def cb_editdest(call: CallbackQuery, state: FSMContext):
    fid  = call.data.split(":")[2]
    form = _load_form(fid)
    if not form: await call.answer("یافت نشد", show_alert=True); return
    await state.clear()
    await state.update_data(
        edit_form_id=fid,
        fb_title=form.title, fb_fields=form.fields,
        fb_thanks=form.thank_you_message,
    )
    await state.set_state(FormBuilderStates.fb_edit_dest)
    kb = InlineKeyboardMarkup(inline_keyboard=[_home_back(f"fb:detail:{fid}")])
    await call.message.edit_text(
        "📤 آیدی گروه جدید را وارد کنید:", parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  DELETE FORM
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("fb:delete:"))
async def cb_delete_form(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    fid  = call.data.split(":")[2]
    form = _load_form(fid)
    if not form: await call.answer("یافت نشد", show_alert=True); return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🗑 بله، حذف شود", f"fb:del_yes:{fid}"),
         _btn("❌ انصراف",        f"fb:detail:{fid}")],
    ])
    await call.message.edit_text(
        f"⚠️ آیا از حذف فرم {bold(esc(form.title))} مطمئنید؟\n_این عمل قابل بازگشت نیست\\._",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data.startswith("fb:del_yes:"))
async def cb_del_yes(call: CallbackQuery, state: FSMContext):
    fid = call.data.split(":")[2]
    forms_db.delete(fid)
    await call.message.edit_text(
        "🗑 فرم با موفقیت حذف شد\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("📋 لیست فرم‌ها", "fb:list"), _btn("🏠 خانه", "fb:menu")]
        ])
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════
#  USER — FILL FORM
# ══════════════════════════════════════════════════════════════════════

async def _schedule_timeout(bot: Bot, chat_id: int, uid: str, fid: str, state: FSMContext):
    """Cancel form if user doesn't finish within FORM_TIMEOUT_MINUTES."""
    await asyncio.sleep(FORM_TIMEOUT_MINUTES * 60)
    current_state = await state.get_state()
    if current_state == FormFillStates.filling.state:
        fill_data = await state.get_data()
        if fill_data.get("filling_form_id") == fid:
            await state.clear()
            try:
                await bot.send_message(
                    chat_id,
                    f"⏰ مهلت پر کردن فرم به پایان رسید\\. دوباره تلاش کنید\\.",
                    parse_mode="MarkdownV2",
                )
            except Exception:
                pass


async def start_form_for_user(
    message: Message,
    state: FSMContext,
    fid: str,
    bot: Bot,
):
    """Entry point: user triggers a form (called from panel renderer)."""
    form = _load_form(fid)
    if not form:
        await message.answer("❌ فرم یافت نشد\\.", parse_mode="MarkdownV2"); return
    if not form.is_active:
        await message.answer("❌ این فرم در حال حاضر غیرفعال است\\.", parse_mode="MarkdownV2"); return
    if not form.fields:
        await message.answer("❌ این فرم فیلدی ندارد\\.", parse_mode="MarkdownV2"); return

    await state.set_state(FormFillStates.filling)
    await state.update_data(
        filling_form_id=fid,
        filling_field_idx=0,
        filling_answers={},
        filling_started=datetime.utcnow().isoformat(),
    )

    asyncio.create_task(
        _schedule_timeout(bot, message.chat.id, str(message.from_user.id), fid, state)
    )
    await _ask_next_field(message, form, 0)


async def _ask_next_field(target: Message, form: Form, idx: int):
    field = FormField.from_dict(form.fields[idx])
    req   = "" if field.required else " \\(اختیاری\\)"
    total = len(form.fields)

    header = (
        f"{bold(esc(form.title))}\n"
        f"📋 فیلد {bold(esc(str(idx+1)))} از {bold(esc(str(total)))}{req}\n\n"
        f"{bold(esc(field.label))}"
    )

    # دکمه ویرایش فیلدهای قبلی (اگه idx > 0)
    def _nav_rows(extra_skip: list = []) -> list:
        rows = []
        if extra_skip:
            rows.append(extra_skip)
        if idx > 0:
            rows.append([_btn("✏️ ویرایش پاسخ قبلی", f"ff:edit:{form.id}:{idx}")])
        rows.append([_btn("❌ لغو فرم", f"ff:cancel:{form.id}")])
        return rows

    if field.type == "share_phone":
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 اشتراک شماره تلفن", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await target.answer(
            f"{header}\n\n_دکمه زیر را بزنید تا شماره شما ثبت شود:_",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )
        # inline nav جداگانه برای share_phone
        nav = _nav_rows()
        if nav:
            await target.answer("​", reply_markup=InlineKeyboardMarkup(inline_keyboard=nav))
    elif field.type == "select" and field.options:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=opt)] for opt in field.options],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        nav = _nav_rows()
        await target.answer(header, parse_mode="MarkdownV2", reply_markup=kb)
        if nav:
            await target.answer("​", reply_markup=InlineKeyboardMarkup(inline_keyboard=nav))
    elif field.type == "photo":
        skip_btn = [] if field.required else [_btn("⏭ رد کردن", f"ff:skip:{form.id}:{idx}")]
        rows = _nav_rows(skip_btn)
        kb_inline = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
        await target.answer(
            f"{header}\n\n_یک تصویر ارسال کنید:_",
            parse_mode="MarkdownV2",
            reply_markup=kb_inline or ReplyKeyboardRemove(),
        )
    else:
        hint = {
            "text":   "",
            "number": "\n_فقط عدد وارد کنید_",
            "phone":  "\n_شماره تلفن: مثال 09xxxxxxxxx_",
            "email":  "\n_آدرس ایمیل را وارد کنید_",
        }.get(field.type, "")
        skip_btn = [] if field.required else [_btn("⏭ رد کردن", f"ff:skip:{form.id}:{idx}")]
        rows = _nav_rows(skip_btn)
        kb_inline = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
        await target.answer(
            f"{header}{esc(hint)}",
            parse_mode="MarkdownV2",
            reply_markup=kb_inline or ReplyKeyboardRemove(),
        )


@router.message(FormFillStates.filling)
async def fsm_fill_field(message: Message, state: FSMContext):
    data    = await state.get_data()
    fid     = data.get("filling_form_id")
    idx     = data.get("filling_field_idx", 0)
    answers = data.get("filling_answers", {})

    form    = _load_form(fid)
    if not form or idx >= len(form.fields):
        await state.clear(); return

    field = FormField.from_dict(form.fields[idx])

    # Validate
    answer = None
    if field.type == "share_phone":
        if message.contact:
            answer = message.contact.phone_number
        elif not field.required:
            answer = ""
        else:
            edit_kb = _edit_field_kb(fid, idx, answers)
            await message.answer(
                "📱 لطفاً از دکمه زیر شماره خود را ارسال کنید\\.",
                parse_mode="MarkdownV2", reply_markup=edit_kb
            ); return
    elif field.type == "photo":
        if message.photo:
            answer = message.photo[-1].file_id
        elif not field.required:
            answer = ""
        else:
            edit_kb = _edit_field_kb(fid, idx, answers)
            await message.answer(
                "🖼 لطفاً یک تصویر ارسال کنید\\.", parse_mode="MarkdownV2",
                reply_markup=edit_kb
            ); return
    elif field.type == "number":
        txt = (message.text or "").strip()
        if not txt.lstrip("-").replace(".", "").isdigit():
            if not field.required:
                answer = ""
            else:
                edit_kb = _edit_field_kb(fid, idx, answers)
                await message.answer(
                    "🔢 لطفاً فقط عدد وارد کنید\\.", parse_mode="MarkdownV2",
                    reply_markup=edit_kb
                ); return
        else:
            answer = txt
    else:
        answer = (message.text or "").strip()
        if not answer and field.required:
            edit_kb = _edit_field_kb(fid, idx, answers)
            await message.answer(
                f"❌ این فیلد الزامی است\\. لطفاً {bold(esc(field.label))} را وارد کنید:",
                parse_mode="MarkdownV2",
                reply_markup=edit_kb
            ); return

    answers[field.name] = {"label": field.label, "value": answer, "type": field.type}
    next_idx = idx + 1

    if next_idx >= len(form.fields):
        # Form complete
        await state.update_data(filling_answers=answers)
        await _submit_form(message, state, form, answers)
    else:
        await state.update_data(filling_field_idx=next_idx, filling_answers=answers)
        await _ask_next_field(message, form, next_idx)


@router.callback_query(F.data.startswith("ff:skip:"))
async def cb_ff_skip(call: CallbackQuery, state: FSMContext):
    parts   = call.data.split(":")
    fid     = parts[2]
    idx     = int(parts[3])
    data    = await state.get_data()
    answers = data.get("filling_answers", {})
    form    = _load_form(fid)
    if not form: await call.answer(); return

    field = FormField.from_dict(form.fields[idx])
    answers[field.name] = {"label": field.label, "value": "—", "type": field.type}
    next_idx = idx + 1

    if next_idx >= len(form.fields):
        await state.update_data(filling_answers=answers)
        await _submit_form(call.message, state, form, answers)
    else:
        await state.update_data(filling_field_idx=next_idx, filling_answers=answers)
        await _ask_next_field(call.message, form, next_idx)
    await call.answer()


def _edit_field_kb(fid: str, cur_idx: int, answers: dict) -> "InlineKeyboardMarkup | None":
    """کیبورد ویرایش فیلدهای قبلاً پر شده — برای نمایش در پیام‌های خطا."""
    if cur_idx == 0 or not answers:
        return None
    rows = []
    # نمایش آخرین فیلد پر شده برای ویرایش
    rows.append([_btn(f"✏️ ویرایش فیلد قبلی", f"ff:edit:{fid}:{cur_idx}")])
    rows.append([_btn("❌ لغو فرم", f"ff:cancel:{fid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("ff:edit:"))
async def cb_ff_edit(call: CallbackQuery, state: FSMContext):
    """برگشت به فیلد قبلی برای ویرایش."""
    parts   = call.data.split(":")
    fid     = parts[2]
    cur_idx = int(parts[3])
    back_idx = max(0, cur_idx - 1)

    data    = await state.get_data()
    answers = data.get("filling_answers", {})
    form    = _load_form(fid)
    if not form:
        await call.answer("فرم یافت نشد", show_alert=True); return

    # حذف آخرین جواب تا کاربر دوباره وارد کنه
    field_back = FormField.from_dict(form.fields[back_idx])
    answers.pop(field_back.name, None)
    await state.update_data(filling_field_idx=back_idx, filling_answers=answers)
    await _ask_next_field(call.message, form, back_idx)
    await call.answer()


@router.callback_query(F.data.startswith("ff:cancel:"))
async def cb_ff_cancel(call: CallbackQuery, state: FSMContext):
    """لغو کامل فرم."""
    await state.clear()
    await call.message.edit_text(
        f"❌ {italic('فرم لغو شد\\.')}",
        parse_mode="MarkdownV2",
    )
    await call.answer()


async def _submit_form(
    message: Message,
    state: FSMContext,
    form: Form,
    answers: dict,
):
    uid    = str(message.from_user.id)
    uname  = message.from_user.username or ""
    fname  = message.from_user.first_name or ""
    now    = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Thank user
    await message.answer(
        form.thank_you_message,
        parse_mode="MarkdownV2",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.clear()

    # Build report
    lines = [
        bold("📋 فرم دریافت شد"),
        "",
        f"📌 فرم: {bold(esc(form.title))}",
        f"👤 کاربر: {esc('@'+uname) if uname else code(uid)} \\({esc(fname)}\\)",
        f"🕐 زمان: {esc(now)}",
        "",
        bold("پاسخ‌ها:"),
    ]
    for field_name, ans in answers.items():
        label = ans.get("label", field_name)
        value = ans.get("value", "—")
        ftype = ans.get("type", "text")
        if ftype == "photo":
            lines.append(f"📷 {bold(esc(label))}: \\[تصویر\\]")
        else:
            lines.append(f"• {bold(esc(label))}: {esc(str(value))}")

    report = "\n".join(lines)
    bot: Bot = message.bot

    # Send to destination group
    if form.destination_group:
        try:
            await bot.send_message(
                form.destination_group,
                report,
                parse_mode="MarkdownV2",
            )
            # Send any photo answers separately
            for field_name, ans in answers.items():
                if ans.get("type") == "photo" and ans.get("value") and ans["value"] != "—":
                    await bot.send_photo(
                        form.destination_group,
                        ans["value"],
                        caption=esc(f"📷 {ans['label']} — {uname or uid}"),
                        parse_mode="MarkdownV2",
                    )
        except Exception as e:
            logger.error("Failed to send form to group %s: %s", form.destination_group, e)

    # Notify admins
    if form.notify_admin:
        from utils.db import admins_db
        for admin_id, adm in admins_db.all_items():
            if adm.get("permissions") and ("all" in adm["permissions"] or "forms" in adm["permissions"]):
                try:
                    await bot.send_message(int(admin_id), report, parse_mode="MarkdownV2")
                except Exception:
                    pass

    # Save to user record
    from utils.db import users_db
    submission = {
        "form_id":   form.id,
        "form_title": form.title,
        "answers":   answers,
        "submitted_at": datetime.utcnow().isoformat(),
    }
    users_db.append_to_list(uid, "orders", submission)


# ══════════════════════════════════════════════════════════════════════
#  MENU CALLBACK + COMMAND
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "fb:menu")
async def cb_form_menu(call: CallbackQuery, state: FSMContext):
    if not _require_admin(str(call.from_user.id)): await call.answer("⛔"); return
    await state.clear()
    await send_form_menu(call.message, edit=True)
    await call.answer()


@router.message(Command("forms"))
async def cmd_forms(message: Message, state: FSMContext):
    if not _require_admin(str(message.from_user.id)): return
    await send_form_menu(message, edit=False)
