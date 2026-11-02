"""macOS permissions requested when their features start."""
import subprocess
import sys


class InputMonitoringPermissionError(RuntimeError):
    pass


class AccessibilityPermissionError(RuntimeError):
    pass


_PRIVACY_SETTINGS = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    "screen_recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
}


def privacy_permission_granted(feature: str) -> bool:
    """Return a permission state without prompting or changing system settings."""
    if sys.platform != "darwin":
        return True
    try:
        if feature == "accessibility":
            from ApplicationServices import AXIsProcessTrusted
            return bool(AXIsProcessTrusted())
        if feature == "input_monitoring":
            from Quartz import CGPreflightListenEventAccess
            return bool(CGPreflightListenEventAccess())
        if feature == "screen_recording":
            from Quartz import CGPreflightScreenCaptureAccess
            return bool(CGPreflightScreenCaptureAccess())
    except (ImportError, AttributeError):
        return False
    raise ValueError(f"Unknown macOS privacy feature: {feature}")


def open_privacy_settings(feature: str) -> bool:
    """Open the macOS settings pane for a permission-dependent feature."""
    if sys.platform != "darwin":
        return False
    try:
        url = _PRIVACY_SETTINGS[feature]
    except KeyError as error:
        raise ValueError(f"Unknown macOS privacy feature: {feature}") from error
    try:
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


def require_accessibility_permission() -> None:
    if sys.platform != "darwin":
        return
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
        raise AccessibilityPermissionError(
            "Allow Wordcel in System Settings > Privacy & Security > Accessibility."
        )


def require_input_monitoring_permission() -> None:
    if sys.platform != "darwin":
        return
    from Quartz import CGPreflightListenEventAccess, CGRequestListenEventAccess
    if not CGPreflightListenEventAccess() and not CGRequestListenEventAccess():
        raise InputMonitoringPermissionError(
            "Allow Wordcel in System Settings > Privacy & Security > Input Monitoring."
        )


def require_screen_capture_permission(*, request_access: bool = False) -> None:
    if sys.platform != "darwin":
        return
    try:
        from Quartz import CGPreflightScreenCaptureAccess
    except ImportError as error:
        raise RuntimeError("Screen capture needs Wordcel's macOS dependencies.") from error
    if not CGPreflightScreenCaptureAccess():
        # Request when screen lookup starts, never during frame capture.
        if request_access:
            from Quartz import CGRequestScreenCaptureAccess
            if CGRequestScreenCaptureAccess():
                return
        raise RuntimeError(
            "Allow Wordcel in System Settings > Privacy & Security > Screen Recording."
        )
