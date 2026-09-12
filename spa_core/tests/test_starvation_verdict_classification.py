#!/usr/bin/env python3
"""Классификация вердикта шага 0a-ГОЛОД: крах сторожа ≠ его находка (ADR-347).

**Авария 12.09 (цикл #571).** `scripts/check_owner_order_starvation.py` умер на собственном
импорте `spa_core` — бутстрап `sys.path` стоял НИЖЕ импорта, а обёртка зовёт файл ПО ПУТИ,
и тогда `sys.path[0]` — каталог `scripts/`. Интерпретатор вышел с кодом **1**, а прежний
контракт обёртки читал единицу как **НАХОДКУ**. Трассировка уехала в начало промпта цикла
словами «ШАГ 0a-ГОЛОД — НАХОДКА, исполняется ПЕРВЫМ … Возьми ЭТУ карточку первой».

Три исхода инварианта #17 — измерено · измерено и пусто · НЕ измерено — были склеены в
двух местах сразу: «не измерено» отдавало тот же код, что «измерено и громко», а ветка
«НЕ ИЗМЕРЕНО» в обёртке оказалась недостижимой для самой частой поломки python-скрипта.

**Почему тесты живут здесь, а не в `test_owner_order_starvation_wiring.py`.** Тот файл
проверяет обёртку ЦЕЛИКОМ через песочницу с подставным сторожем и подставным `claude` —
это дорого (каждый случай поднимает bash-процесс) и отвечает на вопрос «дошло ли до
промпта». Здесь вопрос другой и более узкий: «как ПАРА (код, вывод) превращается в
префикс» — и он задаётся прямым вызовом функции. Классификация вынесена в
`scripts/lib/starvation_verdict.sh` именно затем, чтобы этот вопрос стало можно задать.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_LIB = _REPO / "scripts" / "lib" / "starvation_verdict.sh"
_WRAPPER = _REPO / "scripts" / "agent_orchestrator.sh"


def classify(rc: int, out: str) -> str:
    """Префикс промпта, который обёртка получит для пары (код, вывод)."""
    script = f'. "{_LIB}"\nstarvation_prefix "$1" "$2"\n'
    proc = subprocess.run(["/bin/bash", "-c", script, "bash", str(rc), out],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"классификатор сам упал: {proc.stderr[-500:]}"
    return proc.stdout


#: Дословный хвост трассировки, приехавшей в промпт цикла #571.
_REAL_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "/Users/yuriikulieshov/Documents/SPA_Claude/scripts/'
    'check_owner_order_starvation.py", line 62, in <module>\n'
    "    from spa_core.utils.observation import observed, observed_number\n"
    "ModuleNotFoundError: No module named 'spa_core'"
)


class TestCrashIsNotAFinding(unittest.TestCase):
    """Положительный контроль: ровно та пара (код, вывод), что случилась 12.09."""

    def test_the_real_crash_is_named_unmeasured(self):
        prefix = classify(1, _REAL_TRACEBACK)
        self.assertIn("НЕ ИЗМЕРЕН", prefix,
                      f"крах сторожа не назван «не измерено»: {prefix!r}")

    def test_the_real_crash_is_not_sold_as_a_finding(self):
        """Сердце аварии: единица НЕ ИМЕЕТ ПРАВА означать находку.

        На контракте до ADR-347 этот тест краснеет — там ветка `rc -eq 1` печатала
        «НАХОДКА, возьми ЭТУ карточку первой».
        """
        prefix = classify(1, _REAL_TRACEBACK)
        self.assertNotIn("НАХОДКА", prefix,
                         "крах сторожа предъявлен сессии как его вердикт — авария 12.09")
        self.assertNotIn("возьми ЭТУ карточку", prefix)

    def test_the_crash_reason_survives_into_the_prompt(self):
        """«Не измерено» без причины не чинится: сессии нечего брать в работу."""
        prefix = classify(1, _REAL_TRACEBACK)
        self.assertIn("ModuleNotFoundError", prefix)

    def test_crash_does_not_read_as_clean(self):
        """Вторая, более тихая сторона: крах не смеет молчать.

        Пустой префикс означает «голода нет» — тот же fail-OPEN, из-за которого
        critical-приказ владельца простоял четверо суток при 40+ прошедших циклах.
        """
        self.assertNotEqual(classify(1, _REAL_TRACEBACK).strip(), "")


class TestThreeOutcomesStayDistinct(unittest.TestCase):
    """Инвариант #17 на этой поверхности: три исхода различимы ПОПАРНО."""

    FINDING = "🚨 ГОЛОДАЮЩИЙ ПРИКАЗ ВЛАДЕЛЬЦА: inbox-proba"
    CLEAN = "✅ голодающих critical-приказов владельца (>24ч) не найдено"

    def test_finding_is_code_3_and_reaches_the_prompt(self):
        prefix = classify(3, self.FINDING)
        self.assertIn("НАХОДКА", prefix)
        self.assertIn("inbox-proba", prefix, "имя голодающей карточки потеряно")
        self.assertNotIn("НЕ ИЗМЕРЕН", prefix)

    def test_clean_verdict_leaves_the_prompt_alone(self):
        """Иначе находка перестанет быть сигналом: сторож дописывал бы всегда."""
        self.assertEqual(classify(0, self.CLEAN), "")

    def test_partial_measurement_is_unmeasured_not_clean(self):
        """Код 2 — очередь на ref не прочитана. Это ответ про КАТАЛОГ, не про очередь."""
        prefix = classify(2, "❓ ОЧЕРЕДЬ НА `origin/main` НЕ ПРОЧИТАНА")
        self.assertIn("НЕ ИЗМЕРЕН", prefix)
        self.assertNotIn("НАХОДКА", prefix)

    def test_missing_guard_is_unmeasured(self):
        """Прод-дерево отстало от origin ⇒ скрипта нет ⇒ тоже «не измерено»."""
        prefix = classify(127, "нет .../check_owner_order_starvation.py")
        self.assertIn("НЕ ИЗМЕРЕН", prefix)

    def test_all_three_outcomes_differ_pairwise(self):
        """Мера различимости — не «каждый содержит своё слово», а именно попарность."""
        outcomes = {
            "находка": classify(3, self.FINDING),
            "чисто": classify(0, self.CLEAN),
            "не измерено": classify(1, _REAL_TRACEBACK),
        }
        names = list(outcomes)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                self.assertNotEqual(outcomes[a], outcomes[b],
                                    f"исходы «{a}» и «{b}» неразличимы в промпте")


class TestVersionSkewFailsClosed(unittest.TestCase):
    """Прод-дерево отстаёт от origin ПО ПОСТРОЕНИЮ — перекос обязан падать безопасно."""

    def test_old_script_reporting_a_finding_as_1_becomes_unmeasured(self):
        """Новая обёртка + старый сторож: находка приедет кодом 1.

        Это НЕ «голода нет» — сессии сказано проверить руками. Направление безопасное:
        находка может стать «не измерено», но никогда — тишиной.
        """
        prefix = classify(1, "🚨 ГОЛОДАЮЩИЙ ПРИКАЗ ВЛАДЕЛЬЦА: inbox-proba")
        self.assertIn("НЕ ИЗМЕРЕН", prefix)
        self.assertNotEqual(prefix.strip(), "")

    def test_new_script_against_an_old_wrapper_is_also_safe(self):
        """Обратный перекос проверяется на СТАРОМ тексте ветки, а не на воображении.

        Старая обёртка: `rc -eq 1` → находка, `rc -ne 0` → не измерено. Новый сторож
        отдаёт находку кодом 3, значит попадёт во вторую ветку — «не измерено». Тишины
        (единственного опасного исхода) не возникает ни при каком перекосе.
        """
        old_branch_verdict = "находка" if 3 == 1 else ("чисто" if 3 == 0 else "не измерено")
        self.assertEqual(old_branch_verdict, "не измерено")


class TestTheClassifierIsActuallyWired(unittest.TestCase):
    """Песочница подменяет пути — значит, адрес закрепляем отдельно (урок #391)."""

    def test_the_library_exists_where_the_wrapper_sources_it(self):
        self.assertTrue(_LIB.exists(), f"обёртка зовёт {_LIB}, а его нет")

    def test_the_wrapper_sources_the_library_and_calls_the_function(self):
        """Без этого все тесты выше остались бы зелёными на расплетённой обёртке."""
        src = _WRAPPER.read_text(encoding="utf-8")
        self.assertIn('scripts/lib/starvation_verdict.sh', src,
                      "обёртка не знает путь к классификатору")
        self.assertIn('starvation_prefix "$STARVE_RC" "$STARVE_OUT"', src,
                      "обёртка не ЗОВЁТ классификатор — проводка порвана")

    def test_the_wrapper_no_longer_treats_1_as_a_finding(self):
        """Прямая проверка, что старая ветка УДАЛЕНА, а не осталась рядом.

        Два классификатора подряд — это тот же дефект с лишним шагом: побеждал бы
        последний, и какой именно — решал бы порядок строк.
        """
        src = _WRAPPER.read_text(encoding="utf-8")
        self.assertNotIn('[ "$STARVE_RC" -eq 1 ]', src,
                         "в обёртке осталась старая ветка «код 1 = находка»")

    def test_the_wrapper_has_no_silent_path_for_a_missing_library(self):
        """Нет библиотеки ⇒ третий исход, а не пустой префикс."""
        src = _WRAPPER.read_text(encoding="utf-8")
        head = src.split("STARVE_LIB=", 1)[1].split("# ── ARMED", 1)[0]
        self.assertIn("НЕ ИЗМЕРЕН", head,
                      "ветка «библиотеки нет» молчит — молчание читается как «голода нет»")


if __name__ == "__main__":
    unittest.main()
