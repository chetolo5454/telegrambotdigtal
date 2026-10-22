"""
Flask Web Application & REST API for Case Tracker.
Serves the modern, responsive Arabic RTL dashboard and coordinates background jobs.
"""

import os
import json
import threading
from typing import Optional, Dict, Any
from flask import Flask, render_template, request, jsonify, Response, send_file
from ..auth import AuthManager
from ..api import DigitalGovAPI
from ..storage import StorageManager
from ..core import CaseTrackerCore, GROUPS
from ..evidence import EvidenceGenerator
from ..reconcile import reconcile_cases
from ..browser_login import run_browser_login
from ..auto_login import run_auto_login, parse_credentials, import_tokens_from_file

# Configure paths
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(WEB_DIR, "templates")
STATIC_DIR = os.path.join(WEB_DIR, "static")

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=STATIC_DIR
)
app.config["SECRET_KEY"] = "case-tracker-secret-key-2026"

auth_mgr = AuthManager()
api_client = DigitalGovAPI(auth_mgr)
storage_mgr = StorageManager()
core_engine = CaseTrackerCore(api_client, storage_mgr)
evidence_gen = EvidenceGenerator(api_client, storage_mgr)

# Browser login state tracking
login_state = {
    "in_progress": False,
    "status_message": "",
    "success": False,
    "error": None
}

# Auto-login (One-Click) state tracking
auto_login_state = {
    "in_progress": False,
    "status_message": "",
    "success": False,
    "error": None
}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status", methods=["GET"])
def get_status():
    session_status = auth_mgr.get_status()
    settings = storage_mgr.get_settings()
    snapshot = storage_mgr.get_snapshot()
    changes = storage_mgr.get_changes()

    phone, has_pass = parse_credentials()
    token_file_res = import_tokens_from_file()

    return jsonify({
        "ok": True,
        "auth": session_status,
        "settings": settings,
        "changes_count": len(changes),
        "last_fetched_cairo": snapshot.get("fetchedAtCairo") if snapshot else None,
        "requests_count": snapshot.get("count", 0) if snapshot else 0,
        "browser_login": login_state,
        "auto_login": auto_login_state,
        "credentials": {
            "has_login_info": bool(phone and has_pass),
            "phone": phone,
            "has_token_file": token_file_res.get("ok", False),
            "token_file_valid": bool(token_file_res.get("ok") and not (token_file_res.get("info") or {}).get("is_expired"))
        }
    })


@app.route("/api/requests", methods=["GET"])
def get_requests():
    snapshot = storage_mgr.get_snapshot()
    names = storage_mgr.get_names()
    changes = storage_mgr.get_changes()
    settings = storage_mgr.get_settings()

    requests_list = snapshot.get("requests", []) if snapshot else []

    # Calculate counts for each group
    group_counts = {}
    for g in GROUPS:
        group_counts[g["k"]] = len([r for r in requests_list if g["f"](r)])
    group_counts["unnamed"] = len([r for r in requests_list if not names.get(r["requestNumber"])])

    return jsonify({
        "ok": True,
        "requests": requests_list,
        "names": names,
        "changes": changes,
        "settings": settings,
        "counts": group_counts,
        "fetchedAtCairo": snapshot.get("fetchedAtCairo") if snapshot else None
    })


@app.route("/api/refresh", methods=["POST"])
def refresh():
    res = core_engine.refresh()
    return jsonify(res)


@app.route("/api/names", methods=["POST"])
def update_name():
    data = request.get_json() or {}
    req_num = data.get("requestNumber")
    name = data.get("name", "")
    if not req_num:
        return jsonify({"ok": False, "error": "MISSING_REQUEST_NUMBER"}), 400

    updated_names = storage_mgr.set_name(req_num, name)
    return jsonify({"ok": True, "names": updated_names})


@app.route("/api/backup-names", methods=["GET"])
def backup_names():
    backup = storage_mgr.backup_names()
    return Response(
        json.dumps(backup, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=case-names-backup.json"}
    )


@app.route("/api/restore-names", methods=["POST"])
def restore_names():
    try:
        if "file" in request.files:
            file = request.files["file"]
            content = json.loads(file.read().decode("utf-8"))
        else:
            content = request.get_json() or {}

        count = storage_mgr.restore_names(content)
        return jsonify({"ok": True, "restored_count": count})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/ack-changes", methods=["POST"])
def ack_changes():
    storage_mgr.acknowledge_changes()
    return jsonify({"ok": True})


@app.route("/api/audit", methods=["GET"])
def get_audit():
    req_num = request.args.get("requestNumber")
    entries = storage_mgr.get_audit_log(req_num)
    return jsonify({"ok": True, "entries": entries, "count": len(entries)})


@app.route("/api/evidence/<request_number>", methods=["GET"])
def get_evidence(request_number):
    try:
        bundle = evidence_gen.generate(request_number)
        as_download = request.args.get("download", "0") == "1"
        if as_download:
            return Response(
                json.dumps(bundle, ensure_ascii=False, indent=2),
                mimetype="application/json",
                headers={"Content-Disposition": f"attachment; filename=evidence-{request_number}.json"}
            )
        return jsonify({"ok": True, "evidence": bundle})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/evidence/<request_number>/html", methods=["GET"])
def get_evidence_html(request_number):
    try:
        temp_path = os.path.join(storage_mgr.data_dir, f"temp_evidence_{request_number}.html")
        evidence_gen.generate(request_number, export_html_path=temp_path)
        return send_file(temp_path, mimetype="text/html")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/reconcile", methods=["GET"])
def get_reconciliation():
    try:
        rows = reconcile_cases(api_client, storage_mgr)
        return jsonify({"ok": True, "rows": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/login-browser", methods=["POST"])
def trigger_browser_login():
    global login_state
    if login_state["in_progress"]:
        return jsonify({"ok": False, "error": "تسجيل الدخول جاري بالفعل في نافذة متصفح."})

    login_state = {
        "in_progress": True,
        "status_message": "جارٍ تشغيل المتصفح...",
        "success": False,
        "error": None
    }

    def worker():
        global login_state
        def cb(msg):
            login_state["status_message"] = msg

        res = run_browser_login(auth_mgr, status_callback=cb)
        login_state["in_progress"] = False
        if res.get("ok"):
            login_state["success"] = True
            login_state["status_message"] = "تم تسجيل الدخول بنجاح!"
            # Trigger refresh automatically
            try:
                core_engine.refresh()
            except Exception:
                pass
        else:
            login_state["success"] = False
            login_state["error"] = res.get("error")

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    return jsonify({"ok": True, "message": "تم بدء جلسة تسجيل الدخول في المتصفح."})


@app.route("/api/login-status", methods=["GET"])
def check_login_status():
    return jsonify(login_state)


@app.route("/api/auto-login", methods=["POST"])
def trigger_auto_login():
    """
    Trigger one-click automated login using credentials in 'login info.text'.
    Runs silently via CDP, captures tokens, and updates cases.
    """
    global auto_login_state
    if auto_login_state["in_progress"]:
        return jsonify({"ok": False, "error": "عملية تسجيل الدخول التلقائي جارية بالفعل."})

    auto_login_state = {
        "in_progress": True,
        "status_message": "جارٍ قراءة بيانات الدخول والاتصال بالمتصفح...",
        "success": False,
        "error": None
    }

    def worker():
        global auto_login_state
        def cb(msg):
            auto_login_state["status_message"] = msg

        res = run_auto_login(auth_mgr, status_callback=cb)
        auto_login_state["in_progress"] = False
        if res.get("ok"):
            auto_login_state["success"] = True
            auto_login_state["status_message"] = "تم تسجيل الدخول وتحديث التوكن بنجاح!"
            # Automatically refresh cases immediately
            try:
                core_engine.refresh()
            except Exception:
                pass
        else:
            auto_login_state["success"] = False
            auto_login_state["error"] = res.get("error")

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    return jsonify({"ok": True, "message": "تم بدء تسجيل الدخول التلقائي بضغطة زر."})


@app.route("/api/auto-login-status", methods=["GET"])
def check_auto_login_status():
    return jsonify(auto_login_state)


@app.route("/api/import-token-file", methods=["POST"])
def import_token_file():
    """
    Imports token directly from 'token.text' and refreshes cases immediately.
    """
    ok = auth_mgr.load_from_token_file()
    if not ok:
        # Check why
        res = import_tokens_from_file()
        err = res.get("error") or "تعذّر استيراد التوكن من الملف أو أن صلاحيته منتهية."
        return jsonify({"ok": False, "error": err}), 400

    status = auth_mgr.get_status()
    refresh_result = core_engine.refresh()
    return jsonify({
        "ok": True,
        "message": "تم استيراد التوكن من ملف token.text وتحديث الدعاوى بنجاح!",
        "status": status,
        "refresh_result": refresh_result
    })


@app.route("/api/credentials-status", methods=["GET"])
def get_credentials_status():
    phone, has_pass = parse_credentials()
    token_res = import_tokens_from_file()
    return jsonify({
        "ok": True,
        "has_credentials": bool(phone and has_pass),
        "phone": phone,
        "has_token_file": token_res.get("ok", False),
        "token_file_info": token_res.get("info") if token_res.get("ok") else None
    })


@app.route("/api/set-tokens", methods=["POST"])
def set_manual_tokens():
    data = request.get_json() or {}
    acc = data.get("accessToken", "").strip()
    ref = data.get("refreshToken", "").strip()

    if not acc:
        return jsonify({"ok": False, "error": "يرجى توفير accessToken على الأقل."}), 400

    auth_mgr.set_tokens(acc, ref)
    # Check if we can refresh immediately or if it's valid
    status = auth_mgr.get_status()
    # Trigger refresh
    refresh_result = core_engine.refresh()

    return jsonify({
        "ok": True,
        "status": status,
        "refresh_result": refresh_result
    })


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json() or {}
    updated = storage_mgr.update_settings(data)
    return jsonify({"ok": True, "settings": updated})


@app.route("/api/logout", methods=["POST"])
def logout():
    auth_mgr.clear()
    return jsonify({"ok": True, "message": "تم تسجيل الخروج بنجاح."})


def create_app():
    core_engine.start_watcher()
    return app
