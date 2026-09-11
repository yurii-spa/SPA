"""Тесты §41 ТЗ «Portfolio CIO» — ограничения auto-execution.

Каждая проверка здесь — положительный контроль над ОШИБКОЙ ИЗМЕРЕНИЯ, которая
уже была сделана, а не пересказ модуля. Авария, которую воспроизводит этот
файл, — не падение прода, а неверный ВЫВОД: замер 07.09 на настоящем
``_apply_risk_policy_gate`` показал, что T3 суммарно 25 % проходит гейт с нулём
нарушений, хотя ``RiskConfig.max_total_t3_allocation = 0.15`` объявлено — и
отчёт «объявленное поле не связывает» был бы ВЕРНЫМ ответом на НЕ ТОТ вопрос:
поле читает аллокатор. Проверки ниже краснеют, если модуль снова начнёт судить
о двенадцати ограничениях владельца по одной поверхности решения.

Литеральных pid здесь нет вовсе. Единственная литеральная дата — якорь
инъекции.
"""
# FROZEN-DATE-OK: injected-clock — литерал `NOW` служит ТОЛЬКО якорем: он
# передаётся параметром `now=` в `M.run(...)`, и единственное поле отчёта, где
# он оказывается, — `generated_at`. Ни одна проверка этого файла не спрашивает
# время у ОС и ни одна не судит о свежести, поэтому сдвиг календаря их не
# трогает.

from __future__ import annotations

import ast
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import cio_auto_execution_limits as M

NOW = dt.datetime(2026, 3, 4, 5, 6, 7, tzinfo=dt.timezone.utc)

#: Один прогон на весь файл: он детерминирован и не трогает живое состояние,
#: а двенадцать проб × три поверхности — не та цена, которую стоит платить
#: заново в каждом тесте.
_RUN: dict = {}


def _run() -> dict:
    if not _RUN:
        _RUN.update(M.run(write=False, now=NOW))
    return _RUN


def _limit(doc: dict, key: str) -> dict:
    return next(x for x in doc["limits"] if x["limit"] == key)


# ─────── 1. ЛОВУШКА: ограничение связывает НЕ ТАМ, где его ищут ─────────────

class TestTheTrapThatMadeThisModuleNecessary(unittest.TestCase):
    """Замер по одной поверхности даёт верный ответ на не тот вопрос."""

    def test_t3_total_cap_now_binds_at_the_gate_too(self):
        """РАСТЯЖКА СРАБОТАЛА: ADR-337 закрыл щель, и тест сменил сторону.

        Инв. #16 — изменение намеренное (11.09). Прежняя редакция утверждала
        обратное: «гейт обязан ПРОПУСТИТЬ T3 суммарно 25 %» — и прямо писала,
        зачем: «если проверка покраснеет сама, то есть гейт начнёт применять
        суммарный потолок T3, узнать об этом надо здесь, а не из отчёта».
        Она покраснела ровно от этого: ADR-337 научил `check_new_position` и
        `check_portfolio_health` считать T3 СУММАРНО (порог 0.15 не менялся).

        Сцена сохранена дословно: 25 % на ДВУХ пулах T3 (15 % + 10 %), каждый
        ниже потолка НА ПРОТОКОЛ (20 %), сумма выше потолка НА ТИР (15 %) —
        иначе спрашивалось бы другое ограничение. Утверждение перевёрнуто, а не
        снято: теперь оно сторожит, что гейт потолок ПРИМЕНЯЕТ, и покраснеет,
        если его снимут. Метод двухповерхностного замера этим не отменяется —
        соседний тест по-прежнему требует, чтобы тот же потолок связывал у
        аллокатора.
        """
        keys = M._t3_probe_keys()
        self.assertGreaterEqual(
            len(keys), 2,
            "канонический tier_map обязан назвать ≥2 ключа T3 — иначе "
            "предпосылка теста не обеспечена и судить не о чем")
        a, b = keys[0], keys[1]
        spec = [{"protocol": a, "tier": "T3", "apy_pct": 4.0},
                {"protocol": b, "tier": "T3", "apy_pct": 5.0},
                {"protocol": "pendle", "tier": "T2", "apy_pct": 8.0}]
        verdict = M._gate_verdict(
            {a: 0.15 * M._SCENE_CAPITAL_USD, b: 0.10 * M._SCENE_CAPITAL_USD,
             "pendle": 0.15 * M._SCENE_CAPITAL_USD}, spec)
        self.assertFalse(
            verdict.startswith("approved=True"),
            "гейт перестал применять СУММАРНЫЙ потолок T3 (ADR-337): каждый пул "
            "ниже потолка на протокол, а сумма 25 % выше потолка на тир 15 % — "
            f"и это снова прошло бы; получено: {verdict}")

    def test_the_same_cap_does_bind_at_the_allocator(self):
        """…и та же величина у аллокатора СВЯЗЫВАЕТ. Обе половины — измерением."""
        keys = M._t3_probe_keys()
        self.assertGreaterEqual(len(keys), 2, "предпосылка теста не обеспечена")
        a, b = keys[0], keys[1]
        weights = {a: 0.15, b: 0.10, "aave_v3": 0.40}
        after = json.loads(M._alloc_weights_verdict("_enforce_t3_total_cap", weights))
        self.assertAlmostEqual(
            0.15, after[a] + after[b], places=6,
            msg="_enforce_t3_total_cap обязан срезать СУММУ T3 до объявленных 15 %")

    def test_report_names_the_surface_and_the_gap(self):
        """Отчёт обязан НАЗВАТЬ обе половины, а не свести их к «есть/нет»."""
        tiers = _limit(_run(), "allowed_tiers")
        self.assertEqual(M.BINDING, tiers["outcome"])
        self.assertIn("allocator", tiers["surfaces_binding"])
        gaps = " ".join(g["gap"] for g in tiers["gaps"])
        self.assertTrue(
            any(g["surface"] == "gate" for g in tiers["gaps"]),
            "пробел ограничения на гейте обязан быть назван — иначе замер "
            "выдаёт наполовину работающее ограничение за работающее")
        self.assertIn("max_total_t3_allocation", gaps)

    def test_chains_bind_at_the_allocator_and_are_silent_at_the_gate(self):
        """Вторая половина той же ловушки — сети (ADR-136/ADR-025)."""
        chains = _limit(_run(), "allowed_chains")
        self.assertEqual(M.BINDING, chains["outcome"])
        self.assertEqual(["allocator"], chains["surfaces_binding"])
        self.assertTrue(
            any(g["surface"] == "gate" for g in chains["gaps"]),
            "гейт сеть не судит вовсе — это обязано быть в отчёте, иначе "
            "«сети ограничены» прочтётся как «ограничены везде»")

    def test_a_gate_only_measurement_would_have_been_wrong(self):
        """Прямое доказательство, что одноповерхностный замер соврал бы.

        Проверка не пересказывает вывод модуля, а ПОВТОРЯЕТ ошибочный замер и
        показывает, что он даёт противоположный ответ.
        """
        gate_only = [r for r in _limit(_run(), "allowed_chains")["records"]
                     if r["surface"] == "gate" and r["axis"] == "quantity"]
        self.assertTrue(gate_only, "проба на гейте обязана существовать")
        self.assertFalse(
            any(r["changed"] for r in gate_only),
            "по одному гейту `allowed chains` выглядит отсутствующим")
        alloc_only = [r for r in _limit(_run(), "allowed_chains")["records"]
                      if r["surface"] == "allocator" and r["axis"] == "quantity"]
        self.assertTrue(
            any(r["changed"] for r in alloc_only),
            "…а по аллокатору — работающим. Ровно это расхождение и есть "
            "предмет §41; сойдись обе стороны, тест бессмыслен")


# ─────────── 2. Положительный контроль — условие ВСЕГО отчёта ───────────────

class TestControlGatesTheWholeTally(unittest.TestCase):
    """Счёт нельзя читать, пока не доказано, что проба вообще работает."""

    def test_healthy_scene_permits_the_move_on_all_three_surfaces(self):
        control = _run()["control"]
        self.assertTrue(control["passed"], control["reason"])
        base = control["healthy_baseline"]
        self.assertTrue(base["gate"].startswith("approved=True|err=False"))
        self.assertEqual("ACT", base["economics"])

    def test_a_blocked_healthy_scene_makes_every_limit_unchecked(self):
        """Сцена, которая и без ограничения запрещает ход, обесценивает всё.

        Мутируется ПРОВОДКА (базовая линия), а не отдельная проба: именно так
        отчёт и сломался бы в жизни — сцена перестала бы проходить гейт после
        чужой правки порогов, и все двенадцать ответов молча стали бы «нет».
        """
        original = M._healthy_baselines
        M._healthy_baselines = lambda: dict(
            original(), gate="approved=False|err=False|book={}")
        try:
            doc = M.run(write=False, now=NOW)
        finally:
            M._healthy_baselines = original
        self.assertEqual("UNCHECKED", doc["overall"])
        self.assertFalse(doc["control"]["passed"])
        self.assertEqual(len(M.OWNER_LIMITS), doc["tally"][M.UNCHECKED])
        self.assertTrue(doc["unchecked"], "молчаливого «не измерено» быть не должно")

    def test_a_surface_with_no_binding_limit_makes_the_tally_unreadable(self):
        """«Поверхность не реагирует» ≠ «проба сломана» — и это надо доказать.

        Если бы модуль не требовал хотя бы одного BINDING на КАЖДОЙ поверхности,
        сломанный вызов гейта выглядел бы как честный вывод «у гейта нет ни
        одного ограничения владельца».
        """
        original = M._binding_surfaces
        M._binding_surfaces = lambda results: {"allocator", "economics"}
        try:
            doc = M.run(write=False, now=NOW)
        finally:
            M._binding_surfaces = original
        self.assertEqual("UNCHECKED", doc["overall"])
        self.assertIn("gate", doc["control"]["reason"])
        self.assertEqual(len(M.OWNER_LIMITS), doc["tally"][M.UNCHECKED])

    def test_control_names_every_surface_it_covers(self):
        covered = set(_run()["control"]["surfaces_with_a_binding_limit"])
        self.assertEqual(
            set(M.SURFACES), covered,
            "контроль обязан покрывать ВСЕ объявленные поверхности — иначе "
            "необъявленная остаётся неизмеренной, а счёт всё равно читается")


# ──────── 3. «Не измерено» — третий исход, а не ноль и не скип ──────────────

class TestUnmeasuredIsItsOwnOutcome(unittest.TestCase):

    def test_a_raising_probe_becomes_unchecked_with_a_reason(self):
        original = M._probe_allowed_assets

        def _boom(*_a, **_k):
            raise RuntimeError("проба сломана намеренно")

        M.OWNER_LIMITS = tuple(
            (k, w, c, _boom if k == "allowed_assets" else p)
            for k, w, c, p in M.OWNER_LIMITS)
        try:
            doc = M.run(write=False, now=NOW)
        finally:
            M.OWNER_LIMITS = tuple(
                (k, w, c, original if k == "allowed_assets" else p)
                for k, w, c, p in M.OWNER_LIMITS)
        entry = _limit(doc, "allowed_assets")
        self.assertEqual(M.UNCHECKED, entry["outcome"])
        self.assertIn("проба сломана намеренно", entry["unchecked_reason"])
        self.assertTrue(
            any("allowed assets" in u for u in doc["unchecked"]),
            "упавшая проба обязана попасть в `unchecked` отчёта, а не исчезнуть")
        self.assertNotEqual(
            "OK", doc["overall"],
            "отчёт с неизмеренным ограничением не имеет права быть зелёным")

    def test_missing_t3_key_refuses_loudly_instead_of_passing(self):
        """Нет ключа T3 ⇒ сказать «не измерено», а не судить по чужому ключу."""
        original = M._t3_probe_keys
        M._t3_probe_keys = lambda: []
        try:
            records = M._probe_allowed_tiers(
                M._healthy_baselines(), M._declared_policy_fields(),
                M._allocator_cap_origin(M.REPO_ROOT))
        finally:
            M._t3_probe_keys = original
        self.assertTrue(
            any("НЕ ИЗМЕРЕНО" in r["detail"] for r in records),
            "отсутствие материала для пробы обязано быть НАЗВАНО")
        self.assertFalse(
            any(r["surface"] == "allocator" and r["axis"] == "threshold"
                for r in records),
            "без ключа T3 нельзя утверждать, что ручка аллокатора повернулась")


# ─────── 4. «Ручка» = поле политики, а не любой поворачиваемый атрибут ──────

class TestAKnobCountsOnlyIfTheOwnerDeclaredIt(unittest.TestCase):

    def test_turning_a_non_policy_dial_does_not_earn_binding(self):
        """Порог, повернувшийся из кода, даёт LITERAL, а не BINDING.

        Воспроизводит настоящий случай `allowed protocols`: допуск решает
        атрибут класса адаптера (`IS_ADVISORY`), он реально работает — и ровно
        поэтому его легко засчитать за выполненное требование
        «policy-configurable», которым он не является.
        """
        outcome, detail = M._classify([
            M._rec("allocator", "quantity", True, "величина спрашивается"),
            M._rec("allocator", "threshold", True, "атрибут класса повернулся"),
        ])
        self.assertEqual(M.LITERAL, outcome)
        self.assertIn("зашит в коде", detail)

    def test_allowed_protocols_is_literal_in_the_real_report(self):
        entry = _limit(_run(), "allowed_protocols")
        self.assertEqual(M.LITERAL, entry["outcome"])
        self.assertEqual(["allocator"], entry["surfaces_binding"])

    def test_declared_but_unasked_is_its_own_dangerous_middle(self):
        """DECLARED_INERT нельзя сливать с ABSENT: в конфиге ручка ВИДНА."""
        outcome, _ = M._classify([
            M._rec("gate", "quantity", False, "величина не спрашивается"),
            M._rec("gate", "threshold", False, "поле объявлено",
                   "max_concentration_t1", "RiskConfig"),
        ])
        self.assertEqual(M.DECLARED_INERT, outcome)

    def test_nothing_at_all_is_absent(self):
        outcome, _ = M._classify([
            M._rec("gate", "quantity", False, "не спрашивается"),
            M._rec("gate", "threshold", False, "поля нет"),
        ])
        self.assertEqual(M.ABSENT, outcome)

    def test_policy_fields_are_measured_not_listed(self):
        fields = M._declared_policy_fields()
        self.assertIn("max_total_t3_allocation", fields["RiskConfig"])
        self.assertIn("min_gain_pp", fields["TriggerParams"])
        self.assertNotIn(
            "IS_ADVISORY", fields["RiskConfig"] | fields["TriggerParams"],
            "признак класса адаптера политикой не объявлен — засчитать его "
            "ручкой значило бы отчитаться о невыполненном требовании")


# ────────── 5. Происхождение потолка аллокатора — разбором дерева ───────────

class TestCapOriginIsParsedNotAssumed(unittest.TestCase):

    def test_known_caps_resolve_to_their_policy_fields(self):
        origins = M._allocator_cap_origin(M.REPO_ROOT)
        self.assertEqual("max_total_t3_allocation", origins.get("T3_TOTAL_CAP"))
        self.assertEqual("max_concentration_t1", origins.get("T1_CAP"))
        self.assertEqual("BASE_CHAIN_CAP", origins.get("BASE_CHAIN_CAP"))

    def test_a_bare_literal_yields_no_origin(self):
        """Потолок-литерал обязан выглядеть литералом, а не полем политики."""
        self.assertIsNone(M._policy_field_in(ast.parse("0.15", mode="eval").body))
        self.assertEqual(
            "max_total_t3_allocation",
            M._policy_field_in(ast.parse(
                'getattr(_POLICY_CONFIG, "max_total_t3_allocation", 0.15)',
                mode="eval").body))


# ──────────── 6. Герметичность: вердикт о КОДЕ, а не о хосте ───────────────

class TestVerdictDoesNotDependOnTheHost(unittest.TestCase):

    def test_an_empty_state_dir_and_the_real_one_give_the_same_tally(self):
        """Тот же вывод при ПУСТОМ и при НАСТОЯЩЕМ каталоге состояния.

        Сравнивать два пустых временных каталога бессмысленно: такая проверка
        зеленеет, ничего не сравнив, и это ровно тот вакуум, ради которого её
        стоило бы и не писать. Здесь одна сторона — живой ``data/`` репозитория,
        другая — пустой каталог; если хоть один вердикт держится на сегодняшнем
        состоянии хоста, счёт разойдётся.
        """
        import os
        real = Path(M.REPO_ROOT) / "data"
        if not real.is_dir():
            self.fail("живого data/ в дереве нет — предпосылка проверки не "
                      "обеспечена, и молча пропустить её нельзя")
        env = os.environ.get("SPA_DATA_DIR")
        tallies = []
        try:
            with tempfile.TemporaryDirectory() as empty:
                for state_dir in (empty, str(real)):
                    os.environ["SPA_DATA_DIR"] = state_dir
                    tallies.append(M.run(write=False, now=NOW)["tally"])
        finally:
            if env is None:
                os.environ.pop("SPA_DATA_DIR", None)
            else:
                os.environ["SPA_DATA_DIR"] = env
        self.assertEqual(
            tallies[0], tallies[1],
            "вердикт §41 обязан говорить о КОДЕ, а не о сегодняшнем состоянии")

    def test_a_root_without_the_source_tree_refuses_instead_of_inventing(self):
        """Корень без исходников ⇒ UNCHECKED, а НЕ «порог зашит в коде».

        Настоящая ошибка, найденная прогоном моста: ``run(root=…)`` на корне,
        где лежит только ``data/``, не находил `allocator.py`, оставался без
        имён полей политики — и `allowed tiers` с `allowed chains` молча
        съезжали с BINDING на LITERAL. Отчёт объявил бы «порог зашит в коде»
        ровно про те потолки, которые читаются из RiskConfig. Fail-OPEN в
        сторону ложной находки тише красного и потому опаснее.
        """
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            doc = M.run(root=tmp, write=False, now=NOW)
        self.assertEqual("UNCHECKED", doc["overall"])
        self.assertFalse(doc["control"]["passed"])
        self.assertIn("allocator.py", doc["control"]["reason"])
        self.assertEqual(len(M.OWNER_LIMITS), doc["tally"][M.UNCHECKED])
        self.assertEqual(
            0, doc["tally"][M.LITERAL],
            "ни одно ограничение не имеет права получить исход «порог зашит в "
            "коде», когда источник порогов просто не прочитан")

    def test_run_with_write_false_touches_no_file(self):
        report = Path(M.REPO_ROOT) / M.REPORT_REL
        before = report.stat().st_mtime if report.exists() else None
        M.run(write=False, now=NOW)
        after = report.stat().st_mtime if report.exists() else None
        self.assertEqual(before, after,
                         "замер без записи не имеет права трогать отчёт")

    def test_report_is_written_where_asked_and_nowhere_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = M.run(root=tmp, write=True, now=NOW)
            written = Path(tmp) / M.REPORT_REL
            self.assertTrue(written.exists())
            self.assertEqual(doc["overall"],
                             json.loads(written.read_text())["overall"])


# ─────────────── 7. Форма отчёта: то, что читают люди и мост ────────────────

class TestReportShape(unittest.TestCase):

    def test_all_twelve_owner_limits_are_present_in_the_owners_order(self):
        doc = _run()
        self.assertEqual(12, doc["limits_total"])
        self.assertEqual([k for k, _, _, _ in M.OWNER_LIMITS],
                         [x["limit"] for x in doc["limits"]])

    def test_tally_sums_to_twelve(self):
        self.assertEqual(12, sum(_run()["tally"].values()))

    def test_every_limit_carries_an_outcome_and_a_measurement(self):
        for entry in _run()["limits"]:
            self.assertIn(entry["outcome"],
                          (M.BINDING, M.LITERAL, M.DECLARED_INERT,
                           M.ABSENT, M.UNCHECKED))
            self.assertTrue(
                entry["detail"] or entry["unchecked_reason"],
                f"{entry['limit']}: исход без объяснения читать нельзя")
            if entry["outcome"] != M.UNCHECKED:
                self.assertTrue(
                    entry["records"],
                    f"{entry['limit']}: исход без единой пробы — это мнение")

    def test_absent_findings_carry_the_experiment_that_produced_them(self):
        """«Ограничения нет» обязано ехать вместе с тем, что было сделано."""
        absent = [f for f in _run()["findings"]
                  if f["code"].startswith("absent:")]
        self.assertTrue(absent)
        for finding in absent:
            self.assertIn("Измерено:", finding["message"])

    def test_gap_findings_disappear_when_the_gap_is_not_recorded(self):
        """Проводка пробелов не украшение: снял `gap` — исчезла находка."""
        with_gap = M._findings(
            [{"limit": "x", "owner_wording": "x", "constrains": "x",
              "outcome": M.BINDING, "detail": "d", "unchecked_reason": "",
              "records": [], "surfaces_binding": ["allocator"],
              "gaps": [{"surface": "gate", "gap": "не судит"}]}],
            True, "", {})[0]
        without = M._findings(
            [{"limit": "x", "owner_wording": "x", "constrains": "x",
              "outcome": M.BINDING, "detail": "d", "unchecked_reason": "",
              "records": [], "surfaces_binding": ["allocator"], "gaps": []}],
            True, "", {})[0]
        self.assertTrue(any(f["code"].startswith("surface_gap:") for f in with_gap))
        self.assertFalse(any(f["code"].startswith("surface_gap:") for f in without))

    def test_advisory_says_the_money_path_is_untouched(self):
        self.assertIn("money-path", _run()["advisory"])

    def test_owner_criterion_is_quoted_not_paraphrased(self):
        criterion = _run()["owner_criterion"]
        for phrase in ("max trade amount", "max daily turnover",
                       "minimum persistence", "maximum acceptable risk delta",
                       "policy-configurable"):
            self.assertIn(phrase, criterion)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
