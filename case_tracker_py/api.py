"""
Digital Egypt API Client.
Communicates with https://apis.digital.gov.eg for fetching requests, progress history, and searches.
"""

import json
from typing import Optional, Dict, Any, List, Union
import httpx
from .auth import AuthManager

API_BASE = "https://apis.digital.gov.eg"
CIVIL_SLUG = "CRT-09"

DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "cache-control": "no-store",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


class DigitalGovAPI:
    def __init__(self, auth_manager: Optional[AuthManager] = None):
        self.auth = auth_manager or AuthManager()

    def call(
        self,
        path: str,
        method: str = "GET",
        body: Optional[Union[Dict[str, Any], str]] = None,
        use_auth: bool = True,
        return_raw: bool = False
    ) -> Dict[str, Any]:
        """
        Executes an HTTP request to apis.digital.gov.eg.
        Handles token authorization, 401 automatic refresh, and error reporting.
        """
        if not path.startswith("/"):
            path = "/" + path

        url = f"{API_BASE}{path}"
        headers = dict(DEFAULT_HEADERS)

        if use_auth:
            token = self.auth.get_valid_access_token()
            if not token:
                return {
                    "ok": False,
                    "error": "NOT_LOGGED_IN",
                    "status": 401,
                    "message": "لم يتم تسجيل الدخول بعد أو انتهت صلاحية الجلسة."
                }
            headers["authorization"] = f"Bearer {token}"

        data_kwargs = {}
        if body is not None:
            if isinstance(body, (dict, list)):
                headers["content-type"] = "application/json"
                data_kwargs["json"] = body
            else:
                data_kwargs["content"] = str(body)

        try:
            with httpx.Client(timeout=25.0) as client:
                res = client.request(method.upper(), url, headers=headers, **data_kwargs)

                # If 401 Unauthorized and auth was used, attempt refresh once
                if res.status_code == 401 and use_auth:
                    if self.auth.refresh():
                        new_token = self.auth.access_token
                        headers["authorization"] = f"Bearer {new_token}"
                        res = client.request(method.upper(), url, headers=headers, **data_kwargs)

                text = res.text
                json_data = None
                try:
                    json_data = res.json()
                except Exception:
                    pass

                result = {
                    "ok": res.is_success,
                    "status": res.status_code,
                    "json": json_data,
                    "text": text if not json_data else None,
                    "path": path
                }
                if return_raw:
                    result["raw"] = text
                if not res.is_success:
                    result["error"] = f"HTTP_{res.status_code}"
                    if json_data and isinstance(json_data, dict) and "msg" in json_data:
                        result["message"] = json_data["msg"]

                return result

        except httpx.RequestError as e:
            return {
                "ok": False,
                "error": "REQUEST_FAILED",
                "message": f"تعذّر الاتصال بخوادم مصر الرقمية: {e}",
                "status": 0
            }

    def get_my_requests(self, civil_only: bool = False, return_raw: bool = False) -> Dict[str, Any]:
        """
        Fetches all user requests from /portal/myRequests.
        """
        res = self.call("/portal/myRequests", method="GET", return_raw=return_raw)
        if not res.get("ok"):
            return res

        data = res.get("json") or {}
        requests_container = data.get("requests") or {}
        raw_list = requests_container.get("requests") or []

        if civil_only:
            filtered = [r for r in raw_list if r.get("serviceSlug") == CIVIL_SLUG]
        else:
            filtered = raw_list

        res["list"] = filtered
        return res

    def get_request_progress(self, wf_id: str, data_id: str, return_raw: bool = False) -> Dict[str, Any]:
        """
        Fetches request progress steps from /portal/requestProgress/{wfId}/{dataId}.
        """
        wf = wf_id or "CRT"
        path = f"/portal/requestProgress/{wf}/{data_id}"
        return self.call(path, method="GET", return_raw=return_raw)

    def get_profile(self) -> Dict[str, Any]:
        """
        Fetches user profile details from /portal/profile.
        """
        return self.call("/portal/profile", method="GET")

    def search_term(self, term: str) -> List[Dict[str, Any]]:
        """
        Searches for term across known endpoints.
        """
        endpoints = [
            "/portal/myRequests",
            "/portal/profile",
            "/portal/cases",
            "/portal/driving-licenses",
            "/portal/vehicles",
            "/alerts"
        ]
        results = []
        term_str = str(term).strip()
        for ep in endpoints:
            r = self.call(ep, method="GET", return_raw=True)
            if r.get("ok") and r.get("raw"):
                raw = r["raw"]
                count = raw.count(term_str)
                results.append({"path": ep, "status": r["status"], "occurrences": count})
            else:
                results.append({"path": ep, "status": r.get("status", 0), "occurrences": 0, "error": r.get("error")})
        return results
