"""
Authentication Manager for Digital Egypt (مصر الرقمية).
Handles JWT decoding, token persistence, and automatic token refresh.
"""

import os
import json
import base64
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo
import httpx

API_BASE = "https://apis.digital.gov.eg"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SESSION_FILE = os.path.join(DATA_DIR, "session.json")

CAIRO_TZ = ZoneInfo("Africa/Cairo")


def _clean_token(t: Optional[str]) -> str:
    if not t:
        return ""
    return str(t).strip().strip('"').strip("'")


def decode_jwt(token: str) -> Optional[Dict[str, Any]]:
    """
    Decodes a JWT without verification to inspect expiration and claims.
    """
    token = _clean_token(token)
    if not token or "." not in token:
        return None
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        # Adjust base64 padding
        rem = len(payload_b64) % 4
        if rem > 0:
            payload_b64 += "=" * (4 - rem)
        # URL safe base64 decode
        payload_b64 = payload_b64.replace("-", "+").replace("_", "/")
        decoded_bytes = base64.b64decode(payload_b64)
        return json.loads(decoded_bytes.decode("utf-8", errors="replace"))
    except Exception:
        return None


def get_token_info(token: str) -> Optional[Dict[str, Any]]:
    """
    Returns structured info about a token including expiration and human dates.
    """
    claims = decode_jwt(token)
    if not claims:
        return None

    exp = claims.get("exp")
    iat = claims.get("iat")
    now_ts = time.time()

    exp_iso = datetime.fromtimestamp(exp, tz=timezone.utc).isoformat() if exp else None
    iat_iso = datetime.fromtimestamp(iat, tz=timezone.utc).isoformat() if iat else None
    seconds_left = int(exp - now_ts) if exp else None

    return {
        "issued_at_utc": iat_iso,
        "expires_at_utc": exp_iso,
        "seconds_left": seconds_left,
        "is_expired": (seconds_left is not None and seconds_left <= 0),
        "nid": claims.get("nid"),
        "username": claims.get("username"),
        "sub": claims.get("sub"),
        "claims": claims
    }


ROOT_TOKEN_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "token.text"))


class AuthManager:
    def __init__(self, session_path: str = SESSION_FILE):
        self.session_path = session_path
        os.makedirs(os.path.dirname(self.session_path), exist_ok=True)
        self.session_data: Dict[str, Any] = self._load()

        # If session is empty or expired, try loading from token.text if available
        curr_info = get_token_info(self.access_token) if self.access_token else None
        if not curr_info or curr_info.get("is_expired"):
            self.load_from_token_file()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.session_path):
            try:
                with open(self.session_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self):
        try:
            with open(self.session_path, "w", encoding="utf-8") as f:
                json.dump(self.session_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[خطأ في حفظ الجلسة]: {e}")

    @property
    def access_token(self) -> str:
        return _clean_token(self.session_data.get("accessToken"))

    @property
    def refresh_token(self) -> str:
        return _clean_token(self.session_data.get("refreshToken"))

    def set_tokens(self, access_token: str, refresh_token: Optional[str] = None):
        """
        Saves new tokens and updates session data.
        """
        acc = _clean_token(access_token)
        ref = _clean_token(refresh_token) if refresh_token else self.refresh_token

        self.session_data["accessToken"] = acc
        if ref:
            self.session_data["refreshToken"] = ref
        self.session_data["updatedAt"] = datetime.now(timezone.utc).isoformat()

        # Extract user info
        info = get_token_info(acc)
        if info:
            if info.get("nid"):
                self.session_data["nid"] = info["nid"]
            if info.get("username"):
                self.session_data["username"] = info["username"]

        self._save()

    def load_from_token_file(self, token_path: Optional[str] = None) -> bool:
        """
        Attempts to read tokens from token.text and set them into the session.
        """
        path = token_path or ROOT_TOKEN_FILE
        if not os.path.isfile(path):
            return False

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read().strip()

            acc = ""
            ref = ""

            try:
                data = json.loads(content)
                acc = _clean_token(data.get("accessToken"))
                ref = _clean_token(data.get("refreshToken"))
            except Exception:
                pass

            if not acc:
                import re
                jwts = re.findall(r"ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", content)
                if jwts:
                    acc = jwts[0]
                    if len(jwts) > 1:
                        ref = jwts[1]

            if acc:
                info = get_token_info(acc)
                if info and not info.get("is_expired"):
                    self.set_tokens(acc, ref)
                    print(f"[نجاح]: تم استيراد التوكن الساري من ملف {os.path.basename(path)}.")
                    return True
                elif ref:
                    # Token might be expired but refresh token could be valid
                    ref_info = get_token_info(ref)
                    if ref_info and not ref_info.get("is_expired"):
                        self.set_tokens(acc, ref)
                        return self.refresh()
            return False
        except Exception as e:
            print(f"[خطأ استيراد التوكن من الملف]: {e}")
            return False

    def clear(self):
        """
        Clears the stored session.
        """
        self.session_data = {}
        if os.path.exists(self.session_path):
            try:
                os.remove(self.session_path)
            except Exception:
                pass

    def get_status(self) -> Dict[str, Any]:
        """
        Returns full inspection status of the current session.
        """
        acc = self.access_token
        ref = self.refresh_token

        acc_info = get_token_info(acc) if acc else None
        ref_info = get_token_info(ref) if ref else None

        logged_in = bool(acc and acc_info and not acc_info.get("is_expired"))
        can_refresh = bool(ref and ref_info and not ref_info.get("is_expired"))

        return {
            "logged_in": logged_in or can_refresh,
            "access_token_present": bool(acc),
            "access_token_valid": bool(acc_info and not acc_info.get("is_expired")),
            "access_seconds_left": acc_info.get("seconds_left") if acc_info else 0,
            "can_refresh": can_refresh,
            "refresh_seconds_left": ref_info.get("seconds_left") if ref_info else 0,
            "user_nid": self.session_data.get("nid") or (acc_info.get("nid") if acc_info else None),
            "user_phone": self.session_data.get("username") or (acc_info.get("username") if acc_info else None),
            "updatedAt": self.session_data.get("updatedAt")
        }

    def refresh(self) -> bool:
        """
        Calls POST /identity/refresh-token using the stored refreshToken.
        Updates accessToken on success.
        """
        ref = self.refresh_token
        if not ref:
            return False

        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        payload = {"refreshToken": ref}

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(f"{API_BASE}/identity/refresh-token", json=payload, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    new_acc = data.get("accessToken")
                    if new_acc:
                        new_ref = data.get("refreshToken") or ref
                        self.set_tokens(new_acc, new_ref)
                        print("[نجاح]: تم تجديد توكن الجلسة تلقائياً بنجاح.")
                        return True
                print(f"[فشل التجديد]: استجابة الـ API برمز {res.status_code}")
                return False
        except Exception as e:
            print(f"[استثناء أثناء التجديد]: {e}")
            return False

    def get_valid_access_token(self) -> Optional[str]:
        """
        Returns a valid accessToken. If expired or close to expiry (<60s), attempts to refresh it.
        """
        acc = self.access_token
        if not acc:
            return None

        info = get_token_info(acc)
        # If token is still valid for more than 60 seconds, use it
        if info and not info.get("is_expired") and (info.get("seconds_left") or 0) > 60:
            return acc

        # Attempt refresh
        if self.refresh():
            return self.access_token

        # Return existing even if close to expiry as last resort
        return acc if (info and not info.get("is_expired")) else None
