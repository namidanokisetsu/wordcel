import sys
import plistlib
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from wordcel.utils import startup


class _Key:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.values = {}
        self.winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER=object(), KEY_SET_VALUE=1, REG_SZ=1,
            CreateKeyEx=lambda *_args: _Key(),
            OpenKey=self._open_key,
            SetValueEx=lambda _key, name, _reserved, _kind, value: self.values.__setitem__(name, value),
            QueryValueEx=lambda _key, name: (self.values[name], 1),
            DeleteValue=lambda _key, name: self.values.pop(name),
        )

    def _open_key(self, *_args):
        if not self.values:
            raise FileNotFoundError
        return _Key()

    def test_enable_query_and_disable(self):
        with patch.object(startup.sys, "platform", "win32"), patch.dict(sys.modules, {"winreg": self.winreg}):
            startup.set_startup_enabled(True)
            self.assertIn("wordcel", self.values)
            self.assertTrue(startup.is_startup_enabled())
            startup.set_startup_enabled(False)
            self.assertFalse(self.values)

    def test_packaged_command_quotes_executable(self):
        with patch.object(startup.sys, "executable", r"C:\Program Files\wordcel\wordcel.exe"), \
                patch.object(startup.sys, "frozen", True, create=True):
            self.assertEqual(
                startup.startup_command(),
                f'"{Path(startup.sys.executable).resolve()}"',
            )


class MacStartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.agent = Path(temporary.name) / "LaunchAgents" / "wordcel.plist"
        for replacement in (patch.object(startup.sys, "platform", "darwin"),
                            patch.object(startup, "_launch_agent_path", return_value=self.agent)):
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_packaged_app_opens_in_background_at_login_and_can_be_disabled(self):
        executable = "/Applications/Wordcel Test.app/Contents/MacOS/wordcel"
        with patch.object(startup.sys, "executable", executable), \
                patch.object(startup.sys, "frozen", True, create=True):
            self.assertFalse(startup.is_startup_enabled())
            startup.set_startup_enabled(True)
        agent = plistlib.loads(self.agent.read_bytes())
        self.assertEqual(agent["ProgramArguments"], ["/usr/bin/open", "-g", "/Applications/Wordcel Test.app"])
        self.assertEqual(agent["LimitLoadToSessionType"], "Aqua")
        self.assertTrue(startup.is_startup_enabled())
        self.assertNotIn("KeepAlive", agent)
        startup.set_startup_enabled(False)
        startup.set_startup_enabled(False)
        self.assertFalse(startup.is_startup_enabled())

    def test_source_preserves_virtual_environment_symlink_and_argument_boundaries(self):
        executable = self.agent.parent.parent / "source with spaces" / "bin" / "python"
        executable.parent.mkdir(parents=True)
        executable.symlink_to(sys.executable)
        with patch.object(startup.sys, "executable", str(executable)), \
                patch.object(startup.sys, "frozen", False, create=True):
            startup.set_startup_enabled(True)
        agent = plistlib.loads(self.agent.read_bytes())
        self.assertEqual(agent["ProgramArguments"], [str(executable), "-m", "wordcel.main"])

    def test_invalid_registration_and_failed_write_do_not_destroy_existing_entry(self):
        self.agent.parent.mkdir()
        self.agent.write_bytes(b"invalid plist")
        self.assertFalse(startup.is_startup_enabled())
        startup.set_startup_enabled(True)
        previous = self.agent.read_bytes()
        with patch.object(startup.plistlib, "dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                startup.set_startup_enabled(True)
        self.assertEqual(self.agent.read_bytes(), previous)
        self.assertEqual(list(self.agent.parent.iterdir()), [self.agent])


if __name__ == "__main__":
    unittest.main()
