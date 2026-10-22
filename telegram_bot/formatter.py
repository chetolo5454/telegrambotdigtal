"""
Message and Case Formatter for Telegram Bot.
Formats case cards, status changes, and notifications in clean Arabic HTML/Markdown.
"""

from typing import Dict, Any, List, Optional

STATUS_ICONS = {
    "202": "🟡", # تم تقدير الرسوم
    "203": "🟢", # تم دفع الرسوم
    "204": "🔵", # قيدت في جدول المحكمة
    "207": "🟣", # إبلاغ المحامي
    "210": "🔴", # غير مستوفي
    "201": "ℹ️", # تحت المراجعة
    "1":   "📝", # مسودة
    "6":   "❌"  # ملغاة
}


def get_status_icon(case_code: str, step_code: str = "") -> str:
    return STATUS_ICONS.get(case_code) or STATUS_ICONS.get(step_code) or "📄"


def format_case_card(case: Dict[str, Any], client_name: Optional[str] = None, index: Optional[int] = None) -> str:
    req_num = case.get("requestNumber", "—")
    name = client_name or "—"
    case_code = str(case.get("caseCode", ""))
    step_code = str(case.get("stepCode", ""))
    status = case.get("caseMessage") or case.get("stepMessage") or "غير محدد"
    icon = get_status_icon(case_code, step_code)
    
    date = case.get("updatedAtCairo") or case.get("updatedAt") or "—"
    payments = case.get("allPayments", [])
    pays_str = ", ".join([f"<code>{p}</code>" for p in payments]) if payments else "—"
    
    idx_str = f"<b>#{index}</b> " if index is not None else ""
    
    lines = [
        f"{idx_str}⚖️ <b>الطلب:</b> <code>{req_num}</code>",
        f"👤 <b>الموكل:</b> <b>{name}</b>",
        f"{icon} <b>الحالة:</b> {status} (كود: {case_code or step_code})",
        f"💳 <b>رقم السداد:</b> {pays_str}",
        f"📅 <b>تاريخ التحديث:</b> {date}",
    ]
    return "\n".join(lines)


def format_change_notification(change: Dict[str, Any], client_name: Optional[str] = None) -> str:
    req_num = change.get("requestNumber", "")
    kind = change.get("kind", "change")
    name = client_name or "—"
    new_status = change.get("newCaseMessage") or change.get("newStepMessage") or "حالة جديدة"
    old_status = change.get("oldCaseMessage") or change.get("oldStepMessage") or "—"
    new_code = str(change.get("newCaseCode") or "")
    icon = get_status_icon(new_code)
    
    payments = change.get("allPayments", [])
    pays_str = ", ".join([f"<code>{p}</code>" for p in payments]) if payments else "—"
    
    if kind == "new":
        header = "🆕 <b>[طلب جديد تم رصده]</b>"
    else:
        header = "🔔 <b>[تحديث طرأ على حالة طلب]</b>"
        
    lines = [
        f"{header}",
        f"⚖️ <b>رقم الطلب:</b> <code>{req_num}</code>",
        f"👤 <b>الموكل:</b> <b>{name}</b>",
        f"{icon} <b>الحالة الجديدة:</b> {new_status} (كود: {new_code})",
    ]
    if kind != "new" and old_status != "—":
        lines.append(f"⏮ <b>الحالة السابقة:</b> {old_status}")
        
    if payments:
        lines.append(f"💳 <b>رقم السداد:</b> {pays_str}")
        
    lines.append(f"⏰ <b>توقيت الرصد (القاهرة):</b> {change.get('detectedAtCairo', 'الآن')}")
    return "\n".join(lines)


def format_session_status(status: Dict[str, Any]) -> str:
    logged_in = status.get("logged_in", False)
    state_str = "🟢 نشطة ومتصلة" if logged_in else "🔴 غير متصلة أو منتهية"
    
    secs = status.get("access_seconds_left", 0)
    mins = max(0, round(secs / 60))
    
    lines = [
        f"🔐 <b>حالة جلسة مصر الرقمية:</b>",
        f"• الاتصال: <b>{state_str}</b>",
        f"• الرقم القومي: <code>{status.get('user_nid') or '—'}</code>",
        f"• رقم الهاتف: <code>{status.get('user_phone') or '—'}</code>",
        f"• الصلاحية المتبقية: <b>{mins} دقيقة</b>",
        f"• إمكانية التجديد الذاتي: {'نعم ✅' if status.get('can_refresh') else 'يلزم تسجيل الدخول ❌'}",
    ]
    return "\n".join(lines)
