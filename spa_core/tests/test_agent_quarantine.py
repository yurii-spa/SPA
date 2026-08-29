"""Карантин агента: инструмент устроен как ОТКАЗ (решение владельца 28.08).

Агента не удаляют — откладывают в `attic/`, чтобы вернуть одной командой, если кто-то
закричит. Крик = доказательство нужности; это измерительный прибор, а не уборка.

Каждый тест — реальный дефект, допущенный при постройке 28.08:

  1. **Главная проверка была ЗАГЛУШКОЙ.** `_live_measure` возвращала «потребителей 0»
     всегда — сторож не мог отказать по существу.
  2. **«Проба отказа» ПОДЕЙСТВОВАЛА:** прогон по списку агентов реально отложил живого
     `com.spa.swarm_dwell` (возвращён немедленно). Отсюда `--dry-run`: проверка
     инструмента не имеет права действовать.
  3. **«Не измерено» ≠ «никто».** Если замер не состоялся, карантин обязан ОТКАЗАТЬ.
  4. Первая версия замера считала только читателей-код и записала бы в кандидаты
     `watchdog` и `artifact_freshness` — у монитора потребитель ЧЕЛОВЕК.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import scripts.agent_quarantine as q  # noqa: E402


def _manifest(tmp: Path, label="com.spa.x", role="research"):
    (tmp / "architecture").mkdir(parents=True, exist_ok=True)
    (tmp / "architecture" / "manifest.json").write_text(json.dumps(
        {"agents": [{"label": label, "role": role, "schedule": "interval:3600s"}]}), encoding="utf-8")


class _Env:
    """Подменяет пути модуля на временные — живая система не трогается."""

    def __init__(self, td):
        self.tmp = Path(td)
        self.calls = []

    def __enter__(self):
        self._old = (q.REPO, q.LAUNCH_AGENTS, q.ATTIC, q.REGISTRY)
        q.REPO = self.tmp
        q.LAUNCH_AGENTS = self.tmp / "LaunchAgents"
        q.ATTIC = self.tmp / "attic" / "agents"
        q.REGISTRY = q.ATTIC / "QUARANTINE.json"
        q.LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
        _manifest(self.tmp)
        return self

    def __exit__(self, *a):
        q.REPO, q.LAUNCH_AGENTS, q.ATTIC, q.REGISTRY = self._old

    def runner(self, *args, **kw):
        self.calls.append(args[0] if args else None)
        class _R: returncode = 0
        return _R()


NOBODY = lambda label: {"measured": True, "consumers": 0}
SOMEBODY = lambda label: {"measured": True, "consumers": 3}
UNMEASURED = lambda label: {"measured": False, "consumers": 0}


class TestRefusals(unittest.TestCase):
    def test_protected_label_is_never_quarantined(self):
        with TemporaryDirectory() as td, _Env(td) as env:
            _manifest(env.tmp, label="com.spa.daily_cycle")
            with self.assertRaises(q.Refused) as e:
                q.quarantine("com.spa.daily_cycle", "r", NOBODY, runner=env.runner)
            self.assertIn("защищённом", str(e.exception))

    def test_unknown_agent_is_refused(self):
        with TemporaryDirectory() as td, _Env(td) as env:
            with self.assertRaises(q.Refused) as e:
                q.quarantine("com.spa.ghost", "r", NOBODY, runner=env.runner)
            self.assertIn("нет в", str(e.exception))

    def test_consumed_product_is_refused(self):
        with TemporaryDirectory() as td, _Env(td) as env:
            with self.assertRaises(q.Refused) as e:
                q.quarantine("com.spa.x", "r", SOMEBODY, runner=env.runner)
            self.assertIn("потребляют", str(e.exception))

    def test_unmeasured_is_refused_not_treated_as_nobody(self):
        """Авария 3: «не знаю» — это не «никто». Fail-CLOSED."""
        with TemporaryDirectory() as td, _Env(td) as env:
            with self.assertRaises(q.Refused) as e:
                q.quarantine("com.spa.x", "r", UNMEASURED, runner=env.runner)
            self.assertIn("НЕ измерено", str(e.exception))

    def test_measure_that_raises_is_refused(self):
        def boom(label): raise RuntimeError("манифест недоступен")
        with TemporaryDirectory() as td, _Env(td) as env:
            with self.assertRaises(q.Refused):
                q.quarantine("com.spa.x", "r", boom, runner=env.runner)

    def test_double_quarantine_is_refused(self):
        with TemporaryDirectory() as td, _Env(td) as env:
            q.quarantine("com.spa.x", "r", NOBODY, runner=env.runner)
            with self.assertRaises(q.Refused) as e:
                q.quarantine("com.spa.x", "r", NOBODY, runner=env.runner)
            self.assertIn("уже в карантине", str(e.exception))


class TestZeroConsumersIsNotAlwaysEvidence(unittest.TestCase):
    """Замер 29.08: два кандидата из шести оказались ложными ПО ПОСТРОЕНИЮ.

    Оба — один класс: «ноль читателей файла» доказывает что-то только там, где файл
    вообще есть и потребляют его через файл. Без этих двух отказов вторая партия
    предложила бы владельцу выключить `com.spa.familyfund` — живой API инвесторов.
    """

    def test_agent_producing_nothing_is_refused_not_quarantined(self):
        """`cmo_editorial`: PRODUCES = () ⇒ ноль читателей у НИЧЕГО — тавтология."""
        with TemporaryDirectory() as td, _Env(td) as env:
            _manifest(env.tmp)
            produces_nothing = lambda _l: {"measured": True, "applicable": False,
                                           "consumers": 0, "declared": []}
            with self.assertRaises(q.Refused) as e:
                q.quarantine("com.spa.x", "r", produces_nothing, runner=env.runner)
            self.assertIn("тавтология", str(e.exception))

    def test_daemon_is_refused_because_its_consumer_arrives_over_the_network(self):
        """`familyfund`: сервер API — его читают по HTTP, канала «сеть» у нас нет."""
        with TemporaryDirectory() as td, _Env(td) as env:
            (env.tmp / "architecture").mkdir(parents=True, exist_ok=True)
            (env.tmp / "architecture" / "manifest.json").write_text(json.dumps(
                {"agents": [{"label": "com.spa.x", "role": "infra",
                             "schedule": "daemon"}]}), encoding="utf-8")
            with self.assertRaises(q.Refused) as e:
                q.quarantine("com.spa.x", "r", NOBODY, runner=env.runner)
            self.assertIn("демон", str(e.exception))

    def test_a_real_unconsumed_file_producer_is_still_quarantinable(self):
        """Обратная сторона: отказы не должны обессмыслить прибор."""
        with TemporaryDirectory() as td, _Env(td) as env:
            _manifest(env.tmp)
            r = q.quarantine("com.spa.x", "r", NOBODY, runner=env.runner, dry_run=True)
            self.assertTrue(r)


class TestTheFlagItselfIsMeasured(unittest.TestCase):
    """Отказ выше проверен на ПОДСТАВНОМ замере — значит настоящий замер не проверен.

    Мутация 29.08 это показала: сняв развилку в `consumers_of`, набор остался ЗЕЛЁНЫМ,
    потому что тесты карантина подсовывают свою `measure`. Сторож был бы зелёным, а
    проводка мёртвой — `applicable` никогда не стал бы False в проде.
    """

    def _measure(self, declared):
        from spa_core.monitoring import artifact_consumers as ac
        from spa_core.monitoring import artifact_contract as acon
        e, d = acon._entry_modules, acon.declared_produces
        try:
            acon._entry_modules = lambda _r: {"com.spa.x": "spa_core.monitoring.artifact_consumers"}
            acon.declared_produces = lambda _f: declared
            return ac.consumers_of("com.spa.x", Path(__file__).resolve().parents[2])
        finally:
            acon._entry_modules, acon.declared_produces = e, d

    def test_empty_produces_makes_the_question_inapplicable(self):
        r = self._measure(())
        self.assertTrue(r["measured"], "замер СОСТОЯЛСЯ — это не «не знаю»")
        self.assertIs(r["applicable"], False)
        self.assertIn("НЕПРИМЕНИМО", r["note"])

    def test_declared_artifact_keeps_the_question_applicable(self):
        """Обратная сторона: у агента с продуктом вопрос остаётся законным."""
        r = self._measure(("data/nikto_ne_chitaet_etot_fail.json",))
        self.assertIs(r["applicable"], True)
        self.assertTrue(r["measured"])

    def test_unreadable_declaration_is_not_measured_at_all(self):
        """И третий исход не потерян: объявления нет ⇒ «не измерено», не «неприменимо»."""
        r = self._measure(None)
        self.assertFalse(r["measured"])
        self.assertIs(r["applicable"], True)


class TestDryRunCannotAct(unittest.TestCase):
    """Авария 2: моя же «проба отказа» отложила живого агента."""

    def test_dry_run_moves_nothing_and_calls_nothing(self):
        with TemporaryDirectory() as td, _Env(td) as env:
            plist = q.LAUNCH_AGENTS / "com.spa.x.plist"
            plist.write_text("<plist/>", encoding="utf-8")
            r = q.quarantine("com.spa.x", "r", NOBODY, runner=env.runner, dry_run=True)
            self.assertTrue(r["dry_run"])
            self.assertTrue(plist.is_file(), "dry-run НЕ имеет права двигать plist")
            self.assertEqual(env.calls, [], "dry-run НЕ имеет права звать launchctl")
            self.assertEqual(q.load_registry().get("quarantined", {}), {})


class TestRoundTrip(unittest.TestCase):
    def test_quarantine_then_restore_returns_the_plist(self):
        with TemporaryDirectory() as td, _Env(td) as env:
            plist = q.LAUNCH_AGENTS / "com.spa.x.plist"
            plist.write_text("<plist/>", encoding="utf-8")
            rec = q.quarantine("com.spa.x", "не читается никем", NOBODY, runner=env.runner)
            self.assertFalse(plist.is_file())
            self.assertTrue((q.ATTIC / "com.spa.x.plist").is_file())
            self.assertIn("restore", rec)
            q.restore("com.spa.x", runner=env.runner)
            self.assertTrue(plist.is_file(), "возврат обязан вернуть plist на место")
            self.assertEqual(q.load_registry().get("quarantined", {}), {})

    def test_registry_records_how_to_undo(self):
        with TemporaryDirectory() as td, _Env(td) as env:
            (q.LAUNCH_AGENTS / "com.spa.x.plist").write_text("<plist/>", encoding="utf-8")
            rec = q.quarantine("com.spa.x", "причина", NOBODY, runner=env.runner)
            self.assertIn("agent_quarantine.py restore com.spa.x", rec["restore"])
            self.assertEqual(rec["reason"], "причина")
            self.assertIn("at", rec)

    def test_restore_of_unknown_is_refused(self):
        with TemporaryDirectory() as td, _Env(td) as env:
            with self.assertRaises(q.Refused):
                q.restore("com.spa.x", runner=env.runner)


class TestOwnerIsAConsumer(unittest.TestCase):
    """Авария 4: у монитора потребитель — ЧЕЛОВЕК, а не код."""

    def test_agent_that_alerts_the_owner_counts_as_consumed(self):
        from spa_core.monitoring.artifact_consumers import consumers_of
        r = consumers_of("com.spa.watchdog")
        self.assertTrue(r["measured"])
        self.assertGreater(r["consumers"], 0,
                           "сторож, кричащий владельцу, не может считаться никому не нужным")
        self.assertTrue(r["by_channel"]["owner"])


if __name__ == "__main__":
    unittest.main()
