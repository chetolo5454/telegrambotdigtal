"""
Digital Evidence File & Bank Reconciliation Generator for Digital Egypt Cases.
Produces tamper-evident JSON bundles and standalone HTML/Markdown reports
with cryptographic SHA-256 digests and timeline analysis.
"""

import os
import json
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional
from .api import DigitalGovAPI
from .storage import StorageManager

CAIRO_TZ = ZoneInfo("Africa/Cairo")


def to_cairo_time(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        cairo_dt = dt.astimezone(CAIRO_TZ)
        return cairo_dt.strftime("%Y-%m-%d %I:%M:%S %p")
    except Exception:
        return iso_str


def sha256_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_nid(obj: Any) -> Any:
    """
    Recursively removes 'createUser' (National ID) for privacy.
    """
    if isinstance(obj, list):
        return [strip_nid(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: strip_nid(v) for k, v in obj.items() if k != "createUser"}
    return obj


def get_all_payments(r: Dict[str, Any]) -> List[str]:
    primary = r.get("paymentRequestNumber")
    others = r.get("otherPaymentRequestNumbers") or []
    res = []
    if primary:
        res.append(str(primary))
    for p in others:
        if p and str(p) not in res:
            res.append(str(p))
    return res


def analyze_evidence(item: Dict[str, Any], progress: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    steps = (progress and progress.get("requestProgress")) or []
    timeline = []
    for s in steps:
        created = s.get("createdAt")
        timeline.append({
            "stepCode": str(s.get("stepCode", "")),
            "caseCode": str(s.get("caseCode", "")),
            "stepMessage": s.get("stepMessage", ""),
            "caseMessage": s.get("caseMessage", ""),
            "writtenBy": s.get("platform") or "system",
            "createdAtUTC": created,
            "createdAtCairo": to_cairo_time(created)
        })

    est = [s for s in timeline if s["caseCode"] == "202"]
    paid = [s for s in timeline if s["caseCode"] == "203"]
    payments = get_all_payments(item)
    distinct = list(dict.fromkeys(payments))

    guide = [
        f"سجّلت المنصة {len(paid)} حدث «تم دفع الرسوم» و {len(distinct)} رقم سداد: {('، '.join(distinct) if distinct else '—')}."
    ]

    if len(paid) <= 1 and len(distinct) <= 1:
        guide.append(
            "هذا يعني أن المنصة سجّلت دفعة واحدة فقط لهذا الطلب. إن كان البنك قد خصم المبلغ مرتين فالدليل "
            "على الخصم المزدوج يكون في كشف حساب البنك وإشعاراته (برقم مرجع وتوقيت لكل عملية) وليس في بيانات المنصة؛ "
            "وقد تكون العمليتان قد نُفذتا على نفس رقم السداد."
        )
    else:
        guide.append(
            "وجود أكثر من حدث دفع أو أكثر من رقم سداد يستدعي مطابقة كل واحد منها مع عمليات كشف حساب البنك."
        )

    guide.append(
        "للمطابقة: قارن رقم السداد وتوقيت حدث الدفع هنا برقم المرجع وتوقيت العملية في إشعار البنك أو كشف الحساب."
    )

    return {
        "paymentRequestNumber": item.get("paymentRequestNumber"),
        "otherPaymentRequestNumbers": item.get("otherPaymentRequestNumbers") or [],
        "distinctPaymentNumbers": distinct,
        "feesEstimatedEvents": len(est),
        "feesPaidEvents": len(paid),
        "feesEstimatedAtUTC": est[0]["createdAtUTC"] if est else None,
        "feesEstimatedAtCairo": est[0]["createdAtCairo"] if est else None,
        "firstPaidAtUTC": paid[0]["createdAtUTC"] if paid else None,
        "firstPaidAtCairo": paid[0]["createdAtCairo"] if paid else None,
        "paidEventsWrittenBy": [s["writtenBy"] for s in paid],
        "currentStatus": item.get("caseMessage"),
        "platformLastUpdatedUTC": item.get("updatedAt"),
        "platformLastUpdatedCairo": to_cairo_time(item.get("updatedAt")),
        "timeline": timeline,
        "readingGuide": guide
    }


class EvidenceGenerator:
    def __init__(self, api: Optional[DigitalGovAPI] = None, storage: Optional[StorageManager] = None):
        self.api = api or DigitalGovAPI()
        self.storage = storage or StorageManager()

    def generate(
        self,
        request_number: str,
        export_json_path: Optional[str] = None,
        export_html_path: Optional[str] = None
    ) -> Dict[str, Any]:
        req_num = str(request_number).strip()

        # Fetch requests list with raw response
        mr = self.api.get_my_requests(return_raw=True)
        if not mr.get("ok"):
            raise RuntimeError(f"تعذّر جلب قائمة الطلبات: {mr.get('message') or mr.get('error')}")

        items = mr.get("list") or []
        target = next((r for r in items if str(r.get("requestNumber")) == req_num), None)
        if not target:
            raise ValueError(f"لم يتم العثور على طلب برقم '{req_num}' في حسابك.")

        # Fetch progress steps
        wf_id = target.get("wfId") or "CRT"
        data_id = target.get("dataId")
        pr = self.api.get_request_progress(wf_id, data_id, return_raw=True)

        progress_json = pr.get("json") or {}
        analysis = analyze_evidence(target, progress_json)

        names = self.storage.get_names()
        client_name = names.get(req_num)
        audit_entries = self.storage.get_audit_log(req_num)

        now_utc = datetime.now(timezone.utc).isoformat()
        now_cairo = to_cairo_time(now_utc)

        sources = []
        if mr.get("raw"):
            sources.append({
                "label": "myRequests (قائمة الطلبات كاملة)",
                "path": "/portal/myRequests",
                "httpStatus": mr.get("status"),
                "sha256OfOriginalResponse": sha256_digest(mr["raw"]),
                "byteLength": len(mr["raw"].encode("utf-8"))
            })
        if pr.get("raw"):
            sources.append({
                "label": "requestProgress (سجل مراحل الطلب)",
                "path": f"/portal/requestProgress/{wf_id}/{data_id}",
                "httpStatus": pr.get("status"),
                "sha256OfOriginalResponse": sha256_digest(pr["raw"]),
                "byteLength": len(pr["raw"].encode("utf-8"))
            })

        bundle = {
            "type": "payment-evidence",
            "toolVersion": "2.0.0",
            "collectedAtUTC": now_utc,
            "collectedAtCairo": now_cairo,
            "requestNumber": req_num,
            "dataId": data_id,
            "GARequestId": target.get("GARequestId"),
            "clientName": client_name,
            "analysis": analysis,
            "platformRecord": strip_nid(target),
            "platformProgress": strip_nid(progress_json),
            "sources": sources,
            "auditLogForThisRequest": audit_entries,
            "notes": [
                "تحتوي البصمة sha256 على بصمة نص الاستجابة الأصلية كما وصلت من خوادم مصر الرقمية.",
                "الملف يوثّق البيانات المعروضة على المنصة وقت الجمع؛ وهو مكمل لمستندات البنك الرسمية (كشف الحساب، إشعارات الخصم، الإيصالات)."
            ]
        }

        if export_json_path:
            os.makedirs(os.path.dirname(export_json_path), exist_ok=True)
            with open(export_json_path, "w", encoding="utf-8") as f:
                json.dump(bundle, f, ensure_ascii=False, indent=2)

        if export_html_path:
            self._export_html(bundle, export_html_path)

        return bundle

    def _export_html(self, bundle: Dict[str, Any], filepath: str):
        analysis = bundle["analysis"]
        timeline_rows = "".join([
            f"<tr><td>{s['caseCode']}</td><td><b>{s['caseMessage']}</b><br><small>{s['stepMessage']}</small></td>"
            f"<td>{s['createdAtCairo']}</td><td><code>{s['writtenBy']}</code></td></tr>"
            for s in analysis["timeline"]
        ])
        guides = "".join([f"<li>{g}</li>" for g in analysis["readingGuide"]])

        html = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>ملف أدلة - طلب {bundle['requestNumber']}</title>
<style>
  body {{ font-family: "Segoe UI", Tahoma, Arial, sans-serif; background: #f8fafc; color: #1e293b; padding: 24px; margin: 0; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; max-width: 900px; margin: 0 auto 20px; padding: 24px; box-shadow: 0 4px 6px -1px rgba(0,0,0,.05); }}
  h1 {{ margin: 0 0 10px; color: #1e40af; font-size: 20px; }}
  .meta {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 20px; font-size: 14px; border-bottom: 1px solid #e2e8f0; padding-bottom: 16px; }}
  .badge {{ display: inline-block; background: #dbeafe; color: #1e40af; padding: 4px 10px; border-radius: 999px; font-weight: 600; font-size: 13px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 13.5px; }}
  th, td {{ border: 1px solid #e2e8f0; padding: 10px 12px; text-align: right; }}
  th {{ background: #f1f5f9; color: #475569; }}
  ul {{ line-height: 1.8; margin: 8px 0; }}
  .guide {{ background: #eff6ff; border-right: 4px solid #3b82f6; padding: 12px 16px; border-radius: 6px; margin: 16px 0; }}
  code {{ font-family: Consolas, monospace; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; }}
</style>
</head>
<body>
<div class="card">
  <h1>تقرير الأدلة الرقمية لطلب إقامة دعوى مدنية</h1>
  <div class="meta">
    <div>رقم الطلب: <b>{bundle['requestNumber']}</b></div>
    <div>الموكل: <b>{bundle['clientName'] or 'غير محدد'}</b></div>
    <div>الحالة الحالية: <span class="badge">{analysis['currentStatus']}</span></div>
    <div>تاريخ الجمع: <b>{bundle['collectedAtCairo']}</b></div>
  </div>

  <h3>دليل المطابقة البنكية</h3>
  <div class="guide">
    <ul>{guides}</ul>
  </div>

  <h3>سجل مراحل الطلب الموثق على المنصة (Timeline)</h3>
  <table>
    <thead><tr><th>كود الحالة</th><th>وصف الحالة والمرحلة</th><th>التوقيت (بتوقيت القاهرة)</th><th>الجهة المسجلة</th></tr></thead>
    <tbody>{timeline_rows or '<tr><td colspan="4">لا توجد مراحل مسجلة</td></tr>'}</tbody>
  </table>

  <h3 style="margin-top:24px;">المصادر والبصمات الرقمية (SHA-256)</h3>
  <table>
    <thead><tr><th>المصدر</th><th>كود الاستجابة</th><th>البصمة الرقمية (SHA-256)</th></tr></thead>
    <tbody>
      {''.join([f"<tr><td>{s['label']}</td><td>HTTP {s.get('httpStatus')}</td><td><code>{s.get('sha256OfOriginalResponse')}</code></td></tr>" for s in bundle['sources']])}
    </tbody>
  </table>
</div>
</body>
</html>"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
