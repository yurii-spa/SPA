#!/usr/bin/env python3
"""Тесты генератора реестра зрелости (scripts/build_maturity_register.py).

**Положительный контроль обязателен** (`.claude/rules/deployment.md`): проверка,
никогда не видевшая настоящей поломки, — украшение. Здесь каждый тест
воспроизводит аварию, случившуюся при постройке реестра 2026-08-20:

  1. **Самоссылка.** Генератор держит все ключевые слова в таблице `SUBJECTS`,
     поэтому grep находил ЕГО САМОГО и «кода нет» превращалось в «1 файл» —
     для КАЖДОГО непостроенного слоя разом. Девять L2 читались как L3, то есть
     реестр врал ровно в том, ради чего написан.
  2. **Код без применения.** Валидатор карточек покрыт тестом, карточек ноль.
     Правило «код + тесты = L4» называло это «работает внутри процесса».
  3. **Дрейф файла.** `--check` обязан краснеть, когда `MATURITY_REGISTER.md`
     разошёлся с замером, и не краснеть из-за одной лишь отметки времени.

Только stdlib. Оффлайн: сеть не трогается, реальный `docs/` не переписывается.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "build_maturity_register.py"


def _load():
    spec = importlib.util.spec_from_file_location("_mreg", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSelfReferenceExcluded(unittest.TestCase):
    """Авария 1: генератор находил сам себя."""

    def test_generator_never_counts_as_implementation(self):
        mod = _load()
        # Ключевые слова непостроенных слоёв присутствуют в самом генераторе:
        # он обязан вычесть себя, иначе замер «0» невозможен в принципе.
        for pattern in ("builder_os", "investment_committee", "strategy_discovery"):
            hits = mod._rg(pattern, mod.CODE_ROOTS)
            self.assertNotIn(
                str(_SCRIPT), [str(Path(h).resolve()) for h in hits],
                f"генератор посчитал сам себя реализацией для {pattern!r}",
            )

    def test_unbuilt_layers_measure_zero_code(self):
        """Мутация: убрать фильтр self — и этот тест краснеет."""
        mod = _load()
        agents = mod._load_agents()
        by_key = {s["key"]: s for s in mod.SUBJECTS}
        for key in ("builder_os", "committee", "discovery", "btc_cycle", "eth_yield"):
            m = mod.measure(by_key[key], agents)
            self.assertEqual(m["code"], 0, f"{key}: ожидали 0 файлов кода, получили {m['code']}")
            self.assertEqual(m["level"], 2, f"{key}: непостроенный слой обязан быть L2")


class TestCodeWithoutData(unittest.TestCase):
    """Авария 2: код с тестами, но без данных, объявлялся работающим."""

    def test_declared_data_glob_with_zero_matches_caps_level(self):
        mod = _load()
        subject = dict(key="_t", name="t", docs=["x.md"],
                       paths=["spa_core/utils/atomic.py"], keywords="",
                       agents="", data_glob=["data/__never_exists__/*.json"])
        m = mod.measure(subject, [])
        self.assertEqual(m["data"], 0)
        self.assertLessEqual(m["level"], 3,
                             "функция, не производящая данных, не может быть L4+")

    def test_without_data_glob_the_cap_does_not_fire(self):
        """Обратный контроль: правило не должно занижать всё подряд."""
        mod = _load()
        subject = dict(key="_t", name="t", docs=["x.md"],
                       paths=["spa_core/governance/kill_switch.py",
                              "spa_core/tests/test_kill_switch.py"],
                       keywords="", agents="")
        m = mod.measure(subject, [])
        self.assertFalse(m["has_data_check"])
        self.assertGreaterEqual(m["level"], 4)


class TestCheckMode(unittest.TestCase):
    """Авария 3: файл разошёлся с замером и об этом никто не сказал."""

    def test_check_passes_on_freshly_generated_file(self):
        res = subprocess.run([sys.executable, str(_SCRIPT), "--check"],
                             capture_output=True, text=True, timeout=300, cwd=str(_REPO))
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_check_fails_when_a_level_is_overstated(self):
        """Смысловая ложь: непостроенный слой записан как построенный."""
        mod = _load()
        text = mod.build()
        faked = text.replace("(лестница по фазам)**<br/><sub>", "(лестница по фазам)**<br/><sub>", 1)
        # поднимаем BTC с L2 на L5 — ровно то, ради чего сторож существует
        faked = re.sub(r"(\*\*BTC capital cycle[^|]*\|) L2 \|", r"\1 L5 |", faked)
        self.assertNotEqual(faked, text, "подделка не применилась — тест бессмыслен")
        self.assertNotEqual(mod._levels(faked), mod._levels(text))

    def test_counter_drift_alone_is_not_drift(self):
        """Иначе сторож краснел бы на КАЖДОМ коммите и его бы отключили.

        Число файлов кода меняется от любой правки репозитория; уровень — нет.
        Сверяется только уровень.
        """
        mod = _load()
        text = mod.build()
        churned = re.sub(r"\| (\d+) \| (\d+) \|", r"| 999 | 998 |", text)
        self.assertNotEqual(churned, text, "подделка не применилась — тест бессмыслен")
        self.assertEqual(mod._levels(churned), mod._levels(text))

    def test_timestamp_alone_is_not_drift(self):
        mod = _load()
        a = mod.build()
        b = a.replace("замер от **2026", "замер от **2030")
        self.assertEqual(mod._levels(a), mod._levels(b))


class TestHonestSeparation(unittest.TestCase):
    """Замер и суждение не смешиваются — иначе мнение читается как измерение."""

    def test_every_subject_has_a_judgment(self):
        mod = _load()
        missing = [s["key"] for s in mod.SUBJECTS if s["key"] not in mod.JUDGMENT]
        self.assertEqual(missing, [], f"без суждения: {missing}")

    def test_judgment_never_supplies_measured_fields(self):
        mod = _load()
        measured = {"code", "tests", "live", "level", "data"}
        for key, j in mod.JUDGMENT.items():
            self.assertEqual(measured & set(j), set(),
                             f"{key}: суждение подменяет замер {measured & set(j)}")


class TestFindingsFromAdversarialReview(unittest.TestCase):
    """Пять дефектов, найденных состязательным разбором 2026-08-20.

    Все пять — одного рода: колонка, объявленная ЗАМЕРОМ («соврать не может»),
    врала. Это ровно то, ради чего реестр написан, поэтому каждый закрыт
    проверкой, а не правкой текста.
    """

    def test_agent_pattern_matches_label_without_com_spa_prefix(self):
        """Авария: `^io_` не совпадал НИ С ЧЕМ — все метки начинаются с com.spa.

        Реестр печатал «живых агентов: 0» по продуктовому слою, у которого их
        тринадцать, и противоречил собственному же разделу ниже.
        """
        mod = _load()
        agents = [{"label": "com.spa.io_quant", "intent": "active"},
                  {"label": "com.spa.io_health", "intent": "retired"},
                  {"label": "com.spa.telegram_bot", "intent": "active"}]
        self.assertEqual(mod._agent_matches(r"^io_", agents), ["com.spa.io_quant"])

    def test_live_io_agents_are_actually_counted(self):
        """Замер на настоящем манифесте: продуктовый слой не может быть пустым."""
        mod = _load()
        live = mod._agent_matches(r"^io_", mod._load_agents())
        self.assertGreater(len(live), 0, "io_*-агенты снова не находятся")

    def test_keyword_mentions_do_not_raise_the_level(self):
        """Авария: одно случайное вхождение подстроки давало L2 → L3.

        `external_capital` находился как ключ JSON-отчёта, `two_layer` — как имя
        файла в списке путей пушера. Оба слоя печатались как «код есть».
        """
        mod = _load()
        subject = dict(key="_t", name="t", docs=["00_index.md"], paths=[],
                       keywords=r"atomic_save", agents="")
        m = mod.measure(subject, [])
        self.assertGreater(m["mentions"], 0, "проверка бессмысленна без упоминаний")
        self.assertEqual(m["code"], 0)
        self.assertEqual(m["level"], 2, "упоминание — не реализация")

    def test_every_referenced_doc_exists(self):
        """Авария: ссылка на `ADR-069-telegram-owner-workspace.md`, которого нет."""
        mod = _load()
        self.assertEqual(mod._check_doc_refs(), [])

    def test_data_glob_counts_only_tracked_files(self):
        """Авария: уровень зависел от gitignored артефактов.

        Файл не может быть верен одновременно в CI (артефактов нет) и на боевом
        хосте (есть) — а `--check` гоняется именно в CI.
        """
        mod = _load()
        tracked = mod._tracked()
        self.assertTrue(tracked, "git ls-files пуст — проверка ничего не меряет")
        self.assertNotIn("data/agent_passports.json", tracked)
        subject = dict(key="_t", name="t", docs=["00_index.md"],
                       paths=["spa_core/utils/atomic.py"], keywords="", agents="",
                       data_glob=["data/agent_passports.json"])
        self.assertEqual(mod.measure(subject, [])["data"], 0)


class TestCheckRedBranchHasAPositiveControl(unittest.TestCase):
    """`--check` обязан уметь вернуть 1 — иначе CI-шаг ничего не сторожит.

    До разбора красную ветку не запускал ни один тест: замена `if drift:` на
    `if False:` оставляла набор зелёным. Проверка, никогда не видевшая поломки,
    — украшение (`.claude/rules/deployment.md`).
    """

    def _run_check_against(self, text: str) -> int:
        import tempfile
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "REG.md"
            fake.write_text(text, encoding="utf-8")
            mod.OUT = fake
            argv = sys.argv
            sys.argv = ["build_maturity_register.py", "--check"]
            try:
                return mod.main()
            finally:
                sys.argv = argv

    def test_overstated_level_makes_check_return_one(self):
        mod = _load()
        text = mod.build()
        faked = re.sub(r"(\*\*BTC capital cycle[^|]*\|) L2 \|", r"\1 L5 |", text)
        self.assertNotEqual(faked, text, "подделка не применилась — тест бессмыслен")
        self.assertEqual(self._run_check_against(faked), 1)

    def test_honest_file_makes_check_return_zero(self):
        """Обратный контроль: на верном файле красная ветка молчит."""
        mod = _load()
        self.assertEqual(self._run_check_against(mod.build()), 0)

    def test_missing_file_makes_check_return_one(self):
        self.assertEqual(self._run_check_against(""), 1)


if __name__ == "__main__":
    unittest.main()
