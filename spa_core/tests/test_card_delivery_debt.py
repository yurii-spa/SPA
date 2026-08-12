"""Долг доставки: провал обязан поехать снова (ADR-081, цикл #204).

Каждый тест — положительный контроль аварии 12.08, а не украшение. Что было
измерено в тот день (песочница = копия живого дерева, подставная доставка,
`now` = 19:03Z — время следующего РЕАЛЬНОГО прогона моста):

* прогон 13:03Z: `closed=3`, `card_delivery: FAILED (пыталось 3)`, `rc=4`,
  доставлено 0 — три карточки на `origin` не попали;
* в `data/findings_bridge_state.json` все три уже `status: closed` ⇒ ни одна
  не попадёт в `created`/`closed` следующего прогона;
* прогон 19:03Z в песочнице: `created=[]`, `closed=[]`, **доставка пыталась
  везти `[]`**;
* `deliver([])` отвечает `IDLE`, а шаг 0-офис печатает `IDLE` ЗЕЛЁНОЙ строкой.

То есть провал не просто не лечился — через два часа он сам себя заметал, и
ADR-080 п.6 («придержана, поедет следующим прогоном, мост ходит каждый цикл»)
опирался на повтор, которого не существовало.

Пушер и читатель origin здесь ВСЕГДА инъектируются: тест, ушедший в сеть или в
очередь владельца, фальсифицирует и то и другое.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import card_delivery as cd
from spa_core.monitoring import findings_bridge as fb

# FROZEN-DATE-OK: часы инъектируются во ВСЕ функции, что судят о возрасте долга
# (`deliver(now=)`, `debt_block(now=)`); обе стороны сравнения закреплены тестом.
NOW = dt.datetime(2030, 3, 1, 12, 0, tzinfo=dt.timezone.utc)
LATER = NOW + dt.timedelta(hours=6)      # следующий прогон моста (интервал 21600с)
MUCH_LATER = NOW + dt.timedelta(hours=30)

#: Три карточки, доставка которых провалилась 12.08 в 13:03Z.
STUCK = ("inbox-nahodka-petli-data-investment-os-health.md",
         "inbox-nahodka-petli-docs-system-briefing-md-po.md",
         "inbox-nahodka-petli-postura-ofisa-critical-no.md")


class Pusher:
    """Инъектируемый пушер. `rc=4` воспроизводит отказ 12.08 дословно."""

    def __init__(self, rc=0, out="ok"):
        self.rc, self.out = rc, out
        self.calls = []

    def __call__(self, root, paths, message, allow_overwrite=False):
        self.calls.append({"paths": list(paths), "message": message,
                           "allow_overwrite": allow_overwrite})
        return self.rc, self.out

    @property
    def last_names(self):
        return sorted(os.path.basename(p) for p in self.calls[-1]["paths"])


def absent_reader(root, repo_path):
    """На origin файла нет — путь едет как создание (ветка без переноса)."""
    return cd.REMOTE_ABSENT, None, "на origin файла нет — это создание"


def mkroot(td, cards=STUCK):
    tracker = os.path.join(td, cd.TRACKER_REL)
    os.makedirs(tracker, exist_ok=True)
    os.makedirs(os.path.join(td, "data"), exist_ok=True)
    paths = []
    for name in cards:
        p = os.path.join(tracker, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"---\nstatus: done\n---\n\n# {name}\n")
        paths.append(os.path.realpath(p))
    return os.path.realpath(td), paths


def rel(name):
    return os.path.join(cd.TRACKER_REL, name)


class FailedDeliveryIsRemembered(unittest.TestCase):
    """Первая половина аварии: провал никуда не записывался."""

    def test_failed_push_becomes_debt(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            r = cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=4),
                           reader=absent_reader)
            self.assertEqual(r["status"], cd.FAILED)
            self.assertEqual(r["debt"]["count"], 3)
            self.assertEqual(r["debt"]["paths"], sorted(rel(n) for n in STUCK))

    def test_debt_survives_on_disk_between_runs(self):
        """Долг обязан пережить прогон: механизм в памяти лечил бы ноль."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=4), reader=absent_reader)
            on_disk = json.load(open(os.path.join(root, cd.DEBT_REL), encoding="utf-8"))
            self.assertEqual(sorted(on_disk["debt"]), sorted(rel(n) for n in STUCK))

    def test_disabled_delivery_still_owes(self):
        """Выключенная доставка — не «доставлено»: карточки остаются долгом."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            r = cd.deliver(paths, root=root, now=NOW, pusher=Pusher(),
                           env={cd.ENV_FLAG: "0"}, reader=absent_reader)
            self.assertEqual(r["status"], cd.DISABLED)
            self.assertEqual(r["debt"]["count"], 3)

    def test_unchecked_delivery_still_owes(self):
        """«Не измерено» — тоже не «на origin»."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)

            def boom(*a, **k):
                raise RuntimeError("origin недоступен")

            r = cd.deliver(paths, root=root, now=NOW, pusher=boom, reader=absent_reader)
            self.assertEqual(r["status"], cd.UNCHECKED)
            self.assertEqual(r["debt"]["count"], 3)


class DebtIsActuallyRetried(unittest.TestCase):
    """Сердце аварии: следующий прогон вёз ПУСТОЙ список."""

    def test_next_run_with_nothing_touched_retries_the_debt(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: до починки здесь ехал `[]` и статус был IDLE."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=4), reader=absent_reader)

            # Следующий прогон: мост ничего не создал и не закрыл — список пуст,
            # ровно как в 19:03Z. Долг обязан подставить те же три карточки.
            p2 = Pusher(rc=0)
            r2 = cd.deliver([], root=root, now=LATER, pusher=p2, reader=absent_reader)
            self.assertEqual(len(p2.calls), 1, "пушер не был позван — долг не поехал")
            self.assertEqual(p2.last_names, sorted(STUCK))
            self.assertEqual(r2["status"], cd.DELIVERED)
            self.assertEqual(r2["debt"]["count"], 0, "доехавшее обязано сняться с долга")
            self.assertEqual(r2["debt"]["retried"], sorted(rel(n) for n in STUCK))

    def test_retry_is_one_batch_with_the_new_work(self):
        """Долг едет ВМЕСТЕ со свежими карточками — одним коммитом, не двумя."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            cd.deliver(paths[:1], root=root, now=NOW, pusher=Pusher(rc=4), reader=absent_reader)
            p2 = Pusher()
            cd.deliver(paths[1:], root=root, now=LATER, pusher=p2, reader=absent_reader)
            self.assertEqual(len(p2.calls), 1)
            self.assertEqual(p2.last_names, sorted(STUCK))

    def test_debt_does_not_duplicate_a_path_already_asked_for(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=4), reader=absent_reader)
            p2 = Pusher()
            cd.deliver(paths, root=root, now=LATER, pusher=p2, reader=absent_reader)
            self.assertEqual(len(p2.calls[0]["paths"]), 3)

    def test_attempts_grow_until_delivery(self):
        """Счётчик попыток — это возраст беды, по нему видно «само не пройдёт»."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            r = None
            for i in range(cd.DEBT_STALE_ATTEMPTS):
                r = cd.deliver(paths if i == 0 else [], root=root,
                               now=NOW + dt.timedelta(hours=6 * i),
                               pusher=Pusher(rc=4), reader=absent_reader)
            self.assertEqual(r["debt"]["max_attempts"], cd.DEBT_STALE_ATTEMPTS)
            self.assertEqual(r["debt"]["stale"], sorted(rel(n) for n in STUCK))
            self.assertEqual(r["debt"]["stale_after"], cd.DEBT_STALE_ATTEMPTS)

    def test_debt_age_is_measured_from_first_failure_not_last(self):
        """Возраст долга — с ПЕРВОГО провала: иначе вечная беда всегда «свежая»."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=4), reader=absent_reader)
            r = cd.deliver([], root=root, now=MUCH_LATER, pusher=Pusher(rc=4),
                           reader=absent_reader)
            self.assertEqual(r["debt"]["oldest_hours"], 30.0)


class DebtIsRecoveredFromTheLastReceipt(unittest.TestCase):
    """Авария 12.08 случилась ДО появления долга — иначе три карточки застряли бы
    и после починки: файла долга нет, а мост их больше не тронет никогда."""

    def test_owed_from_receipt_reads_the_real_2026_08_12_receipt(self):
        receipt = {"status": cd.FAILED, "returncode": 4,
                   "attempted": [rel(n) for n in STUCK], "delivered": [],
                   "reason": "пушер вернул 4 — карточки на origin НЕ попали"}
        self.assertEqual(sorted(cd.owed_from_receipt(receipt)),
                         sorted(rel(n) for n in STUCK))

    def test_delivered_and_already_on_origin_are_not_owed(self):
        receipt = {"status": cd.PARTIAL,
                   "attempted": [rel(n) for n in STUCK],
                   "delivered": [rel(STUCK[0])],
                   "already_on_origin": [rel(STUCK[1])]}
        self.assertEqual(cd.owed_from_receipt(receipt), [rel(STUCK[2])])

    def test_missing_debt_file_is_rebuilt_from_the_receipt_and_retried(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ подъёма реальной потери 12.08."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td)
            # Квитанция от 13:03Z есть, файла долга нет — состояние прода на
            # момент починки, байт в байт по полям.
            with open(os.path.join(root, cd.STATUS_REL), "w", encoding="utf-8") as f:
                json.dump({"generated_at": NOW.isoformat(), "status": cd.FAILED,
                           "returncode": 4, "attempted": [rel(n) for n in STUCK],
                           "delivered": [],
                           "reason": "пушер вернул 4 — карточки на origin НЕ попали"}, f)
            self.assertFalse(os.path.exists(os.path.join(root, cd.DEBT_REL)))

            p = Pusher()
            r = cd.deliver([], root=root, now=LATER, pusher=p, reader=absent_reader)
            self.assertEqual(p.last_names, sorted(STUCK))
            self.assertEqual(r["status"], cd.DELIVERED)


class GreenLineNeedsAnEmptyDebt(unittest.TestCase):
    """Вторая половина аварии: `IDLE` печатался ЗЕЛЁНЫМ при трёх недоставленных."""

    def test_idle_with_debt_is_not_idle(self):
        receipt = {"status": cd.IDLE, "reason": "доставлять нечего"}
        cd.enforce_debt_status(receipt, {rel(STUCK[0]): {"attempts": 1}})
        self.assertEqual(receipt["status"], cd.DEBT)
        self.assertIn(cd.DEBT, cd.NOT_DELIVERED)
        self.assertIn("НЕ ДОСТАВЛЕНО", receipt["reason"])

    def test_idle_with_empty_debt_stays_idle(self):
        """Контроль в обратную сторону: пустой долг не смеет краснить чистый прогон."""
        receipt = {"status": cd.IDLE, "reason": "доставлять нечего"}
        cd.enforce_debt_status(receipt, {})
        self.assertEqual(receipt["status"], cd.IDLE)

    def test_render_names_the_debt(self):
        r = {"status": cd.FAILED, "attempted": [rel(n) for n in STUCK], "reason": "x",
             "debt": {"count": 3, "oldest_hours": 6.0, "stale": [], "stale_after": 5}}
        self.assertIn("ДОЛГ 3", cd.render(r))
        self.assertIn("старшему 6.0ч", cd.render(r))

    def test_render_says_unmeasured_for_old_receipts(self):
        """Квитанция без блока долга — «НЕ ИЗМЕРЕН», а не «долга нет»."""
        self.assertIn("НЕ ИЗМЕРЕН", cd.render({"status": cd.IDLE, "attempted": []}))

    def test_render_stays_quiet_when_debt_is_measured_zero(self):
        r = {"status": cd.DELIVERED, "attempted": [rel(STUCK[0])], "delivered": [rel(STUCK[0])],
             "debt": {"count": 0, "oldest_hours": None, "stale": [], "stale_after": 5}}
        self.assertNotIn("ДОЛГ", cd.render(r))
        self.assertNotIn("НЕ ИЗМЕРЕН", cd.render(r))


class DebtCannotBlockDelivery(unittest.TestCase):
    """Долг заведён ради доставки и не смеет её остановить — иначе лекарство
    становится болезнью (`validate` отклоняет пачку ЦЕЛИКОМ)."""

    def test_vanished_debtor_is_dropped_and_named_not_silently_kept(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=4), reader=absent_reader)
            os.remove(paths[0])  # карточку удалили из дерева

            p2 = Pusher()
            r2 = cd.deliver([], root=root, now=LATER, pusher=p2, reader=absent_reader)
            self.assertEqual(r2["status"], cd.DELIVERED, "исчезнувший должник уронил пачку")
            self.assertEqual(p2.last_names, sorted(STUCK[1:]))
            dropped = {d["path"] for d in r2["debt"]["dropped"]}
            self.assertEqual(dropped, {rel(STUCK[0])})
            self.assertIn("снят с долга", r2["debt"]["dropped"][0]["reason"])

    def test_board_is_never_dragged_in_by_the_debt(self):
        """_BOARD.md долгом не возится: пушер отказал бы и уронил всю пачку."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ("a.md",))
            board = os.path.join(root, cd.TRACKER_REL, "_BOARD.md")
            with open(board, "w", encoding="utf-8") as f:
                f.write("---\nstatus: new\n---\n")
            with open(os.path.join(root, cd.DEBT_REL), "w", encoding="utf-8") as f:
                json.dump({"debt": {rel("_BOARD.md"): {"since": NOW.isoformat(),
                                                       "attempts": 1}}}, f)
            p = Pusher()
            r = cd.deliver([], root=root, now=LATER, pusher=p, reader=absent_reader)
            self.assertEqual(len(p.calls), 0)
            self.assertEqual(r["debt"]["count"], 0)
            self.assertEqual([d["path"] for d in r["debt"]["dropped"]], [rel("_BOARD.md")])

    def test_use_debt_false_measures_a_single_run(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=4), reader=absent_reader)
            p2 = Pusher()
            r2 = cd.deliver([], root=root, now=LATER, pusher=p2,
                            reader=absent_reader, use_debt=False)
            self.assertEqual(len(p2.calls), 0)
            self.assertEqual(r2["status"], cd.IDLE)
            self.assertNotIn("debt", r2)

    def test_write_status_false_does_not_touch_the_debt_file(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=4),
                       reader=absent_reader, write_status=False)
            self.assertFalse(os.path.exists(os.path.join(root, cd.DEBT_REL)))


class BridgeInheritsTheRetry(unittest.TestCase):
    """Повтор живёт в доставке, а не у вызывающего: мост получает его, не зная."""

    def test_bridge_run_with_nothing_touched_still_delivers_the_debt(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=4), reader=absent_reader)

            seen = {}

            def deliver_spy(p, root=None, now=None):
                r = cd.deliver(p, root=root, now=now, pusher=Pusher(),
                               reader=absent_reader)
                seen["attempted"] = r["attempted"]
                return r

            fb.run_bridge(root=root, now=LATER, deliver=deliver_spy)
            # Мост «коснулся» нуля карточек — и всё равно довёз три должных.
            self.assertEqual(sorted(seen["attempted"]), sorted(rel(n) for n in STUCK))


if __name__ == "__main__":
    unittest.main()
