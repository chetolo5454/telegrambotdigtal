"""
Configuration Manager for Digital Egypt Case Tracker Telegram Bot.
"""

import os
import json
from typing import Dict, Any, List

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BOT_DIR, "bot_config.json")
DEFAULT_CONFIG = {
    "bot_token": "",
    "allowed_chat_ids": [],
    "auto_check_interval_minutes": 10,
    "auto_notify_enabled": True
}


def load_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_CONFIG, **data}
        except Exception as e:
            print(f"[تحذير في قراءة إعدادات البوت]: {e}")
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(cfg: Dict[str, Any]):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[خطأ في حفظ إعدادات البوت]: {e}")


def get_bot_token() -> str:
    # Priority: Environment variable -> config file
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token and token != "YOUR_BOT_TOKEN_HERE":
        return token
    cfg = load_config()
    tok = cfg.get("bot_token", "").strip()
    if tok and tok != "YOUR_BOT_TOKEN_HERE":
        return tok
    return ""


def is_user_allowed(chat_id: int) -> bool:
    env_ids = os.getenv("ALLOWED_CHAT_IDS", "").strip()
    if env_ids:
        try:
            allowed = [int(x.strip()) for x in env_ids.split(",") if x.strip()]
            if allowed:
                return chat_id in allowed
        except Exception:
            pass

    cfg = load_config()
    allowed = cfg.get("allowed_chat_ids", [])
    if not allowed:
        # If no allowed IDs configured yet, allow first user and register them
        allowed.append(chat_id)
        cfg["allowed_chat_ids"] = allowed
        save_config(cfg)
        return True
    return chat_id in allowed
