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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
