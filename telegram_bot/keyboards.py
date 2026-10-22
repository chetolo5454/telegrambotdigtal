"""
Telegram Keyboards (Reply Keyboards & Inline Keyboards) for Case Tracker Bot.
"""

from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Any


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """
    Bottom persistent navigation keyboard in Arabic.
    """
    keyboard = [
        [KeyboardButton("📋 عرض الطلبات"), KeyboardButton("⚡ تحديث الدعاوى")],
        [KeyboardButton("💳 أرقام السداد"), KeyboardButton("🔑 تجديد التوكن")],
        [KeyboardButton("🔍 بحث عن طلب"), KeyboardButton("ℹ️ حالة الجلسة")],
        [KeyboardButton("🔔 التنبيهات الدورية")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_filter_inline_keyboard(counts: Dict[str, int]) -> InlineKeyboardMarkup:
    """
    Inline filter buttons matching the web UI groups.
    """
    fees_count = counts.get("fees", 0)
    paid_count = counts.get("203", 0)
    estimated_count = counts.get("202", 0)
    court_count = counts.get("204", 0)
    lawyer_count = counts.get("207", 0)
    all_count = sum(counts.values()) if not counts.get("all") else counts["all"]
    unnamed_count = counts.get("unnamed", 0)

    buttons = [
        [
            InlineKeyboardButton(f"🟡 تقدير الرسوم ({estimated_count})", callback_data="filter:202"),
            InlineKeyboardButton(f"🟢 تم الدفع ({paid_count})", callback_data="filter:203")
        ],
        [
            InlineKeyboardButton(f"🔵 قيدت بالجدول ({court_count})", callback_data="filter:204"),
            InlineKeyboardButton(f"🟣 إبلاغ المحامي ({lawyer_count})", callback_data="filter:207")
        ],
        [
            InlineKeyboardButton(f"👤 بدون اسم ({unnamed_count})", callback_data="filter:unnamed"),
            InlineKeyboardButton(f"📋 عرض الكل ({all_count})", callback_data="filter:all")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_cases_pagination_keyboard(current_page: int, total_pages: int, filter_key: str = "all") -> InlineKeyboardMarkup:
    """
    Pagination inline buttons (Next, Prev, Refresh).
    """
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("◀️ السابق", callback_data=f"page:{filter_key}:{current_page-1}"))
    nav_row.append(InlineKeyboardButton(f"{current_page} / {total_pages}", callback_data="noop"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton("التالي ▶️", callback_data=f"page:{filter_key}:{current_page+1}"))

    buttons = [
        nav_row,
        [
            InlineKeyboardButton("🔍 تصفية حسب الحالة", callback_data="show_filters"),
            InlineKeyboardButton("⚡ تحديث فوري", callback_data="refresh_now")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_auto_login_inline_keyboard() -> InlineKeyboardMarkup:
    """
    Inline actions when token expires or user requests token refresh.
    """
    buttons = [
        [InlineKeyboardButton("⚡ جلب وتجديد التوكن الآن (بضغطة زر)", callback_data="do_auto_login")],
        [InlineKeyboardButton("📂 استيراد من ملف token.text", callback_data="do_import_token")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_notifications_keyboard(is_enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "❌ إيقاف المراقبة التلقائية" if is_enabled else "✅ تشغيل المراقبة التلقائية"
    toggle_data = "notify:disable" if is_enabled else "notify:enable"
    buttons = [
        [InlineKeyboardButton(toggle_text, callback_data=toggle_data)],
        [InlineKeyboardButton("⚡ فحص التغييرات الآن", callback_data="refresh_now")]
    ]
    return InlineKeyboardMarkup(buttons)
