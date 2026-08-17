"""Полнота архива исходов по ЗАКРЫТЫМ дням (карточка #256 → цикл #258).

Почему эта проверка вообще заведена, одной строкой: `outcomes.jsonl` — не
снимок, а append-only архив, и его ВОЗРАСТ ничего не говорит о том, работает ли
запись. День без evidenced-бара производитель сознательно не занимает, поэтому
возрастной бюджет обязан терпеть 31ч ожидания — и ровно столько же он терпит
настоящую остановку. Полнота спрашивает другое и краснеет в первые часы.

Устройство набора (правило класса «сторож отвечает не на тот вопрос»):
  * положительные контроли воспроизводят форму настоящей аварии — закрытый
    evidenced-день без строки;
  * обратные контроли закрепляют ровно те случаи, ради которых бюджет и
    растягивали: сегодняшний незакрытый день · день без evidenced-бара
    (07-19/07-27 fail-closed by design) · дни до появления архива;
  * отдельный обратный контроль на то, что возрастной бюджет B2 НЕ ослаблен:
    две проверки отвечают на два разных вопроса, и обе обязаны остаться.

Время — ВХОД (`now=`) во всех тестах: фиксированы обе стороны сравнения
(и часы, и отметки дней), поэтому набор не протухает от смены календаря.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import loop_retro as lr
from spa_core.monitoring import outcomes_archive as oa

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# FROZEN-DATE-OK: injected-clock — преференция #1 `.claude/rules/deployment.md`:
# часы инъектируются (`now=`) ВМЕСТЕ с фиксированными отметками дней, обе стороны
# сравнения закреплены, и от сдвига календаря тест не зависит. Даты здесь и есть
# предмет проверки: вопрос ровно в том, какой день уже ЗАКРЫТ.
NOW = dt.datetime(2026, 8, 12, 9, 30, tzinfo=dt.timezone.utc)


def _write_tree(tmp: str, *, outcome_days, bars):
    """Мини-дерево: архив исходов + кривая. `bars` — [(дата, evidenced?)]."""
    io_dir = os.path.join(tmp, "data", "investment_os")
    os.makedirs(io_dir, exist_ok=True)
    with open(os.path.join(tmp, oa.OUTCOMES_REL), "w", encoding="utf-8") as f:
        for d in outcome_days:
            f.write(json.dumps({"schema": 1, "date": d, "equity_close": 100000.0}) + "\n")
    daily = []
    for date, evidenced in bars:
        bar = {"date": date, "close_equity": 100000.0, "evidenced": bool(evidenced)}
        if not evidenced:
            # Форма настоящих fail-closed дней трека (07-19 / 07-27): бар есть,
            # живого цикла за ним нет — строки исхода такой день не ждёт.
            bar["source"] = "backfill"
        daily.append(bar)
    with open(os.path.join(tmp, "data", "equity_curve_daily.json"), "w",
              encoding="utf-8") as f:
        json.dump({"daily": daily}, f)


def _days(first: str, last: str):
    a = dt.date.fromisoformat(first)
    b = dt.date.fromisoformat(last)
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


class Completeness(unittest.TestCase):
    """Сама проверка: что она считает дырой, а что — исправным ожиданием."""

    def test_closed_evidenced_day_without_a_line_is_a_hole(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — форма остановки 10.08: цикл в этот день
        отработал (бар evidenced), день ЗАКРЫТ, а строки исхода за него нет."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-07", "2026-08-08",
                                      "2026-08-09", "2026-08-11"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-11")])
            rep = oa.analyze_completeness(tmp, now=NOW)
        self.assertTrue(rep["measured"])
        self.assertFalse(rep["complete"])
        self.assertEqual(rep["missing_days"], ["2026-08-10"])
        self.assertIn("2026-08-10", rep["reason"])

    def test_today_is_not_closed_and_is_never_demanded(self):
        """ОБРАТНЫЙ КОНТРОЛЬ: сегодняшний день ещё может быть дописан своим же
        тактом. Требовать его — та самая ложная тревога, из-за которой
        возрастной бюджет пришлось растягивать."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=_days("2026-08-06", "2026-08-11"),
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-12")])
            rep = oa.analyze_completeness(tmp, now=NOW)
        self.assertTrue(rep["complete"], rep["reason"])
        self.assertNotIn("2026-08-12", rep["missing_days"])

    def test_day_without_an_evidenced_bar_is_not_demanded(self):
        """ОБРАТНЫЙ КОНТРОЛЬ: 07-19 / 07-27 — дни, когда система честно
        отказалась. Строки исхода они не ждут и тревоги давать не должны."""
        bars = [(d, d != "2026-08-09") for d in _days("2026-08-06", "2026-08-11")]
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-07", "2026-08-08",
                                      "2026-08-10", "2026-08-11"],
                        bars=bars)
            rep = oa.analyze_completeness(tmp, now=NOW)
        self.assertTrue(rep["complete"], rep["reason"])
        self.assertEqual(rep["missing_days"], [])

    def test_days_before_the_archive_existed_are_not_demanded(self):
        """ОБРАТНЫЙ КОНТРОЛЬ: трек идёт с 22.06, архив заведён 06.08. Требовать
        от производителя июньские дни значило бы сочинить находку."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=_days("2026-08-06", "2026-08-11"),
                        bars=[(d, True) for d in _days("2026-06-22", "2026-08-11")])
            rep = oa.analyze_completeness(tmp, now=NOW)
        self.assertTrue(rep["complete"], rep["reason"])
        self.assertEqual(rep["anchor_date"], "2026-08-06")

    def test_time_is_an_input_not_the_environment(self):
        """Один и тот же диск даёт РАЗНЫЙ вердикт при разных часах: пока день
        не закрыт — молчим, как только закрылся — дыра названа."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=_days("2026-08-06", "2026-08-10"),
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-11")])
            during = oa.analyze_completeness(
                tmp, now=dt.datetime(2026, 8, 11, 23, 59, tzinfo=dt.timezone.utc))
            after = oa.analyze_completeness(
                tmp, now=dt.datetime(2026, 8, 12, 0, 1, tzinfo=dt.timezone.utc))
        self.assertTrue(during["complete"])
        self.assertEqual(after["missing_days"], ["2026-08-11"])

    def test_empty_archive_is_unmeasured_never_complete(self):
        """fail-CLOSED: якоря нет ⇒ «не измерено» с причиной, и слова «полно»
        в ответе не появляется вовсе."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp, outcome_days=[],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-11")])
            rep = oa.analyze_completeness(tmp, now=NOW)
        self.assertFalse(rep["measured"])
        self.assertNotIn("complete", rep)
        self.assertTrue(rep["reason"])

    def test_unreadable_curve_is_unmeasured_never_complete(self):
        """«Источника правды нет» — это не «дыр нет»: без кривой неизвестно,
        какие дни ОБЯЗАНЫ иметь строку."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp, outcome_days=_days("2026-08-06", "2026-08-11"), bars=[])
            os.remove(os.path.join(tmp, "data", "equity_curve_daily.json"))
            rep = oa.analyze_completeness(tmp, now=NOW)
        self.assertFalse(rep["measured"])
        self.assertNotIn("complete", rep)
        self.assertIn("equity_curve_daily", rep["reason"])

    def test_a_hole_is_seen_while_the_age_budget_still_tolerates(self):
        """ЗАЧЕМ ВСЁ ЭТО, одним числом: дыра видна через полчаса после полуночи,
        когда с последней успешной записи прошло ~24.5ч — то есть возрастной
        бюджет 31ч в этот момент ещё молчит и промолчит ещё почти 7 часов."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=_days("2026-08-06", "2026-08-10"),
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-11")])
            now = dt.datetime(2026, 8, 12, 0, 30, tzinfo=dt.timezone.utc)
            rep = oa.analyze_completeness(tmp, now=now)
        self.assertEqual(rep["missing_days"], ["2026-08-11"])
        # Последняя успешная запись — 10.08 (последний день, за который строка
        # есть); возьмём даже самый поздний момент того дня.
        last_write = dt.datetime(2026, 8, 10, 23, 59, tzinfo=dt.timezone.utc)
        age_h = (now - last_write).total_seconds() / 3600.0
        self.assertLess(age_h, 31.0)


class RetroWiring(unittest.TestCase):
    """У находки обязан быть читатель: ретро → мост (findings_bridge)."""

    def test_incomplete_archive_becomes_a_retro_finding(self):
        comp = {"measured": True, "complete": False,
                "missing_days": ["2026-08-10"], "reason": "…"}
        rep = lr.build_report([], None, None, NOW, outcomes_completeness=comp)
        by_key = {f["key"]: f for f in rep["findings"]}
        self.assertIn("retro:outcomes_incomplete", by_key)
        msg = by_key["retro:outcomes_incomplete"]["message"]
        self.assertIn("2026-08-10", msg)
        # Находка обязана называть, что производитель сам это не догонит —
        # иначе следующий цикл будет ждать самоизлечения, которого не бывает.
        self.assertIn("не догонит", msg)

    def test_complete_archive_emits_no_finding(self):
        comp = {"measured": True, "complete": True, "missing_days": [], "reason": "…"}
        rep = lr.build_report([], None, None, NOW, outcomes_completeness=comp)
        self.assertNotIn("retro:outcomes_incomplete",
                         [f["key"] for f in rep["findings"]])

    def test_unmeasured_completeness_is_unchecked_not_a_finding(self):
        """«Не измерено» не имеет права ни исчезнуть в тишине, ни притвориться
        находкой: пустой архив в свежем дереве — не поломка производителя."""
        comp = {"measured": False, "reason": "архив исходов пуст или отсутствует"}
        rep = lr.build_report([], None, None, NOW, outcomes_completeness=comp)
        self.assertNotIn("retro:outcomes_incomplete",
                         [f["key"] for f in rep["findings"]])
        metrics = [u["metric"] for u in rep["unchecked"]]
        self.assertIn("полнота архива исходов по закрытым дням", metrics)

    def test_report_always_carries_the_block(self):
        """Блок присутствует всегда — иначе «полноту не мерили» и «полно» стали
        бы неразличимы для читателя отчёта."""
        rep = lr.build_report([], None, None, NOW)
        self.assertIn("outcomes_completeness", rep)


class AgeBudgetNotWeakened(unittest.TestCase):
    """ОБРАТНЫЙ КОНТРОЛЬ к самой правке: возрастной бюджет B2 остаётся на месте.

    Соблазн «раз есть полнота, возраст можно ослабить» — это ровно тот обмен,
    который правило класса запрещает: зелёный ответ на свой вопрос не есть
    ответ на нужный, и наоборот.
    """

    def test_manifest_still_declares_an_age_slo_for_the_archive(self):
        man = json.load(open(os.path.join(REPO_ROOT, "architecture", "manifest.json"),
                             encoding="utf-8"))
        art = next(a for a in man["artifacts"]
                   if a["path"] == "data/investment_os/outcomes.jsonl")
        self.assertEqual(art["status"], "active")
        self.assertGreater(float(art["slo_hours"]), 0.0)
        self.assertEqual(float(art["period_hours"]), 24.0)

    def test_completeness_does_not_touch_the_conformance_budget(self):
        """Проверка полноты живёт у производителя и про бюджеты не знает —
        связать их значило бы получить один сторож вместо двух."""
        src = open(oa.__file__, encoding="utf-8").read()
        self.assertNotIn("slo_hours", src)
        self.assertNotIn("architecture_conformance.run", src)


class OfficeStepReadsRetro(unittest.TestCase):
    """Второй читатель — обязательный шаг 0-офис.

    До этой правки `data/loop_retro.json` печатался как «(пусто)»: generic-ветка
    ищет `status`/`reason`, а у ретро их нет. Артефакт числился прочитанным
    (квитанция ставилась), и НИ ОДНА его находка в контекст сессии не попадала —
    тот же fail-OPEN, который в этом файле рецидивировал трижды (#170/#176/#248).

    Снимок ниже — verbatim прод (`data/loop_retro.json`, 2026-08-16T07:03:38Z),
    сокращённый по длине списков: тест, написанный по памяти, повторил бы дефект.
    """

    RETRO_PROD = {
        "generated_at": "2026-08-16T07:03:38.403610+00:00",
        "adr": "ADR-066", "window_days": 14, "analysts": [], "candidates": [],
        "findings": [],
        "verdict_archive": None, "outcomes": None,
        "unchecked": [{"metric": "реализация возможностей (forward evidenced APY)",
                       "reason": "позиции и evidenced-APY копятся в outcomes.jsonl (11 дн.)"}],
        "loop_health_snapshot": None, "ratchet": {"unresolved_agents_now": 0},
    }

    @staticmethod
    def _render(data):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_consume_office_reports_c258",
            os.path.join(REPO_ROOT, "scripts", "consume_office_reports.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return "\n".join(mod._summarize_json(
            "data/loop_retro.json", data,
            now=dt.datetime(2026, 8, 16, 9, 30, tzinfo=dt.timezone.utc),
            root=REPO_ROOT))

    def test_prod_snapshot_is_no_longer_rendered_as_empty(self):
        text = self._render(dict(self.RETRO_PROD))
        self.assertNotIn("(пусто)", text)
        self.assertIn("находок ретро: 0", text)

    def test_retro_findings_reach_the_session_context(self):
        data = dict(self.RETRO_PROD)
        data["findings"] = [{"key": "retro:outcomes_incomplete", "severity": "WARN",
                             "message": "архив исходов неполон: строки нет за 1 день"}]
        text = self._render(data)
        self.assertIn("находок ретро: 1", text)
        self.assertIn("архив исходов неполон", text)
        self.assertIn("[WARN]", text)

    def test_incomplete_archive_is_printed_as_a_judgement(self):
        data = dict(self.RETRO_PROD)
        data["outcomes_completeness"] = {
            "measured": True, "complete": False, "missing_days": ["2026-08-10"],
            "reason": "строк нет за 1 закрыт(ых) evidenced-дн(я/ей): 2026-08-10"}
        text = self._render(data)
        self.assertIn("НЕПОЛОН", text)
        self.assertIn("2026-08-10", text)

    def test_missing_block_is_said_aloud_not_assumed_fine(self):
        """Снимок прода блока ещё не содержит (произведён ДО этой доставки) —
        и шаг обязан сказать «не измерено», а не промолчать утвердительно."""
        text = self._render(dict(self.RETRO_PROD))
        self.assertIn("полнота архива исходов НЕ ИЗМЕРЕНО", text)

    def test_complete_archive_says_so_with_numbers(self):
        data = dict(self.RETRO_PROD)
        data["outcomes_completeness"] = {
            "measured": True, "complete": True, "missing_days": [],
            "expected_days": 10, "anchor_date": "2026-08-06", "reason": "…"}
        text = self._render(data)
        self.assertIn("архив исходов полон", text)
        self.assertIn("2026-08-06", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
