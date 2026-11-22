"""Контроли прибора «шаг ИЗМЕРЕН с одного носителя, вердикт о другом» (ADR-1072).

Каждый тест — либо воспроизведение НАСТОЯЩЕЙ аварии, либо контроль на обратную
сторону. Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md` § «Проверка сторожа сторожей»).

Главный положительный контроль — **прежняя редакция
`counterfactual_tracking_census.py`**, та самая, в которой достижимость
горизонта решалась шагом ДНЕВНОГО ТРЕКА (ADR-1071). Её текст лежит рядом
фикстурой: брать его из git внутри теста значило бы сделать вердикт теста
свойством ГЛУБИНЫ КЛОНА, а прод-клон УСЕЧЁН (`.claude/rules/deployment.md`
§ поправка #1031 — 252 вершины из 28 011, и git молчит об этом кодом 0).

Литеральных дат в файле нет ни одной: предмет прибора — синтаксис, а не время.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics import foreign_carrier_cadence_census as fcc

_REPO = Path(__file__).resolve().parents[2]

# ─────────────────────────── сцены ───────────────────────────────────────────

#: ПРЕЖНЯЯ редакция переписи §31 — настоящая авария ADR-1071, сжатая до сути.
#: Шаг измерен с носителя `daily`, вердикт выносится о горизонте, а горизонт
#: несут носители `eval`/`replay`.
SCENE_THE_REAL_DEFECT = '''
def _cadence_hours(daily):
    """Шаг наблюдения входов — минимальный зазор между датами трека."""
    gaps = [1.0, 24.0]
    if not gaps:
        return None, "нет"
    return min(gaps), None


def measure_horizons(carriers):
    carrier_h = {}
    ev = carriers.get("eval")
    rp = carriers.get("replay")
    carrier_h["judge"] = ev
    carrier_h["replay"] = rp
    cadence, why = _cadence_hours(carriers.get("daily"))
    rows = {}
    for h in ("1h", "6h"):
        hh = HORIZON_HOURS[h]
        if hh < cadence:
            rows[h] = "unreachable_by_cadence"
    return rows
'''

#: ПОЧИНЕННАЯ форма: шаг снят с ТОГО носителя, который несёт величину.
SCENE_FIXED_SAME_CARRIER = '''
def _pricing_cadence_hours(record_rows):
    gaps = [0.5, 1.5]
    return min(gaps), None


def measure_horizons(carriers):
    cadence, why = _pricing_cadence_hours(carriers.get("records"))
    rows = {}
    for h in ("1h",):
        hh = HORIZON_HOURS[h]
        if hh < cadence:
            rows[h] = "unreachable"
    return rows
'''

#: Шаг ИЗМЕРЕН, и носитель у функции РОВНО ОДИН — безопасно по построению.
SCENE_SINGLE_CARRIER = '''
def _cadence_hours(daily):
    gaps = [24.0]
    return min(gaps), None


def judge(carriers):
    cadence, why = _cadence_hours(carriers.get("daily"))
    age = 5.0
    if age > cadence:
        return "stale"
    return "fresh"
'''

#: Шаг ОБЪЯВЛЕН — порог есть решение, вопрос о носителе не применим.
SCENE_DECLARED_THRESHOLD = '''
MAX_AGE_HOURS = 26.0


def judge(carriers):
    doc = carriers.get("daily")
    age = 5.0
    if age > MAX_AGE_HOURS:
        return "stale"
    return "fresh"
'''

#: ЗАЖИМ — `max(x, пол)` статистикой не является (ложное срабатывание первой
#: редакции прибора: так в знаменатель попали шестеро чужих).
SCENE_CLAMP_IS_NOT_A_MEASUREMENT = '''
def cadence_hours(schedule):
    """Такт агента из ОБЪЯВЛЕННОГО расписания — ни одного носителя."""
    return max(int(schedule) / 3600.0, 0.0834)


def judge(carriers):
    doc = carriers.get("daily")
    other = carriers.get("eval")
    age = 5.0
    if age > cadence_hours("interval:3600s"):
        return "stale"
    return "fresh"
'''

#: Одна мерка зовётся с РАЗНЫХ носителей — честное «не измерено».
SCENE_TWO_CARRIERS_ONE_METER = '''
def _cadence_hours(rows):
    gaps = [1.0]
    return min(gaps), None


def judge(carriers):
    a, _ = _cadence_hours(carriers.get("daily"))
    b, _ = _cadence_hours(carriers.get("records"))
    age = 5.0
    if age > a:
        return "stale"
    return "fresh"
'''

#: Комментарий — НЕ зов. Воспроизводит ложное срабатывание самого прибора:
#: первая редакция `exported_steps` грепала сырой текст и зачла эту строку.
SCENE_COMMENT_IS_NOT_A_CALLER = '''
def other():
    # cadence, why = _cadence_hours(x) — упоминание в прозе, а не зов
    """Док-строка тоже упоминает _cadence_hours(carriers.get("daily"))."""
    return 1
'''

#: `==` вердиктом о свежести не является — это сверка.
SCENE_EQUALITY_IS_NOT_A_VERDICT = '''
def _cadence_hours(daily):
    gaps = [24.0]
    return min(gaps), None


def judge(carriers):
    cadence, why = _cadence_hours(carriers.get("daily"))
    other = carriers.get("eval")
    age = 24.0
    return age == cadence
'''


#: ОБРАТНАЯ сторона зажима: статистика по коллекции ЕСТЬ, а имя шага не
#: ПРЕТЕНДУЕТ. Сцена записана по выжившей мутации **M16** первого мутационного
#: прогона цикла #1215: из двух обязательных условий
#: :func:`fcc.measured_step_functions` батарея проверяла только одно
#: («имя претендует, а статистики нет» — класс `AClampIsNotAMeasurement`), и
#: снятие второго («имя больше не требуется») вердикта батареи НЕ МЕНЯЛО.
SCENE_NAME_MUST_CLAIM_A_STEP = '''
def worst_latency_ms(samples):
    """Статистика по коллекции — но мерка НЕ шага: имя шага не претендует."""
    return max(samples)


def judge(carriers):
    other = carriers.get("eval")
    age = 5.0
    if age > worst_latency_ms(carriers.get("daily")):
        return "stale"
    return "fresh"
'''


def _kinds(text: str, rel: str = "scene.py"):
    sites, why, steps = fcc.census_module_full(rel, text)
    assert why is None, why
    return [s["kind"] for s in sites], sites, steps


# ──────────────────── 1. настоящая авария ADR-1071 ───────────────────────────

class TheRealDefectIsFound(unittest.TestCase):
    """Положительный контроль на НАСТОЯЩЕЙ аварии, а не на выдуманной."""

    def test_the_pre_fix_edition_is_named_a_subject_of_the_class(self):
        kinds, sites, _ = _kinds(SCENE_THE_REAL_DEFECT)
        self.assertEqual(kinds, [fcc.CLASS_SUBJECT],
                         f"прежняя редакция ADR-1071 обязана быть предметом класса: {sites}")

    def test_the_subject_names_the_carrier_the_step_was_measured_from(self):
        _, sites, _ = _kinds(SCENE_THE_REAL_DEFECT)
        self.assertEqual(sites[0]["step_carrier"], "bag:daily",
                         "вердикт без имени носителя шага нечем проверить")

    def test_the_subject_names_the_other_carriers_the_function_reads(self):
        _, sites, _ = _kinds(SCENE_THE_REAL_DEFECT)
        others = sites[0]["other_carriers"]
        self.assertIn("bag:eval", others)
        self.assertIn("bag:replay", others)
        self.assertNotIn("bag:daily", others,
                         "носитель шага не может быть сам себе чужим")

    def test_the_fixed_edition_is_NOT_a_subject(self):
        """Обратная сторона: починка обязана СНЯТЬ находку, иначе мера слепа."""
        kinds, sites, _ = _kinds(SCENE_FIXED_SAME_CARRIER)
        self.assertNotIn(fcc.CLASS_SUBJECT, kinds,
                         f"шаг снят с ТОГО носителя — предмета быть не может: {sites}")

    def test_the_real_pre_fix_module_from_the_tree_is_a_subject(self):
        """Та же авария, но на ЖИВОМ файле дерева: починенная редакция чиста.

        Это контроль на ПРАВДИВОСТЬ фикстур выше: сцена сжата руками, и если
        сжатие потеряло предмет, настоящий файл об этом скажет.
        """
        real = (_REPO / "spa_core/analytics/counterfactual_tracking_census.py")
        if not real.is_file():                       # pragma: no cover
            self.fail(f"предпосылка НЕ ОБЕСПЕЧЕНА: нет {real}")
        kinds, sites, steps = _kinds(real.read_text(encoding="utf-8"), real.name)
        self.assertNotIn(fcc.CLASS_SUBJECT, kinds,
                         f"починенная редакция ADR-1071 обязана быть чистой: {sites}")
        self.assertIn("_cadence_hours", steps,
                      "мерка шага осталась в модуле как ФАКТ о треке — она обязана "
                      "быть видна прибору, иначе знаменатель врёт")


# ──────────────────── 2. роды различимы (инв. #17) ───────────────────────────

class TheFourKindsAreDistinguishable(unittest.TestCase):

    def test_a_single_carrier_is_safe_by_construction_not_a_subject(self):
        kinds, sites, _ = _kinds(SCENE_SINGLE_CARRIER)
        self.assertEqual(kinds, ["single_carrier"], sites)
        self.assertNotEqual(kinds, [fcc.CLASS_SUBJECT])

    def test_a_declared_threshold_is_its_own_kind_not_a_subject_and_not_unmeasured(self):
        kinds, sites, _ = _kinds(SCENE_DECLARED_THRESHOLD)
        self.assertEqual(kinds, ["step_declared"], sites)

    def test_two_carriers_for_one_meter_is_unmeasured_WITH_A_NAMED_REASON(self):
        kinds, sites, _ = _kinds(SCENE_TWO_CARRIERS_ONE_METER)
        self.assertIn("unmeasured", kinds, sites)
        row = [s for s in sites if s["kind"] == "unmeasured"][0]
        self.assertIn("РАЗНЫХ носителей", row["reason"])
        self.assertIn("bag:daily", row["reason"])
        self.assertIn("bag:records", row["reason"],
                      "причина обязана назвать ОБА носителя, иначе её нечем разрешить")

    def test_unmeasured_is_never_reported_as_a_clean_zero(self):
        _, sites, _ = _kinds(SCENE_TWO_CARRIERS_ONE_METER)
        doc = {"measured": True, "repo_root": "/x", "scan_dirs": ["spa_core"],
               "modules_read": 1, "unparsed": [], "sites": sites,
               "tally": {k: sum(1 for s in sites if s["kind"] == k) for k in fcc.KINDS},
               "measured_steps": [], "subjects": [], "container_crossings": [],
               "exported_steps": []}
        text = fcc.format_report(doc)
        self.assertIn("НЕ ИЗМЕРЕНО: 1", text,
                      "«не измерено» обязано быть ВИДНО отдельным числом (инв. #17)")

    def test_the_kind_vocabulary_is_closed_and_the_tally_covers_it(self):
        """Расширение словаря молча — это новый род, не названный в сводке."""
        self.assertEqual(set(fcc.KINDS),
                         {"foreign_carrier_candidate", "single_carrier",
                          "step_declared", "unmeasured"})
        self.assertIn(fcc.CLASS_SUBJECT, fcc.KINDS)

    def test_every_site_carries_a_kind_from_the_closed_vocabulary(self):
        for scene in (SCENE_THE_REAL_DEFECT, SCENE_SINGLE_CARRIER,
                      SCENE_DECLARED_THRESHOLD, SCENE_TWO_CARRIERS_ONE_METER):
            _, sites, _ = _kinds(scene)
            for s in sites:
                self.assertIn(s["kind"], fcc.KINDS, s)


# ──────────────── 3. замер против объявления: зажим не статистика ────────────

class AClampIsNotAMeasurement(unittest.TestCase):
    """Ложное срабатывание ПЕРВОЙ редакции прибора, записанное тестом.

    Критерий «в теле есть `min`/`max`» зачёл замером шестерых, считающих по
    ОБЪЯВЛЕНИЮ: `max(такт, 0.0834)` — это ПОЛ, а не статистика по носителю.
    Знаменатель 8 был неверен; верный — 3.
    """

    def test_a_two_argument_max_is_not_a_measured_step(self):
        _, _, steps = _kinds(SCENE_CLAMP_IS_NOT_A_MEASUREMENT)
        self.assertEqual(steps, {},
                         "зажим `max(x, пол)` замером шага не является")

    def test_and_so_the_clamp_site_is_not_a_subject_though_it_reads_two_carriers(self):
        """Обратная сторона: двух носителей в функции НЕ ДОСТАТОЧНО для находки."""
        kinds, sites, _ = _kinds(SCENE_CLAMP_IS_NOT_A_MEASUREMENT)
        self.assertNotIn(fcc.CLASS_SUBJECT, kinds, sites)

    def test_a_statistic_over_a_collection_IS_a_measured_step(self):
        _, _, steps = _kinds(SCENE_SINGLE_CARRIER)
        self.assertIn("_cadence_hours", steps)
        self.assertEqual(steps["_cadence_hours"]["statistics"], ["min"])

    def test_the_live_tree_clamp_in_slo_proposal_stays_out_of_the_denominator(self):
        """Тот же вопрос ЖИВОМУ файлу, на котором ошибка и была найдена."""
        real = _REPO / "spa_core/monitoring/slo_proposal.py"
        if not real.is_file():                       # pragma: no cover
            self.fail(f"предпосылка НЕ ОБЕСПЕЧЕНА: нет {real}")
        _, _, steps = _kinds(real.read_text(encoding="utf-8"), real.name)
        self.assertNotIn("cadence_hours", steps,
                         "`cadence_hours(schedule)` разбирает ОБЪЯВЛЕНИЕ — "
                         "числить его замером по носителю значит приписать "
                         "классу чужого")


# ───── 3b. ОБА условия мерки обязательны (выжившая мутация M16, #1215) ───────

class TheNameMustClaimAStep(unittest.TestCase):
    """Второе обязательное условие мерки шага, записанное выжившей мутацией.

    `measured_step_functions` требует ДВУХ условий сразу: имя ПРЕТЕНДУЕТ быть
    меркой шага **и** тело считает статистику по коллекции. Класс
    `AClampIsNotAMeasurement` выше закрывал ровно одну сторону («имя
    претендует, статистики нет»); обратную — «статистика есть, имя не
    претендует» — не закрывала ни одна сцена, и мутация M16 (снятие проверки
    имени) первого прогона #1215 **ВЫЖИЛА**: набор упавших имён не изменился.
    Выжившую записываем, а не замазываем (`.claude/rules/acceptance.md` п. 3 —
    контроль в обе стороны у каждой претензии).

    Почему проверка имени несущая: без неё меркой шага числится ЛЮБАЯ функция
    со статистикой по коллекции, знаменатель раздувается чужими, а «кандидатов
    0» становится утверждением неизвестной силы — то же самое, чем была ошибка
    №1 первой редакции прибора, только с другой стороны.
    """

    def test_a_statistic_whose_name_does_not_claim_a_step_is_not_a_measured_step(self):
        _, _, steps = _kinds(SCENE_NAME_MUST_CLAIM_A_STEP)
        self.assertEqual(steps, {},
                         "`max(samples)` в `worst_latency_ms` — статистика по "
                         "коллекции, но НЕ шаг: имя шага не претендует, и "
                         "числить её меркой значит раздуть знаменатель чужими")

    def test_and_so_the_site_is_not_a_subject_though_it_reads_two_carriers(self):
        """Обратная сторона: двух носителей рядом со статистикой НЕ ДОСТАТОЧНО."""
        kinds, sites, _ = _kinds(SCENE_NAME_MUST_CLAIM_A_STEP)
        self.assertNotIn(fcc.CLASS_SUBJECT, kinds, sites)

    def test_the_same_scene_with_a_claiming_name_IS_a_subject(self):
        """Различающая половина: меняется РОВНО имя — и род меняется.

        Без этой половины первая проверка была бы верна и по причине «сцена
        вообще не доходит до разбора», а не «имя не претендует».
        """
        claiming = SCENE_NAME_MUST_CLAIM_A_STEP.replace(
            "worst_latency_ms", "_latency_cadence_hours")
        kinds, sites, steps = _kinds(claiming)
        self.assertIn("_latency_cadence_hours", steps, steps)
        self.assertIn(fcc.CLASS_SUBJECT, kinds, sites)


# ─────────────── 4. слепоты ИЗМЕРЕНЫ, а не объявлены словами ─────────────────

class TheBlindSpotsAreMeasured(unittest.TestCase):

    def test_prose_is_not_a_caller(self):
        """Ложное срабатывание самого прибора: греп зачёл КОММЕНТАРИЙ зовом."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core").mkdir()
            (root / "spa_core" / "meter.py").write_text(SCENE_SINGLE_CARRIER,
                                                        encoding="utf-8")
            (root / "spa_core" / "prose.py").write_text(SCENE_COMMENT_IS_NOT_A_CALLER,
                                                        encoding="utf-8")
            doc = fcc.census(root, scan_dirs=("spa_core",))
        self.assertTrue(doc["measured"], doc)
        exported = doc["exported_steps"]
        self.assertEqual([e["step"] for e in exported], ["_cadence_hours"])
        self.assertEqual(exported[0]["foreign_callers"], [],
                         "упоминание в прозе зовом НЕ является (ADR-1028)")

    def test_a_real_foreign_call_IS_counted(self):
        """Обратная сторона: настоящий зов из чужого модуля обязан НАЙТИСЬ."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core").mkdir()
            (root / "spa_core" / "meter.py").write_text(SCENE_SINGLE_CARRIER,
                                                        encoding="utf-8")
            (root / "spa_core" / "user.py").write_text(
                "from spa_core.meter import _cadence_hours\n"
                "def go(rows):\n"
                "    return _cadence_hours(rows)\n", encoding="utf-8")
            doc = fcc.census(root, scan_dirs=("spa_core",))
        callers = doc["exported_steps"][0]["foreign_callers"]
        self.assertEqual(len(callers), 1, callers)
        self.assertTrue(callers[0].startswith("spa_core/user.py:"), callers)

    def test_a_container_crossing_is_named_not_silently_swallowed(self):
        text = ('def _cadence_hours(daily):\n'
                '    gaps = [1.0]\n'
                '    return min(gaps)\n'
                '\n'
                'def collect(carriers):\n'
                '    entry = {}\n'
                '    tact = _cadence_hours(carriers.get("daily"))\n'
                '    entry["tact_hours"] = tact\n'
                '    return entry\n')
        rows = fcc.container_crossings("scene.py", text)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["steps"], ["_cadence_hours"])
        self.assertEqual(rows[0]["function"], "collect")

    def test_a_container_literal_does_NOT_propagate_provenance(self):
        """Правило дома: «контейнер привязкой НЕ является».

        `rows[h] = {"cadence_hours": cadence}` не делает `rows` шагом. Считать
        «RHS содержит имя» происхождением значило бы оправдать аварию
        2026-08-04 (`.claude/rules/deployment.md` § «Время в тестах»).
        """
        text = ('def _cadence_hours(daily):\n'
                '    gaps = [1.0]\n'
                '    return min(gaps)\n'
                '\n'
                'def judge(carriers):\n'
                '    other = carriers.get("eval")\n'
                '    cadence = _cadence_hours(carriers.get("daily"))\n'
                '    bundle = {"cadence_hours": cadence}\n'
                '    age = 5.0\n'
                '    if age > bundle:\n'
                '        return "stale"\n'
                '    return "fresh"\n')
        kinds, sites, _ = _kinds(text)
        self.assertNotIn(fcc.CLASS_SUBJECT, kinds,
                         f"отображение-литерал провенанс обрывает НАМЕРЕННО: {sites}")

    def test_both_blind_spots_are_printed_as_numbers(self):
        doc = fcc.census(_REPO, scan_dirs=("spa_core/analytics",))
        text = fcc.format_report(doc)
        self.assertIn("СЛЕПОТА 1", text)
        self.assertIn("СЛЕПОТА 2", text)
        self.assertIn("ЗНАМЕНАТЕЛЬ", text,
                      "«кандидатов 0» без знаменателя — утверждение неизвестной силы")


# ──────────────── 5. распаковка, операторы, провенанс ────────────────────────

class ProvenanceWiring(unittest.TestCase):

    def test_tuple_unpacking_binds_BOTH_names(self):
        """Настоящая форма аварии: `cadence, why = _cadence_hours(x)`.

        Потеряй распаковку — и предмет ADR-1071 стал бы невидим: шаг приходит
        ПЕРВЫМ членом кортежа, а не возвратом скаляра.
        """
        kinds, _, _ = _kinds(SCENE_THE_REAL_DEFECT)
        self.assertEqual(kinds, [fcc.CLASS_SUBJECT],
                         "распаковка обязана связывать имя слева с зовом справа")

    def test_equality_is_not_a_freshness_verdict(self):
        kinds, sites, _ = _kinds(SCENE_EQUALITY_IS_NOT_A_VERDICT)
        self.assertEqual(kinds, [], f"`==` — сверка, а не вердикт о свежести: {sites}")

    def test_carrier_token_names_the_bag_key(self):
        import ast as _ast
        node = _ast.parse('carriers.get("daily")', mode="eval").body
        self.assertEqual(fcc.carrier_token(node), "bag:daily")
        node = _ast.parse('docs["eval"]', mode="eval").body
        self.assertEqual(fcc.carrier_token(node), "bag:eval")

    def test_an_arbitrary_dict_get_is_NOT_a_carrier(self):
        """Иначе любой `cfg.get("x")` числился бы носителем и класс раздулся."""
        import ast as _ast
        node = _ast.parse('cfg.get("timeout")', mode="eval").body
        self.assertIsNone(fcc.carrier_token(node))

    def test_a_data_path_literal_IS_a_carrier(self):
        import ast as _ast
        node = _ast.parse('"data/equity_curve_daily.json"', mode="eval").body
        self.assertEqual(fcc.carrier_token(node), "path:data/equity_curve_daily.json")


# ──────────────── 6. три исхода прибора и дерево как ВХОД ────────────────────

class ThreeOutcomesAndTheTreeIsAnInput(unittest.TestCase):

    def _run(self, *argv):
        proc = subprocess.run(
            [sys.executable, "-m",
             "spa_core.analytics.foreign_carrier_cadence_census", *argv],
            cwd=_REPO, capture_output=True, text=True)
        return proc

    def test_an_unreadable_named_tree_is_UNMEASURED_with_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "net-takogo-dereva"
            proc = self._run("--repo-root", str(missing))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("НЕ ИЗМЕРЕНО", proc.stdout)

    def test_an_empty_tree_is_UNMEASURED_not_a_clean_zero(self):
        """Ноль модулей — это «нечем мерить», а не «кандидатов нет»."""
        with tempfile.TemporaryDirectory() as td:
            doc = fcc.census(Path(td), scan_dirs=("spa_core",))
        self.assertFalse(doc["measured"], doc)
        self.assertIn("ни одного модуля", doc["reason"])

    def test_a_tree_with_the_defect_exits_1_and_names_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core").mkdir()
            (root / "spa_core" / "bad.py").write_text(SCENE_THE_REAL_DEFECT,
                                                      encoding="utf-8")
            doc = fcc.census(root, scan_dirs=("spa_core",))
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["tally"][fcc.CLASS_SUBJECT], 1, doc["sites"])
        self.assertEqual(len(doc["subjects"]), 1)

    def test_a_clean_tree_exits_0(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core").mkdir()
            (root / "spa_core" / "ok.py").write_text(SCENE_SINGLE_CARRIER,
                                                     encoding="utf-8")
            doc = fcc.census(root, scan_dirs=("spa_core",))
        self.assertEqual(doc["tally"][fcc.CLASS_SUBJECT], 0, doc["sites"])

    def test_the_default_tree_is_PRINTED_when_not_named(self):
        """ADR-933: умолчание печатается, иначе вердикт о дереве анонимен."""
        proc = self._run()
        self.assertIn("дерево НЕ НАЗВАНО входом --repo-root", proc.stdout)

    def test_a_named_tree_is_not_announced_as_a_default(self):
        proc = self._run("--repo-root", str(_REPO))
        self.assertNotIn("дерево НЕ НАЗВАНО", proc.stdout)

    def test_json_output_is_machine_readable(self):
        proc = self._run("--repo-root", str(_REPO), "--json")
        doc = json.loads(proc.stdout)
        self.assertTrue(doc["measured"])
        self.assertEqual(set(doc["tally"]), set(fcc.KINDS))

    def test_a_syntactically_broken_module_is_named_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core").mkdir()
            (root / "spa_core" / "ok.py").write_text(SCENE_SINGLE_CARRIER,
                                                     encoding="utf-8")
            (root / "spa_core" / "broken.py").write_text("def f(:\n",
                                                         encoding="utf-8")
            doc = fcc.census(root, scan_dirs=("spa_core",))
        self.assertTrue(any("broken.py" in u for u in doc["unparsed"]), doc["unparsed"])

    def test_the_instrument_writes_nothing(self):
        """ADVISORY по объявлению: прибор только ЧИТАЕТ."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core").mkdir()
            (root / "spa_core" / "ok.py").write_text(SCENE_SINGLE_CARRIER,
                                                     encoding="utf-8")
            before = sorted(p.as_posix() for p in root.rglob("*"))
            fcc.census(root, scan_dirs=("spa_core",))
            after = sorted(p.as_posix() for p in root.rglob("*"))
        self.assertEqual(before, after, "прибор не вправе писать ни одного файла")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
