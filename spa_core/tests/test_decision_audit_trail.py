"""Сторож §43 ТЗ CIO: объяснима ли прошлая перекладка ЧЕРЕЗ ДАННЫЕ.

Каждый тест ниже — положительный контроль на состояние, ИЗМЕРЕННОЕ в живом
дереве 06.09 (цикл #506) по 44 реальным перекладкам ``data/audit_trail.jsonl``:

* ``market snapshot`` не восстановим ни по одной — ``protocol_history`` пуст, а
  ``snapshot_id`` именует прогон;
* ``policy version`` и ``configuration version`` не пишет ни одно событие цикла,
  хотя сами значения (`v1.0`, `2026-05-20`) существуют;
* ``optimizer version`` — это ИМЯ модели, а не версия;
* ``calculations`` — в цепочке хода нет ни одной величины, из которой следует
  цель; строки вердикта гейта объясняют ОТКАЗ, а не выбор;
* ``trade_id`` назван дважды и более у 12 из 30 значений.

Модуль ничего не гейтит — он МЕРЯЕТ и НАЗЫВАЕТ, поэтому вся его польза живёт в
проводке (кто зовёт, кто читает), и ровно она обычно пропадает молча. Проводка
здесь проверяется ФОРМОЙ ВЫЗОВА и ПОВЕДЕНИЕМ читателя, а не именем в тексте.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest

from spa_core.monitoring import decision_audit_trail as m

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# FROZEN-DATE-OK: injected-clock — NOW уезжает в `run(now=)`, и ВСЕ отметки
# фикстур ниже производятся от него же (`_d`). Календарь хоста не участвует ни
# в одном вердикте этого файла.
NOW = dt.datetime(2026, 9, 6, 12, tzinfo=dt.timezone.utc)


def _d(days_ago: int) -> str:
    """Дата-строка, отсчитанная ОТ ЯКОРЯ, а не от календаря машины."""
    return (NOW - dt.timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _ts(days_ago: int) -> str:
    return (NOW - dt.timedelta(days=days_ago)).isoformat()


def _chain(days_ago: int, *, trade_id: str = "T001", corr: str = "c1",
           proposal: dict | None = None, verdict: dict | None = None,
           move: dict | None = None) -> list[dict]:
    """Одна цепочка цикла: старт → предложение → вердикт гейта → ход."""
    ts = _ts(days_ago)
    events = [
        {"event_type": "cycle_start", "correlation_id": corr, "timestamp": ts,
         "snapshot_id": f"{_d(days_ago)}:deadbeefdeadbeef",
         "data": {"cycle_date": _d(days_ago)}},
        {"event_type": "allocation_proposal", "correlation_id": corr, "timestamp": ts,
         "data": proposal if proposal is not None
         else {"target_usd": {"aave_v3": 40000.0}, "model_used": "optimized_yield"}},
        {"event_type": "risk_verdict", "correlation_id": corr, "timestamp": ts,
         "data": verdict if verdict is not None
         else {"approved": True, "violations": [], "warnings": []}},
        {"event_type": "trade_executed", "correlation_id": corr, "timestamp": ts,
         "data": move if move is not None
         else {"trade_id": trade_id, "diff_usd": 12000.0,
               "from_allocation": {"aave_v3": 52000.0},
               "to_allocation": {"aave_v3": 40000.0, "morpho_blue": 12000.0}}},
    ]
    return events


class _Tree:
    """Одноразовое дерево: только те файлы, которые тест назвал сам."""

    def __init__(self, events: list[dict] | None, **files: object):
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name
        os.makedirs(os.path.join(self.root, "data"), exist_ok=True)
        if events is not None:
            with open(os.path.join(self.root, m.TRAIL_REL), "w", encoding="utf-8") as fh:
                for e in events:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        for rel, payload in files.items():
            path = os.path.join(self.root, getattr(m, rel))
            with open(path, "w", encoding="utf-8") as fh:
                if rel.endswith("_REL") and str(payload).startswith("RAW:"):
                    fh.write(str(payload)[4:])
                else:
                    json.dump(payload, fh, ensure_ascii=False)

    def run(self, **kw):
        return m.run(root=self.root, now=NOW, write=False, **kw)

    def close(self):
        self.dir.cleanup()


def _field(doc: dict, key: str) -> dict:
    return doc["owner_fields"][key]


def _codes(doc: dict) -> set:
    return {f["code"] for f in doc["findings"]}


class TestOwnerFieldList(unittest.TestCase):
    """Девять полей — список ВЛАДЕЛЬЦА, а не наш."""

    def test_exactly_the_nine_fields_of_the_order(self):
        self.assertEqual(
            [k for k, _ in m.OWNER_FIELDS],
            ["market_snapshot", "portfolio_snapshot", "policy_version",
             "configuration_version", "optimizer_version", "decision",
             "calculations", "execution_result", "post_trade_result"])

    def test_owner_horizon_carries_its_provenance(self):
        # Месяц — литерал ВЛАДЕЛЬЦА. Число без происхождения через месяц
        # неотличимо от подобранного нами.
        self.assertIn("§43", m.OWNER_HORIZON_PROVENANCE)
        self.assertEqual(m.OWNER_HORIZON_DAYS, 30)


class TestMarketSnapshot(unittest.TestCase):
    """Замер 06.09: истории ставок по протоколам не ведёт НИКТО."""

    def test_absent_when_protocol_history_is_empty(self):
        t = _Tree(_chain(40), APY_HISTORY_REL={"protocol_history": {}})
        try:
            doc = t.run()
            f = _field(doc, "market_snapshot")
            self.assertEqual(f["counts"][m.ABSENT], 1)
            self.assertIn("не ведёт никто", f["detail"])
        finally:
            t.close()

    def test_present_when_history_carries_that_day(self):
        # Обратная сторона: сторож обязан ЗЕЛЕНЕТЬ на почине, иначе он мерит
        # не восстановимость, а собственное настроение.
        day = _d(40)
        t = _Tree(_chain(40),
                  APY_HISTORY_REL={"protocol_history": {"aave_v3": {day: 2.7},
                                                        "morpho_blue": {day: 4.5}}})
        try:
            f = _field(t.run(), "market_snapshot")
            self.assertEqual(f["counts"][m.PRESENT], 1)
            self.assertIn("2 протокол", f["detail"])
        finally:
            t.close()

    def test_absent_when_history_has_other_days_only(self):
        t = _Tree(_chain(40),
                  APY_HISTORY_REL={"protocol_history": {"aave_v3": {_d(3): 2.7}}})
        try:
            f = _field(t.run(), "market_snapshot")
            self.assertEqual(f["counts"][m.ABSENT], 1)
        finally:
            t.close()

    def test_unreadable_history_is_unmeasured_not_absent(self):
        # Третий исход самостоятелен: «файл нечитаем» ≠ «данных нет».
        t = _Tree(_chain(40))
        try:
            f = _field(t.run(), "market_snapshot")
            self.assertEqual(f["counts"][m.UNMEASURED], 1)
            self.assertEqual(f["counts"][m.ABSENT], 0)
        finally:
            t.close()


class TestVersionsAreNotRecorded(unittest.TestCase):
    """Замер 06.09: значения существуют, а записи рядом с решением нет."""

    def test_policy_version_absent_and_names_the_live_value(self):
        t = _Tree(_chain(40))
        try:
            f = _field(t.run(), "policy_version")
            self.assertEqual(f["counts"][m.ABSENT], 1)
            self.assertIn("теряется не значение", f["detail"])
        finally:
            t.close()

    def test_policy_version_present_when_the_verdict_carries_it(self):
        t = _Tree(_chain(40, verdict={"approved": True, "policy_version": "v1.0"}))
        try:
            f = _field(t.run(), "policy_version")
            self.assertEqual(f["counts"][m.PRESENT], 1)
            self.assertEqual(f["detail"], "v1.0")
        finally:
            t.close()

    def test_configuration_version_absent(self):
        t = _Tree(_chain(40))
        try:
            self.assertEqual(_field(t.run(), "configuration_version")["counts"][m.ABSENT], 1)
        finally:
            t.close()

    def test_empty_string_is_not_a_version(self):
        # Пустая строка прошла бы проверку «ключ есть» и объявила бы поле
        # записанным, ничего не записав.
        t = _Tree(_chain(40, verdict={"approved": True, "policy_version": ""}))
        try:
            self.assertEqual(_field(t.run(), "policy_version")["counts"][m.ABSENT], 1)
        finally:
            t.close()


class TestOptimizerVersion(unittest.TestCase):
    def test_model_name_is_partial_not_present(self):
        t = _Tree(_chain(40))
        try:
            f = _field(t.run(), "optimizer_version")
            self.assertEqual(f["counts"][m.PARTIAL], 1)
            self.assertIn("ИМЯ модели", f["detail"])
        finally:
            t.close()

    def test_absent_when_no_model_recorded(self):
        t = _Tree(_chain(40, proposal={"target_usd": {"aave_v3": 1.0}}))
        try:
            self.assertEqual(_field(t.run(), "optimizer_version")["counts"][m.ABSENT], 1)
        finally:
            t.close()


class TestCalculations(unittest.TestCase):
    """«Из чего следует цель» — вопрос, на который трейл не отвечает."""

    def test_absent_when_chain_carries_no_numbers(self):
        t = _Tree(_chain(40))
        try:
            f = _field(t.run(), "calculations")
            self.assertEqual(f["counts"][m.ABSENT], 1)
        finally:
            t.close()

    def test_gate_reasons_are_partial_and_named_as_refusal(self):
        t = _Tree(_chain(40, verdict={"approved": True, "violations": [],
                                      "warnings": ["Concentration 37.9% approaching limit"]}))
        try:
            f = _field(t.run(), "calculations")
            self.assertEqual(f["counts"][m.PARTIAL], 1)
            self.assertIn("ОТКАЗА", f["detail"])
        finally:
            t.close()

    def test_shadow_numbers_are_not_offered_as_this_moves_calculations(self):
        # Накопитель ADR-060 хранит числа за ТОТ ЖЕ день, но это расчёт ДРУГОГО
        # (советательного) решения. Подставить его значило бы объяснить ход
        # чужой арифметикой — ровно то, что §43 и запрещает.
        day = _d(40)
        t = _Tree(_chain(40))
        try:
            with open(os.path.join(t.root, m.SHADOW_HISTORY_REL), "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"cycle_date": day, "verdict": "HOLD",
                                     "gain_pp": 0.05, "book_apy_pp": 5.79}) + "\n")
            f = _field(t.run(), "calculations")
            self.assertNotEqual(f["counts"][m.PRESENT], 1)
            self.assertIn("ДРУГОГО решения", f["detail"])
        finally:
            t.close()


class TestPresentFields(unittest.TestCase):
    """Три поля трейл отдаёт — и сторож обязан сказать это вслух."""

    def test_portfolio_decision_and_execution_are_present(self):
        t = _Tree(_chain(40))
        try:
            doc = t.run()
            for key in ("portfolio_snapshot", "decision", "execution_result"):
                self.assertEqual(_field(doc, key)["counts"][m.PRESENT], 1, key)
            self.assertIn("fields_recoverable", _codes(doc))
        finally:
            t.close()

    def test_empty_from_allocation_is_absent(self):
        t = _Tree(_chain(40, move={"trade_id": "T001", "diff_usd": 1.0,
                                   "from_allocation": {}, "to_allocation": {"a": 1.0}}))
        try:
            self.assertEqual(_field(t.run(), "portfolio_snapshot")["counts"][m.ABSENT], 1)
        finally:
            t.close()

    def test_partial_only_fields_are_said_out_loud(self):
        # Поле, которое НИ РАЗУ не отдаётся целиком, обязано быть НАЗВАНО, даже
        # если что-то по нему есть: «частично» — это не «есть».
        t = _Tree(_chain(40), EQUITY_REL={"daily": [{"date": _d(39), "equity": 1.0}]})
        try:
            codes = _codes(t.run())
            self.assertIn("field_partial:optimizer_version", codes)
            self.assertIn("field_partial:post_trade_result", codes)
        finally:
            t.close()

    def test_each_move_is_explained_by_ITS_OWN_cycle_not_by_any_other(self):
        # Цепочку хода даёт correlation_id. Возьми вместо неё весь трейл — и
        # ход объяснится предложением ЧУЖОГО цикла; проверяется тем, что у хода
        # БЕЗ своего предложения цель обязана быть absent, хотя в трейле она есть.
        events = [e for e in _chain(40, corr="c1")
                  if e["event_type"] != "allocation_proposal"]
        events += _chain(3, corr="c2", trade_id="T009")
        t = _Tree(events)
        try:
            by_id = {mv["trade_id"]: mv for mv in t.run()["moves"]}
            self.assertEqual(by_id["T001"]["fields"]["decision"]["status"], m.ABSENT)
            self.assertEqual(by_id["T001"]["fields"]["optimizer_version"]["status"], m.ABSENT)
            self.assertEqual(by_id["T009"]["fields"]["decision"]["status"], m.PRESENT)
        finally:
            t.close()

    def test_decision_is_absent_when_the_proposal_belongs_to_another_cycle(self):
        # Цель берётся из ЦЕПОЧКИ ЭТОГО хода. Возьми её из «последнего
        # предложения вообще» — и объяснение хода станет чужим.
        events = _chain(40, corr="c1")
        events = [e for e in events if e["event_type"] != "allocation_proposal"]
        events += _chain(3, corr="c2", trade_id="T009")
        t = _Tree(events)
        try:
            doc = t.run()
            by_id = {mv["trade_id"]: mv for mv in doc["moves"]}
            self.assertEqual(by_id["T001"]["fields"]["decision"]["status"], m.ABSENT)
            self.assertEqual(by_id["T009"]["fields"]["decision"]["status"], m.PRESENT)
        finally:
            t.close()


class TestPostTradeResult(unittest.TestCase):
    def test_partial_when_only_the_book_level_day_exists(self):
        t = _Tree(_chain(40), EQUITY_REL={"daily": [{"date": _d(39), "equity": 100_500.0}]})
        try:
            f = _field(t.run(), "post_trade_result")
            self.assertEqual(f["counts"][m.PARTIAL], 1)
            self.assertIn("вклада ИМЕННО этого хода", f["detail"])
        finally:
            t.close()

    def test_absent_when_no_day_follows_the_move(self):
        t = _Tree(_chain(40), EQUITY_REL={"daily": [{"date": _d(41), "equity": 100_000.0}]})
        try:
            self.assertEqual(_field(t.run(), "post_trade_result")["counts"][m.ABSENT], 1)
        finally:
            t.close()


class TestIdentity(unittest.TestCase):
    """Вопрос владельца поставлен ЧЕРЕЗ ход — значит у хода нужно имя."""

    def test_reused_trade_id_is_critical(self):
        events = _chain(40, corr="c1", trade_id="T003")
        events += _chain(3, corr="c2", trade_id="T003")
        t = _Tree(events)
        try:
            doc = t.run()
            self.assertIn("trade_id_not_unique", _codes(doc))
            self.assertEqual(doc["identity"]["reused_ids"], 1)
            self.assertEqual(doc["overall"], "CRITICAL")
        finally:
            t.close()

    def test_unique_ids_raise_no_collision(self):
        events = _chain(40, corr="c1", trade_id="T003")
        events += _chain(3, corr="c2", trade_id="T004")
        t = _Tree(events)
        try:
            doc = t.run()
            self.assertNotIn("trade_id_not_unique", _codes(doc))
            self.assertEqual(doc["identity"]["reused_ids"], 0)
        finally:
            t.close()

    def test_move_without_a_name_is_counted_not_ignored(self):
        t = _Tree(_chain(40, move={"diff_usd": 1.0, "from_allocation": {"a": 2.0},
                                   "to_allocation": {"a": 1.0}}))
        try:
            doc = t.run()
            self.assertEqual(doc["identity"]["unnamed_moves"], 1)
            self.assertIn("unnamed_moves", _codes(doc))
        finally:
            t.close()


class TestSnapshotIdProbe(unittest.TestCase):
    """Адресует ли `snapshot_id` содержимое — решается ОПЫТОМ, не чтением."""

    def test_clock_derived_id_is_not_content_addressed(self):
        seq = iter(["d:aaa", "d:bbb"])
        probe = m.probe_snapshot_id(lambda _date: next(seq), "2026-08-31")
        self.assertTrue(probe["measured"])
        self.assertFalse(probe["content_addressed"])

    def test_stable_id_is_content_addressed(self):
        probe = m.probe_snapshot_id(lambda date: f"{date}:same", "2026-08-31")
        self.assertTrue(probe["content_addressed"])

    def test_missing_producer_is_unmeasured_not_a_verdict(self):
        probe = m.probe_snapshot_id(None, "2026-08-31")
        self.assertFalse(probe["measured"])
        self.assertIn("не поставлен", probe["reason"])

    def test_the_real_producer_today_is_not_content_addressed(self):
        # Положительный контроль на ЖИВОЙ производитель: пока snapshot_id
        # строится от стенных часов, восстановить по нему нечего. Починят —
        # тест покраснеет, и это правильный сигнал, а не поломка.
        from spa_core.audit import audit_trail as at
        probe = m.probe_snapshot_id(at._make_snapshot_id, "2026-08-31")
        self.assertTrue(probe["measured"])
        self.assertFalse(probe["content_addressed"])


class TestThirdOutcome(unittest.TestCase):
    """«Не измерено» — самостоятельный исход, не ноль и не скип."""

    def test_missing_trail_is_unchecked(self):
        t = _Tree(None)
        try:
            doc = t.run()
            self.assertEqual(doc["overall"], m._UNCHECKED)
            self.assertTrue(doc["unchecked"])
            self.assertEqual(doc["findings"], [])
        finally:
            t.close()

    def test_trail_without_moves_is_unchecked_not_ok(self):
        t = _Tree([e for e in _chain(40) if e["event_type"] != "trade_executed"])
        try:
            doc = t.run()
            self.assertEqual(doc["overall"], m._UNCHECKED)
        finally:
            t.close()

    def test_unparseable_lines_are_reported(self):
        t = _Tree(_chain(40))
        try:
            with open(os.path.join(t.root, m.TRAIL_REL), "a", encoding="utf-8") as fh:
                fh.write("{ не json\n")
            doc = t.run()
            self.assertEqual(doc["population"]["unparseable_lines"], 1)
            self.assertTrue(any("не разобраны" in u for u in doc["unchecked"]))
        finally:
            t.close()


class TestVerdictAndClock(unittest.TestCase):
    def test_a_never_recoverable_field_makes_the_verdict_critical(self):
        t = _Tree(_chain(40))
        try:
            doc = t.run()
            self.assertEqual(doc["overall"], "CRITICAL")
            self.assertIn("field_never_recoverable:policy_version", _codes(doc))
            self.assertIn("no_move_is_fully_answerable", _codes(doc))
        finally:
            t.close()

    def test_age_and_horizon_come_from_the_injected_clock(self):
        # Положительный контроль на ПРОВОДКУ часов: обе перекладки построены от
        # якоря, поэтому «старше месяца» здесь ровно одна на любом хосте.
        events = _chain(40, corr="c1", trade_id="T001")
        events += _chain(3, corr="c2", trade_id="T002")
        t = _Tree(events)
        try:
            doc = t.run()
            self.assertEqual(doc["population"]["moves"], 2)
            self.assertEqual(doc["population"]["moves_older_than_owner_horizon"], 1)
            ages = {mv["trade_id"]: mv["age_days"] for mv in doc["moves"]}
            self.assertEqual(ages["T001"], 40.5)
            self.assertEqual(ages["T002"], 3.5)
        finally:
            t.close()

    def test_write_false_touches_nothing(self):
        t = _Tree(_chain(40))
        try:
            before = sorted(os.listdir(os.path.join(t.root, "data")))
            t.run()
            self.assertEqual(sorted(os.listdir(os.path.join(t.root, "data"))), before)
        finally:
            t.close()

    def test_the_trail_itself_is_never_rewritten(self):
        t = _Tree(_chain(40))
        try:
            path = os.path.join(t.root, m.TRAIL_REL)
            before = open(path, encoding="utf-8").read()
            m.run(root=t.root, now=NOW, write=True)
            self.assertEqual(open(path, encoding="utf-8").read(), before)
        finally:
            t.close()


# ── Проводка: без неё сторож пишет отчёт один раз в жизни ─────────────────────

class TestWiring(unittest.TestCase):

    def test_findings_bridge_actually_calls_run(self):
        # Предметом является `<модуль>.run(...)` В ТЕЛЕ `main` — то, что
        # действительно исполнит `com.spa.decision_loop`. Имя в комментарии или
        # в PRODUCES вызовом не является.
        src = open(os.path.join(REPO_ROOT, "spa_core/monitoring/findings_bridge.py"),
                   encoding="utf-8").read()
        tree = ast.parse(src)
        main = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        called = False
        for node in ast.walk(main):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "decision_audit_trail"):
                called = True
        self.assertTrue(called, "findings_bridge.main не зовёт decision_audit_trail.run")

    def test_produces_declares_the_artifact(self):
        from spa_core.monitoring import findings_bridge
        self.assertIn(m.REPORT_REL, findings_bridge.PRODUCES)

    def test_manifest_declares_BOTH_homes(self):
        # Дом артефакта — ДВЕ записи: `produces` паспорта агента и строка
        # реестра. Удаление ЛЮБОЙ из них оставляет артефакт без дома.
        man = json.load(open(os.path.join(REPO_ROOT, "architecture/manifest.json"),
                             encoding="utf-8"))
        rows = [a for a in man["artifacts"] if a.get("path") == m.REPORT_REL]
        self.assertEqual(len(rows), 1, "нет строки реестра артефактов")
        self.assertEqual(rows[0]["producer"], "com.spa.decision_loop")
        self.assertIn("orchestrator_protocol", rows[0]["consumers"])
        agent = next(a for a in man["agents"] if a.get("label") == "com.spa.decision_loop")
        self.assertIn(m.REPORT_REL,
                      [x.get("artifact") for x in (agent.get("produces") or [])],
                      "паспорт com.spa.decision_loop не объявляет артефакт")

    def _office(self):
        path = os.path.join(REPO_ROOT, "scripts", "consume_office_reports.py")
        spec = importlib.util.spec_from_file_location("_office_c506", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_office_declares_the_producer(self):
        self.assertEqual(self._office()._PRODUCER["decision_audit_trail.json"],
                         "spa_core/monitoring/decision_audit_trail.py")

    def test_office_named_branch_prints_the_nine_fields(self):
        # Ветка читателя проверяется ПОВЕДЕНИЕМ: отчёт скармливается настоящему
        # `_summarize_json`, и в выводе ищется формулировка, которую печатает
        # ТОЛЬКО именная ветка. Так тест краснеет и от удаления ветки, и от её
        # вырождения в общий `else`.
        office = self._office()
        t = _Tree(_chain(40))
        try:
            doc = t.run()
        finally:
            t.close()
        text = "\n".join(office._summarize_json("decision_audit_trail.json", doc))
        self.assertIn("девять полей §43", text)
        self.assertIn("объяснимы ПОЛНОСТЬЮ", text)
        self.assertIn("ADVISORY", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
