"""Проводка двух сторожей приказа «Portfolio CIO» — измеряется, а не подразумевается.

Оба модуля (`capital_evidence_coverage` — приёмка §5 ТЗ, `pool_identity_collision`
— гэп G1) ничего не гейтят: они МЕРЯЮТ и НАЗЫВАЮТ. Значит вся их польза живёт в
проводке — кто их вызывает и кто читает результат, — и ровно она обычно и
пропадает молча.

Замер этого цикла (#486), сделанный ДО написания файла: у обоих модулей были
зелёные собственные тесты (34 и 26), объявление в `PRODUCES`, запись в манифесте
и ветка в обязательном шаге 0-офис — и при этом **удаление вызова из
`findings_bridge.main` не покрасило НИ ОДНОГО теста набора** (52 passed до
мутации, 52 passed после). Сторож, которого никто не зовёт, пишет отчёт раз в
жизни; артефакт протухает, и об этом говорит только SLO — то есть спустя часы и
чужим голосом.

Проверяется ФОРМА ВЫЗОВА, а не имя в тексте. Строка `import
capital_evidence_coverage` в комментарии или в `PRODUCES` — не вызов; предметом
является `<модуль>.run(...)` внутри тела `main`, то есть то, что действительно
исполнит `com.spa.decision_loop`.

Ветка читателя проверяется ПОВЕДЕНИЕМ: отчёт скармливается настоящему
`_summarize_json`, и в выводе ищется формулировка, которую печатает только
именная ветка. Так тест краснеет и от удаления ветки, и от её вырождения в
общий `else`.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# FROZEN-DATE-OK: injected-clock — NOW уезжает в `_summarize_json(now=)`, а
# отметки отчётов производятся от него же; календарь хоста не участвует.
NOW = dt.datetime(2026, 9, 4, 18, tzinfo=dt.timezone.utc)

SUBJECTS = {
    "capital_evidence_coverage": "data/capital_evidence_coverage.json",
    "pool_identity_collision": "data/pool_identity_collision.json",
}


def _load_office_reader():
    path = os.path.join(REPO_ROOT, "scripts", "consume_office_reports.py")
    spec = importlib.util.spec_from_file_location("_office_reader_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _called_modules_in_main(source: str) -> set[str]:
    """Имена модулей, у которых в теле ``main`` действительно зовут ``.run(...)``."""
    tree = ast.parse(source)
    called: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "main"):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "run"
                and isinstance(sub.func.value, ast.Name)
            ):
                called.add(sub.func.value.id)
    return called


class TestTheDecisionLoopActuallyCallsThem(unittest.TestCase):
    def test_both_guards_are_run_by_the_decision_loop(self):
        source = open(
            os.path.join(REPO_ROOT, "spa_core", "monitoring", "findings_bridge.py"),
            encoding="utf-8",
        ).read()
        called = _called_modules_in_main(source)
        for name in SUBJECTS:
            self.assertIn(
                name,
                called,
                f"{name}.run(...) не зовётся в findings_bridge.main — сторож не "
                f"исполняется агентом com.spa.decision_loop, а его артефакт будет "
                f"молча протухать",
            )

    def test_the_form_of_the_check_is_a_call_not_a_mention(self):
        """Положительный контроль на САМУ мерку: упоминания имени ей мало."""
        mention_only = "def main(argv=None):\n    # capital_evidence_coverage тут только назван\n    pass\n"
        self.assertNotIn("capital_evidence_coverage", _called_modules_in_main(mention_only))


class TestTheOfficeStepReadsThem(unittest.TestCase):
    """Артефакт без обязательного читателя — это отчёт в пустоту (ADR-066, B3)."""

    def test_manifest_declares_both_for_the_orchestrator(self):
        manifest = json.load(
            open(os.path.join(REPO_ROOT, "architecture", "manifest.json"), encoding="utf-8")
        )
        declared = {
            a["path"]: a
            for a in manifest.get("artifacts", [])
            if a.get("status") == "active"
        }
        for rel in SUBJECTS.values():
            self.assertIn(rel, declared, f"{rel} не объявлен active в манифесте")
            self.assertIn(
                "orchestrator_protocol",
                declared[rel].get("consumers") or [],
                f"{rel} объявлен без потребителя orchestrator_protocol — обязательный "
                f"шаг 0-офис его не откроет",
            )

    def test_capital_coverage_has_a_named_branch_not_the_generic_fallback(self):
        mod = _load_office_reader()
        report = {
            "generated_at": NOW.isoformat(),
            "verdict": "UNCHECKED",
            "capital_coverage_pct": 75.0,
            "target_pct": 100.0,
            "baseline_pct": 25.0,
            "deployed_usd": 80000.0,
            "usd": {"evidenced": 60000.0, "literal": 0.0, "unmeasured": 20000.0},
            "by_protocol": [
                {
                    "protocol": "frax",
                    "bucket": "unmeasured",
                    "message": "frax: $20,000 в книге, а записи о провенансе нет вовсе",
                }
            ],
            "adapters_live_pct": 95.0,
            "divergence_pp": 20.0,
            "unchecked": [],
            "history": {"status": "OK", "books_measured": 2, "coverage_pct_min": 75.0,
                        "coverage_pct_max": 100.0, "window_truncated": False,
                        "covered_days": 30.0, "window_days": 30.0, "books_unmeasured": 0},
        }
        text = "\n".join(
            mod._summarize_json("data/capital_evidence_coverage.json", report, now=NOW)
        )
        self.assertIn("доля КАПИТАЛА", text)
        # Число-двойник обязано звучать РЯДОМ: пока оба равны 100 %, подмену не видно.
        self.assertIn("ДРУГОЙ вопрос", text)
        # Неизмеренный доллар называется поимённо, а не растворяется в «не 100 %».
        self.assertIn("frax", text)

    def test_pool_identity_has_a_named_branch_not_the_generic_fallback(self):
        mod = _load_office_reader()
        report = {
            "generated_at": NOW.isoformat(),
            "overall": "CRITICAL",
            "counts": {"critical": 1, "warn": 0, "info": 0, "unchecked": 0},
            "keys_compared": ["fluid_usdc", "fluid_fusdc"],
            "collisions": [
                {
                    "severity": "CRITICAL",
                    "message": "fluid_fusdc + fluid_usdc: ключи ранжируются на ОДНОМ пуле",
                }
            ],
            "unreachable_refusals": [],
            "findings": [],
            "unchecked": [],
        }
        text = "\n".join(
            mod._summarize_json("data/pool_identity_collision.json", report, now=NOW)
        )
        self.assertIn("тождество пулов", text)
        self.assertIn("ОДНОМ пуле", text)


if __name__ == "__main__":
    unittest.main()
