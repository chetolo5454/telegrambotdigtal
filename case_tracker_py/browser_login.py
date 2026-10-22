"""
Automated Browser Login Helper for Digital Egypt.
Uses Selenium with Edge or Chrome to open the platform, allow user login,
and automatically capture the session tokens from sessionStorage ('persist:root').
"""

import time
import json
from typing import Optional, Dict, Any, Callable
from .auth import AuthManager, _clean_token


def _extract_tokens_from_storage(raw_persist: Optional[str]) -> Optional[Dict[str, str]]:
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


def run_browser_login(
    auth_manager: Optional[AuthManager] = None,
    timeout_seconds: int = 300,
    status_callback: Optional[Callable[[str], None]] = None,
    close_on_success: bool = True
) -> Dict[str, Any]:
    """
    Launches Edge (or Chrome) to digital.gov.eg login page, waits for the user to log in,
    and captures accessToken and refreshToken from sessionStorage.
    """
    if auth_manager is None:
        auth_manager = AuthManager()

    def update_status(msg: str):
        if status_callback:
            status_callback(msg)
        print(f"[تسجيل الدخول]: {msg}")

    update_status("جارٍ بدء المتصفح...")

    driver = None
    last_err = None

    # Try Edge first (standard on Windows), then Chrome
    try:
        from selenium import webdriver
        from selenium.webdriver.edge.options import Options as EdgeOptions
        edge_options = EdgeOptions()
        edge_options.add_argument("--disable-blink-features=AutomationControlled")
        edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        edge_options.add_experimental_option("useAutomationExtension", False)
        driver = webdriver.Edge(options=edge_options)
        update_status("تم تشغيل متصفح Edge بنجاح.")
    except Exception as e:
        last_err = e
        update_status(f"تعذّر تشغيل Edge ({e})، جارٍ محاولة تشغيل Chrome...")
        try:
            from selenium.webdriver.chrome.options import Options as ChromeOptions
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            driver = webdriver.Chrome(options=chrome_options)
            update_status("تم تشغيل متصفح Chrome بنجاح.")
        except Exception as e2:
            last_err = e2
            msg = f"تعذّر تشغيل المتصفح تلقائياً: {last_err}. يمكنك إدخال التوكن يدوياً في الأداة."
            update_status(msg)
            return {"ok": False, "error": msg}

    try:
        target_url = "https://digital.gov.eg/profile?target=myRequests"
        update_status("جارٍ فتح صفحة مصر الرقمية...")
        driver.get(target_url)

        update_status("في انتظار تسجيل دخولك في المتصفح المفتوح (أدخل كلمة المرور/كود التحقق إن طُلب منك)...")

        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            try:
                # Check if driver is still open
                _ = driver.current_url
            except Exception:
                update_status("تم إغلاق نافذة المتصفح قبل اكتمال تسجيل الدخول.")
                return {"ok": False, "error": "BROWSER_CLOSED"}

            try:
                raw_persist = driver.execute_script("return sessionStorage.getItem('persist:root');")
                tokens = _extract_tokens_from_storage(raw_persist)
                if tokens and tokens.get("accessToken"):
                    acc = tokens["accessToken"]
                    ref = tokens.get("refreshToken", "")
                    auth_manager.set_tokens(acc, ref)
                    update_status("تم التقاط جلسة تسجيل الدخول بنجاح وحفظها!")
                    return {
                        "ok": True,
                        "accessToken": acc,
                        "refreshToken": ref,
                        "status": auth_manager.get_status()
                    }
            except Exception:
                pass

            time.sleep(1.5)

        update_status("انتهت مهلة انتظار تسجيل الدخول (5 دقائق).")
        return {"ok": False, "error": "TIMEOUT"}

    finally:
        if close_on_success and driver:
            try:
                driver.quit()
            except Exception:
                pass
