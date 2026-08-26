"""N параллельных слотов замка цикла оркестратора (owner-decision 26.08).

Владелец: очередь наполняется быстрее, чем разгружается — «проверь и внедри, если
безопасно» 2 параллельных цикла. Ревью безопасности (замер 26.08) нашло единственный
незакрытый риск (дубли в Telegram при двух отправителях, чинится отдельно —
``outbound_lock`` в ``telegram_client``) и подтвердило: захват карточек, слияние
STATE/журнала, повтор при столкновении пуша — уже гонко-устойчивы. Остаётся сам замок
ADR-070 п.9 («один цикл одновременно») — он должен научиться пускать ``N`` независимых
держателей, не переставая быть тем же замком для ``N=1`` (умолчание, сегодняшнее прод-
поведение).

Каждый тест ниже — либо регрессия (N=1 не отличим от кода ДО этой правки), либо новое
поведение (N=2: два разных держателя, третий — отказ, третий слот освобождается верно).
Время и живость — вход (``now=``, поддельный ``ps``), не окружение — см. соседний
``test_orchestrator_cycle_lock.py``, чьи конвенции этот файл наследует.
"""
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
LOCK_PY = ROOT / "scripts" / "orchestrator_cycle_lock.py"
SIBLING_PY = ROOT / "scripts" / "check_undelivered_work.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = _load(LOCK_PY, "_test_orchestrator_cycle_lock_slots")
SIB = _load(SIBLING_PY, "_test_cycle_lock_slots_sibling")

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
LSTART_A = "Wed Aug 26 10:00:00 2026"
LSTART_B = "Wed Aug 26 11:00:00 2026"
LSTART_C = "Wed Aug 26 11:30:00 2026"


def ps_alive(start=LSTART_A):
    return lambda pid: (0, start + "\n")


def ps_map(mapping):
    """Подставная ``ps``, отвечающая РАЗНЫМ временем старта для разных pid — плоский
    ``ps_alive(X)`` отвечает одним и тем же ``X`` любому pid, а с двумя РАЗНЫМИ живыми
    держателями это читает второго как «чужой процесс переиспользовал тот же pid» —
    (`session_pid_start` не совпал) — и снимает его как брошенный, ровно та путаница,
    ради которой ``session_pid_start`` вообще существует (см. ``same_identity``)."""
    def _ps(pid):
        start = mapping.get(pid)
        return (0, start + "\n") if start else (1, "")
    return _ps


class _FakeSibling:
    """Тонкая обёртка вокруг НАСТОЯЩЕГО ``check_undelivered_work``: подменяет ТОЛЬКО
    ``shared_log`` (на герметичный tmp-путь), остальное (``session_state``, ``ACTIVE``,
    ``UNKNOWN``, ``_ps_lstart``) — реальные символы модуля. ``mock.Mock(wraps=...)`` тут
    не годится: сравнения ``state == sibling.ACTIVE`` внутри ``classify()`` требуют
    настоящей строки-константы, а не Mock-обёртки вокруг неё."""

    def __init__(self, real, log_path: Path):
        self._real = real
        self._log_path = log_path

    def shared_log(self, *_a, **_k):
        return (self._log_path, None)

    def __getattr__(self, name):
        return getattr(self._real, name)


class SlotCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # Для тестов slot_lock_dir() в изоляции (без acquire/classify) — обычный Mock.
        self.fake = mock.Mock()
        self.fake.shared_log.return_value = (self.base / "session_changes.jsonl", None)
        # Для тестов полной цепочки acquire/release/status — реальный SIB под герметичным путём.
        self.sib = _FakeSibling(SIB, self.base / "session_changes.jsonl")


# ── slot_lock_dir: путь слота 0 — БЕЗ ИЗМЕНЕНИЙ, слоты 1+ — рядом ────────────

class TestSlotLockDir(SlotCase):
    def test_slot_0_is_the_original_unsuffixed_path(self):
        path, err = L.slot_lock_dir(self.fake, 0)
        self.assertIsNone(err)
        self.assertEqual(self.base / L.LOCK_DIRNAME, path)

    def test_slot_1_is_a_sibling_directory_with_suffix(self):
        path, err = L.slot_lock_dir(self.fake, 1)
        self.assertIsNone(err)
        self.assertEqual(self.base / f"{L.LOCK_DIRNAME}.1", path)

    def test_slot_2_gets_its_own_suffix_too(self):
        path, _ = L.slot_lock_dir(self.fake, 2)
        self.assertEqual(self.base / f"{L.LOCK_DIRNAME}.2", path)

    def test_unresolved_shared_tree_propagates_to_every_slot(self):
        self.fake.shared_log.return_value = (Path("/tmp/nowhere/x.jsonl"), "не определено")
        for slot in (0, 1, 2):
            _, err = L.slot_lock_dir(self.fake, slot)
            self.assertTrue(err, f"slot {slot} обязан унаследовать причину недоступности")


# ── acquire_any_slot: N=1 не отличим от прямого acquire() ────────────────────

class TestAcquireAnySlotDefaultIsUnchanged(SlotCase):
    def test_max_concurrent_1_free_lock_acquires_slot_0(self):
        v, msg, slot, path = L.acquire_any_slot(
            1, L.holder_record("cycle-111", 111, LSTART_A, NOW), "cycle-111", 111, self.sib,
            now=NOW, self_pid_start=LSTART_A, ps=ps_alive())
        self.assertEqual(L.ACQUIRED, v, msg)
        self.assertEqual(0, slot)
        self.assertEqual(self.base / L.LOCK_DIRNAME, path)

    def test_max_concurrent_1_busy_when_slot_0_taken(self):
        v0, _, _, _ = L.acquire_any_slot(
            1, L.holder_record("cycle-111", 111, LSTART_A, NOW), "cycle-111", 111, self.sib,
            now=NOW, self_pid_start=LSTART_A, ps=ps_alive(LSTART_A))
        self.assertEqual(L.ACQUIRED, v0)
        v1, msg1, slot1, path1 = L.acquire_any_slot(
            1, L.holder_record("cycle-222", 222, LSTART_B, NOW), "cycle-222", 222, self.sib,
            now=NOW, self_pid_start=LSTART_B, ps=ps_alive(LSTART_A))
        self.assertEqual(L.BUSY, v1, msg1)
        self.assertIsNone(slot1)
        self.assertIsNone(path1)

    def test_max_concurrent_1_ignores_a_second_slot_even_if_it_exists(self):
        """Слот 1 свободен, но при N=1 его никто не пробует — иначе N=1 перестал бы
        быть N=1 и прод, ещё не поднявший второй launchd-агент, тихо получил бы 2."""
        L.acquire_any_slot(1, L.holder_record("cycle-111", 111, LSTART_A, NOW),
                           "cycle-111", 111, self.sib, now=NOW, self_pid_start=LSTART_A,
                           ps=ps_alive(LSTART_A))
        v, msg, slot, path = L.acquire_any_slot(
            1, L.holder_record("cycle-222", 222, LSTART_B, NOW), "cycle-222", 222, self.sib,
            now=NOW, self_pid_start=LSTART_B, ps=ps_alive(LSTART_A))
        self.assertEqual(L.BUSY, v, msg)
        self.assertFalse((self.base / f"{L.LOCK_DIRNAME}.1").exists(),
                         "N=1 не имеет права создать второй слот")


# ── acquire_any_slot: N=2 — новое поведение ───────────────────────────────────

class TestAcquireAnySlotTwoHolders(SlotCase):
    def test_two_different_sessions_each_get_their_own_slot(self):
        v_a, _, slot_a, _ = L.acquire_any_slot(
            2, L.holder_record("cycle-111", 111, LSTART_A, NOW), "cycle-111", 111, self.sib,
            now=NOW, self_pid_start=LSTART_A, ps=ps_alive(LSTART_A))
        v_b, _, slot_b, _ = L.acquire_any_slot(
            2, L.holder_record("cycle-222", 222, LSTART_B, NOW), "cycle-222", 222, self.sib,
            now=NOW, self_pid_start=LSTART_B, ps=ps_alive(LSTART_A))
        self.assertEqual(L.ACQUIRED, v_a)
        self.assertEqual(L.ACQUIRED, v_b)
        self.assertEqual({0, 1}, {slot_a, slot_b}, "два держателя обязаны попасть в РАЗНЫЕ слоты")

    def test_third_session_is_busy_when_both_slots_taken(self):
        ps = ps_map({111: LSTART_A, 222: LSTART_B, 333: LSTART_C})
        for sess, pid, start in (("cycle-111", 111, LSTART_A), ("cycle-222", 222, LSTART_B)):
            v, msg, _, _ = L.acquire_any_slot(
                2, L.holder_record(sess, pid, start, NOW), sess, pid, self.sib,
                now=NOW, self_pid_start=start, ps=ps)
            self.assertEqual(L.ACQUIRED, v, msg)
        v3, msg3, slot3, path3 = L.acquire_any_slot(
            2, L.holder_record("cycle-333", 333, LSTART_C, NOW), "cycle-333", 333, self.sib,
            now=NOW, self_pid_start=LSTART_C, ps=ps)
        self.assertEqual(L.BUSY, v3, msg3)
        self.assertIsNone(slot3)
        self.assertIn("2", msg3, "сообщение обязано назвать сколько слотов занято")

    def test_same_session_retrying_gets_already_mine_on_its_own_slot(self):
        rec = L.holder_record("cycle-111", 111, LSTART_A, NOW)
        v1, _, slot1, _ = L.acquire_any_slot(2, rec, "cycle-111", 111, self.sib,
                                             now=NOW, self_pid_start=LSTART_A, ps=ps_alive())
        v2, _, slot2, _ = L.acquire_any_slot(2, rec, "cycle-111", 111, self.sib,
                                             now=NOW, self_pid_start=LSTART_A, ps=ps_alive())
        self.assertEqual(L.ACQUIRED, v1)
        self.assertEqual(L.ALREADY_MINE, v2)
        self.assertEqual(slot1, slot2, "повторный вызов той же сессии обязан найти СВОЙ слот")


# ── release_any_slot: снимает ровно свой слот, чужие не трогает ──────────────

class TestReleaseAnySlot(SlotCase):
    def test_releases_the_slot_it_actually_holds(self):
        L.acquire_any_slot(2, L.holder_record("cycle-111", 111, LSTART_A, NOW),
                           "cycle-111", 111, self.sib, now=NOW, self_pid_start=LSTART_A,
                           ps=ps_alive(LSTART_A))
        L.acquire_any_slot(2, L.holder_record("cycle-222", 222, LSTART_B, NOW),
                           "cycle-222", 222, self.sib, now=NOW, self_pid_start=LSTART_B,
                           ps=ps_alive(LSTART_A))
        v, msg = L.release_any_slot(2, "cycle-111", 111, self.sib, self_pid_start=LSTART_A)
        self.assertEqual(L.RELEASED, v, msg)
        # Слот 0 свободен для новых, слот 1 (cycle-222) остаётся занят.
        v_new, _, _, _ = L.acquire_any_slot(
            2, L.holder_record("cycle-333", 333, LSTART_C, NOW), "cycle-333", 333, self.sib,
            now=NOW, self_pid_start=LSTART_C, ps=ps_alive(LSTART_A))
        self.assertEqual(L.ACQUIRED, v_new)
        rec_other, _ = L.read_holder(self.base / f"{L.LOCK_DIRNAME}.1")
        self.assertEqual("cycle-222", rec_other["session"],
                         "release чужой сессии не смеет трогать соседний слот")

    def test_releasing_a_session_that_holds_nothing_is_not_held(self):
        v, msg = L.release_any_slot(2, "cycle-999", 999, self.sib, self_pid_start=LSTART_C)
        self.assertEqual(L.NOT_HELD, v, msg)


# ── status_all: наблюдение без единой мутации ─────────────────────────────────

class TestStatusAll(SlotCase):
    def test_all_free_when_nothing_taken(self):
        rows = L.status_all(2, "cycle-111", 111, self.sib, now=NOW)
        self.assertEqual([0, 1], [s for s, *_ in rows])
        self.assertTrue(all(v == L.FREE for _, v, _, _ in rows))

    def test_reflects_exactly_which_slots_are_busy(self):
        L.acquire_any_slot(2, L.holder_record("cycle-111", 111, LSTART_A, NOW),
                           "cycle-111", 111, self.sib, now=NOW, self_pid_start=LSTART_A,
                           ps=ps_alive(LSTART_A))
        rows = L.status_all(2, "cycle-999", 999, self.sib, now=NOW, ps=ps_alive(LSTART_A))
        verdicts = {s: v for s, v, _, _ in rows}
        self.assertEqual(L.BUSY, verdicts[0])
        self.assertEqual(L.FREE, verdicts[1])

    def test_status_all_never_mutates_the_lock(self):
        L.acquire_any_slot(2, L.holder_record("cycle-111", 111, LSTART_A, NOW),
                           "cycle-111", 111, self.sib, now=NOW, self_pid_start=LSTART_A,
                           ps=ps_alive(LSTART_A))
        before, _ = L.read_holder(self.base / L.LOCK_DIRNAME)
        L.status_all(2, "cycle-999", 999, self.sib, now=NOW, ps=ps_alive(LSTART_A))
        after, _ = L.read_holder(self.base / L.LOCK_DIRNAME)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
