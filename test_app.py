"""Settings and Flask app tests (no browser, no network).

    python test_app.py

Needs Flask, PyYAML and anthropic installed (imports src/app.py).
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, "src")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
_HOME = tempfile.TemporaryDirectory()
os.environ["DATING_COPILOT_HOME"] = _HOME.name

import keyring  # noqa: E402
import keyring.backend  # noqa: E402
import keyring.errors  # noqa: E402


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.d = {}

    def set_password(self, service, user, password):
        self.d[(service, user)] = password

    def get_password(self, service, user):
        return self.d.get((service, user))

    def delete_password(self, service, user):
        if (service, user) not in self.d:
            raise keyring.errors.PasswordDeleteError("absent")
        del self.d[(service, user)]


keyring.set_keyring(MemoryKeyring())

import secrets_store  # noqa: E402
import settings  # noqa: E402
import runlog  # noqa: E402
from app import create_app  # noqa: E402


class FakeController:
    def __init__(self):
        self.running = False
        self.started_with = None

    def is_running(self):
        return self.running

    def status(self):
        return {"state": "running" if self.running else "idle",
                "running": self.running, "messages": [], "last_summary": None}

    def start(self, **kw):
        if self.running:
            return False
        self.running, self.started_with = True, kw
        return True

    def stop(self):
        was, self.running = self.running, False
        return was

    def start_login(self):
        if self.running:
            return False
        self.running = True
        return True


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rub = Path(self.tmp.name) / "rubric.yaml"
        self.sc = Path(self.tmp.name) / "scoring.yaml"
        shutil.copy(settings.RUBRIC, self.rub)
        shutil.copy(settings.SCORING, self.sc)
        self._old = (settings.RUBRIC, settings.SCORING)
        settings.RUBRIC, settings.SCORING = self.rub, self.sc
        f = runlog.home() / "settings.json"
        if f.exists():
            f.unlink()

    def tearDown(self):
        settings.RUBRIC, settings.SCORING = self._old
        self.tmp.cleanup()

    def test_read_matches_repo_defaults(self):
        s = settings.read()
        self.assertEqual((s["age_min"], s["age_max"]), (26, 34))
        self.assertEqual(s["distance_km_max"], 20)
        self.assertEqual(s["height_max_cm"], 173)
        self.assertEqual(s["auto_like"], 58)

    def test_write_updates_yaml_and_keeps_comments(self):
        before = self.sc.read_text()
        settings.write({"auto_like": 70, "age_min": 27, "distance_km_max": 15})
        s = settings.read()
        self.assertEqual((s["auto_like"], s["age_min"], s["distance_km_max"]), (70, 27, 15))
        self.assertIn("# tune this after reading the first digest", self.sc.read_text())
        self.assertIn("# Hard filters.", self.rub.read_text())
        # Only the threshold line changed in scoring.yaml.
        diff = [l for l in self.sc.read_text().splitlines()
                if l not in before.splitlines()]
        self.assertEqual(len(diff), 1)

    def test_weights_untouched(self):
        import yaml
        w0 = yaml.safe_load(self.sc.read_text())
        settings.write({"auto_like": 65})
        w1 = yaml.safe_load(self.sc.read_text())
        w0["thresholds"]["auto_like"] = w1["thresholds"]["auto_like"]
        self.assertEqual(w0, w1)

    def test_validation(self):
        for bad in ({"age_min": 40, "age_max": 30}, {"auto_like": 150},
                    {"max_likes": 1000}, {"max_profiles": 5000},
                    {"distance_km_max": "abc"}, {"age_min": 10}):
            with self.assertRaises(ValueError, msg=str(bad)):
                settings.write(bad)

    def test_invalid_write_changes_nothing(self):
        before = self.rub.read_text()
        with self.assertRaises(ValueError):
            settings.write({"age_min": 40, "age_max": 30})
        self.assertEqual(self.rub.read_text(), before)

    def test_run_kwargs_quiet_hours_wrap(self):
        settings.write({"quiet_start": 23, "quiet_end": 7})
        h = settings.run_kwargs()["quiet_hours"]
        self.assertIn(23, h)
        self.assertIn(0, h)
        self.assertNotIn(12, h)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.ctl = FakeController()
        self.app = create_app(self.ctl)
        self.c = self.app.test_client()
        page = self.c.get("/", base_url="http://127.0.0.1:5000").get_data(as_text=True)
        self.token = page.split('const TOKEN = "')[1].split('"')[0]
        self.base = "http://127.0.0.1:5000"

    def post(self, path, body=None, token=True, base=None):
        h = {"X-App-Token": self.token} if token else {}
        return self.c.post(path, json=body or {}, headers=h,
                           base_url=base or self.base)

    def test_page_has_token_and_loads(self):
        self.assertEqual(len(self.token) > 20, True)

    def test_post_without_token_is_forbidden(self):
        self.assertEqual(self.post("/api/start", token=False).status_code, 403)
        self.assertFalse(self.ctl.running)

    def test_foreign_host_is_forbidden(self):
        r = self.c.get("/api/status", base_url="http://evil.example")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.post("/api/start", base="http://evil.example").status_code, 403)

    def test_start_stop_flow(self):
        self.assertEqual(self.post("/api/start").status_code, 200)
        self.assertTrue(self.ctl.running)
        self.assertIn("max_likes", self.ctl.started_with)
        self.assertEqual(self.post("/api/start").status_code, 409)
        self.assertEqual(self.post("/api/stop").status_code, 200)
        self.assertFalse(self.ctl.running)

    def test_login_endpoint(self):
        self.assertEqual(self.post("/api/login", token=False).status_code, 403)
        self.assertEqual(self.post("/api/login").status_code, 200)
        self.assertEqual(self.post("/api/login").status_code, 409)

    def test_settings_locked_while_running(self):
        self.ctl.running = True
        self.assertEqual(self.post("/api/settings", {"auto_like": 60}).status_code, 409)

    def test_settings_validation_error_is_400(self):
        r = self.post("/api/settings", {"max_likes": 9999})
        self.assertEqual(r.status_code, 400)
        self.assertIn("max_likes", r.get_json()["error"])

    def test_feed_and_stats_endpoints(self):
        self.assertEqual(self.c.get("/api/feed", base_url=self.base).status_code, 200)
        r = self.c.get("/api/stats", base_url=self.base).get_json()
        self.assertIn("histogram", r)

    def test_setup_endpoint(self):
        r = self.c.get("/api/setup", base_url=self.base).get_json()
        self.assertEqual(set(r), {"keychain", "anthropic_key", "telegram",
                                  "tinder_session", "env_file"})

    GOOD_KEY = "sk-ant-api03-" + "a" * 30
    GOOD_TOKEN = "123456789:" + "A" * 35

    def test_secret_saved_to_keychain_and_never_returned(self):
        r = self.post("/api/secrets", {"name": "ANTHROPIC_API_KEY", "value": self.GOOD_KEY})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(secrets_store.get("ANTHROPIC_API_KEY"), self.GOOD_KEY)
        for path in ("/api/setup", "/api/settings", "/api/status"):
            body = self.c.get(path, base_url=self.base).get_data(as_text=True)
            self.assertNotIn(self.GOOD_KEY, body)
        self.assertNotIn(self.GOOD_KEY, r.get_data(as_text=True))

    def test_secret_validation_and_clear(self):
        bad = self.post("/api/secrets", {"name": "TELEGRAM_BOT_TOKEN", "value": "nope"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.post("/api/secrets", {"name": "X", "value": "1"}).status_code, 400)
        self.post("/api/secrets", {"name": "TELEGRAM_BOT_TOKEN", "value": self.GOOD_TOKEN})
        self.assertEqual(secrets_store.get("TELEGRAM_BOT_TOKEN"), self.GOOD_TOKEN)
        self.post("/api/secrets", {"name": "TELEGRAM_BOT_TOKEN", "value": ""})
        self.assertIsNone(secrets_store.get("TELEGRAM_BOT_TOKEN"))

    def test_secrets_need_token_and_stopped_session(self):
        self.assertEqual(self.post("/api/secrets", {"name": "ANTHROPIC_API_KEY",
                         "value": self.GOOD_KEY}, token=False).status_code, 403)
        self.ctl.running = True
        self.assertEqual(self.post("/api/secrets", {"name": "ANTHROPIC_API_KEY",
                         "value": self.GOOD_KEY}).status_code, 409)

    def test_load_into_env_prefers_existing_env(self):
        secrets_store.set("TELEGRAM_CHAT_ID", "987654321")
        os.environ["TELEGRAM_CHAT_ID"] = "111111111"
        secrets_store.load_into_env()
        self.assertEqual(os.environ["TELEGRAM_CHAT_ID"], "111111111")
        os.environ.pop("TELEGRAM_CHAT_ID")
        secrets_store.load_into_env()
        self.assertEqual(os.environ["TELEGRAM_CHAT_ID"], "987654321")
        os.environ.pop("TELEGRAM_CHAT_ID")


if __name__ == "__main__":
    unittest.main(verbosity=2)
