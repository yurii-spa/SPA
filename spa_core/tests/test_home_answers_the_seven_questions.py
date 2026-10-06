"""spa_core/tests/test_home_answers_the_seven_questions.py — Director OS v2 (ADR-571, WP2).

Automates the deterministic half of the design's 30-second comprehension script (§5): for the
fixture scene (spa_core/tests/fixtures/mission_truth_scene.json), the text app.js would render
for Главная must already contain the answer to each of the seven questions, without opening any
"Доказательства" drawer.

Two of the seven answers (#1 the money chip, #7 the same-host attention line) are composed by
app.js from a copy-deck TEMPLATE (MC_I18N.tf) rather than shown verbatim, so this test ports that
one small, pure substitution rule to Python and runs it against the exact same template strings
app.js uses (read straight out of i18n.js's dictionary, not re-typed here) — it is not a second,
independently-invented copy of the wording. The other five answers are cell-level display_ru
sentences that app.js shows byte-for-byte (see TestEvidenceIsTheOnlyDrawer /
test_mission_ui_static.py for the structural proof that this is really what gets rendered), so
the test reads them straight from the fixture.

This is the DETERMINISTIC, no-browser half of §5's acceptance. Visual/responsive verification
(no horizontal scroll, tap targets, one-scroll budget at 375/390/430px) still needs an actual
browser pass by the integrator — this file does not attempt to fake a DOM or a viewport.
"""
import json
import re
import unittest
from pathlib import Path

UI_DIR = Path(__file__).resolve().parents[2] / "spa_core" / "studio_os" / "mission_ui"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "mission_truth_scene.json"


def _i18n_dict():
    js = (UI_DIR / "i18n.js").read_text(encoding="utf-8")
    m = re.search(r"/\*I18N_START\*/(.*?)/\*I18N_END\*/", js, re.S)
    return json.loads(m.group(1))


def _tf(dict_, key, lang, **vars_):
    """Mirrors window.MC_I18N.tf(key, vars) in app.js: plain {name} substitution, nothing else."""
    s = dict_[lang][key]
    # Mirrors i18n.js tf(): a missing/None value renders «не измерено», never "" (inv #17).
    return re.sub(r"\{(\w+)\}", lambda m: ("не измерено" if vars_.get(m.group(1)) is None else str(vars_.get(m.group(1)))), s)


class TestHomeAnswersTheSevenQuestions(unittest.TestCase):
    def setUp(self):
        self.scene = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.deck = _i18n_dict()
        self.strip = {tile["key"]: tile for tile in self.scene["home"]["strip"]}

    def _tile_text(self, key):
        tile = self.strip[key]
        self.assertEqual(tile["state"], "MEASURED", f"fixture tile {key!r} must be MEASURED for this script")
        return tile["display_ru"]

    def test_q1_real_money_chip(self):
        mc = self.scene["home"]["money_chip"]
        text = _tf(self.deck, "header.money_chip", "ru", usd="$" + str(mc["usd"]))
        self.assertIn("$0", text)
        self.assertIn("не разрешены", text)

    def test_q2_something_broken_names_it_in_words(self):
        text = self._tile_text("system")
        self.assertIn("novel_edge_rnd", text)
        self.assertIn("исследование новых идей", text)

    def test_q3_rate_window_and_drawdown_together(self):
        text = self._tile_text("yield")
        self.assertIn("4,9", text)
        self.assertIn("%", text)
        self.assertIn("−0,04", text)  # worst drawdown, inv. #8: never shown apart from the rate
        self.assertIn("опится", text)  # "...копится.../Копится..." — Balanced/Aggressive note, same tile

    def test_q4_site_fresh_and_honest_yes_no_plus_date(self):
        text = self._tile_text("product")
        self.assertIn("да", text)
        self.assertIn("01.10", text)

    def test_q5_what_claude_is_doing_and_whether_stuck(self):
        text = self._tile_text("claude")
        self.assertIn("RM-TRUTH-01", text)
        self.assertIn("карточка", text)
        self.assertIn("стадия", text)
        self.assertIn("блокер", text)

    def test_q6_what_is_needed_from_owner_and_how_much(self):
        text = self._tile_text("needs")
        self.assertIn("ваших вопросов", text)
        self.assertIn("0", text)
        self.assertIn("тема не объявлена", text)
        self.assertIn("11", text)

    def test_q7_off_mac_copy_in_one_tap(self):
        att = self.scene["home"]["attention"]
        same_host = next(a for a in att if a["kind"] == "same_host")
        text = self.deck["ru"]["home.attention.same_host"]
        self.assertIn("копия на том же диске", text)
        self.assertEqual(same_host["kind"], "same_host")  # the fixture actually surfaces this line


if __name__ == "__main__":
    unittest.main()
