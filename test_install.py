"""Mac installer script, signing script and entitlements.

    python test_install.py

The macOS-only commands (uname, ditto, open, xattr, osascript, curl) are replaced
by tiny stand-ins on PATH, so the real script runs end to end on any system.
"""

import os
import plistlib
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "install_mac.sh"
APP = "Dating Copilot.app"

STUBS = {
    "uname": '''#!/bin/sh
case "$1" in -s) echo "${FAKE_OS:-Darwin}";; -m) echo arm64;; esac''',
    "curl": '''#!/bin/sh
# curl -fL --progress-bar URL -o OUT   (URL is a local path in the tests)
url=""; out=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift 2;; -*) shift;; *) url="$1"; shift;; esac
done
cp "${url#file://}" "$out"''',
    "ditto": '''#!/bin/sh
if [ "$1" = "-x" ]; then unzip -q "$3" -d "$4"; else cp -R "$1" "$2"; fi''',
    "xattr": '''#!/bin/sh
echo "xattr $*" >> "$STUB_LOG"''',
    "open": '''#!/bin/sh
echo "open $*" >> "$STUB_LOG"''',
    "osascript": '''#!/bin/sh
echo "osascript $*" >> "$STUB_LOG"''',
    "sleep": "#!/bin/sh\nexit 0",
}


def make_zip(path: Path, with_app=True):
    with zipfile.ZipFile(path, "w") as z:
        if with_app:
            z.writestr(f"{APP}/Contents/MacOS/dating-copilot", "binary")
            z.writestr(f"{APP}/Contents/Info.plist", "plist")
        else:
            z.writestr("README.txt", "wrong archive")


class InstallScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, body in STUBS.items():
            p = self.bin / name
            p.write_text(body + "\n")
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.log = self.tmp / "calls.log"
        self.zip = self.tmp / "app.zip"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, **extra):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home),
               "STUB_LOG": str(self.log), "DATING_COPILOT_URL": str(self.zip), **extra}
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def test_installs_the_app_clears_quarantine_and_opens_it(self):
        make_zip(self.zip)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        dest = self.home / "Applications" / APP          # /Applications is not writable here
        self.assertTrue((dest / "Contents" / "MacOS" / "dating-copilot").exists())
        self.assertIn("com.apple.quarantine", self.calls())
        self.assertIn(f"open {dest}", self.calls())

    def test_replaces_an_existing_copy_but_keeps_user_data(self):
        make_zip(self.zip)
        old = self.home / "Applications" / APP / "Contents"
        old.mkdir(parents=True)
        (old / "stale.txt").write_text("old version")
        data = self.home / ".dating-copilot"
        data.mkdir()
        (data / "runlog.db").write_text("precious")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertFalse((old / "stale.txt").exists())
        self.assertEqual((data / "runlog.db").read_text(), "precious")

    def test_quits_a_running_copy_first(self):
        make_zip(self.zip)
        self.run_script()
        self.assertIn("quit", self.calls())

    def test_refuses_a_wrong_archive(self):
        make_zip(self.zip, with_app=False)
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not contain", r.stderr)
        self.assertNotIn("open ", self.calls())

    def test_macos_only(self):
        make_zip(self.zip)
        r = self.run_script(FAKE_OS="Linux")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("macOS only", r.stderr)

    def test_missing_download_fails_cleanly(self):
        r = self.run_script()                       # zip never created
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("open ", self.calls())


class SigningFilesTests(unittest.TestCase):
    def test_scripts_have_valid_syntax(self):
        for script in (SCRIPT, ROOT / "packaging" / "sign_and_notarize_mac.sh"):
            r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{script.name}: {r.stderr}")

    def test_entitlements_plist(self):
        data = plistlib.loads((ROOT / "packaging" / "mac_entitlements.plist").read_bytes())
        for key in ("com.apple.security.cs.allow-jit",
                    "com.apple.security.cs.allow-unsigned-executable-memory",
                    "com.apple.security.cs.disable-library-validation"):
            self.assertIs(data[key], True)

    def test_signing_script_signs_deepest_first_and_never_prints_secrets(self):
        text = (ROOT / "packaging" / "sign_and_notarize_mac.sh").read_text()
        self.assertIn("--options runtime", text)
        self.assertIn("--timestamp", text)
        self.assertIn("sort -rn", text)                  # deepest paths first
        self.assertNotIn("echo \"$APPLE_APP_PASSWORD", text)

    def test_workflow_signing_is_optional(self):
        text = (ROOT / ".github" / "workflows" / "build.yml").read_text()
        self.assertIn("env.MACOS_CERTIFICATE != ''", text)
        self.assertIn("env.MACOS_CERTIFICATE == ''", text)
        self.assertIn("install_mac.sh", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
