"""Offline tests for tools/android_probe.py. The UI dump below follows the
format `uiautomator dump` writes (including adb's trailing status line); it is
a synthetic sample of the Android format, not a capture of any dating app."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "tools"))
import android_probe  # noqa: E402

DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" content-desc="" clickable="false" bounds="[0,0][1080,2400]">
    <node index="0" text="Marie, 28" resource-id="app:id/name" class="android.widget.TextView" content-desc="" clickable="false" bounds="[40,1800][600,1880]" />
    <node index="1" text="" resource-id="app:id/like" class="android.widget.ImageButton" content-desc="Like" clickable="true" bounds="[700,2000][900,2200]" />
    <node index="2" text="   " resource-id="" class="android.view.View" content-desc="" clickable="false" bounds="[0,0][1,1]" />
  </node>
</hierarchy>
UI hierchary dumped to: /dev/tty"""


class ParseUiDump(unittest.TestCase):
    def test_keeps_only_nodes_with_text_or_description(self):
        nodes = android_probe.parse_ui_dump(DUMP)
        self.assertEqual([n["text"] or n["desc"] for n in nodes],
                         ["Marie, 28", "Like"])

    def test_fields(self):
        like = android_probe.parse_ui_dump(DUMP)[1]
        self.assertEqual(like["id"], "app:id/like")
        self.assertTrue(like["clickable"])
        self.assertEqual(like["bounds"], "[700,2000][900,2200]")

    def test_ignores_adb_trailer(self):
        self.assertEqual(len(android_probe.parse_ui_dump(DUMP)), 2)

    def test_empty_or_garbage_input(self):
        self.assertEqual(android_probe.parse_ui_dump(""), [])
        self.assertEqual(android_probe.parse_ui_dump("ERROR: null root"), [])


class ReadOnly(unittest.TestCase):
    def test_only_read_only_adb_commands(self):
        src = (Path(__file__).parent / "tools" / "android_probe.py").read_text()
        for forbidden in ('"input"', '"tap"', '"swipe"', '"install"',
                          '"keyevent"', '"push"'):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
