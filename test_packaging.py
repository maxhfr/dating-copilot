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
