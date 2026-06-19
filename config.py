import os

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "7907271263:AAGecgvh_xA-xMVVidpSG6TuEW7MW-eCWi0")

ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "4857")

ADMIN_IDS: list[int] = [
    # int("YOUR_TELEGRAM_ID"),
]

DATA_DIR: str = os.path.join(os.path.dirname(__file__), "data")
USERS_FILE: str = os.path.join(DATA_DIR, "users.json")
PANELS_FILE: str = os.path.join(DATA_DIR, "panels.json")
FORMS_FILE: str = os.path.join(DATA_DIR, "forms.json")
DISCOUNTS_FILE: str = os.path.join(DATA_DIR, "discounts.json")
BOT_SETTINGS_FILE: str = os.path.join(DATA_DIR, "bot_settings.json")
ADMINS_FILE: str = os.path.join(DATA_DIR, "admins.json")

DEFAULT_LANGUAGE: str = "fa"
MAX_FLOOD_MESSAGES: int = 5
FLOOD_INTERVAL_SECONDS: int = 5
SESSION_TIMEOUT_SECONDS: int = 300

os.makedirs(DATA_DIR, exist_ok=True)
