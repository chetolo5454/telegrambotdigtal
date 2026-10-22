"""
Automated One-Click Login & Token Extractor for Digital Egypt (منصة مصر الرقمية).
Uses Chrome DevTools Protocol (CDP) to drive Edge or Chrome directly,
eliminating the need for WebDriver executables, downloads, or admin privileges.
Reads credentials from 'login info.text' and exports fresh tokens to 'token.text'.
"""

import os
import sys
import re
import json
import time
import socket
import shutil
import asyncio
import subprocess
from typing import Optional, Dict, Any, Callable, Tuple
import httpx
import websockets

from .auth import AuthManager, _clean_token, get_token_info

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_LOGIN_INFO_PATH = os.path.join(ROOT_DIR, "login info.text")
DEFAULT_TOKEN_FILE_PATH = os.path.join(ROOT_DIR, "token.text")
EDGE_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "data", "browser_profile")


def find_browser_executable() -> Optional[str]:
    """
    Finds Microsoft Edge or Google Chrome executable on Windows.
    """
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    # Fallback to PATH lookup
    for name in ["msedge", "edge", "chrome", "google-chrome"]:
        p = shutil.which(name)
        if p and os.path.isfile(p):
            return p

    return None


def find_free_port() -> int:
    """Finds an available local port for CDP."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def parse_credentials(file_path: str = DEFAULT_LOGIN_INFO_PATH) -> Tuple[str, str]:
    """
    Parses phone number and password from the login info file.
    Supports Arabic and English formats.
    """
    if not os.path.isfile(file_path):
        return "", ""

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        # Phone extraction
        phone_match = (
            re.search(r"(?:رقم\s*الهاتف.*?[:=]|\bphone.*?[:=]|\busername.*?[:=])\s*([0-9]+)", text, re.IGNORECASE)
            or re.search(r"\b(01[0125]\d{8})\b", text)
        )
        phone = phone_match.group(1).strip() if phone_match else ""

        # Password extraction
        pass_match = re.search(
            r"(?:كلم[ةه]\s*ال[سش]ر.*?[:=]|كلم[ةه]\s*المرور.*?[:=]|\bpass(?:word)?.*?[:=])\s*([^\r\n]+)",
            text,
            re.IGNORECASE
        )
        password = pass_match.group(1).strip() if pass_match else ""

        return phone, password
    except Exception as e:
        print(f"[خطأ قراءة بيانات الدخول]: {e}")
        return "", ""


def import_tokens_from_file(file_path: str = DEFAULT_TOKEN_FILE_PATH) -> Dict[str, Any]:
    """
    Reads token from token.text and returns accessToken and refreshToken.
    """
    if not os.path.isfile(file_path):
        return {"ok": False, "error": f"الملف غير موجود: {file_path}"}

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().strip()

        acc = ""
        ref = ""

        # Try parsing JSON first
        try:
            data = json.loads(content)
            acc = _clean_token(data.get("accessToken"))
            ref = _clean_token(data.get("refreshToken"))
        except Exception:
            pass

        # Regex fallback for raw JWTs
        if not acc:
            jwts = re.findall(r"ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", content)
            if jwts:
                acc = jwts[0]
                if len(jwts) > 1:
                    ref = jwts[1]

        if not acc:
            return {"ok": False, "error": "لم يتم العثور على رمز accessToken داخل الملف."}

        info = get_token_info(acc)
        return {
            "ok": True,
            "accessToken": acc,
            "refreshToken": ref,
            "info": info
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def save_tokens_to_token_file(
    access_token: str,
    refresh_token: Optional[str] = None,
    file_path: str = DEFAULT_TOKEN_FILE_PATH
):
    """
    Saves new tokens to token.text in formatted JSON with metadata.
    """
    try:
        acc_info = get_token_info(access_token)
        ref_info = get_token_info(refresh_token) if refresh_token else None

        data = {
            "apiBase": "https://apis.digital.gov.eg",
            "accessToken": access_token,
            "refreshToken": refresh_token or "",
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "access": {
                "issuedAt": acc_info.get("issued_at_utc") if acc_info else None,
                "expiresAt": acc_info.get("expires_at_utc") if acc_info else None,
                "secondsLeft": acc_info.get("seconds_left") if acc_info else None,
                "claims": acc_info.get("claims") if acc_info else None
            },
            "refresh": {
                "issuedAt": ref_info.get("issued_at_utc") if ref_info else None,
                "expiresAt": ref_info.get("expires_at_utc") if ref_info else None,
                "secondsLeft": ref_info.get("seconds_left") if ref_info else None,
                "claims": ref_info.get("claims") if ref_info else None
            }
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"[نجاح]: تم تحديث ملف {os.path.basename(file_path)} بنجاح.")
    except Exception as e:
        print(f"[تحذير]: تعذّر حفظ التوكن في ملف {file_path}: {e}")


def _extract_tokens_from_raw_storage(raw_persist: Optional[str]) -> Optional[Dict[str, str]]:
    if not raw_persist:
        return None
    try:
        root = json.loads(raw_persist)
        auth_slice_raw = root.get("authSlice")
        if not auth_slice_raw:
            return None
        auth_slice = json.loads(auth_slice_raw)
        acc = _clean_token(auth_slice.get("accessToken"))
        ref = _clean_token(auth_slice.get("refreshToken"))
        if acc:
            return {"accessToken": acc, "refreshToken": ref}
    except Exception:
        pass
    return None


async def _perform_cdp_login_async(
    browser_exe: str,
    phone: str,
    password: str,
    headless: bool = True,
    status_callback: Optional[Callable[[str], None]] = None,
    timeout_seconds: int = 90
) -> Dict[str, Any]:
    def log(msg: str):
        if status_callback:
            status_callback(msg)
        print(f"[تسجيل الدخول التلقائي]: {msg}")

    port = find_free_port()
    os.makedirs(EDGE_PROFILE_DIR, exist_ok=True)

    cmd = [
        browser_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={EDGE_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-background-networking",
        "--disable-client-side-phishing-detection",
        "--disable-default-apps",
        "--disable-hang-monitor",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-features=Translate,OptimizationHints",
        "https://digital.gov.eg/"
    ]
    if headless:
        cmd.append("--headless=new")

    log("جارٍ تشغيل المتصفح والاتصال ببوابة مصر الرقمية...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    try:
        # Wait for CDP endpoint to respond
        cdp_base = f"http://127.0.0.1:{port}"
        connected = False
        for _ in range(15):
            await asyncio.sleep(0.8)
            try:
                with httpx.Client(timeout=2.0) as client:
                    r = client.get(f"{cdp_base}/json")
                    if r.status_code == 200 and r.json():
                        connected = True
                        break
            except Exception:
                pass

        if not connected:
            return {"ok": False, "error": "تعذّر الاتصال بواجهة تصحيح المتصفح (CDP)."}

        log("تم الاتصال بالمتصفح بنجاح. في انتظار تحميل الصفحة الرئيسية...")
        await asyncio.sleep(3.5)

        # Get tabs list
        with httpx.Client(timeout=3.0) as client:
            tabs = client.get(f"{cdp_base}/json").json()

        page_tabs = [t for t in tabs if t.get("type") == "page"]
        if not page_tabs:
            return {"ok": False, "error": "لم يتم العثور على نافذة الصفحة المفتوحة."}

        target_tab = page_tabs[0]
        ws_url = target_tab.get("webSocketDebuggerUrl")

        # Step 1: Click the main login button on digital.gov.eg
        log("جارٍ النقر على زر تسجيل الدخول للانتقال إلى شاشة الدخول...")
        async with websockets.connect(ws_url) as ws:
            click_js = """
            (() => {
                const btn = Array.from(document.querySelectorAll('button')).find(
                    b => b.className && b.className.includes('MuiButton-containedPrimary')
                );
                if (btn) {
                    btn.click();
                    return 'CLICKED';
                }
                // Try any anchor or button with login in href
                const link = Array.from(document.querySelectorAll('a, button')).find(
                    el => (el.innerText && el.innerText.includes('دخول')) || (el.href && el.href.includes('login'))
                );
                if (link) {
                    link.click();
                    return 'CLICKED_LINK';
                }
                return 'NOT_FOUND';
            })()
            """
            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": click_js}}))
            await ws.recv()

        # Step 2: Wait for Keycloak login tab to appear
        log("جارٍ فتح صفحة المصادقة وتسجيل الدخول...")
        login_tab = None
        for _ in range(15):
            await asyncio.sleep(1.0)
            with httpx.Client(timeout=3.0) as client:
                all_tabs = client.get(f"{cdp_base}/json").json()
            login_tab = next((t for t in all_tabs if "login.di.gov.eg" in t.get("url", "")), None)
            if login_tab:
                break

        if not login_tab:
            return {"ok": False, "error": "تعذّر الانتقال إلى صفحة تسجيل الدخول (login.di.gov.eg)."}

        # Step 3: Enter Phone Number (username)
        log(f"جارٍ إدخال رقم الهاتف ({phone})...")
        entered_phone = False
        for _ in range(12):
            await asyncio.sleep(0.6)
            try:
                with httpx.Client(timeout=3.0) as client:
                    all_tabs = client.get(f"{cdp_base}/json").json()
                login_tab = next((t for t in all_tabs if "login.di.gov.eg" in t.get("url", "")), None)
                if not login_tab:
                    continue

                async with websockets.connect(login_tab["webSocketDebuggerUrl"]) as ws_login:
                    phone_js = f"""
                    (() => {{
                        const u = document.getElementById('username');
                        if (u) {{
                            u.value = '{phone}';
                            u.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            u.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            const btn = document.getElementById('kc-login');
                            if (btn) {{
                                btn.click();
                                return 'SUBMITTED';
                            }}
                        }}
                        return 'WAITING';
                    }})()
                    """
                    await ws_login.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": phone_js}}))
                    res = json.loads(await ws_login.recv())
                    if res.get("result", {}).get("result", {}).get("value") == "SUBMITTED":
                        entered_phone = True
                        break
            except Exception:
                pass

        if not entered_phone:
            return {"ok": False, "error": "تعذّر العثور على حقل إدخال رقم الهاتف في شاشة الدخول."}

        # Step 4: Wait for navigation to password screen, then enter password
        log("جارٍ إدخال كلمة المرور...")
        await asyncio.sleep(3.0)
        entered_pass = False
        for _ in range(15):
            try:
                with httpx.Client(timeout=3.0) as client:
                    all_tabs = client.get(f"{cdp_base}/json").json()
                login_tab = next((t for t in all_tabs if "login.di.gov.eg" in t.get("url", "")), None)
                if not login_tab:
                    await asyncio.sleep(0.8)
                    continue

                async with websockets.connect(login_tab["webSocketDebuggerUrl"]) as ws_pass:
                    # Check for errors on page first
                    check_err_js = "document.querySelector('.alert-error, #input-error, .instruction')?.innerText || ''"
                    await ws_pass.send(json.dumps({"id": 30, "method": "Runtime.evaluate", "params": {"expression": check_err_js}}))
                    err_res = json.loads(await ws_pass.recv())
                    page_err = err_res.get("result", {}).get("result", {}).get("value")
                    if page_err and any(k in page_err for k in ["غير صحيح", "خطأ", "invalid", "error"]):
                        return {"ok": False, "error": f"رسالة من البوابة: {page_err}"}

                    pass_js = f"""
                    (() => {{
                        const p = document.getElementById('password');
                        if (p) {{
                            p.value = '{password}';
                            p.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            p.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            const btn = document.getElementById('kc-login');
                            if (btn) {{
                                btn.click();
                                return 'SUBMITTED';
                            }}
                        }}
                        return 'WAITING';
                    }})()
                    """
                    await ws_pass.send(json.dumps({"id": 3, "method": "Runtime.evaluate", "params": {"expression": pass_js}}))
                    res = json.loads(await ws_pass.recv())
                    if res.get("result", {}).get("result", {}).get("value") == "SUBMITTED":
                        entered_pass = True
                        break
            except Exception:
                pass
            await asyncio.sleep(0.8)

        if not entered_pass:
            return {"ok": False, "error": "تعذّر إدخال كلمة المرور في شاشة الدخول."}

        # Step 5: Wait for redirection back to digital.gov.eg and capture session tokens
        log("جارٍ إتمام الدخول والتقاط رمز الجلسة (Tokens)...")
        start_wait = time.time()
        while time.time() - start_wait < timeout_seconds:
            await asyncio.sleep(1.2)
            try:
                with httpx.Client(timeout=3.0) as client:
                    all_tabs = client.get(f"{cdp_base}/json").json()

                for t in all_tabs:
                    t_url = t.get("url", "")
                    if "digital.gov.eg" in t_url and "login.di.gov.eg" not in t_url:
                        async with websockets.connect(t["webSocketDebuggerUrl"]) as ws_portal:
                            token_js = "sessionStorage.getItem('persist:root');"
                            await ws_portal.send(json.dumps({"id": 100, "method": "Runtime.evaluate", "params": {"expression": token_js}}))
                            t_res = json.loads(await ws_portal.recv())
                            raw_storage = t_res.get("result", {}).get("result", {}).get("value")
                            tokens = _extract_tokens_from_raw_storage(raw_storage)
                            if tokens and tokens.get("accessToken"):
                                log("تم تسجيل الدخول بنجاح والتقاط الجلسة والتوكن!")
                                return {
                                    "ok": True,
                                    "accessToken": tokens["accessToken"],
                                    "refreshToken": tokens.get("refreshToken", "")
                                }
            except Exception:
                pass

        return {"ok": False, "error": "انتهت المهلة قبل اكتمال التقاط الجلسة من المتصفح."}

    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def run_auto_login(
    auth_manager: Optional[AuthManager] = None,
    phone: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = True,
    status_callback: Optional[Callable[[str], None]] = None,
    sync_token_file: bool = True
) -> Dict[str, Any]:
    """
    Executes automated one-click login:
    1. Reads credentials from 'login info.text' (if not explicitly passed).
    2. Runs CDP browser login against Digital Egypt Keycloak.
    3. Saves fresh tokens to AuthManager.
    4. Automatically writes updated tokens to 'token.text'.
    """
    if auth_manager is None:
        auth_manager = AuthManager()

    # Parse credentials if not supplied
    if not phone or not password:
        p, pw = parse_credentials()
        phone = phone or p
        password = password or pw

    if not phone or not password:
        err = "لم يتم العثور على رقم الهاتف أو كلمة المرور في ملف 'login info.text'."
        if status_callback:
            status_callback(err)
        return {"ok": False, "error": err}

    browser_exe = find_browser_executable()
    if not browser_exe:
        err = "لم يتم العثور على متصفح Microsoft Edge أو Google Chrome على هذا الجهاز."
        if status_callback:
            status_callback(err)
        return {"ok": False, "error": err}

    try:
        # Run async CDP login
        res = asyncio.run(_perform_cdp_login_async(
            browser_exe=browser_exe,
            phone=phone,
            password=password,
            headless=headless,
            status_callback=status_callback
        ))

        if res.get("ok"):
            acc = res["accessToken"]
            ref = res.get("refreshToken")
            auth_manager.set_tokens(acc, ref)

            # Also update token.text file
            if sync_token_file:
                save_tokens_to_token_file(acc, ref)

            res["status"] = auth_manager.get_status()
            return res
        else:
            return res

    except Exception as e:
        err_msg = f"حدث استثناء أثناء تسجيل الدخول التلقائي: {e}"
        if status_callback:
            status_callback(err_msg)
        return {"ok": False, "error": err_msg}
