"""
Windows Desktop Notifications & Console Alerts for Digital Egypt Case Tracker.
"""

import sys
import base64
import subprocess
import xml.sax.saxutils as saxutils
from typing import Optional

# Ensure stdout handles Unicode characters on Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def send_windows_toast(title: str, message: str, app_id: str = "متتبع الدعاوى المدنية") -> bool:
    """
    Sends a native Windows 10/11 Toast notification via PowerShell.
    Uses UTF-16LE EncodedCommand to ensure proper Arabic text handling without encoding issues.
    """
    safe_title = saxutils.escape(str(title or ""))
    safe_msg = saxutils.escape(str(message or ""))
    safe_app = saxutils.escape(str(app_id or "متتبع الدعاوى"))

    ps_code = f"""
try {{
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $template = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>{safe_title}</text>
            <text>{safe_msg}</text>
        </binding>
    </visual>
</toast>
"@
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($template)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{safe_app}").Show($toast)
}} catch {{
    # Fallback silently if toast manager is unavailable
}}
"""
    try:
        encoded = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=5
        )
        return True
    except Exception:
        return False


def notify(title: str, message: str, client_name: Optional[str] = None):
    """
    Notify user of a case change via both desktop toast and console output.
    """
    full_title = f"تنبيه متتبع الدعاوى: {title}"
    if client_name:
        full_msg = f"[{client_name}] {message}"
    else:
        full_msg = message

    # Safe console print
    try:
        print(f"\n[تنبيه] {full_title} - {full_msg}")
    except Exception:
        pass

    # Windows Toast notification
    if sys.platform == "win32":
        try:
            send_windows_toast(full_title, full_msg)
        except Exception:
            pass
