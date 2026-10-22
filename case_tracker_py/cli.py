"""
Command Line Interface (CLI) for Case Tracker.
Provides terminal commands for updating cases, monitoring, evidence generation,
and starting the Web UI.
"""

import sys
import time
import argparse
import webbrowser
from typing import Optional
from .auth import AuthManager
from .api import DigitalGovAPI
from .storage import StorageManager
from .core import CaseTrackerCore, GROUPS
from .evidence import EvidenceGenerator
from .reconcile import reconcile_cases
from .browser_login import run_browser_login
from .auto_login import run_auto_login

# Ensure terminal printing doesn't crash on Windows Arabic encoding
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def print_banner():
    print("=" * 70)
    print("       متتبع الدعاوى المدنية - منصة مصر الرقمية (Python Tool)")
    print("=" * 70)


def print_cases_table(requests: list, names: dict, changes: dict = None):
    changes = changes or {}
    print("\n{:<4} {:<14} {:<24} {:<22} {:<20} {:<16}".format(
        "#", "رقم الطلب", "اسم الموكل", "الحالة", "آخر تحديث", "أرقام السداد"
    ))
    print("-" * 105)

    for idx, r in enumerate(requests, 1):
        req_num = r.get("requestNumber", "")
        name = names.get(req_num, "—")
        status = r.get("caseMessage", "") or r.get("stepMessage", "")
        date = r.get("updatedAtCairo", "") or r.get("updatedAt", "")
        pays = " + ".join(r.get("allPayments", [])) or "—"

        ch = changes.get(req_num)
        ch_flag = " [جديد]" if ch and ch.get("kind") == "new" else (" [تغيير]" if ch else "")

        print("{:<4} {:<14} {:<24} {:<22} {:<20} {:<16}".format(
            idx, req_num, name[:22], (status + ch_flag)[:20], date[:18], pays[:16]
        ))
    print("-" * 105)
    print(f"إجمالي الدعاوى المعروضة: {len(requests)}")


def run_cli():
    parser = argparse.ArgumentParser(
        description="أداة بايثون لتتبع ومراقبة قضايا ودعاوى مصر الرقمية",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("--serve", action="store_true", help="تشغيل واجهة الويب التفاعلية (الموصى به)")
    parser.add_argument("--port", type=int, default=5000, help="منفذ خادم واجهة الويب (افتراضي: 5000)")
    parser.add_argument("--no-browser", action="store_true", help="عدم فتح المتصفح تلقائياً عند تشغيل السيرفر")
    parser.add_argument("--list", action="store_true", help="عرض جدول الدعاوى المحفوظة محلياً في التيرمنال")
    parser.add_argument("--refresh", action="store_true", help="تحديث فوري لبيانات الدعاوى وعرضها في التيرمنال")
    parser.add_argument("--watch", action="store_true", help="تشغيل وضع المراقبة الدورية المباشر في الخلفية")
    parser.add_argument("--interval", type=int, default=10, help="فترة التحديث التلقائي بالدقائق في وضع المراقبة (افتراضي: 10)")
    parser.add_argument("--auto-login", action="store_true", help="تسجيل الدخول التلقائي بضغطة زر ببيانات ملف login info.text وجلب التوكن")
    parser.add_argument("--import-token", action="store_true", help="استيراد التوكن مباشرة من ملف token.text وتحديث الدعاوى")
    parser.add_argument("--bot", action="store_true", help="تشغيل بوت التليجرام لمتابعة الدعاوى وتلقي الإشعارات على الهاتف")
    parser.add_argument("--login", action="store_true", help="فتح المتصفح لتسجيل الدخول والتقاط رمز الجلسة تلقائياً")
    parser.add_argument("--token", type=str, help="تعيين رمز الوصول (Access Token) يدوياً")
    parser.add_argument("--refresh-token", type=str, help="تعيين رمز التجديد (Refresh Token)")
    parser.add_argument("--status", action="store_true", help="عرض حالة الجلسة وصلاحية التوكن")
    parser.add_argument("--evidence", type=str, metavar="REQ_NUM", help="تصدير ملف الأدلة الرقمية لطلب محدد")
    parser.add_argument("--reconcile", action="store_true", help="عرض جدول مطابقة أرقام السداد مع البنك")
    parser.add_argument("--audit", action="store_true", help="عرض سجل التدقيق للتغييرات")
    parser.add_argument("--backup", type=str, metavar="FILE", help="تصدير نسخة احتياطية لأسماء الموكلين إلى ملف JSON")
    parser.add_argument("--restore", type=str, metavar="FILE", help="استرجاع أسماء الموكلين من ملف JSON")
    parser.add_argument("--set-name", nargs=2, metavar=("REQ_NUM", "NAME"), help="تحديد اسم موكل لطلب محدد")

    args = parser.parse_args()

    auth = AuthManager()
    api = DigitalGovAPI(auth)
    storage = StorageManager()
    core = CaseTrackerCore(api, storage)
    ev_gen = EvidenceGenerator(api, storage)

    print_banner()

    # Handle manual token
    if args.token:
        auth.set_tokens(args.token, args.refresh_token)
        print(f"[نجاح] تم حفظ التوكن بنجاح. حالة الجلسة:")
        print(auth.get_status())
        return

    # Handle set-name
    if args.set_name:
        req_num, name = args.set_name
        storage.set_name(req_num, name)
        print(f"[نجاح] تم ربط الطلب {req_num} باسم الموكل: {name}")
        return

    # Handle backup
    if args.backup:
        storage.backup_names(args.backup)
        print(f"[نجاح] تم تصدير النسخة الاحتياطية إلى: {args.backup}")
        return

    # Handle restore
    if args.restore:
        count = storage.restore_names(args.restore)
        print(f"[نجاح] تم استرجاع {count} اسم موكل من الملف: {args.restore}")
        return

    # Handle status
    if args.status:
        s = auth.get_status()
        print("\n--- حالة الجلسة والتوكن ---")
        print(f"متصل: {'نعم' if s['logged_in'] else 'لا'}")
        print(f"الرقم القومي: {s.get('user_nid') or '—'}")
        print(f"رقم الحساب: {s.get('user_phone') or '—'}")
        print(f"صلاحية التوكن: {round(s.get('access_seconds_left', 0)/60)} دقيقة")
        print(f"إمكانية التجديد: {'نعم' if s['can_refresh'] else 'لا'}")
        return

    # Handle auto-login
    if args.auto_login:
        print("\n[تسجيل الدخول التلقائي]: جارٍ قراءة بيانات ملف 'login info.text' والاتصال ببوابة مصر الرقمية...")
        res = run_auto_login(auth)
        if res.get("ok"):
            print("\n[نجاح] تم تسجيل الدخول وحفظ التوكن في الجلسة وتحديث ملف token.text!")
            print("جارٍ تحديث قائمة الدعاوى...")
            ref_res = core.refresh()
            if ref_res.get("ok"):
                print_cases_table(ref_res["requests"], ref_res["names"])
        else:
            print(f"\n[فشل تسجيل الدخول التلقائي]: {res.get('error')}")
        return

    # Handle import-token
    if args.import_token:
        print("\nجارٍ استيراد التوكن من ملف token.text...")
        if auth.load_from_token_file():
            print("[نجاح] تم استيراد التوكن الساري بنجاح!")
            ref_res = core.refresh()
            if ref_res.get("ok"):
                print_cases_table(ref_res["requests"], ref_res["names"])
        else:
            print("[خطأ] تعذّر استيراد التوكن من ملف token.text أو أن صلاحيته منتهية.")
        return

    # Handle bot
    if args.bot:
        from telegram_bot.bot import run_bot
        run_bot()
        return

    # Handle login
    if args.login:
        print("\nجارٍ تشغيل المتصفح لتسجيل الدخول...")
        res = run_browser_login(auth)
        if res.get("ok"):
            print("\n[نجاح] تم تسجيل الدخول وحفظ الجلسة بنجاح!")
            print("جارٍ تحديث قائمة الدعاوى...")
            ref_res = core.refresh()
            if ref_res.get("ok"):
                print_cases_table(ref_res["requests"], ref_res["names"])
        else:
            print(f"\n[فشل]: {res.get('error')}")
        return

    # Handle evidence
    if args.evidence:
        req_num = args.evidence.strip()
        print(f"\nجارٍ استخراج وتوثيق الأدلة الرقمية للطلب {req_num}...")
        json_file = f"evidence-{req_num}.json"
        html_file = f"evidence-{req_num}.html"
        try:
            bundle = ev_gen.generate(req_num, export_json_path=json_file, export_html_path=html_file)
            print(f"[نجاح] تم إنشاء ملف الأدلة:")
            print(f"  - ملف JSON: {json_file}")
            print(f"  - تقرير HTML: {html_file}")
            analysis = bundle["analysis"]
            print(f"\nملخص التحليل: عدد أحداث الدفع: {analysis['feesPaidEvents']} - الحالة: {analysis['currentStatus']}")
        except Exception as e:
            print(f"[خطأ]: {e}")
        return

    # Handle reconcile
    if args.reconcile:
        print("\nجارٍ جلب وتدقيق أرقام السداد مع مراحل الدعاوى...")
        rows = reconcile_cases(api, storage)
        print("\n{:<14} {:<20} {:<18} {:<16} {:<24}".format(
            "رقم الطلب", "الموكل", "أرقام السداد", "عمليات الدفع", "أول دفع (القاهرة)"
        ))
        print("-" * 95)
        for r in rows:
            print("{:<14} {:<20} {:<18} {:<16} {:<24}".format(
                r["requestNumber"], (r["name"] or "—")[:18], r["paymentNumbers"][:16],
                f"{r['paidEventsCount']} دفع", r["firstPaidCairo"]
            ))
        print("-" * 95)
        return

    # Handle audit
    if args.audit:
        entries = storage.get_audit_log()
        print(f"\n--- سجل التدقيق والتغييرات المرصودة ({len(entries)} سجل) ---")
        for e in reversed(entries[-25:]):
            at = e.get("at", "")[:19]
            req = e.get("requestNumber", "")
            msg = e.get("caseMessage", "")
            pays = "+".join(e.get("payments", []))
            first = "رصد أولي" if e.get("firstObservation") else "تغيير"
            print(f"[{at}] طلب {req} - {msg} (سداد: {pays or '—'}) [{first}]")
        return

    # Handle list
    if args.list:
        snapshot = storage.get_snapshot()
        if not snapshot or not snapshot.get("requests"):
            print("\nلا توجد دعاوى محفوظة محلياً بعد. استخدم --refresh أو --login لتحديث البيانات.")
            return
        names = storage.get_names()
        changes = storage.get_changes()
        print(f"\n--- قائمة الدعاوى المحفوظة محلياً (آخر تحديث: {snapshot.get('fetchedAtCairo') or '—'}) ---")
        print_cases_table(snapshot["requests"], names, changes)
        return

    # Handle refresh
    if args.refresh:
        print("\nجارٍ تحديث بيانات الدعاوى من مصر الرقمية...")
        res = core.refresh()
        if res.get("ok"):
            print_cases_table(res["requests"], res["names"], res.get("changes"))
        else:
            print(f"[تعذّر التحديث]: {res.get('message') or res.get('error')}")
            print("تلميح: إذا لم تكن مسجل الدخول، استخدم الأمر: python run_tracker.py --login")
        return

    # Handle watch
    if args.watch:
        interval_mins = max(1, args.interval)
        print(f"\n[بدء المراقبة المستمرة]: سيتم فحص المنصة كل {interval_mins} دقائق وإرسال إشعارات ويندوز عند أي تغيير.")
        print("اضغط Ctrl+C للإيقاف في أي وقت.\n")

        while True:
            try:
                res = core.refresh()
                if res.get("ok"):
                    now_str = time.strftime("%I:%M:%S %p")
                    print(f"[{now_str}] تم الفحص بنجاح. إجمالي الدعاوى: {len(res['requests'])} - تغييرات جديدة: {res.get('new_changes_count', 0)}")
                else:
                    print(f"[{time.strftime('%I:%M:%S %p')}] تعذّر الفحص: {res.get('message') or res.get('error')}")
                time.sleep(interval_mins * 60)
            except KeyboardInterrupt:
                print("\nتم إيقاف المراقبة.")
                break
            except Exception as e:
                print(f"[خطأ]: {e}")
                time.sleep(30)
        return

    # Default action: Start Web UI
    from .web.app import create_app
    port = args.port
    url = f"http://127.0.0.1:{port}"
    print(f"\n[تشغيل واجهة الويب]: الخادم متاح على الرابط: {url}")
    print("اضغط Ctrl+C لإيقاف الخادم.\n")

    if not args.no_browser:
        def open_browser():
            time.sleep(1.2)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        import threading
        threading.Thread(target=open_browser, daemon=True).start()

    flask_app = create_app()
    flask_app.run(host="127.0.0.1", port=port, debug=False)
