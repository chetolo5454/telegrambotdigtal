"""
Core Case Tracker Engine.
Normalizes data, detects state and payment changes, updates audit logs,
and manages background auto-refresh scheduling.
"""

import time
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from .api import DigitalGovAPI, CIVIL_SLUG
from .storage import StorageManager
from .evidence import get_all_payments, to_cairo_time
from .notifier import notify


def pick_request(r: Dict[str, Any]) -> Dict[str, Any]:
    pays = get_all_payments(r)
    return {
        "requestNumber": str(r.get("requestNumber", "")),
        "dataId": str(r.get("dataId", "")),
        "stepCode": str(r.get("stepCode", "")),
        "caseCode": str(r.get("caseCode", "")),
        "stepMessage": r.get("stepMessage", ""),
        "caseMessage": r.get("caseMessage", ""),
        "canContinue": bool(r.get("canContinue")),
        "createdAt": r.get("createdAt"),
        "createdAtCairo": to_cairo_time(r.get("createdAt")),
        "updatedAt": r.get("updatedAt"),
        "updatedAtCairo": to_cairo_time(r.get("updatedAt")),
        "submitTime": r.get("submitTime"),
        "submitTimeCairo": to_cairo_time(r.get("submitTime")),
        "paymentRequestNumber": str(r.get("paymentRequestNumber") or ""),
        "otherPaymentRequestNumbers": [str(x) for x in (r.get("otherPaymentRequestNumbers") or []) if x],
        "allPayments": pays,
        "GARequestId": str(r.get("GARequestId") or ""),
        "wfId": str(r.get("wfId") or "CRT"),
        "serviceSlug": str(r.get("serviceSlug") or ""),
        "serviceName": str(r.get("serviceName") or "")
    }


GROUPS = [
    {"k": "fees", "t": "تقدير ودفع الرسوم", "f": lambda r: r["caseCode"] in ("202", "203"), "always": True},
    {"k": "202", "t": "تم تقدير الرسوم", "f": lambda r: r["caseCode"] == "202"},
    {"k": "203", "t": "تم دفع الرسوم", "f": lambda r: r["caseCode"] == "203"},
    {"k": "201", "t": "تحت المراجعة", "f": lambda r: r["caseCode"] == "201"},
    {"k": "204", "t": "قُيدت في جدول المحكمة", "f": lambda r: r["caseCode"] == "204"},
    {"k": "207", "t": "إبلاغ المحامي", "f": lambda r: r["caseCode"] == "207"},
    {"k": "210", "t": "غير مستوفي", "f": lambda r: r["caseCode"] == "210"},
    {"k": "draft", "t": "مسودات", "f": lambda r: r["stepCode"] == "1"},
    {"k": "cancel", "t": "ملغاة", "f": lambda r: r["stepCode"] == "6"},
    {"k": "all", "t": "الكل", "f": lambda r: True, "always": True},
]


class CaseTrackerCore:
    def __init__(self, api: Optional[DigitalGovAPI] = None, storage: Optional[StorageManager] = None):
        self.api = api or DigitalGovAPI()
        self.storage = storage or StorageManager()
        self.lock = threading.Lock()
        self._watcher_thread: Optional[threading.Thread] = None
        self._stop_watcher = False

    def refresh(self) -> Dict[str, Any]:
        """
        Fetches requests from platform, checks against previous snapshot,
        records changes, updates audit log, sends notifications, and saves new snapshot.
        """
        with self.lock:
            settings = self.storage.get_settings()
            civil_only = settings.get("civil_only", True)

            api_res = self.api.get_my_requests(civil_only=civil_only)
            if not api_res.get("ok"):
                return {
                    "ok": False,
                    "error": api_res.get("error", "API_ERROR"),
                    "message": api_res.get("message", "تعذّر جلب البيانات من المنصة")
                }

            raw_list = api_res.get("list") or []
            normalized = [pick_request(r) for r in raw_list]

            prev_snapshot = self.storage.get_snapshot()
            prev_requests = prev_snapshot.get("requests", []) if prev_snapshot else []
            prev_map = {r["requestNumber"]: r for r in prev_requests}

            current_changes = self.storage.get_changes()
            names = self.storage.get_names()
            now_iso = datetime.now(timezone.utc).isoformat()
            now_ts = int(time.time() * 1000)

            audit_entries = []
            notes = []

            for r in normalized:
                req_num = r["requestNumber"]
                payments_str = "+".join(r["allPayments"])
                sig = f"{r['caseCode']}|{payments_str}|{r['updatedAt']}"

                prev = prev_map.get(req_num)
                client_name = names.get(req_num)

                if prev_snapshot and len(prev_requests) > 0:
                    if not prev:
                        # New case discovered
                        current_changes[req_num] = {"kind": "new", "to": r["caseMessage"], "at": now_ts}
                        notes.append((r, f"طلب جديد: {r['caseMessage']}"))
                        audit_entries.append({
                            "at": now_iso, "requestNumber": req_num, "sig": sig,
                            "caseCode": r["caseCode"], "caseMessage": r["caseMessage"],
                            "payments": r["allPayments"], "updatedAt": r["updatedAt"],
                            "firstObservation": True
                        })
                    elif prev["caseCode"] != r["caseCode"]:
                        # Status code changed
                        from_msg = prev.get("caseMessage", "")
                        current_changes[req_num] = {"kind": "changed", "from": from_msg, "to": r["caseMessage"], "at": now_ts}
                        notes.append((r, f"تغيّرت الحالة: {from_msg} ← {r['caseMessage']}"))
                        audit_entries.append({
                            "at": now_iso, "requestNumber": req_num, "sig": sig,
                            "caseCode": r["caseCode"], "caseMessage": r["caseMessage"],
                            "payments": r["allPayments"], "updatedAt": r["updatedAt"],
                            "firstObservation": False
                        })
                    elif "+".join(prev["allPayments"]) != payments_str:
                        # Payment number changed
                        old_p = " + ".join(prev["allPayments"]) or "—"
                        new_p = " + ".join(r["allPayments"]) or "—"
                        current_changes[req_num] = {"kind": "payment", "from": old_p, "to": new_p, "at": now_ts}
                        notes.append((r, f"تغيّرت أرقام السداد: {new_p}"))
                        audit_entries.append({
                            "at": now_iso, "requestNumber": req_num, "sig": sig,
                            "caseCode": r["caseCode"], "caseMessage": r["caseMessage"],
                            "payments": r["allPayments"], "updatedAt": r["updatedAt"],
                            "firstObservation": False
                        })
                else:
                    # First run initial observation
                    audit_entries.append({
                        "at": now_iso, "requestNumber": req_num, "sig": sig,
                        "caseCode": r["caseCode"], "caseMessage": r["caseMessage"],
                        "payments": r["allPayments"], "updatedAt": r["updatedAt"],
                        "firstObservation": True
                    })

            # Save state
            new_snapshot = {
                "fetchedAt": now_ts,
                "fetchedAtISO": now_iso,
                "fetchedAtCairo": to_cairo_time(now_iso),
                "count": len(normalized),
                "requests": normalized
            }
            self.storage.save_snapshot(new_snapshot)
            self.storage.save_changes(current_changes)
            if audit_entries:
                self.storage.log_audit_entries(audit_entries)

            # Fire notifications if enabled
            if settings.get("enable_notifications", True):
                for req, msg in notes:
                    cname = names.get(req["requestNumber"])
                    notify(f"تغيّرت حالة دعوى {req['requestNumber']}", msg, client_name=cname)

            return {
                "ok": True,
                "snapshot": new_snapshot,
                "changes": current_changes,
                "new_changes_count": len(notes),
                "requests": normalized,
                "names": names
            }

    def start_watcher(self):
        """
        Starts background watcher loop according to settings.
        """
        if self._watcher_thread and self._watcher_thread.is_alive():
            return

        self._stop_watcher = False

        def loop():
            while not self._stop_watcher:
                settings = self.storage.get_settings()
                mins = int(settings.get("auto_refresh_minutes", 10))
                if mins > 0:
                    try:
                        self.refresh()
                    except Exception as e:
                        print(f"[خطأ في التحديث التلقائي]: {e}")
                    # Sleep in small slices to respond quickly to stop signal
                    for _ in range(mins * 60):
                        if self._stop_watcher:
                            break
                        time.sleep(1)
                else:
                    time.sleep(5)

        self._watcher_thread = threading.Thread(target=loop, daemon=True)
        self._watcher_thread.start()

    def stop_watcher(self):
        self._stop_watcher = True
