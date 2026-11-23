"""Тесты §42 ТЗ «Portfolio CIO» — органы остановки у владельца.

Каждая проверка здесь — положительный контроль над НАСТОЯЩИМ поведением, а не
над пересказом модуля: если завтра `/pause` начнёт держать книгу вместо того,
чтобы её опустошать, красной станет первая же проверка, а не отчёт.

Литеральных pid здесь нет вовсе, а единственная литеральная дата — якорь
инъекции, и обе стороны от него закреплены.
"""
# FROZEN-DATE-OK: injected-clock — литерал `NOW` служит ТОЛЬКО якорем: он
# передаётся параметром `now=` в `M.run(...)` и в `M._separability(...)`, а
# отметка снимка внутри сцены (`_seed_scene`) выводится из того же `now`.
# Стенных часов в вердиктах этого файла нет, поэтому сдвиг календаря их не
# трогает. Единственный, кто здесь спрашивает время у ОС, — канонический
# читатель `agent_health` внутри пробы отделимости; он одинаков в обоих
# прогонах пробы, и сравнивается именно РАЗНИЦА между ними.

from __future__ import annotations

import datetime as dt
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import card_acceptance as CA
from spa_core.monitoring import cio_kill_switch_controls as M

REPO = Path(M.REPO_ROOT)
NOW = dt.datetime(2026, 3, 4, 5, 6, 7, tzinfo=dt.timezone.utc)


def _door(command="/pause", state_file="kill_switch_active.json",
          payload=None, handler="cmd_pause"):
    return {
        "command": command,
        "handler": handler,
        "state_file": state_file,
        "payload": payload if payload is not None
                   else {"active": True, "reason": "manual_telegram",
                         "detail": "Kill-switch armed manually via Telegram /pause"},
        "payload_keys_not_literal": [],
    }


# ─────────────── 1. Ядро: что дверь владельца ДЕЛАЕТ с книгой ────────────────

class TestDoorEffectIsMeasuredOnTheRealPath(unittest.TestCase):
    """Эффект двери меряется настоящими `kill_switch` + `cycle_gates`."""

    def test_pause_door_empties_the_book(self):
        scene = M._scene()
        measured = M._measure_door(_door(), scene)
        self.assertTrue(measured["triggered"])
        self.assertEqual(M.EFFECT_ALL_CASH, measured["effect"])
        self.assertEqual(
            0.0, sum(measured["target_after"].values()),
            "дверь `/pause` обязана оставить книгу пустой — иначе весь вердикт "
            "§42 держится не на измерении")

    def test_resume_door_leaves_the_book_alone(self):
        """Обратный контроль: без взвода путь решения книгу не трогает."""
        scene = M._scene()
        measured = M._measure_door(
            _door(command="/resume", handler="cmd_resume",
                  payload={"active": False, "reason": "manual_telegram_resume"}),
            scene)
        self.assertFalse(measured["triggered"])
        self.assertEqual(M.EFFECT_NO_EFFECT, measured["effect"])
        self.assertEqual(scene["target"], measured["target_after"])

    def test_healthy_scene_keeps_capital_deployed(self):
        """Положительный контроль №1 сам обязан быть верным."""
        healthy = M._healthy_effect(M._scene())
        self.assertFalse(healthy["triggered"])
        self.assertEqual(M.EFFECT_NO_EFFECT, healthy["effect"])

    def test_effect_is_read_from_money_not_from_notes(self):
        """Записка в `notes` не должна решать вердикт: решают деньги."""
        scene = M._scene()
        emptied = {"target": {k: 0.0 for k in scene["held"]}, "notes": []}
        self.assertEqual(M.EFFECT_ALL_CASH, M._classify_effect(scene, emptied))
        chatty = {"target": dict(scene["held"]), "notes": ["что-то сказали"]}
        self.assertEqual(M.EFFECT_HOLD_ONLY, M._classify_effect(scene, chatty))


# ─────────────── 2. Дверь ищется в канале владельца, разбором ────────────────

class TestOwnerChannelEnumeration(unittest.TestCase):

    def test_real_bot_publishes_exactly_two_state_writing_doors(self):
        channel = M._owner_doors(str(REPO))
        self.assertIsNone(channel["unchecked"])
        self.assertIn("/pause", channel["commands"])
        commands = sorted(d["command"] for d in channel["doors"])
        self.assertEqual(
            ["/pause", "/resume"], commands,
            "поверхность остановки владельца изменилась — вердикт §42 обязан "
            "быть перемерен, а не унаследован")
        for door in channel["doors"]:
            self.assertEqual("kill_switch_active.json", door["state_file"])

    def test_payload_is_taken_verbatim_and_non_literals_are_named(self):
        channel = M._owner_doors(str(REPO))
        pause = next(d for d in channel["doors"] if d["command"] == "/pause")
        self.assertIs(True, pause["payload"]["active"])
        self.assertEqual("manual_telegram", pause["payload"]["reason"])
        self.assertIn(
            "set_at", pause["payload_keys_not_literal"],
            "нелитеральные ключи обязаны быть НАЗВАНЫ, а не тихо отброшены")

    def test_unparseable_channel_is_unchecked_not_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            channel = M._owner_doors(tmp)
        self.assertIsNotNone(channel["unchecked"])
        self.assertEqual([], channel["doors"])

    def test_module_never_presses_the_owner_door(self):
        """Модуль не смеет звать `cmd_pause`: это взвело бы боевой кран."""
        source = (REPO / "spa_core" / "monitoring"
                  / "cio_kill_switch_controls.py").read_text(encoding="utf-8")
        body = source.split('"""', 2)[-1]      # без docstring, где имя упомянуто
        for forbidden in ("cmd_pause(", "cmd_resume(", "TelegramBot("):
            self.assertNotIn(forbidden, body)


# ───────────────── 3. Классификация органа: эффект, потом имя ────────────────

class TestControlOutcome(unittest.TestCase):

    def test_matching_effect_wins_over_name(self):
        doors = [dict(_door(), effect=M.EFFECT_HOLD_ONLY)]
        outcome, door, _ = M._control_outcome(M.EFFECT_HOLD_ONLY, ("pause",), doors)
        self.assertEqual(M.PRESENT, outcome)
        self.assertEqual("/pause", door["command"])

    def test_door_wearing_the_name_but_doing_another_thing_is_conflated(self):
        doors = [dict(_door(), effect=M.EFFECT_ALL_CASH)]
        outcome, door, detail = M._control_outcome(
            M.EFFECT_HOLD_ONLY, ("pause",), doors)
        self.assertEqual(M.CONFLATED, outcome)
        self.assertIn("ALL_CASH", detail)
        self.assertEqual("/pause", door["command"])

    def test_no_door_claims_the_name_is_absent_not_conflated(self):
        """Существующий кран не смеет засчитываться КАЖДОМУ органу."""
        doors = [dict(_door(), effect=M.EFFECT_ALL_CASH)]
        outcome, door, _ = M._control_outcome(
            M.EFFECT_HOLD_ONLY, ("pause", "execution"), doors)
        self.assertEqual(M.ABSENT, outcome)
        self.assertIsNone(door)

    def test_idle_door_is_never_credited(self):
        doors = [dict(_door(), effect=M.EFFECT_NO_EFFECT)]
        outcome, _, _ = M._control_outcome(M.EFFECT_HOLD_ONLY, ("pause",), doors)
        self.assertEqual(M.ABSENT, outcome)


# ──────────────────── 4. Положительный контроль ВСЕГО отчёта ────────────────

class TestPositiveControlGovernsTheWholeReport(unittest.TestCase):

    def test_report_on_the_real_tree_passes_control(self):
        doc = M.run(root=str(REPO), write=False, now=NOW)
        self.assertTrue(doc["control"]["passed"], doc["control"]["reason"])
        self.assertEqual(len(M.OWNER_CONTROLS), sum(doc["tally"].values()))

    def test_no_acting_door_makes_the_whole_count_unchecked(self):
        """Дверь, которая ни на что не влияет, обязана снять счёт целиком."""
        original = M._owner_doors
        M._owner_doors = lambda root: {          # noqa: ARG005
            "commands": ["/pause"],
            "doors": [_door(state_file="not_a_stop_signal.json")],
            "unchecked": None,
        }
        try:
            doc = M.run(root=str(REPO), write=False, now=NOW)
        finally:
            M._owner_doors = original
        self.assertFalse(doc["control"]["passed"])
        self.assertEqual("UNCHECKED", doc["overall"])
        self.assertEqual(len(M.OWNER_CONTROLS), doc["tally"][M.UNCHECKED])
        self.assertTrue(doc["unchecked"])
        self.assertEqual([], doc["findings"],
                         "без контроля находки объявлять нельзя")

    def test_broken_healthy_scene_is_unchecked_not_a_finding(self):
        original = M._healthy_effect
        M._healthy_effect = lambda scene: {       # noqa: ARG005
            "triggered": True, "reason": "подстроено",
            "effect": M.EFFECT_ALL_CASH, "target_after": {}}
        try:
            doc = M.run(root=str(REPO), write=False, now=NOW)
        finally:
            M._healthy_effect = original
        self.assertFalse(doc["control"]["passed"])
        self.assertEqual("UNCHECKED", doc["overall"])
        self.assertIn("здоровой сцене", doc["control"]["reason"])


# ──────────────────────── 5. Отделимость наблюдения ─────────────────────────

class TestSeparability(unittest.TestCase):

    def test_real_producers_survive_the_armed_door(self):
        result = M._separability(_door(), NOW)
        self.assertEqual("SEPARABLE", result["verdict"])
        self.assertEqual(len(M._SEPARABILITY_PROBES), len(result["probes"]))
        for probe in result["probes"]:
            self.assertEqual("PRODUCES", probe["outcome"], probe)

    def test_owner_channel_names_the_armed_door_and_it_is_MEASURED(self):
        result = M._separability(_door(), NOW)
        self.assertIn("telegram_warnings_view", result["producers_naming_the_door"])
        view = next(p for p in result["probes"]
                    if p["probe"] == "telegram_warnings_view")
        self.assertNotIn("kill_switch", view["without_door"])
        self.assertIn("kill_switch", view["with_door"])

    def test_producer_that_dies_under_the_door_is_NOT_SEPARABLE(self):
        def dies_when_armed(state_dir):
            if (state_dir / "kill_switch_active.json").exists():
                raise RuntimeError("погашен взведённой дверью")
            return "жив"
        original = M._SEPARABILITY_PROBES
        M._SEPARABILITY_PROBES = (("под_подозрением", "monitoring", dies_when_armed),)
        try:
            result = M._separability(_door(), NOW)
        finally:
            M._SEPARABILITY_PROBES = original
        self.assertEqual("NOT_SEPARABLE", result["verdict"])
        self.assertEqual("STOPS", result["probes"][0]["outcome"])

    def test_producer_broken_without_the_door_is_UNCHECKED_not_a_verdict(self):
        def always_dies(_state_dir):
            raise RuntimeError("сломан сам по себе")
        original = M._SEPARABILITY_PROBES
        M._SEPARABILITY_PROBES = (("сломанный", "monitoring", always_dies),)
        try:
            result = M._separability(_door(), NOW)
        finally:
            M._SEPARABILITY_PROBES = original
        self.assertEqual(M.UNCHECKED, result["verdict"])
        self.assertIn("сломан сам по себе", result["reason"])

    def test_silent_survival_is_named_as_its_own_finding(self):
        original = M._SEPARABILITY_PROBES
        M._SEPARABILITY_PROBES = (("немой", "monitoring", lambda _d: "одно и то же"),)
        try:
            result = M._separability(_door(), NOW)
            findings, _ = M._findings(
                [], {"commands": [], "doors": []}, {}, result, True, "")
        finally:
            M._SEPARABILITY_PROBES = original
        self.assertEqual([], result["producers_naming_the_door"])
        self.assertIn("silent_survival", [f["code"] for f in findings])


# ─────────────────── 6. Проверено и НЕ находка: ключа нет ≡ ноль ────────────

class TestAbsentKeyEqualsExplicitZero(unittest.TestCase):
    """Список all-cash строится из ФИДА — но пропуск ключа книге не помогает."""

    def test_measured_with_the_real_money_functions(self):
        from spa_core.governance.churn_damper import one_sided_turnover
        from spa_core.paper_trading.cycle_runner import _allocation_diff_usd

        held = {"aave_v3": 40_000.0, "pendle": 20_000.0}
        explicit = {k: 0.0 for k in held}
        partial = {"aave_v3": 0.0}          # `pendle` выпал из списка all-cash
        self.assertEqual(_allocation_diff_usd(held, explicit),
                         _allocation_diff_usd(held, partial))
        self.assertEqual(one_sided_turnover(held, explicit),
                         one_sided_turnover(held, partial))


# ──────────────────── 7. Слой решения при взведённой двери ──────────────────

class TestDecisionLayerUnderTheDoor(unittest.TestCase):

    def test_risk_gate_still_approves_while_the_door_is_armed(self):
        decision = M._decision_still_runs(_door(), M._scene())
        self.assertTrue(
            decision["approved"],
            "если гейт перестал одобрять при взведённой двери — «PAUSE CIO» "
            "появился, и вердикт §42 надо перемерить")
        self.assertGreater(decision["proposed_usd"], 0.0)


# ─────────────────────────── 8. Форма отчёта и запись ───────────────────────

class TestReportShape(unittest.TestCase):

    def test_declared_read_schema_is_present_in_the_document(self):
        """Схема, объявленная шагом 0-офис, обязана быть в отчёте."""
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import consume_office_reports as C
        finally:
            sys.path.pop(0)
        declared = C._READ_SCHEMA.get("cio_kill_switch_controls.json")
        self.assertTrue(declared, "артефакт не объявлен шагу 0-офис")
        doc = M.run(root=str(REPO), write=False, now=NOW)
        for path in declared:
            node = doc
            for part in path.split("."):
                self.assertIsInstance(node, dict, path)
                self.assertIn(part, node, f"схема обещает `{path}`")
                node = node[part]

    def test_injected_clock_reaches_the_document(self):
        doc = M.run(root=str(REPO), write=False, now=NOW)
        self.assertEqual(NOW.isoformat(), doc["generated_at"])

    def test_write_lands_under_the_given_root_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spa_core" / "telegram").mkdir(parents=True)
            shutil.copy2(REPO / "spa_core" / "telegram" / "bot.py",
                         root / "spa_core" / "telegram" / "bot.py")
            M.run(root=str(root), write=True, now=NOW)
            written = root / M.REPORT_REL
            self.assertTrue(written.exists())
            doc = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(NOW.isoformat(), doc["generated_at"])

    def test_every_owner_control_carries_a_named_provenance(self):
        """Ни один ожидаемый эффект не назначен модулем от себя."""
        doc = M.run(root=str(REPO), write=False, now=NOW)
        for control in doc["controls"]:
            self.assertIn("ADR-", control["promise_source"], control["control"])


# ──────── 10. Аварийный выход под тримом ADR-850 (ADR-988, ось №1) ──────────

def _trim_that_doses(target_usd, *, current_positions, capital_usd, notes, **_kw):
    """Поддельный Step 2e'': урезает ЛЮБОЙ ход вдвое, включая выход в кэш."""
    half = {p: float(current_positions.get(p, 0.0)) * 0.5
            + float(target_usd.get(p, 0.0)) * 0.5
            for p in set(current_positions) | set(target_usd)}
    return half, {"verdict": "TRIMMED_TO_ADMISSIBLE", "k": 0.5,
                  "damper_reason": "within_limits", "why": "поддельный трим урезал всё"}


def _trim_that_never_trims(target_usd, **_kw):
    """Поддельный трим, который не урезает ничего — контроль обязан это поймать."""
    return dict(target_usd), {"verdict": "ALREADY_WITHIN_SIZE_CAPS", "k": 1.0,
                              "damper_reason": "within_limits", "why": "ничего не делаю"}


def _trim_that_raises(*_a, **_kw):
    raise RuntimeError("дверь трима порвана")


def _trim_silent_untouched(target_usd, *, current_positions, capital_usd, notes, **_kw):
    """Выход не тронут, но причина НЕ дверь демпфера; перетасовку режет честно."""
    deployed = sum(float(v) for v in target_usd.values())
    if deployed <= 0.01:
        return dict(target_usd), {"verdict": "UNMEASURED", "why": "не смог"}
    from spa_core.paper_trading.admissible_trim import apply_admissible_trim
    return apply_admissible_trim(target_usd, current_positions=current_positions,
                                 capital_usd=capital_usd, notes=notes, **_kw)


class TestEmergencyExitUnderTheTrim(unittest.TestCase):
    """Артефакт 29.10 знал две ступени; с ADR-850 в цикле третья — и она ПОСЛЕ крана."""

    def test_real_trim_leaves_the_emergency_exit_whole_and_names_the_reason(self):
        axis = M._trim_under_door(_door(), M._scene(), NOW)
        self.assertEqual(M.TRIM_EXEMPT, axis["verdict"], axis)
        self.assertEqual("NOT_A_RESHUFFLE", axis["exit_trim_verdict"])
        self.assertEqual("derisk_never_damped", axis["exit_damper_reason"],
                         "освобождение обязано приходить из двери демпфера, а не из «не смог»")
        self.assertEqual(axis["exit_target_after_door"], axis["exit_target_after_trim"])
        self.assertTrue(all(v == 0.0 for v in axis["exit_target_after_trim"].values()))

    def test_positive_control_the_same_trim_cuts_a_reshuffle(self):
        axis = M._trim_under_door(_door(), M._scene(), NOW)
        ctl = axis["control"]
        self.assertTrue(ctl["passed"], ctl)
        self.assertEqual("TRIMMED_TO_ADMISSIBLE", ctl["reshuffle_verdict"])
        self.assertLess(float(ctl["k"]), 1.0)
        self.assertGreater(float(ctl["k"]), 0.0)

    def test_a_trim_that_doses_the_exit_is_DOSED_and_CRITICAL(self):
        axis = M._trim_under_door(_door(), M._scene(), NOW, trim=_trim_that_doses)
        self.assertEqual(M.TRIM_DOSED, axis["verdict"], axis)
        findings, unchecked = M._findings(
            [], {"commands": [], "doors": []}, {}, {"verdict": "SEPARABLE", "reason": ""},
            True, "", trim_axis=axis, candidate={"verdict": M.UNCHECKED})
        codes = {f["code"]: f["severity"] for f in findings}
        self.assertEqual("CRITICAL", codes.get("emergency_exit_dosed_by_trim"), codes)

    def test_a_trim_that_trims_nothing_fails_the_control_and_is_UNCHECKED(self):
        """«Выход не урезан» ничего не стоит, если трим не урезает и перетасовку."""
        axis = M._trim_under_door(_door(), M._scene(), NOW, trim=_trim_that_never_trims)
        self.assertEqual(M.UNCHECKED, axis["verdict"], axis)
        self.assertFalse(axis["control"]["passed"])
        self.assertIn("контроль", axis["unchecked_reason"])

    def test_a_torn_trim_door_is_UNCHECKED_not_EXEMPT(self):
        axis = M._trim_under_door(_door(), M._scene(), NOW, trim=_trim_that_raises)
        self.assertEqual(M.UNCHECKED, axis["verdict"])
        self.assertIn("дверь трима порвана", axis["unchecked_reason"])

    def test_untouched_exit_without_a_named_reason_is_UNCHECKED(self):
        """Книга цела, но освобождение не доказано дверью — третий исход, не EXEMPT."""
        axis = M._trim_under_door(_door(), M._scene(), NOW, trim=_trim_silent_untouched)
        self.assertEqual(M.UNCHECKED, axis["verdict"], axis)
        self.assertTrue(axis["control"]["passed"], "перетасовку этот трим режет честно")
        self.assertIn("не названа", axis["unchecked_reason"])

    def test_exempt_exit_is_an_INFO_finding_that_cites_the_control(self):
        axis = M._trim_under_door(_door(), M._scene(), NOW)
        findings, unchecked = M._findings(
            [], {"commands": [], "doors": []}, {}, {"verdict": "SEPARABLE", "reason": ""},
            True, "", trim_axis=axis, candidate={"verdict": M.UNCHECKED})
        info = next(f for f in findings if f["code"] == "emergency_exit_survives_trim")
        self.assertEqual("INFO", info["severity"])
        self.assertIn("k=0.75", info["message"])
        self.assertTrue(any("PAUSE AUTO EXECUTION" in u for u in unchecked),
                        "неизмеренный кандидат обязан быть назван, а не пропущен")

    def test_the_real_report_carries_the_axis_and_it_is_EXEMPT(self):
        doc = M.run(root=str(REPO), write=False, now=NOW)
        self.assertEqual(M.TRIM_EXEMPT, doc["trim_under_door"]["verdict"])
        self.assertEqual("/pause", doc["trim_under_door"]["door"])


# ──── 11. Кандидат органа PAUSE AUTO EXECUTION — взвод CIO (ADR-988, ось №2) ────

def _channel():
    return {"commands": ["/pause", "/resume"],
            "doors": [_door(), _door("/resume", handler="cmd_resume",
                                    payload={"active": False,
                                             "reason": "manual_telegram_resume"})]}


class TestPauseAutoExecutionCandidate(unittest.TestCase):

    def test_arming_state_is_a_code_constant_with_three_books_and_no_runtime_door(self):
        decl = M._arming_declaration(str(REPO))
        self.assertIsNone(decl["unchecked"])
        self.assertEqual("code_constant", decl["state_lives_in"])
        self.assertEqual(["aggressive", "balanced", "conservative"], decl["books"])
        self.assertEqual([], decl["reads_at_runtime"],
                         "взвод читает файл/окружение — у органа появилась дверь, перемерить")

    def test_real_arming_door_answers_UNARMED_allowed_so_the_candidate_is_NOT_THE_ORGAN(self):
        cand = M._pause_auto_execution_candidate(str(REPO), M._scene(), _channel())
        self.assertEqual(M.CANDIDATE_NOT_THE_ORGAN, cand["verdict"], cand)
        self.assertIsNone(cand["owner_door"])
        self.assertEqual(["kill_switch_active.json"], cand["owner_channel_state_files"])
        self.assertTrue(cand["unarmed_book_reshuffle"]["allowed"])
        self.assertEqual("UNARMED", cand["unarmed_book_reshuffle"]["decision"])
        self.assertFalse(cand["armed_book_reshuffle"]["allowed"],
                         "взведённая книга без вердикта CIO обязана держать (fail-CLOSED)")
        self.assertEqual("HOLD", cand["armed_book_reshuffle"]["decision"])

    def test_a_door_that_would_hold_makes_the_candidate_WOULD_HOLD(self):
        def holding_door(book_id, cio_doc, cur, tgt, damper_reason=None):
            return (False, "HOLD", "поддельный взвод держит всё")
        cand = M._pause_auto_execution_candidate(str(REPO), M._scene(), _channel(),
                                                 trade_allowed=holding_door)
        self.assertEqual(M.CANDIDATE_WOULD_HOLD, cand["verdict"], cand)

    def test_unparseable_arming_file_is_UNCHECKED_with_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand = M._pause_auto_execution_candidate(tmp, M._scene(), _channel())
        self.assertEqual(M.UNCHECKED, cand["verdict"])
        self.assertIn("не разобран", cand["unchecked_reason"])

    def test_a_torn_arming_door_is_UNCHECKED_not_a_verdict(self):
        def torn(*_a, **_k):
            raise RuntimeError("дверь взвода порвана")
        cand = M._pause_auto_execution_candidate(str(REPO), M._scene(), _channel(),
                                                 trade_allowed=torn)
        self.assertEqual(M.UNCHECKED, cand["verdict"])
        self.assertIn("дверь взвода порвана", cand["unchecked_reason"])

    def test_arming_declared_as_non_literal_is_named_not_assumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / M.ARMING_REL
            target.parent.mkdir(parents=True)
            target.write_text("import json\nARMED_BOOKS = json.load(open('x.json'))\n",
                              encoding="utf-8")
            decl = M._arming_declaration(str(root))
        self.assertEqual("not_a_literal", decl["state_lives_in"])
        self.assertIn("open", decl["reads_at_runtime"])
        self.assertIn("load", decl["reads_at_runtime"])

    def test_not_the_organ_is_a_WARN_finding(self):
        cand = M._pause_auto_execution_candidate(str(REPO), M._scene(), _channel())
        findings, _ = M._findings(
            [], {"commands": [], "doors": []}, {}, {"verdict": "SEPARABLE", "reason": ""},
            True, "", trim_axis={"verdict": M.TRIM_EXEMPT, "detail": "", "control": {"k": 1}},
            candidate=cand)
        codes = {f["code"]: f["severity"] for f in findings}
        self.assertEqual("WARN", codes.get("pause_auto_execution_candidate_is_not_the_organ"), codes)

    def test_the_real_report_carries_the_candidate_and_ABSENT_stands(self):
        doc = M.run(root=str(REPO), write=False, now=NOW)
        self.assertEqual(M.CANDIDATE_NOT_THE_ORGAN,
                         doc["pause_auto_execution_candidate"]["verdict"])
        pae = next(c for c in doc["controls"] if c["control"] == "pause_auto_execution")
        self.assertEqual(M.ABSENT, pae["outcome"],
                         "кандидат отвергнут измерением — орган по-прежнему ABSENT")

    def test_office_step_prints_both_axes_and_names_an_older_artifact(self):
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import consume_office_reports as C
        finally:
            sys.path.pop(0)
        declared = C._READ_SCHEMA["cio_kill_switch_controls.json"]
        self.assertIn("trim_under_door", declared)
        self.assertIn("pause_auto_execution_candidate", declared)
        source = (REPO / "scripts" / "consume_office_reports.py").read_text(encoding="utf-8")
        self.assertIn("аварийный выход под тримом ADR-850", source)
        self.assertIn("кандидат органа PAUSE AUTO EXECUTION", source)
        self.assertIn("артефакт снят прибором без этой оси", source,
                      "артефакт прежней версии обязан печататься как НЕ ИЗМЕРЕНО")


# ───────────────────────────── 9. ПРОВОДКА ──────────────────────────────────

class TestWiring(unittest.TestCase):
    """Измеритель без вызывающего и без дома — украшение.

    Существующие парити-сторожа этот артефакт НЕ держат: замер 07.09 — снятие
    его из `PRODUCES` моста не покраснило ни `test_contract_manifest_parity`,
    ни `test_artifact_contract`. Поэтому проводка держится ЗДЕСЬ, и держится
    ФОРМОЙ вызова: упоминание имени в файле проводкой не является (подмена
    импорта псевдонимом оставляет имя на месте, а считать начинает чужое).
    """

    ARTIFACT = "data/cio_kill_switch_controls.json"

    def test_bridge_declares_and_actually_calls_the_measurer(self):
        import ast as _ast
        from spa_core.monitoring import findings_bridge

        self.assertIn(self.ARTIFACT, findings_bridge.PRODUCES)
        source = (REPO / "spa_core" / "monitoring"
                  / "findings_bridge.py").read_text(encoding="utf-8")
        tree = _ast.parse(source)
        alias = None
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ImportFrom) and node.module == "spa_core.monitoring":
                for name in node.names:
                    if name.name == "cio_kill_switch_controls":
                        alias = name.asname or name.name
        self.assertIsNotNone(alias, "мост не импортирует измеритель")
        called = any(
            isinstance(n, _ast.Call)
            and isinstance(n.func, _ast.Attribute) and n.func.attr == "run"
            and isinstance(n.func.value, _ast.Name) and n.func.value.id == alias
            for n in _ast.walk(tree))
        self.assertTrue(called, "мост импортирует измеритель, но не зовёт `run`")

    def test_artifact_has_BOTH_manifest_entries(self):
        manifest = json.loads(
            (REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        entry = next((a for a in manifest["artifacts"]
                      if a.get("path") == self.ARTIFACT), None)
        self.assertIsNotNone(entry, "нет записи в artifacts[] — артефакт бездомный")
        self.assertEqual("active", entry["status"])
        self.assertEqual("com.spa.decision_loop", entry["producer"])
        self.assertIn("orchestrator_protocol", entry["consumers"],
                      "без потребителя шаг 0-офис артефакт не прочитает")
        agent = next(a for a in manifest["agents"]
                     if a.get("label") == "com.spa.decision_loop")
        self.assertIn(self.ARTIFACT,
                      [p.get("artifact") for p in agent["produces"]],
                      "паспорт производителя не называет артефакт — это ВТОРАЯ "
                      "запись, и именно её обычно забывают")

    def test_office_step_can_read_and_print_the_artifact(self):
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import consume_office_reports as C
        finally:
            sys.path.pop(0)
        name = "cio_kill_switch_controls.json"
        self.assertIn(name, C._READ_SCHEMA)
        self.assertEqual("spa_core/monitoring/cio_kill_switch_controls.py",
                         C._PRODUCER[name])
        source = (REPO / "scripts"
                  / "consume_office_reports.py").read_text(encoding="utf-8")
        self.assertIn(f'elif name == "{name}":', source,
                      "у артефакта нет ИМЕННОЙ печатающей ветки — он попадёт в "
                      "generic-разбор и вопрос §42 в контекст не приедет")


# ── 9. §50: критерий «Есть owner pause/kill switch» получил мерку (ADR-1076) ──
#
# Пятьдесят циклов §50 приказа читали ОДНОЙ приёмкой меньше, а у этого критерия
# не было мерки вовсе — при том, что прибор §42 выше мерит его дословно и с
# 12.11 докладывает `CRITICAL`. Ниже — проба, объявившая себя этой меркой, и её
# контроли в ОБЕ стороны (`.claude/rules/acceptance.md`, п. 3).
#
# Зелёного МИРА на настоящем пути решения сегодня нет: ни одна нагрузка двери не
# даёт `HOLD_ONLY` (поэтому орган PAUSE AUTO EXECUTION и числится `ABSENT`), и
# положительный контроль «проба УМЕЕТ сказать satisfied» предъявляется двери
# вердикта замером той формы, что производит прибор. Сцены же самого прибора
# идут по настоящим деревьям — там у пробы есть вход `repo_root`.

S50_PROBE = "owner_has_the_three_stop_organs"
S50_CRITERION = "Есть owner pause/kill switch."

_BOT_TEMPLATE = '''from pathlib import Path

DATA_DIR = Path("data")
KILL_SWITCH_FILE = DATA_DIR / "kill_switch_active.json"


class TelegramBot:
    def _dispatch(self, command):
        handlers = {
%(handlers)s
        }
        return handlers.get(command)
%(methods)s
'''


def _bot_tree(doors, *, claims=()) -> str:
    """Одноразовое дерево с каналом владельца заданной формы.

    `doors` — список `(команда, обработчик, причина)`; каждая ПИШЕТ файл
    состояния настоящего стоп-крана. Форма файла — ровно та, которую разбирает
    `_owner_doors` (константа-путь, карта «команда → self.метод»,
    `_atomic_write_json` с литеральной нагрузкой).

    `claims` — список `(команда, обработчик, текст)`: команда владельцу
    ОПУБЛИКОВАНА и словами органа называется, но состояния не пишет НИЧЕГО.
    Это материал контроля «подстрокой проба не проходит» (ADR-333).
    """
    handlers = "\n".join(f'            "{cmd}": self.{fn},'
                         for cmd, fn, _ in list(doors) + list(claims))
    methods = "".join(
        f'''
    def {fn}(self):
        _atomic_write_json(KILL_SWITCH_FILE, {{"active": True, "reason": "{why}"}})
''' for _, fn, why in doors)
    methods += "".join(
        f'''
    def {fn}(self):
        """{text}"""
        return "{text}"
''' for _, fn, text in claims)
    root = Path(tempfile.mkdtemp(prefix="cio_ks_tree_"))
    channel = root / M.OWNER_CHANNEL_REL
    channel.parent.mkdir(parents=True, exist_ok=True)
    channel.write_text(
        _BOT_TEMPLATE % {"handlers": handlers, "methods": methods},
        encoding="utf-8")
    return str(root)


def _measured(outcomes: dict | None = None, *, control_passed: bool = True,
              separability: str = "SEPARABLE",
              sep_reason: str = "все 3 производителя продолжают производить",
              unchecked_reason: str = "сцена: орган не измерен") -> dict:
    """Замер §42 той формы, которую производит `M.run` — сцена двери вердикта.

    Органы берутся из `M.OWNER_CONTROLS`, а не из списка в тесте: перепиши
    владелец свои три имени — сцены поедут за ним, а не разойдутся молча.
    """
    outcomes = outcomes or {}
    controls = []
    for key, wording, promise, promised, source, words in M.OWNER_CONTROLS:
        outcome = outcomes.get(key, M.PRESENT)
        effect = (promised if outcome == M.PRESENT
                  else M.EFFECT_ALL_CASH if outcome == M.CONFLATED
                  else M.EFFECT_UNMEASURED)
        controls.append({
            "control": key, "owner_wording": wording, "promise": promise,
            "promised_effect": promised, "promise_source": source,
            "claim_words": list(words), "outcome": outcome,
            "door": None if outcome == M.ABSENT else "/kill",
            "measured_effect": effect,
            "detail": "" if outcome == M.PRESENT else f"сцена: {outcome}",
            "unchecked_reason": (unchecked_reason if outcome == M.UNCHECKED else ""),
        })
    return {
        "controls": controls,
        "control": {"passed": control_passed,
                    "reason": "" if control_passed
                              else "ни одна дверь владельца не изменила путь решения"},
        "separability": {"verdict": separability, "reason": sep_reason, "probes": []},
        "tally": {o: sum(1 for c in controls if c["outcome"] == o)
                  for o in (M.PRESENT, M.CONFLATED, M.ABSENT, M.UNCHECKED)},
    }


class TestTheMeasureIsDeclaredForTheOwnersCriterion(unittest.TestCase):
    """Объявление мерки — и его паритет с КАРТОЧКОЙ владельца."""

    def test_probe_is_registered_and_the_tree_reaches_it(self):
        self.assertIn(S50_PROBE, CA.PROBES)
        self.assertEqual(("repo_root",), CA.probe_tree_inputs(S50_PROBE),
                         "без входа `repo_root` проба судила бы СВОЁ дерево, а "
                         "читатель напечатал бы вердикт о чужом")

    def test_declaration_is_byte_exact_with_the_owner_card(self):
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import cio_dod_rollup as DOD
        finally:
            sys.path.pop(0)
        card = Path(M.REPO_ROOT) / DOD.CARD_REL
        self.assertTrue(card.exists(),
                        f"карточки приказа нет в дереве ({card}) — паритет "
                        "объявления с владельцем НЕ ИЗМЕРЕН")
        population = DOD.parse_s50_criteria(card.read_text(encoding="utf-8"))
        self.assertIn(S50_CRITERION, population["criteria"],
                      "строка объявления разошлась с §50 карточки — объявление "
                      "стало СИРОТОЙ, и сводка доложит критерий без мерки")

    def test_the_criterion_has_exactly_one_measure(self):
        self.assertEqual([S50_PROBE],
                         CA.probes_by_s50_criterion().get(S50_CRITERION),
                         "две пробы на один критерий — столкновение объявлений")

    def test_probe_rejects_an_argument(self):
        status, why = CA.run_probe(f"{S50_PROBE}:kill")
        self.assertEqual(CA.UNMEASURED, status)
        self.assertIn("не принимает аргумента", why)


class TestTheVerdictDoorIsGreenOnAWholeContour(unittest.TestCase):
    """Положительный контроль: `satisfied` ДОСТИЖИМ, иначе проба — штамп."""

    def test_three_present_organs_and_a_separable_door_are_satisfied(self):
        status, why = CA.owner_stop_organs_verdict(_measured())
        self.assertEqual(CA.SATISFIED, status, why)
        for _, wording, *_ in M.OWNER_CONTROLS:
            self.assertIn(wording, why,
                          "зелёный вердикт обязан называть ВСЕ три органа — "
                          "иначе он не о требовании владельца")

    def test_the_green_verdict_names_what_was_measured_not_what_was_promised(self):
        status, why = CA.owner_stop_organs_verdict(_measured())
        self.assertEqual(CA.SATISFIED, status)
        self.assertIn(M.EFFECT_ALL_CASH, why)
        self.assertIn(M.EFFECT_HOLD_ONLY, why)


class TestTheVerdictDoorIsRedOnEveryBrokenLink(unittest.TestCase):
    """Красное — на КАЖДОМ порванном звене, и звено НАЗВАНО."""

    def test_every_absent_organ_is_named_one_at_a_time(self):
        for key, wording, *_ in M.OWNER_CONTROLS:
            with self.subTest(organ=key):
                status, why = CA.owner_stop_organs_verdict(
                    _measured({key: M.ABSENT}))
                self.assertEqual(CA.NOT_SATISFIED, status, why)
                self.assertIn(wording, why)
                self.assertIn(M.ABSENT, why)

    def test_every_conflated_organ_is_named_with_its_measured_effect(self):
        for key, wording, _promise, promised, *_ in M.OWNER_CONTROLS:
            if promised == M.EFFECT_ALL_CASH:
                continue   # сцена CONFLATED строится подменой эффекта на ALL_CASH
            with self.subTest(organ=key):
                status, why = CA.owner_stop_organs_verdict(
                    _measured({key: M.CONFLATED}))
                self.assertEqual(CA.NOT_SATISFIED, status, why)
                self.assertIn(wording, why)
                self.assertIn(M.CONFLATED, why)
                self.assertIn(M.EFFECT_ALL_CASH, why)

    def test_a_door_that_silences_monitoring_is_not_satisfied(self):
        status, why = CA.owner_stop_organs_verdict(
            _measured(separability="NOT_SEPARABLE",
                      sep_reason="дверь гасит: portfolio_health (monitoring)"))
        self.assertEqual(CA.NOT_SATISFIED, status, why)
        self.assertIn("portfolio_health", why,
                      "вторая половина §42 обязана называть ПОГАШЕННОГО "
                      "производителя, а не просто краснеть")

    def test_a_present_organ_is_not_named_among_the_broken(self):
        key, wording = M.OWNER_CONTROLS[0][0], M.OWNER_CONTROLS[0][1]
        status, why = CA.owner_stop_organs_verdict(_measured({key: M.ABSENT}))
        self.assertEqual(CA.NOT_SATISFIED, status)
        for other_key, other_wording, *_ in M.OWNER_CONTROLS[1:]:
            self.assertNotIn(other_wording, why,
                             f"исправный орган {other_key} назван сломанным — "
                             "владелец пойдёт починять работающую ручку")
        self.assertIn(wording, why)


class TestTheThirdOutcomeIsItsOwn(unittest.TestCase):
    """«Не измерено» никогда не выдаётся ни за находку, ни за чистое (инв. #17)."""

    def test_an_unchecked_organ_is_unmeasured_not_a_finding(self):
        status, why = CA.owner_stop_organs_verdict(
            _measured({"emergency_stop": M.UNCHECKED}))
        self.assertEqual(CA.UNMEASURED, status, why)
        self.assertIn("EMERGENCY STOP", why)
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_unchecked_separability_is_unmeasured(self):
        status, why = CA.owner_stop_organs_verdict(
            _measured(separability=M.UNCHECKED,
                      sep_reason="не измерено: portfolio_health — ImportError"))
        self.assertEqual(CA.UNMEASURED, status, why)
        self.assertIn("portfolio_health", why)

    def test_a_failed_self_control_is_unmeasured_and_names_the_reason(self):
        status, why = CA.owner_stop_organs_verdict(_measured(control_passed=False))
        self.assertEqual(CA.UNMEASURED, status, why)
        self.assertIn("не измерен ни у одной", why)
        self.assertIn("не изменила путь решения", why)

    def test_a_document_that_is_not_the_instruments_is_unmeasured(self):
        for scene in (None, [], {}, {"controls": []}, "ALL_CASH"):
            with self.subTest(scene=repr(scene)[:20]):
                status, _ = CA.owner_stop_organs_verdict(scene)
                self.assertEqual(CA.UNMEASURED, status)


class TestTheProbeMeasuresRealTrees(unittest.TestCase):
    """Сквозь настоящий прибор — по деревьям, а не по пересказу его вывода."""

    def setUp(self):
        self._trees: list[str] = []

    def tearDown(self):
        for tree in self._trees:
            shutil.rmtree(tree, ignore_errors=True)

    def _tree(self, doors, **kw) -> str:
        tree = _bot_tree(doors, **kw)
        self._trees.append(tree)
        return tree

    def test_a_tree_without_the_owner_channel_is_unmeasured(self):
        empty = tempfile.mkdtemp(prefix="cio_ks_empty_")
        self._trees.append(empty)
        status, why = CA.run_probe(S50_PROBE, repo_root=empty)
        self.assertEqual(CA.UNMEASURED, status, why)
        self.assertIn("канал владельца не разобран", why)

    def test_a_channel_without_a_state_door_is_unmeasured_not_absent(self):
        tree = self._tree([])
        status, why = CA.run_probe(S50_PROBE, repo_root=tree)
        self.assertEqual(CA.UNMEASURED, status, why)
        self.assertIn("не измерен ни у одной", why)

    def test_a_kill_only_tree_names_the_two_missing_organs(self):
        tree = self._tree([("/kill", "cmd_kill", "manual_kill")])
        status, why = CA.run_probe(S50_PROBE, repo_root=tree)
        self.assertEqual(CA.NOT_SATISFIED, status, why)
        self.assertIn("PAUSE CIO", why)
        self.assertIn("PAUSE AUTO EXECUTION", why)
        self.assertNotIn("EMERGENCY STOP", why,
                         "аварийная остановка на этом дереве ЕСТЬ и измерена — "
                         "называть её сломанной значит врать в обе стороны")

    def test_a_live_shaped_tree_reports_pause_as_conflated(self):
        tree = self._tree([("/kill", "cmd_kill", "manual_kill"),
                           ("/pause", "cmd_pause", "manual_telegram")])
        status, why = CA.run_probe(S50_PROBE, repo_root=tree)
        self.assertEqual(CA.NOT_SATISFIED, status, why)
        self.assertIn(M.CONFLATED, why)
        self.assertIn("PAUSE CIO", why)

    def test_words_in_a_docstring_are_not_an_organ(self):
        """ADR-333: подстрокой проба не проходит."""
        tree = self._tree(
            [("/kill", "cmd_kill", "manual_kill")],
            claims=[("/pause_execution", "cmd_pause_execution",
                     "pause auto execution: ставит автоисполнение на паузу")])
        status, why = CA.run_probe(S50_PROBE, repo_root=tree)
        self.assertEqual(CA.NOT_SATISFIED, status, why)
        self.assertIn("PAUSE AUTO EXECUTION", why)
        self.assertIn(M.ABSENT, why,
                      "команда названа словами органа, но состояния не пишет — "
                      "это ABSENT; зачти её, и критерий закрывался бы текстом")
        self.assertNotIn(M.PRESENT + ":", why)

    def test_the_probe_writes_nothing_into_the_tree(self):
        tree = self._tree([("/kill", "cmd_kill", "manual_kill")])
        before = sorted(str(p.relative_to(tree))
                        for p in Path(tree).rglob("*") if p.is_file())
        CA.run_probe(S50_PROBE, repo_root=tree)
        after = sorted(str(p.relative_to(tree))
                       for p in Path(tree).rglob("*") if p.is_file())
        self.assertEqual(before, after,
                         "проба обязана только ЧИТАТЬ: отчёт прибора пишется "
                         "лишь при `write=True`")

    def test_the_repo_root_input_changes_the_verdict(self):
        """Инъекция обязана доходить до прибора, а не быть параметром-украшением."""
        kill_only = CA.run_probe(
            S50_PROBE, repo_root=self._tree([("/kill", "cmd_kill", "manual_kill")]))
        empty = tempfile.mkdtemp(prefix="cio_ks_empty2_")
        self._trees.append(empty)
        no_channel = CA.run_probe(S50_PROBE, repo_root=empty)
        self.assertEqual(CA.NOT_SATISFIED, kill_only[0])
        self.assertEqual(CA.UNMEASURED, no_channel[0])

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
