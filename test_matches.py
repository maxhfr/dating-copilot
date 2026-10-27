"""Like -> match conversion: baseline, counting, attribution and statistics.

    python test_matches.py

Uses a throwaway run-log database. No network, no browser.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, "src")
_HOME = tempfile.TemporaryDirectory()
os.environ["DATING_COPILOT_HOME"] = _HOME.name

import runlog  # noqa: E402


def like(name, score=70, ts_offset=0.0, decision="like"):
    """Insert a profile row dated `ts_offset` seconds from now."""
    sid = runlog.start_session("tinder")
    runlog.log_profile(sid, "tinder", {"name": name, "age": 28},
                       {"score": score, "stage": 2, "like": decision == "like", "why": ""})
    if ts_offset:
        with runlog._db() as con:
            con.execute("UPDATE profiles SET ts = ts + ? WHERE id = (SELECT MAX(id) FROM profiles)",
                        (ts_offset,))


def tiles(*pairs):
    return [{"id": i, "name": n} for i, n in pairs]


class MatchTests(unittest.TestCase):
    def setUp(self):
        db = runlog.home() / "runlog.db"
        if db.exists():
            db.unlink()

    def test_not_tracking_until_first_snapshot(self):
        c = runlog.conversion_stats()
        self.assertFalse(c["tracking"])
        self.assertIsNone(c["rate"])

    def test_first_snapshot_is_a_baseline_and_counts_nothing(self):
        r = runlog.record_match_snapshot("tinder", tiles(("a1", "Marine"), ("a2", "Clara")))
        self.assertEqual(r, {"baseline": True, "new": 0, "seen": 2})
        c = runlog.conversion_stats()
        self.assertTrue(c["tracking"])
        self.assertEqual(c["matches"], 0)
        self.assertEqual(c["visible_matches"], 2)

    def test_new_matches_counted_once_and_never_the_baseline(self):
        runlog.record_match_snapshot("tinder", tiles(("a1", "Marine")))
        r = runlog.record_match_snapshot("tinder", tiles(("a1", "Marine"), ("b1", "Lou")))
        self.assertEqual((r["baseline"], r["new"]), (False, 1))
        r = runlog.record_match_snapshot("tinder", tiles(("a1", "Marine"), ("b1", "Lou")))
        self.assertEqual(r["new"], 0)                       # same ids again
        self.assertEqual(runlog.conversion_stats()["matches"], 1)

    def test_baseline_with_no_matches_still_counts_the_first_real_one(self):
        runlog.record_match_snapshot("tinder", [])
        r = runlog.record_match_snapshot("tinder", tiles(("n1", "Iris")))
        self.assertEqual(r["new"], 1)
        self.assertEqual(runlog.conversion_stats()["matches"], 1)

    def test_likes_before_tracking_are_not_in_the_rate(self):
        like("Old", ts_offset=-3600)
        runlog.record_match_snapshot("tinder", [])
        like("Iris")
        like("Zoe")
        runlog.record_match_snapshot("tinder", tiles(("n1", "Iris")))
        c = runlog.conversion_stats()
        self.assertEqual((c["likes"], c["matches"], c["rate"]), (2, 1, 0.5))

    def test_passes_do_not_count_as_likes(self):
        runlog.record_match_snapshot("tinder", [])
        like("Iris")
        like("Nope", decision="pass")
        self.assertEqual(runlog.conversion_stats()["likes"], 1)

    def test_attribution_ignores_accents_and_case(self):
        runlog.record_match_snapshot("tinder", [])
        like("Léa-marie", score=72)
        runlog.record_match_snapshot("tinder", tiles(("m1", "LEA-MARIE")))
        bands = runlog.conversion_stats()["bands"]
        self.assertEqual([(b["from"], b["likes"], b["matches"]) for b in bands], [(70, 1, 1)])

    def test_a_like_is_credited_only_once(self):
        runlog.record_match_snapshot("tinder", [])
        like("Alice", score=61)
        runlog.record_match_snapshot("tinder", tiles(("m1", "Alice"), ("m2", "Alice")))
        c = runlog.conversion_stats()
        self.assertEqual(c["matches"], 2)                    # two real matches...
        self.assertEqual(sum(b["matches"] for b in c["bands"]), 1)   # ...one attributed

    def test_unattributable_match_counts_overall_but_not_in_a_band(self):
        runlog.record_match_snapshot("tinder", [])
        like("Alice", score=66)
        runlog.record_match_snapshot("tinder", tiles(("x1", "Stranger")))
        c = runlog.conversion_stats()
        self.assertEqual(c["matches"], 1)
        self.assertEqual(sum(b["matches"] for b in c["bands"]), 0)

    def test_old_likes_outside_the_window_are_not_credited(self):
        runlog.record_match_snapshot("tinder", [])
        like("Alice", score=66, ts_offset=-40 * 86400)
        runlog.record_match_snapshot("tinder", tiles(("x1", "Alice")))
        self.assertEqual(sum(b["matches"] for b in runlog.conversion_stats()["bands"]), 0)

    def test_bands_are_sorted_high_to_low_with_rates(self):
        runlog.record_match_snapshot("tinder", [])
        for n, s in (("A", 66), ("B", 67), ("C", 74), ("D", 91)):
            like(n, score=s)
        runlog.record_match_snapshot("tinder", tiles(("m1", "C")))
        bands = runlog.conversion_stats()["bands"]
        self.assertEqual([b["from"] for b in bands], [90, 70, 60])
        by = {b["from"]: b for b in bands}
        self.assertEqual((by[70]["likes"], by[70]["matches"], by[70]["rate"]), (1, 1, 1.0))
        self.assertEqual((by[60]["likes"], by[60]["matches"], by[60]["rate"]), (2, 0, 0.0))

    def test_perfect_score_goes_in_the_top_band(self):
        runlog.record_match_snapshot("tinder", [])
        like("Top", score=100)
        self.assertEqual(runlog.conversion_stats()["bands"][0]["from"], 90)

    def test_last_seven_days(self):
        runlog.record_match_snapshot("tinder", [])
        like("Recent")
        runlog.record_match_snapshot("tinder", tiles(("m1", "Recent")))
        c = runlog.conversion_stats()
        self.assertEqual((c["last7"]["likes"], c["last7"]["matches"]), (1, 1))

    def test_snapshot_ignores_entries_without_an_id(self):
        runlog.record_match_snapshot("tinder", [])
        r = runlog.record_match_snapshot("tinder", [{"id": "", "name": "x"}, {"name": "y"}])
        self.assertEqual(r["new"], 0)

    def test_platforms_are_tracked_separately(self):
        runlog.record_match_snapshot("tinder", [])
        self.assertFalse(runlog.conversion_stats("hinge")["tracking"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
