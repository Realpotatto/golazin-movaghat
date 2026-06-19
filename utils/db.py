from utils.json_manager import JsonManager
import config

users_db    = JsonManager(config.USERS_FILE,       {})
admins_db   = JsonManager(config.ADMINS_FILE,      {})
settings_db = JsonManager(config.BOT_SETTINGS_FILE, {})
panels_db   = JsonManager(config.PANELS_FILE,      {})
forms_db    = JsonManager(config.FORMS_FILE,       {})
discounts_db = JsonManager(config.DISCOUNTS_FILE,  {})

import os
_DATA_DIR = config.DATA_DIR
payments_db  = JsonManager(os.path.join(_DATA_DIR, "payments.json"),  {})
referrals_db = JsonManager(os.path.join(_DATA_DIR, "referrals.json"), {})
