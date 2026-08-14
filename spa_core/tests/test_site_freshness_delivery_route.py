"""Тревога владельцу — только когда публику вводят в заблуждение.

Авария 14.08 (задача владельца, голосом: «мне опять она начинает спамить в
телеграм всё то же самое… куча ошибок лезет каждый день одно и то же»).

Что было измерено
-----------------
`site_freshness_monitor` живёт ТОЛЬКО в GitHub Actions (каждые 6 ч, боевые
секреты; launchd-агента у него нет). Проверки сайта проходят, снимок помечен
`degraded: true` — значит каждый прогон заходит в ветку восстановления
`_clear_degrade`. Она правит снимок В РАННЕРЕ и зовёт `push_to_github_batch.py`,
а пушер по контракту (`repo_relative_path`, fail-CLOSED) берёт файл только из
живого дерева Мака или его worktree. В раннере путь — `/home/runner/work/SPA/SPA`,
поэтому отказ гарантирован: `RepoPathError` ⇒ `rc=1` ⇒ КРИТИЧЕСКАЯ тревога
«доставка ОТКАЗАНА» владельцу.

Подавить её было нечем: в CI живого дерева нет, значит нет ни дедупа, ни журнала
канала — модуль честно печатает `отправка МИМО журнала канала (live_tree_absent)`
и шлёт сырым POST. Прогоны 165 (13.08 19:16Z), 166, 167 — четыре побуквенно
одинаковых сообщения в сутки, бессрочно, и НИ ОДНОГО следа в
`data/alert_history.json`. Кран открыл наш же цикл #218, починив форму отчёта:
до него та же тревога падала с KeyError и не уходила никогда.

Почему лечится маршрутом, а не порогом
--------------------------------------
Направление таблички решает всё (инвариант #8 — никогда не завышать):

* не уехала ПОСТАНОВКА таблички ⇒ публика видит завышенное число, а мы знаем, что
  оно завышено. Это авария, звонить обязаны — даже без дедупа;
* не уехало СНЯТИЕ ⇒ публика видит осторожную табличку там, где проверки уже
  проходят. Хуже реальности мы не выглядим, будить человека раз в 6 часов не за
  что; находка уходит в отчёт и в КРАСНЫЙ job (второй канал ADR-YL-011).

Прецедент — ADR-084: штатная самопочинка перестала звонить владельцу, оставшись
в отчёте. Гасится МАРШРУТ, не проверка.

Каждый тест ниже — положительный контроль этой аварии: сними починку, и он
краснеет (проверено тремя мутациями, см. журнал W33).
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "site_freshness_monitor", str(_REPO / "scripts" / "site_freshness_monitor.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Branch(unittest.TestCase):
    """Общий стенд: снимок во временном каталоге = форма CI (дерево не наше)."""

    def setUp(self):
        self.mod = _load()
        del self.mod._DELIVERY_NOTES[:]

    def _run(self, fn: str, snap: dict, *, deliverable: bool, rc: int = 1):
        alerts, pushes = [], []
        with TemporaryDirectory() as t:
            path = Path(t) / "track_snapshot.json"
            path.write_text(json.dumps(snap), encoding="utf-8")

            def _fake_run(cmd, *a, **k):
                pushes.append(cmd)
                return mock.Mock(returncode=rc)

            probe = (lambda *a, **k: (True, "")) if deliverable else \
                    (lambda *a, **k: (False, "пушер работает только из живого дерева"))
            with mock.patch.object(self.mod, "_SNAP", path), \
                 mock.patch.object(self.mod, "_delivery_possible", probe), \
                 mock.patch.object(self.mod, "_alert", lambda r: alerts.append(r)), \
                 mock.patch.object(self.mod.subprocess, "run", _fake_run):
                getattr(self.mod, fn)()
            written = json.loads(path.read_text(encoding="utf-8"))
        return alerts, pushes, written


class TestRecoveryFromAnUndeliverableEnvironment(_Branch):
    """Сердце аварии: снятие таблички из CI. Ровно то, что спамило владельцу."""

    def test_owner_is_not_paged(self):
        alerts, _, _ = self._run("_clear_degrade", {"degraded": True}, deliverable=False)
        self.assertEqual(
            alerts, [],
            "снятие таблички, которое отсюда невозможно, не имеет права звонить "
            "владельцу: в CI дедупа нет по построению — это 4 одинаковых "
            "сообщения в сутки бессрочно")

    def test_the_pusher_is_not_even_called(self):
        """Звать инструмент, который откажет гарантированно, — не попытка, а ритуал."""
        _, pushes, _ = self._run("_clear_degrade", {"degraded": True}, deliverable=False)
        self.assertEqual(pushes, [])

    def test_the_ephemeral_snapshot_is_left_alone(self):
        """Снимок раннера умрёт вместе с job'ом: правка = ложь себе о состоянии."""
        _, _, written = self._run("_clear_degrade", {"degraded": True}, deliverable=False)
        self.assertIs(written["degraded"], True)

    def test_the_reason_is_named_out_loud(self):
        self._run("_clear_degrade", {"degraded": True}, deliverable=False)
        notes = [n for n in self.mod._DELIVERY_NOTES if not n["delivered"]]
        self.assertTrue(notes, "недоставка обязана оставить след в отчёте")
        self.assertEqual(notes[0]["reason"], "delivery_impossible_here")
        self.assertFalse(notes[0]["owner_paged"])
        self.assertEqual(notes[0]["what"], "снятие таблички честности")


class TestTheWholeChainInARunnerShapedTree(unittest.TestCase):
    """Сквозной контроль БЕЗ подмены пробы — то есть ровно прогон 167 (14.08 07:47Z).

    Отдельный тест, потому что классы выше подменяют `_delivery_possible`: они
    проверяют РАЗВИЛКУ, а не то, что она включится в настоящей среде. Ровно на
    этом шве проект горел не раз («сторож честно отвечает на свой вопрос»).
    Здесь работает настоящая проба, настоящий контракт пушера и настоящий путь
    формы GitHub Actions.
    """

    def test_no_alert_no_push_no_write(self):
        mod = _load()
        alerts, pushes = [], []
        with TemporaryDirectory() as t:
            snap = Path(t) / "work" / "SPA" / "SPA" / "landing" / "src" / "data"
            snap.mkdir(parents=True)
            f = snap / "track_snapshot.json"
            f.write_text(json.dumps({"degraded": True, "paper_apy_pct": 5.23}),
                         encoding="utf-8")
            with mock.patch.object(mod, "_SNAP", f), \
                 mock.patch.object(mod, "_alert", lambda r: alerts.append(r)), \
                 mock.patch.object(mod.subprocess, "run",
                                   lambda *a, **k: pushes.append(a) or mock.Mock(returncode=1)):
                mod._clear_degrade()
            written = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(alerts, [], "это и есть те 4 сообщения в сутки")
        # `pushes` ловит и git-вызовы самой пробы (`subprocess.run` подменён на
        # уровне модуля) — нас интересует единственный: запуск инструмента доставки.
        self.assertEqual([c for c in pushes
                          if any("push_to_github" in str(x) for x in c[0])], [])
        self.assertIs(written["degraded"], True)
        self.assertEqual(mod.exit_code(True, mod._DELIVERY_NOTES), 1,
                         "молчание в чате обязано оплачиваться красным job'ом")


class TestProtectionIsNotWeakened(_Branch):
    """Обратная сторона: то, ради чего сторож существует, обязано звонить."""

    def test_undeliverable_degrade_still_pages_the_owner(self):
        """Публика видит завышенное число — тут молчать нельзя ни при какой среде."""
        alerts, _, _ = self._run("_apply_degrade", {"degraded": False}, deliverable=False)
        self.assertTrue(alerts, "непоставленная табличка честности = публичное "
                                "завышение; владелец обязан узнать")
        self.assertIn("HONESTY_PLAQUE_UNDELIVERED", json.dumps(alerts, ensure_ascii=False))

    def test_a_refusal_where_delivery_was_possible_still_pages(self):
        """`rc != 0` из живого дерева — аномалия, а не свойство среды. Обе ветки."""
        for fn, snap in (("_apply_degrade", {"degraded": False}),
                         ("_clear_degrade", {"degraded": True})):
            with self.subTest(fn=fn):
                alerts, pushes, _ = self._run(fn, snap, deliverable=True, rc=5)
                self.assertTrue(pushes, "из живого дерева пушер обязан быть позван")
                self.assertTrue(alerts, "отказ доставки обязан дойти до человека")

    def test_a_successful_push_stays_silent(self):
        alerts, _, written = self._run("_clear_degrade", {"degraded": True},
                                       deliverable=True, rc=0)
        self.assertEqual(alerts, [])
        self.assertIs(written["degraded"], False)


class TestTheProbeMeasuresTheRealContract(unittest.TestCase):
    """Проба обязана спрашивать пушер, а не угадывать по имени каталога."""

    def setUp(self):
        self.mod = _load()

    def test_a_file_of_this_repo_is_deliverable(self):
        ok, why = self.mod._delivery_possible(_REPO / "landing" / "src" / "data" /
                                              "track_snapshot.json")
        self.assertTrue(ok, why)

    def test_a_runner_shaped_path_is_not(self):
        """Форма GitHub Actions: файл вне любого worktree этого репозитория."""
        with TemporaryDirectory() as t:
            p = Path(t) / "work" / "SPA" / "SPA" / "landing" / "src" / "data"
            p.mkdir(parents=True)
            f = p / "track_snapshot.json"
            f.write_text("{}", encoding="utf-8")
            ok, why = self.mod._delivery_possible(f)
        self.assertFalse(ok)
        self.assertTrue(why, "отказ без причины не даёт следующему разбору ничего")

    def test_an_unmeasurable_probe_does_not_block_delivery(self):
        """Не смогли измерить ⇒ пробуем доставить: тихая недоставка хуже лишней попытки."""
        with mock.patch.object(self.mod, "_ROOT", Path("/nonexistent-root-for-probe")):
            ok, _ = self.mod._delivery_possible(_REPO / "README.md")
        self.assertTrue(ok)


class TestUndeliveredWorkTurnsTheJobRed(unittest.TestCase):
    """Раз тревога владельцу для этого направления запрещена — сигнал обязан
    остаться хотя бы в коде возврата. Иначе «снять табличку нечем» неотличимо от
    чистого прогона: отчёт `ok`, код 0, табличка не снимается никогда."""

    def setUp(self):
        self.mod = _load()

    def test_clean_run_stays_green(self):
        self.assertEqual(self.mod.exit_code(True, []), 0)
        self.assertEqual(self.mod.exit_code(True, [{"delivered": True}]), 0)

    def test_undelivered_plaque_reddens_an_otherwise_clean_run(self):
        """Ровно форма 14.08: проверки прошли, а табличка не снялась."""
        self.assertEqual(
            self.mod.exit_code(True, [{"delivered": False,
                                       "reason": "delivery_impossible_here"}]), 1)

    def test_failed_checks_still_redden(self):
        self.assertEqual(self.mod.exit_code(False, []), 1)


if __name__ == "__main__":
    unittest.main()
