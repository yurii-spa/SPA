"""Разбор семи сирот храповика (#248): по каждому решению — след, а не намерение.

Цикл #228 снял три слепоты сканера (докстринг · однофамилец · подстрочная коллизия), и
семь скриптов, всё это время числившихся подключёнными, остались без единого вызывающего.
Дописать их в `unwired_scripts_baseline.json` запрещено самим храповиком, поэтому каждый
разобран поштучно. Здесь закреплены следы — так, чтобы решение нельзя было тихо откатить:

| скрипт | вердикт | что стережёт этот файл |
|---|---|---|
| `day30_review` | СПИСАН | логика зовётся циклом; удалённый вход ничего не добавлял |
| `run_stress_tests` | СПИСАН | писал ЧУЖОЙ артефакт в НЕСОВМЕСТИМОЙ форме — запуск ВРЕДИЛ |
| `ots_anchor` | ПОДКЛЮЧЁН | шаг дневного цикла (обещание ADR-YL-010, не выполнявшееся 43 дня) |
| `perf_budget` | ПОДКЛЮЧЁН | отдельный workflow (вместе с `dfb_perf_budget`) |
| `smoke_test_flagship` | ПОДКЛЮЧЁН | недельный агент (установка — владельца) |
| `reap_stale_worktrees` | КЛАСС | команда протокола цикла — `test_unwired_two_new_classes` |
| `audit_tier_c_wiring_feasibility` | КЛАСС | генератор живого продукта — там же |

Тесты классов — в `test_unwired_two_new_classes.py`; здесь только два списания и три
проводки.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _uncommented(text: str) -> str:
    """Строки shell/yaml без комментариев — упоминание в комментарии вызовом не является."""
    return "\n".join(
        line.split("#", 1)[0] for line in text.splitlines() if line.split("#", 1)[0].strip()
    )


# ───────────────────────────────────────────────────────────────────────────────
# 1. day30_review — СПИСАН: класс схлопнулся в дневной цикл
# ───────────────────────────────────────────────────────────────────────────────
class TestDay30ReviewCollapsedIntoTheCycle(unittest.TestCase):
    """Три независимых следа смерти входа `scripts/day30_review.py` (образец #227).

    1. вызывающего нет — это и сказал храповик 15.08;
    2. ЛОГИКА исполняется каждый цикл: `cycle_runner` шаг 2.1c зовёт
       `spa_core.riskwire.day30_review.write_review`;
    3. равноценный вход остался: у модуля есть свой `main()` под `__main__`,
       то есть `python3 -m spa_core.riskwire.day30_review` делает ровно то же.

    Мёртв был только дубль входа, а не обзор WS1.3.
    """

    def test_the_script_entrypoint_is_gone(self):
        self.assertFalse((_ROOT / "scripts" / "day30_review.py").exists(),
                         "вход-дубль вернулся — либо подключи его, либо он снова сирота")

    def test_the_cycle_still_produces_the_review(self):
        src = (_ROOT / "spa_core" / "paper_trading" / "cycle_runner.py").read_text(encoding="utf-8")
        self.assertIn("from spa_core.riskwire import day30_review", src)
        self.assertIn("write_review(", src)

    def test_the_module_keeps_its_own_cli(self):
        src = (_ROOT / "spa_core" / "riskwire" / "day30_review.py").read_text(encoding="utf-8")
        self.assertIn("def main(", src)
        self.assertIn('__name__ == "__main__"', src)


# ───────────────────────────────────────────────────────────────────────────────
# 2. run_stress_tests — СПИСАН: запуск ВРЕДИЛ (чужой артефакт, чужая форма)
# ───────────────────────────────────────────────────────────────────────────────
class TestRunStressTestsWasHarmful(unittest.TestCase):
    """`data/stress_test_results.json` — артефакт с ДВУМЯ производителями и одним читателем.

    Читает его `spa_core/reporting/tear_sheet_html.py::_build_stress_section`, и читает он
    форму ЖИВОГО производителя `spa_core/risk/stress_tester.py`: ``scenarios`` — СПИСОК
    записей `{scenario, impact_usd, impact_pct}`. Удалённый скрипт писал в тот же файл
    ``scenarios`` СЛОВАРЁМ `{id: {...}}` и с другими ключами. Тест ниже прогоняет обе формы
    через настоящего читателя: живая читается, форма скрипта — нет.

    Это тот же класс, что `daily_paper_report` (#227): не «просто не вызывается», а «вызвать
    нельзя — станет хуже».
    """

    def setUp(self):
        import importlib
        self.mod = importlib.import_module("spa_core.reporting.tear_sheet_html")

    def _section(self, stress_data):
        cls = getattr(self.mod, "TearSheetGenerator", None) or getattr(self.mod, "TearSheet")
        gen = cls.__new__(cls)
        return cls._build_stress_section(gen, {}, stress_data)

    def test_the_live_producer_shape_is_readable(self):
        live = {"scenarios": [
            {"scenario": "USDC Depeg 2023", "impact_usd": -1234.5, "impact_pct": -1.23},
        ]}
        rows = self._section(live)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "USDC Depeg 2023")

    def test_the_deleted_scripts_shape_is_NOT_readable(self):
        """Положительный контроль: форма списанного скрипта у читателя не проходит."""
        script_shape = {"generated_at": "2026-08-15T00:00:00Z", "scenarios": {
            "LUNA_2022": {"scenario_id": "LUNA_2022", "final_value": 1.0},
        }, "summary": "..."}
        with self.assertRaises(AttributeError):
            self._section(script_shape)

    def test_the_script_entrypoint_is_gone(self):
        self.assertFalse((_ROOT / "scripts" / "run_stress_tests.py").exists())


# ───────────────────────────────────────────────────────────────────────────────
# 3. ots_anchor — ПОДКЛЮЧЁН: обещание ADR-YL-010 наконец исполняется
# ───────────────────────────────────────────────────────────────────────────────
class TestOtsAnchorIsScheduled(unittest.TestCase):
    """ADR-YL-010 (03.07): «Daily agent runs ``python3 scripts/ots_anchor.py both``».

    Замер 15.08: `proofs/ots/ots_anchors.jsonl` — ОДНА строка, от 2026-07-02T22:46Z, со
    статусом `pending`; ни одного якорения за 43 дня и ни одного `ots_upgrade`. Обещание
    ADR не выполнялось, потому что «daily agent» не существовал: у `scripts/ots_anchor.py`
    не было ни plist'а, ни строки в цикле, а `spa_core/audit/ots_anchor.py` импортировал
    ровно один файл — сам этот скрипт.

    Здесь закреплено, что шаг живёт в каноническом раннере дневного цикла (там же, где
    #Q3-2 поселил fleet-parity — «флот не обязан расти на одного, чтобы себя же сторожить»),
    и что он НЕ-ФАТАЛЕН: якорение не имеет права уронить трек.
    """

    def setUp(self):
        self.sh = (_ROOT / "scripts" / "run_daily_paper_cycle.sh").read_text(encoding="utf-8")
        self.code = _uncommented(self.sh)

    def test_the_daily_cycle_invokes_the_anchor(self):
        self.assertIn("scripts/ots_anchor.py", self.code,
                      "шаг якорения пропал из дневного цикла — ADR-YL-010 снова не исполняется")
        self.assertIn("both", self.code)

    def test_the_anchor_step_cannot_fail_the_cycle(self):
        """Не-фатальность — часть решения: аудит-слой не двигает капитал и не гейтит трек."""
        idx = self.code.index("scripts/ots_anchor.py")
        tail = self.code[idx:idx + 400]
        self.assertTrue("|| true" in tail or "|| echo" in tail or "set +e" in tail,
                        "шаг якорения обязан быть не-фатальным для цикла")

    def test_the_anchor_runs_after_the_track_advances(self):
        """Порядок обязателен: якорить надо СВЕЖУЮ голову цепи, а не вчерашнюю."""
        self.assertLess(self.code.index("cycle_runner"), self.code.index("scripts/ots_anchor.py"))


# ───────────────────────────────────────────────────────────────────────────────
# 4. perf_budget (+ dfb_perf_budget) — ПОДКЛЮЧЕНЫ отдельным workflow
# ───────────────────────────────────────────────────────────────────────────────
class TestPerfBudgetGatesAreWired(unittest.TestCase):
    """Два perf-гейта money-path были написаны и не запускались НИКОГДА.

    `perf_budget` числился подключённым по подстрочной коллизии с `dfb_perf_budget`
    (#228 её закрыл), а `dfb_perf_budget` лежал в базе храповика с #214. Первый честный
    прогон 15.08 сразу дал находку: surface `cycle` — median 3537 ms против бюджета
    1500 ms. Именно это и означает «гейт без вызывающего»: регрессия могла приехать
    когда угодно, и никто бы не узнал.
    """

    def setUp(self):
        p = _ROOT / ".github" / "workflows" / "perf-budget.yml"
        self.assertTrue(p.is_file(), "workflow perf-budget.yml пропал — гейты снова никто не зовёт")
        self.wf = _uncommented(p.read_text(encoding="utf-8"))

    def test_both_perf_gates_are_invoked(self):
        self.assertIn("scripts/perf_budget.py", self.wf)
        self.assertIn("scripts/dfb_perf_budget.py", self.wf)

    def test_the_gate_is_not_silenced(self):
        """Гейт не имеет права быть декоративным: ни continue-on-error, ни `|| true` на замере.

        (`|| true` допустим на установке тест-зависимостей — их отсутствие харнесс обрабатывает
        сам, честно скипая api-строки; глушить нельзя именно ЗАМЕР.)
        """
        self.assertNotIn("continue-on-error", self.wf)
        for line in self.wf.splitlines():
            if "perf_budget.py" in line and "paths" not in line:
                self.assertNotIn("||", line, f"замер заглушён: {line.strip()}")


# ───────────────────────────────────────────────────────────────────────────────
# 5. smoke_test_flagship — ПОДКЛЮЧЁН недельным агентом (установка — владельца)
# ───────────────────────────────────────────────────────────────────────────────
class TestFlagshipSmokeHasAnAgent(unittest.TestCase):
    """Тяжёлый смоук может исполняться ТОЛЬКО на хосте — это измерено, а не предположено.

    Прогон 15.08 в чистом дереве: 5 отказов из 5. Причина не в смоуке —
    `git ls-files data/rates_desk` = 0 (живые артефакты не в git) и нет `landing/node_modules`.
    Значит «команда, которую запускает CI» в CI неисполнима в принципе, а «команда,
    которую запускает владелец» не запускалась никем. Отсюда plist + обёртка + строка
    установщика; `launchctl` — действие владельца (правило деплоя, п. 6).
    """

    def test_wrapper_and_plist_agree_on_the_script(self):
        wrapper = _ROOT / "scripts" / "agent_smoke_flagship.sh"
        plist = _ROOT / "launchd" / "com.spa.smoke_flagship.plist"
        self.assertTrue(wrapper.is_file() and plist.is_file())
        self.assertIn("scripts/smoke_test_flagship.py",
                      _uncommented(wrapper.read_text(encoding="utf-8")))
        self.assertIn("agent_smoke_flagship.sh", plist.read_text(encoding="utf-8"))

    def test_the_installer_declares_the_label(self):
        """Иначе fleet-parity честно назовёт plist сиротой (`orphan`) — новая ложная находка."""
        inst = (_ROOT / "scripts" / "install_all_agents.sh").read_text(encoding="utf-8")
        self.assertIn("com.spa.smoke_flagship", inst)

    def test_the_agent_logs_outside_documents(self):
        """`~/Documents` под launchd = exit 78 (инвариант #12)."""
        import plistlib
        p = (_ROOT / "launchd" / "com.spa.smoke_flagship.plist").read_bytes()
        doc = plistlib.loads(p)
        for tag in ("StandardOutPath", "StandardErrorPath"):
            self.assertIn(tag, doc, f"{tag} не объявлен — молчащий агент неотличим от мёртвого")
            self.assertTrue(doc[tag].startswith("/tmp/"),
                            f"{tag}={doc[tag]} — launchd в ~/Documents пишет не может (exit 78)")
        # Значение, а не наличие ключа: `<false/>` у RunAtLoad читается как «не при загрузке»
        # (капкан plist'ов, закреплённый правилом деплоя).
        self.assertIs(doc.get("RunAtLoad"), False,
                      "недельный тяжёлый смоук не должен стартовать при каждой загрузке")
        self.assertEqual(doc.get("StartInterval"), 604800)


# ───────────────────────────────────────────────────────────────────────────────
# 6. База храповика не выросла — половина работы, ради которой всё затевалось
# ───────────────────────────────────────────────────────────────────────────────
class TestTheBaselineDidNotGrow(unittest.TestCase):

    def test_none_of_the_seven_was_added_to_the_baseline(self):
        base = set(json.loads(
            (_ROOT / "spa_core" / "tests" / "unwired_scripts_baseline.json")
            .read_text(encoding="utf-8"))["scripts"])
        seven = {"audit_tier_c_wiring_feasibility", "day30_review", "ots_anchor",
                 "perf_budget", "reap_stale_worktrees", "run_stress_tests",
                 "smoke_test_flagship"}
        self.assertEqual(base & seven, set(),
                         "имя из семёрки дописано в базу — это ровно тот запрещённый способ "
                         "покрасить храповик, ради запрета которого он и написан")


if __name__ == "__main__":
    unittest.main()
