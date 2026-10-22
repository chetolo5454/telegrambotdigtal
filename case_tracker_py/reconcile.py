"""
Bank Reconciliation Module for Case Tracker.
Matches cases that have payment numbers with payment events and timestamps.
"""

import time
from typing import List, Dict, Any, Optional
from .api import DigitalGovAPI, CIVIL_SLUG
from .storage import StorageManager
from .evidence import get_all_payments, to_cairo_time


def reconcile_cases(
    api: Optional[DigitalGovAPI] = None,
    storage: Optional[StorageManager] = None,
    delay_between_calls: float = 0.2
) -> List[Dict[str, Any]]:
    api = api or DigitalGovAPI()
    storage = storage or StorageManager()

    res = api.get_my_requests(civil_only=True)
    if not res.get("ok"):
        return []

    reqs = res.get("list") or []
    names = storage.get_names()

    # Filter only cases with payment numbers
    with_pay = [r for r in reqs if len(get_all_payments(r)) > 0]
    rows = []

    for r in with_pay:
        req_num = str(r.get("requestNumber", ""))
        wf_id = r.get("wfId") or "CRT"
        data_id = r.get("dataId")

        pr = api.get_request_progress(wf_id, data_id)
        steps = (pr.get("json") or {}).get("requestProgress") or []
        paid_events = [s for s in steps if str(s.get("caseCode")) == "203"]

        first_paid_utc = paid_events[0].get("createdAt") if paid_events else None
        first_paid_cairo = to_cairo_time(first_paid_utc) if first_paid_utc else "—"
        written_by = [s.get("platform") or "unknown" for s in paid_events]

        rows.append({
            "requestNumber": req_num,
            "name": names.get(req_num, ""),
            "paymentNumbers": " + ".join(get_all_payments(r)),
            "paidEventsCount": len(paid_events),
            "firstPaidCairo": first_paid_cairo,
            "firstPaidUTC": first_paid_utc or "—",
            "writtenBy": ", ".join(written_by) if written_by else "—",
            "caseMessage": r.get("caseMessage", "")
        })

        if delay_between_calls > 0:
            time.sleep(delay_between_calls)

    return rows
