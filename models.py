from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from datetime import datetime
import uuid


def _now() -> str:
    return datetime.utcnow().isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────── BUTTON ───────────────────────────

@dataclass
class Button:
    label: str
    action: str                        # url | panel | form | callback | contact | location
    value: str = ""
    row: int = 0
    col: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Button":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─────────────────────────── PANEL ───────────────────────────

@dataclass
class Panel:
    id: str = field(default_factory=_uid)
    title: str = ""
    type: str = "text"                 # text | photo | video | audio | document | carousel
    content: str = ""
    media_file_id: str = ""
    buttons: list[dict] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    is_home: bool = False
    is_active: bool = True
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Panel":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─────────────────────────── USER ────────────────────────────

@dataclass
class User:
    user_id: str = ""
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    language: str = "fa"
    profile_data: dict[str, Any] = field(default_factory=dict)
    orders: list[dict] = field(default_factory=list)
    is_admin: bool = False
    is_banned: bool = False
    ban_reason: str = ""
    current_panel: Optional[str] = None
    current_form: Optional[str] = None
    form_data: dict[str, Any] = field(default_factory=dict)
    flood_timestamps: list[str] = field(default_factory=list)
    joined_at: str = field(default_factory=_now)
    last_seen: str = field(default_factory=_now)
    referral_by: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "User":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─────────────────────────── ADMIN ───────────────────────────

@dataclass
class Admin:
    user_id: str = ""
    username: str = ""
    permissions: list[str] = field(default_factory=list)
    # permissions: panels | users | forms | discounts | settings | broadcast | stats
    added_at: str = field(default_factory=_now)
    added_by: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Admin":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def has_permission(self, perm: str) -> bool:
        return "all" in self.permissions or perm in self.permissions


# ──────────────────────────── FORM ───────────────────────────

@dataclass
class FormField:
    name: str
    label: str
    type: str = "text"                 # text | number | phone | email | photo | location | select
    required: bool = True
    options: list[str] = field(default_factory=list)
    validation_regex: str = ""
    error_message: str = ""
    order: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FormField":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Form:
    id: str = field(default_factory=_uid)
    title: str = ""
    fields: list[dict] = field(default_factory=list)
    destination_group: str = ""
    destination_admin_ids: list[str] = field(default_factory=list)
    thank_you_message: str = "فرم شما با موفقیت ثبت شد. ✅"
    is_active: bool = True
    notify_admin: bool = True
    allow_edit: bool = False
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Form":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─────────────────────────── DISCOUNT ────────────────────────

@dataclass
class Discount:
    id: str = field(default_factory=_uid)
    code: str = ""
    type: str = "percent"              # percent | fixed
    value: float = 0.0
    expiry: Optional[str] = None       # ISO datetime string or None
    capacity: int = 0                  # 0 = unlimited
    used: int = 0
    used_by: list[str] = field(default_factory=list)
    is_active: bool = True
    min_order_amount: float = 0.0
    description: str = ""
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Discount":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def is_valid(self) -> bool:
        if not self.is_active:
            return False
        if self.capacity > 0 and self.used >= self.capacity:
            return False
        if self.expiry:
            try:
                exp = datetime.fromisoformat(self.expiry)
                if datetime.utcnow() > exp:
                    return False
            except ValueError:
                return False
        return True

    def calculate(self, amount: float) -> float:
        if not self.is_valid():
            return amount
        if amount < self.min_order_amount:
            return amount
        if self.type == "percent":
            return round(amount * (1 - self.value / 100), 2)
        elif self.type == "fixed":
            return max(0.0, round(amount - self.value, 2))
        return amount


# ───────────────────────── BOT SETTINGS ──────────────────────

@dataclass
class WorkingHours:
    enabled: bool = False
    open_time: str = "09:00"
    close_time: str = "21:00"
    days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    # 0=Monday … 6=Sunday
    closed_message: str = "ربات در حال حاضر فعال نیست. لطفاً بعداً تلاش کنید."

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WorkingHours":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AntiFlood:
    enabled: bool = True
    max_messages: int = 5
    interval_seconds: int = 5
    ban_duration_seconds: int = 60
    warn_message: str = "⚠️ لطفاً کمی صبر کنید."

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AntiFlood":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BotSettings:
    language: str = "fa"
    welcome_msg: str = "سلام! به ربات خوش آمدید. 👋"
    error_msg: str = "خطایی رخ داد. لطفاً دوباره تلاش کنید."
    not_found_msg: str = "این بخش یافت نشد."
    panel_inactive_msg: str = "این بخش فعلاً غیرفعال است. لطفاً بعداً مراجعه کنید."
    banned_msg: str = "شما از استفاده از این ربات محروم شده‌اید."
    maintenance_msg: str = "ربات در حال تعمیر است. به زودی برمی‌گردیم! 🔧"
    watermark: str = ""
    watermark_enabled: bool = False
    maintenance: bool = False
    force_join_channels: list[str] = field(default_factory=list)
    force_join_message: str = "برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید:"
    working_hours: dict = field(default_factory=lambda: WorkingHours().to_dict())
    anti_flood: dict = field(default_factory=lambda: AntiFlood().to_dict())
    home_panel_id: Optional[str] = None
    support_username: str = ""
    support_message: str = "برای پشتیبانی با {support} تماس بگیرید."
    currency: str = "تومان"
    payment_info: str = ""
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BotSettings":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
