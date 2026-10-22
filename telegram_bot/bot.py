"""
Main Telegram Bot for Digital Egypt Case Tracker (متتبع دعاوى مصر الرقمية).
Provides interactive chat control, status checking, automated token refresh,
and instant notifications on case changes.
"""

import os
import sys
import asyncio
import logging
from typing import Optional, Dict, Any, List

# Ensure directories are in sys.path
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BOT_DIR, ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from case_tracker_py.auth import AuthManager
from case_tracker_py.api import DigitalGovAPI
from case_tracker_py.storage import StorageManager
from case_tracker_py.core import CaseTrackerCore, GROUPS
from case_tracker_py.auto_login import run_auto_login, import_tokens_from_file

# Support both direct execution (python bot.py) and module import (from telegram_bot.bot import ...)
try:
    from .config import load_config, save_config, get_bot_token, is_user_allowed
    from .formatter import (
        format_case_card,
        format_change_notification,
        format_session_status
    )
    from .keyboards import (
        get_main_reply_keyboard,
        get_filter_inline_keyboard,
        get_cases_pagination_keyboard,
        get_auto_login_inline_keyboard,
        get_notifications_keyboard
    )
except (ImportError, ValueError):
    from config import load_config, save_config, get_bot_token, is_user_allowed
    from formatter import (
        format_case_card,
        format_change_notification,
        format_session_status
    )
    from keyboards import (
        get_main_reply_keyboard,
        get_filter_inline_keyboard,
        get_cases_pagination_keyboard,
        get_auto_login_inline_keyboard,
        get_notifications_keyboard
    )

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("CaseTrackerBot")

# Core singletons
auth_mgr = AuthManager()
api_client = DigitalGovAPI(auth_mgr)
storage_mgr = StorageManager()
core_engine = CaseTrackerCore(api_client, storage_mgr)

PAGE_SIZE = 5


# Security check wrapper
def check_auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else 0
        if not is_user_allowed(user_id):
            if update.message:
                await update.message.reply_text("⛔ عذراً، هذا البوت خاص ولا يمكنك الوصول إليه.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ غير مصرح لك.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


# ---------------- Handlers ----------------

@check_auth
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start Command: Welcome message and main menu.
    """
    snapshot = storage_mgr.get_snapshot()
    count = snapshot.get("count", 0) if snapshot else 0
    status = auth_mgr.get_status()
    
    logged_in = status.get("logged_in", False)
    token_status_str = "🟢 متصلة" if logged_in else "🔴 يلزم تسجيل الدخول / منتهية"
    
    welcome_text = (
        "⚖️ <b>أهلاً بك في بوت متتبع الدعاوى المدنية - منصة مصر الرقمية</b>\n\n"
        f"• حالة الجلسة: <b>{token_status_str}</b>\n"
        f"• إجمالي الدعاوى المحفوظة: <b>{count} دعوى</b>\n"
        f"• آخر تحديث مسجل: <b>{snapshot.get('fetchedAtCairo', '—') if snapshot else '—'}</b>\n\n"
        "يمكنك استخدام الأزرار بالأسفل لمتابعة قضاياك، تحديثها فورياً، أو جلب التوكن بضغطة زر عند الحاجة."
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_reply_keyboard()
    )


@check_auth
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>دليل أوامر البوت:</b>\n\n"
        "• <b>📋 عرض الطلبات:</b> استعراض كافة قضاياك المدنية مع حالاتها وأرقام السداد.\n"
        "• <b>⚡ تحديث الدعاوى:</b> فحص فوري لحالات الطلبات من مصر الرقمية.\n"
        "• <b>💳 أرقام السداد:</b> عرض القضايا المطلوب سداد رسومها مع كود الدفع.\n"
        "• <b>🔑 تجديد التوكن:</b> الدخول الآلي وجلب توكن جديد بضغطة زر.\n"
        "• <b>🔍 بحث عن طلب:</b> اكتب رقم الطلب أو اسم الموكل للبحث عنه مباشرة.\n"
        "• <b>/name &lt;رقم_الطلب&gt; &lt;اسم_الموكل&gt;:</b> ربط اسم الموكل بالطلب.\n"
        "• <b>/status:</b> فحص صلاحية التوكن والوقت المتبقي.\n"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


def _get_filtered_requests(filter_key: str = "all") -> List[Dict[str, Any]]:
    snapshot = storage_mgr.get_snapshot()
    requests_list = snapshot.get("requests", []) if snapshot else []
    names = storage_mgr.get_names()

    if filter_key == "all":
        return requests_list
    elif filter_key == "unnamed":
        return [r for r in requests_list if not names.get(r.get("requestNumber"))]
    elif filter_key == "fees":
        return [r for r in requests_list if str(r.get("caseCode")) in ["202", "203"]]
    else:
        return [r for r in requests_list if str(r.get("caseCode")) == filter_key or str(r.get("stepCode")) == filter_key]


async def _send_cases_page(message_or_query, filter_key: str = "all", page: int = 1):
    reqs = _get_filtered_requests(filter_key)
    names = storage_mgr.get_names()
    total_count = len(reqs)

    if not reqs:
        empty_text = "📭 <b>لا توجد دعاوى مطابقة في هذا التصنيف.</b>"
        if hasattr(message_or_query, "edit_message_text"):
            await message_or_query.edit_message_text(empty_text, parse_mode=ParseMode.HTML)
        else:
            await message_or_query.reply_text(empty_text, parse_mode=ParseMode.HTML)
        return

    total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total_count)
    page_items = reqs[start_idx:end_idx]

    cards = []
    for i, r in enumerate(page_items, start=start_idx + 1):
        name = names.get(r.get("requestNumber"))
        cards.append(format_case_card(r, client_name=name, index=i))

    header = f"📋 <b>قائمة الدعاوى (إجمالي {total_count}) — صفحة {page}/{total_pages}:</b>\n\n"
    body = "\n\n───────────────\n\n".join(cards)
    full_text = header + body

    keyboard = get_cases_pagination_keyboard(page, total_pages, filter_key)

    if hasattr(message_or_query, "edit_message_text"):
        try:
            await message_or_query.edit_message_text(full_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        except Exception:
            pass
    else:
        await message_or_query.reply_text(full_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


@check_auth
async def list_cases_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_cases_page(update.message, filter_key="all", page=1)


@check_auth
async def refresh_cases_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 جارٍ تحديث بيانات الدعاوى من مصر الرقمية...")
    
    # Run refresh in executor to avoid blocking event loop
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, core_engine.refresh)
    
    if res.get("ok"):
        count = len(res.get("requests", []))
        changes = res.get("new_changes_count", 0)
        ch_text = f" تم رصد {changes} تغيير جديد! 🔔" if changes else " لم يطرأ أي تغيير جديد."
        await msg.edit_text(
            f"✅ <b>تم التحديث بنجاح!</b>\nإجمالي الدعاوى: <b>{count}</b>\n{ch_text}",
            parse_mode=ParseMode.HTML
        )
    else:
        err = res.get("message") or res.get("error")
        keyboard = get_auto_login_inline_keyboard() if not auth_mgr.get_status().get("logged_in") else None
        await msg.edit_text(
            f"❌ <b>تعذّر التحديث:</b> {err}\n\nقد تكون الجلسة منتهية، يمكنك جلب توكن جديد بضغطة زر أدناه.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )


@check_auth
async def payments_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Shows cases with pending payment or payment codes.
    """
    snapshot = storage_mgr.get_snapshot()
    reqs = snapshot.get("requests", []) if snapshot else []
    names = storage_mgr.get_names()

    paying_cases = [r for r in reqs if r.get("allPayments") or str(r.get("caseCode")) in ["202", "203"]]

    if not paying_cases:
        await update.message.reply_text("💳 لا توجد دعاوى بها أرقام سداد حالياً.", parse_mode=ParseMode.HTML)
        return

    cards = []
    for i, r in enumerate(paying_cases[:8], start=1):
        name = names.get(r.get("requestNumber"))
        cards.append(format_case_card(r, client_name=name, index=i))

    text = f"💳 <b>أرقام سداد الرسوم (عدد {len(paying_cases)} دعوى):</b>\n\n" + "\n\n───────────────\n\n".join(cards)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


@check_auth
async def session_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = auth_mgr.get_status()
    text = format_session_status(status)
    keyboard = get_auto_login_inline_keyboard() if not status.get("logged_in") else None
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


@check_auth
async def auto_login_prompt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = auth_mgr.get_status()
    text = (
        "🔑 <b>جلب وتجديد التوكن التلقائي (بضغطة زر)</b>\n\n"
        "سيقوم البوت بتشغيل متصفح الخلفية تلقائياً وتسجيل الدخول بالبيانات الموجودة في ملف <code>login info.text</code> "
        "وجلب رمز التوكن وحفظه في ملف <code>token.text</code> فوراً دون أي مجهود منك."
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_auto_login_inline_keyboard()
    )


@check_auth
async def set_client_name_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /name <req_num> <client_name>
    """
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "📝 <b>طريقة الاستخدام:</b>\n<code>/name 3829366214 أحمد مصطفى</code>",
            parse_mode=ParseMode.HTML
        )
        return

    req_num = args[0].strip()
    name = " ".join(args[1:]).strip()
    storage_mgr.set_name(req_num, name)
    await update.message.reply_text(
        f"✅ تم ربط الطلب <code>{req_num}</code> باسم الموكل: <b>{name}</b> بنجاح!",
        parse_mode=ParseMode.HTML
    )


@check_auth
async def notifications_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    is_on = cfg.get("auto_notify_enabled", True)
    mins = cfg.get("auto_check_interval_minutes", 10)
    
    state_text = f"مفعلة وتعمل كل <b>{mins} دقائق</b> ✅" if is_on else "متوقفة ❌"
    text = (
        f"🔔 <b>المراقبة والتنبيهات التلقائية:</b>\n\n"
        f"• الحالة الحالية: {state_text}\n\n"
        "عند تفعيلها، يقوم البوت بفحص البوابة في الخلفية ويرسل لك إشعاراً فورياً على التليجرام "
        "عند حدوث أي تغيير في حالة أي دعوى (تقدير رسوم، سداد، قيد جدول، إبلاغ المحامي)."
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_notifications_keyboard(is_on)
    )


# Handle bottom keyboard texts & search
@check_auth
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "📋 عرض الطلبات":
        await list_cases_command(update, context)
    elif text == "⚡ تحديث الدعاوى":
        await refresh_cases_command(update, context)
    elif text == "💳 أرقام السداد":
        await payments_command(update, context)
    elif text == "🔑 تجديد التوكن":
        await auto_login_prompt_command(update, context)
    elif text == "ℹ️ حالة الجلسة":
        await session_status_command(update, context)
    elif text == "🔔 التنبيهات الدورية":
        await notifications_menu_command(update, context)
    elif text == "🔍 بحث عن طلب":
        await update.message.reply_text("🔍 اكتب رقم الطلب أو اسم الموكل للبحث عنه:")
    else:
        # Search query
        snapshot = storage_mgr.get_snapshot()
        reqs = snapshot.get("requests", []) if snapshot else []
        names = storage_mgr.get_names()

        q = text.lower()
        matches = []
        for r in reqs:
            rn = r.get("requestNumber", "").lower()
            nm = names.get(r.get("requestNumber"), "").lower()
            pays = " ".join(r.get("allPayments", [])).lower()
            if q in rn or q in nm or q in pays:
                matches.append(r)

        if not matches:
            await update.message.reply_text(f"🔍 لم يتم العثور على أي طلب يطابق: <b>{text}</b>", parse_mode=ParseMode.HTML)
            return

        cards = []
        for i, r in enumerate(matches[:6], start=1):
            name = names.get(r.get("requestNumber"))
            cards.append(format_case_card(r, client_name=name, index=i))

        res_text = f"🔍 <b>نتائج البحث عن ({text}) — {len(matches)} نتيجة:</b>\n\n" + "\n\n───────────────\n\n".join(cards)
        await update.message.reply_text(res_text, parse_mode=ParseMode.HTML)


# Callback Query Handler
@check_auth
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "noop":
        return

    if data.startswith("page:"):
        _, f_key, p_num = data.split(":")
        await _send_cases_page(query, filter_key=f_key, page=int(p_num))

    elif data.startswith("filter:"):
        f_key = data.split(":")[1]
        await _send_cases_page(query, filter_key=f_key, page=1)

    elif data == "show_filters":
        snapshot = storage_mgr.get_snapshot()
        reqs = snapshot.get("requests", []) if snapshot else []
        names = storage_mgr.get_names()

        counts = {
            "all": len(reqs),
            "fees": len([r for r in reqs if str(r.get("caseCode")) in ["202", "203"]]),
            "202": len([r for r in reqs if str(r.get("caseCode")) == "202"]),
            "203": len([r for r in reqs if str(r.get("caseCode")) == "203"]),
            "204": len([r for r in reqs if str(r.get("caseCode")) == "204"]),
            "207": len([r for r in reqs if str(r.get("caseCode")) == "207"]),
            "unnamed": len([r for r in reqs if not names.get(r.get("requestNumber"))])
        }
        await query.edit_message_reply_markup(reply_markup=get_filter_inline_keyboard(counts))

    elif data == "refresh_now":
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, core_engine.refresh)
        if res.get("ok"):
            await query.edit_message_text(f"✅ تم التحديث بنجاح! إجمالي الدعاوى: {len(res.get('requests', []))}")
        else:
            await query.edit_message_text(f"❌ تعذّر التحديث: {res.get('message') or res.get('error')}")

    elif data == "do_auto_login":
        await query.edit_message_text("⏳ <b>جارٍ تشغيل تسجيل الدخول التلقائي وجلب التوكن...</b>", parse_mode=ParseMode.HTML)
        
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, run_auto_login, auth_mgr)

        if res.get("ok"):
            # Automatically refresh cases too
            await loop.run_in_executor(None, core_engine.refresh)
            status = auth_mgr.get_status()
            mins = round(status.get("access_seconds_left", 0) / 60)
            await query.edit_message_text(
                f"🎉 <b>تم تسجيل الدخول وجلب التوكن بنجاح!</b>\n\n"
                f"• تم تحديث ملف <code>token.text</code>\n"
                f"• صلاحية التوكن: <b>{mins} دقيقة</b> (تتجدد تلقائياً)\n"
                f"• تم تحديث قائمة الدعاوى فوراً.",
                parse_mode=ParseMode.HTML
            )
        else:
            err = res.get("error", "فشل غير معروف")
            await query.edit_message_text(f"❌ <b>فشل تسجيل الدخول التلقائي:</b> {err}", parse_mode=ParseMode.HTML)

    elif data == "do_import_token":
        ok = auth_mgr.load_from_token_file()
        if ok:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, core_engine.refresh)
            status = auth_mgr.get_status()
            mins = round(status.get("access_seconds_left", 0) / 60)
            await query.edit_message_text(
                f"✅ <b>تم استيراد التوكن من ملف token.text بنجاح!</b>\nصلاحية التوكن: {mins} دقيقة.",
                parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_text("❌ تعذّر استيراد التوكن من ملف token.text أو أن صلاحيته منتهية.")

    elif data.startswith("notify:"):
        action = data.split(":")[1]
        cfg = load_config()
        cfg["auto_notify_enabled"] = (action == "enable")
        save_config(cfg)
        status_str = "تم تشغيل المراقبة التلقائية ✅" if cfg["auto_notify_enabled"] else "تم إيقاف المراقبة التلقائية ❌"
        await query.edit_message_text(status_str)


# Periodic Check Job
async def periodic_check_job(context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    if not cfg.get("auto_notify_enabled", True):
        return

    allowed = cfg.get("allowed_chat_ids", [])
    if not allowed:
        return

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, core_engine.refresh)

    if res.get("ok") and res.get("new_changes_count", 0) > 0:
        changes = storage_mgr.get_changes()
        names = storage_mgr.get_names()

        for req_num, ch in changes.items():
            name = names.get(req_num)
            notif_text = format_change_notification(ch, client_name=name)

            for chat_id in allowed:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=notif_text,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Error sending notification to {chat_id}: {e}")

        # Mark changes as acknowledged after notifying
        storage_mgr.acknowledge_changes()


def create_bot_app():
    token = get_bot_token()
    if not token:
        print("\n[تنبيه]: لم يتم إدخال TELEGRAM_BOT_TOKEN بعد.")
        print("يرجى فتح ملف 'telegram_bot/bot_config.json' ووضع رمز التوكن الخاص ببوتك.")
        return None

    app = ApplicationBuilder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cases", list_cases_command))
    app.add_handler(CommandHandler("refresh", refresh_cases_command))
    app.add_handler(CommandHandler("pay", payments_command))
    app.add_handler(CommandHandler("token", auto_login_prompt_command))
    app.add_handler(CommandHandler("status", session_status_command))
    app.add_handler(CommandHandler("name", set_client_name_command))
    app.add_handler(CommandHandler("notify", notifications_menu_command))

    # Buttons & Text Router
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(callback_router))

    # Setup periodic background job
    cfg = load_config()
    interval_seconds = cfg.get("auto_check_interval_minutes", 10) * 60
    app.job_queue.run_repeating(periodic_check_job, interval=interval_seconds, first=15)

    return app


def run_bot():
    app = create_bot_app()
    if not app:
        return
    print("\n=======================================================")
    print("      تم تشغيل بوت التليجرام لمتتبع الدعاوى بنجاح!     ")
    print("=======================================================")
    print("البوت في انتظار رسائلك على التليجرام الآن...")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
