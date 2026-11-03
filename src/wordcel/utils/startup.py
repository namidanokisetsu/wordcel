"""Per-user operating-system startup registration."""
from __future__ import annotations

import sys
import plistlib
import tempfile
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "wordcel"
LAUNCH_AGENT = "io.github.namidanokisetsu.wordcel"
_installer_mutex = None


def hold_installer_mutex():
    """Keep the Windows installer from changing files/settings while we run."""
    global _installer_mutex
    if sys.platform != "win32" or _installer_mutex is not None:
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateMutexW
    create.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    create.restype = wintypes.HANDLE
    _installer_mutex = create(None, False, "Local\\wordcel")
    if not _installer_mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    # Windows closes the handle on process exit, after all settings are flushed.


def startup_command() -> str:
    """Return the command that starts this exact packaged or source install."""
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return f'"{executable}"'
    if sys.platform.startswith("win"):
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
    return f'"{executable}" -m wordcel.main'


def is_startup_enabled() -> bool:
    if sys.platform == "darwin":
        try:
            with _launch_agent_path().open("rb") as source:
                agent = plistlib.load(source)
            return (isinstance(agent, dict) and agent.get("Label") == LAUNCH_AGENT
                    and agent.get("RunAtLoad") is True and bool(agent.get("ProgramArguments")))
        except (OSError, ValueError, plistlib.InvalidFileException):
            return False
    if not sys.platform.startswith("win"):
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
        return bool(value)
    except FileNotFoundError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    if sys.platform == "darwin":
        path = _launch_agent_path()
        if not enabled:
            path.unlink(missing_ok=True)
            return
        executable = Path(sys.executable).absolute()
        bundle = next((parent for parent in executable.parents if parent.suffix == ".app"), None)
        arguments = (["/usr/bin/open", "-g", str(bundle)] if getattr(sys, "frozen", False) and bundle
                     else [str(executable), "-m", "wordcel.main"])
        agent = dict(Label=LAUNCH_AGENT, ProgramArguments=arguments, RunAtLoad=True,
                     LimitLoadToSessionType="Aqua")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(dir=path.parent, delete=False)
        staged = Path(temporary.name)
        try:
            with temporary:
                plistlib.dump(agent, temporary)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)
        return
    if not sys.platform.startswith("win"):
        return
    import winreg

    if enabled:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        return

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def _launch_agent_path():
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT}.plist"
