"""Optimized notification module for Windows toast notifications.

Key optimizations:
- Reusable PowerShell command templates
- Reduced process spawn overhead
- Better error handling
"""
import subprocess
import time
from typing import List, Dict, Optional

# Cache the PowerShell base template
_TOAST_TEMPLATE = (
    "Add-Type -AssemblyName System.Windows.Forms; "
    "Add-Type -AssemblyName System.Drawing; "
    "$n = New-Object System.Windows.Forms.NotifyIcon; "
    "$n.Icon = [System.Drawing.SystemIcons]::Information; "
    "$n.Visible = $true; "
    "$n.BalloonTipTitle = '{title}'; "
    "$n.BalloonTipText = '{message}'; "
    "$n.ShowBalloonTip(6000); "
    "Start-Sleep -Seconds 6; "
    "$n.Dispose();"
)


def _format_ps_command(title: str, message: str) -> str:
    """Format PowerShell command with escaped strings.

    In PowerShell single-quoted strings, the only escape is '' for a literal '.
    Double quotes are literal inside single quotes, so no need to escape them.
    """
    safe_title = title.replace("'", "''")
    safe_msg = message.replace("'", "''")
    return _TOAST_TEMPLATE.format(title=safe_title, message=safe_msg)


def toast(title: str, message: str) -> bool:
    """Show a Windows toast notification. Returns True on success."""
    ps_command = _format_ps_command(title, message)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=20,
        )
        return result.returncode == 0
    except Exception:
        return False


def notify_due_reminders(reminders: List[Dict]) -> int:
    """Notify user of due reminders. Returns count of shown notifications."""
    from core import memory
    shown = 0
    for r in reminders:
        if toast("Ultron reminder", r["text"]):
            shown += 1
            memory.mark_notified(r["text"])
    return shown


def batched_toast(title: str, messages: List[str], delay: float = 1.0) -> int:
    """Show multiple toast notifications with a delay between them."""
    shown = 0
    for msg in messages:
        if toast(title, msg):
            shown += 1
            if delay > 0:
                time.sleep(delay)
    return shown
