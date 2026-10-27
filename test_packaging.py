"""Paths and browser-setup helpers used by the packaged app.

    python test_packaging.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, "src")
sys.path.insert(0, "packaging")
_HOME = tempfile.TemporaryDirectory()
os.environ["DATING_COPILOT_HOME"] = _HOME.name

import browser_setup  # noqa: E402
import paths  # noqa: E402


class PathsTests(unittest.TestCase):
    def test_checkout_uses_repo_config(self):
        self.assertFalse(paths.frozen())
        self.assertTrue((paths.config_dir() / "rubric.yaml").exists())

    def test_frozen_seeds_writable_config_once(self):
        bundle = Path(tempfile.mkdtemp())
        (bundle / "config").mkdir()
        (bundle / "config" / "rubric.yaml").write_text("age: {min: 26, max: 34}\n")
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", str(bundle), create=True):
            d = paths.config_dir()
            self.assertEqual(d, Path(_HOME.name) / "config")
            (d / "rubric.yaml").write_text("edited: true\n")   # user edit
            paths.config_dir()                                  # must not overwrite
            self.assertEqual((d / "rubric.yaml").read_text(), "edited: true\n")


class IconTests(unittest.TestCase):
    def test_icon_assets_exist(self):
        self.assertTrue(paths.icon_png().exists())
        self.assertTrue((paths.bundle_root() / "packaging" / "icon" / "icon.icns").exists())
        self.assertTrue((paths.bundle_root() / "packaging" / "icon" / "icon.svg").exists())

    def test_icon_path_when_frozen(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", "/bundle", create=True):
            self.assertEqual(paths.icon_png(), Path("/bundle/icon/icon_1024.png"))


class WindowsTests(unittest.TestCase):
    def test_ico_is_valid_and_has_several_sizes(self):
        data = (Path("packaging") / "icon" / "icon.ico").read_bytes()
        self.assertEqual(data[:4], b"\x00\x00\x01\x00")        # ICO header
        self.assertGreaterEqual(int.from_bytes(data[4:6], "little"), 6)

    def test_keep_awake_uses_execution_state_on_windows(self):
        import keep_awake
        calls = []
        with mock.patch.object(keep_awake.sys, "platform", "win32"), \
                mock.patch.object(keep_awake, "_win_set",
                                  side_effect=lambda on: calls.append(on) or True):
            k = keep_awake.KeepAwake()
            self.assertFalse(k.active)
            self.assertTrue(k.set(True))
            self.assertTrue(k.active)
            self.assertTrue(k.set(True))            # idempotent
            self.assertFalse(k.set(False))
            self.assertFalse(k.active)
            self.assertEqual(calls, [True, False])

    def test_keep_awake_survives_win_api_error(self):
        import keep_awake
        with mock.patch.object(keep_awake.sys, "platform", "win32"), \
                mock.patch.object(keep_awake, "_win_set", side_effect=OSError("nope")):
            self.assertFalse(keep_awake.KeepAwake().set(True))

    def test_startup_script_contents(self):
        import launch_agent
        cmd = launch_agent.build_startup_cmd(Path("C:/apps/dc"))
        self.assertIn("run.bat", cmd)
        self.assertIn("app", cmd)
        self.assertTrue(cmd.startswith("@echo off"))
        exe = launch_agent.build_startup_cmd(Path("C:/apps/dc"), exe="C:/x/dating-copilot.exe")
        self.assertIn('start "" "C:/x/dating-copilot.exe"', exe)
        self.assertNotIn("run.bat", exe)

    def test_startup_path_is_in_the_startup_folder(self):
        import launch_agent
        with mock.patch.dict(os.environ, {"APPDATA": "C:/Users/x/AppData/Roaming"}):
            p = str(launch_agent.startup_cmd_path()).replace("\\", "/")
        self.assertTrue(p.endswith("Start Menu/Programs/Startup/Dating Copilot.cmd"))

    def test_run_bat_exists(self):
        text = Path("run.bat").read_text()
        self.assertIn("src\\gui.py", text)
        self.assertIn("src\\cli.py", text)


class EnvFileTests(unittest.TestCase):
    def test_loads_without_overriding_existing(self):
        import envfile
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"DATING_COPILOT_HOME": d, "KEEP_ME": "shell"}):
            (Path(d) / ".env").write_text(
                "# comment\nNEW_VAR=from_file\nKEEP_ME=file\n\nBAD LINE\n", encoding="utf-8")
            os.environ.pop("NEW_VAR", None)
            envfile.load_env()
            self.assertEqual(os.environ["NEW_VAR"], "from_file")
            self.assertEqual(os.environ["KEEP_ME"], "shell")
            os.environ.pop("NEW_VAR", None)


class BrowserTests(unittest.TestCase):
    def test_installed_detection(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": d}):
            self.assertFalse(browser_setup.chromium_installed())
            (Path(d) / "chromium_headless_shell-1248").mkdir()   # not the full browser
            self.assertFalse(browser_setup.chromium_installed())
            (Path(d) / "chromium-1248").mkdir()
            self.assertTrue(browser_setup.chromium_installed())

    def test_bundle_mode_path_is_replaced_by_standard_folder(self):
        # PyInstaller's hook sets PLAYWRIGHT_BROWSERS_PATH=0 (browsers inside
        # the app); we must point at the standard cache so Chromium is found.
        with mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": "0"}):
            p = browser_setup.use_standard_browsers_path()
            self.assertEqual(p, browser_setup.default_browsers_dir())
            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"],
                             str(browser_setup.default_browsers_dir()))

    def test_explicit_path_is_kept(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": d}):
            self.assertEqual(browser_setup.use_standard_browsers_path(), Path(d))
            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], d)

    def test_unset_defaults_to_standard_folder(self):
        env = {k: v for k, v in os.environ.items() if k != "PLAYWRIGHT_BROWSERS_PATH"}
        with mock.patch.dict(os.environ, env, clear=True):
            browser_setup.use_standard_browsers_path()
            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"],
                             str(browser_setup.default_browsers_dir()))

    def test_install_skips_when_present(self):
        with mock.patch.object(browser_setup, "chromium_installed", return_value=True), \
                mock.patch("subprocess.run") as run:
            self.assertTrue(browser_setup.install_chromium(on_status=lambda m: None))
            run.assert_not_called()

    def test_install_runs_command_and_reports_failure(self):
        msgs = []
        fail = mock.Mock(returncode=1, stderr="boom", stdout="")
        with mock.patch.object(browser_setup, "chromium_installed", return_value=False), \
                mock.patch("subprocess.run", return_value=fail) as run:
            self.assertFalse(browser_setup.install_chromium(on_status=msgs.append))
            cmd = run.call_args[0][0]
            self.assertEqual(cmd[-2:], ["install", "chromium"])
        self.assertTrue(any("failed" in m for m in msgs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
