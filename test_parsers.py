"""Unit tests for the page-text parsers in src/platforms/tinder.py.

    python test_parsers.py

No network, no browser, no API calls.

IMPORTANT: no raw page captures are committed to this repo, so the fixtures
below are SYNTHETIC. They are built from the formats documented in
tinder.py's own comments and docstrings ("Morgan27", "Bloquer <name>",
"Vous:" speaker markers, ...). They guard against regressions in the logic
only; they do not prove the parsers match what tinder.com renders today.
When a real capture is available, add it to CAPTURES / the cases below and
mark it as real.
"""

import sys
import types
import unittest

sys.path.insert(0, "src")

# tinder.py imports playwright at module level; the parsers don't need it.
try:
    import playwright.async_api  # noqa: F401
except ImportError:
    pw = types.ModuleType("playwright")
    pw_async = types.ModuleType("playwright.async_api")
    pw_async.async_playwright = None
    sys.modules["playwright"] = pw
    sys.modules["playwright.async_api"] = pw_async

from platforms.tinder import (  # noqa: E402
    _first_int, _parse_name_age, _parse_fields,
    _parse_history, _parse_match_profile,
)

# Synthetic, modelled on the layout documented in tinder.py.
MORGAN_PROFILE = """\
Passer au contenu principal
Matchs
Messages
Morgan27
Retour
Je recherche
\U0001F495
Relation sérieuse
L'essentiel
à 24 kilomètres
170 cm
Femme
Passionnée de randonnée et de cuisine
Mon dimanche idéal :
brunch puis cinéma
Mode de vie
Alcool
\U0001F377
En soirée le week-end
Sport
Tous les jours
Animal de compagnie
Chat
Bloquer Morgan
Signaler Morgan
"""

LOU_THREAD = """\
Matchs
Messages
Historique de conversation avec Lou
Vous avez obtenu un Match avec Lou
20/08/2026 21:16
Envoyé à 21:01
21:01
Vous:
alors on doit deviner ton plat préféré ?
Envoyé
Lou:
haha les pâtes carbonara évidemment
Vu
hier 21:30
Tu peux choisir de répondre
Réponds à Lou
Je ne dis jamais non à un bon resto
Rédigez un message
Je recherche
Relation sérieuse
Plus d’infos sur moi
Bio Tinder
Fan de randonnée et de carbonara
Passions
Randonnée
Cuisine
Mode de vie
Alcool
\U0001F377
Jamais
L’essentiel
à 8 kilomètres
Supprimer le Match
"""


class FirstInt(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(_first_int("170 cm"), 170)

    def test_embedded(self):
        self.assertEqual(_first_int("à 24 kilomètres"), 24)

    def test_first_of_several(self):
        self.assertEqual(_first_int("12 sur 30"), 12)

    def test_none(self):
        self.assertIsNone(_first_int("aucun chiffre"))
        self.assertIsNone(_first_int(""))


class NameAge(unittest.TestCase):
    def test_concatenated(self):
        self.assertEqual(_parse_name_age(MORGAN_PROFILE), ("Morgan", 27))

    def test_accented_name(self):
        self.assertEqual(_parse_name_age("Élodie31\nRetour"), ("Élodie", 31))

    def test_underage_rejected(self):
        self.assertEqual(_parse_name_age("Sam17"), (None, None))

    def test_chrome_ignored(self):
        self.assertEqual(_parse_name_age("Matchs\nMessages\nVous\nLou29"),
                         ("Lou", 29))

    def test_no_match(self):
        self.assertEqual(_parse_name_age("Matchs\nMessages"), (None, None))


class Fields(unittest.TestCase):
    def setUp(self):
        self.f = _parse_fields(MORGAN_PROFILE, "Morgan")

    def test_distance(self):
        self.assertEqual(self.f["distance_km"], 24)

    def test_height(self):
        self.assertEqual(self.f["stated_height_cm"], 170)

    def test_lifestyle_skips_emoji_line(self):
        self.assertEqual(self.f["lifestyle"], {
            "intent": "Relation sérieuse",
            "drinking": "En soirée le week-end",
            "exercise": "Tous les jours",
            "pets": "Chat",
        })

    def test_prompt_joined_with_answer(self):
        self.assertIn("Mon dimanche idéal : brunch puis cinéma", self.f["bio"])

    def test_free_text_kept_name_and_gender_dropped(self):
        bio = self.f["bio"]
        self.assertIn("Passionnée de randonnée et de cuisine", bio)
        self.assertNotIn("Femme", bio)
        self.assertNotIn("Morgan27", bio)

    def test_stops_at_bloquer(self):
        self.assertNotIn("Signaler", self.f["bio"])

    def test_no_height_is_none(self):
        f = _parse_fields("Morgan27\nà 5 kilomètres\nBloquer Morgan", "Morgan")
        self.assertIsNone(f["stated_height_cm"])
        self.assertEqual(f["distance_km"], 5)


class History(unittest.TestCase):
    def setUp(self):
        self.h = _parse_history(LOU_THREAD, "Lou", passions=["Randonnée"])

    def test_speaker_attribution(self):
        self.assertEqual(self.h, [
            {"role": "me", "text": "alors on doit deviner ton plat préféré ?"},
            {"role": "her", "text": "haha les pâtes carbonara évidemment"},
        ])

    def test_stops_before_reply_box(self):
        self.assertFalse(any("resto" in m["text"] for m in self.h))

    def test_no_history_marker(self):
        self.assertEqual(_parse_history("Matchs\nMessages", "Lou"), [])

    def test_shared_passion_chips_not_messages(self):
        body = ("Historique de conversation avec Lou\n"
                "Vous avez obtenu un Match avec Lou\nRandonnée\nCuisine\n"
                "Rédigez un message")
        self.assertEqual(_parse_history(body, "Lou",
                                        passions=["Randonnée", "Cuisine"]), [])

    def test_unmarked_line_defaults_to_her(self):
        body = ("Historique de conversation avec Lou\n"
                "salut toi\nRédigez un message")
        self.assertEqual(_parse_history(body, "Lou"),
                         [{"role": "her", "text": "salut toi"}])

    def test_receipts_and_timestamps_skipped(self):
        body = ("Historique de conversation avec Lou\n"
                "20/08/2026 21:16\n21:16\nVous:\nbonjour\nDistribué\n"
                "Rédigez un message")
        self.assertEqual(_parse_history(body, "Lou"),
                         [{"role": "me", "text": "bonjour"}])


class MatchProfile(unittest.TestCase):
    def setUp(self):
        self.p = _parse_match_profile(LOU_THREAD, "Lou")

    def test_passions(self):
        self.assertEqual(self.p["passions"], ["Randonnée", "Cuisine"])

    def test_bio_first_then_passions(self):
        self.assertTrue(self.p["bio"].startswith("Fan de randonnée"))
        self.assertIn("Passions: Randonnée, Cuisine", self.p["bio"])

    def test_lifestyle(self):
        self.assertEqual(self.p["lifestyle"], {"drinking": "Jamais"})

    def test_distance(self):
        self.assertEqual(self.p["distance_km"], 8)

    def test_no_je_recherche_returns_empty(self):
        self.assertEqual(_parse_match_profile("Matchs\nMessages", "Lou"),
                         {"bio": "", "passions": [], "lifestyle": {},
                          "distance_km": None})


class Capture(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        import platforms.capture as cap
        self.cap = cap
        self.tmp = tempfile.TemporaryDirectory()
        self._old = cap.CAPTURE_DIR
        cap.CAPTURE_DIR = Path(self.tmp.name) / "captures"

    def tearDown(self):
        self.cap.CAPTURE_DIR = self._old
        self.tmp.cleanup()
        import os
        os.environ.pop("CAPTURE", None)

    def test_off_by_default(self):
        self.cap.save_capture("Morgan27")
        self.assertFalse(self.cap.CAPTURE_DIR.exists())

    def test_writes_raw_text_when_enabled(self):
        import os
        os.environ["CAPTURE"] = "1"
        self.cap.save_capture("Morgan27\nRetour")
        files = list(self.cap.CAPTURE_DIR.glob("profile-*.txt"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_text(encoding="utf-8"), "Morgan27\nRetour")
        self.assertNotIn("Morgan", files[0].name)

    def test_never_raises(self):
        import os
        os.environ["CAPTURE"] = "1"
        self.cap.CAPTURE_DIR = self.cap.Path("/proc/nope/captures")
        self.cap.save_capture("x")  # must not raise


class PlatformInterface(unittest.TestCase):
    def test_tinder_implements_platform(self):
        from platforms.base import Platform
        from platforms.tinder import Tinder
        self.assertTrue(issubclass(Tinder, Platform))
        self.assertFalse(Tinder.__abstractmethods__)  # nothing left abstract


if __name__ == "__main__":
    unittest.main(verbosity=2)
