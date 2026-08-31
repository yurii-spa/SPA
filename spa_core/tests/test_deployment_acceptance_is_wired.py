"""Положительные контроли к проводке сторожа «способен ли флот стартовать».

Карточка `inbox-storozh-sposoben-li-flot-startovat-nikem`, замер 28.08 и
перемерено 31.08 на `origin/main` 64444720b: у `deployment_acceptance` не было
НИ ОДНОГО вызывающего — ни launchd-агента, ни шага цикла, ни workflow. Модуль
работал ровно тогда, когда о нём вспоминала живая сессия, то есть отвечал на
свой вопрос только после того, как его кто-то задаст руками.

Правило `.claude/rules/deployment.md` требует от КАЖДОЙ новой проверки
положительный контроль: тест, который краснеет, когда проводку снимают.
Проверка, никогда не видевшая настоящей поломки, — украшение. Поэтому здесь
проверяется не наличие имени в исходнике, а ФОРМА вызова и его последствия:
подменённый сторож обязан менять вердикт домена, а его квитанция — появляться
на диске.

Каждый тест ниже краснеет ровно от одной снятой связи:

* убрать `out.append(self._probe_deployment_acceptance(D))` из
  `check_d5_code_integrity` → `test_d5_asks_whether_the_fleet_can_start`;
* перестать передавать вердикт наружу → `test_critical_reaches_the_domain`;
* убрать `write=True` → `test_probe_leaves_a_receipt_on_disk`;
* назвать каталог явно всегда → `test_default_tree_keeps_the_worktree_guard_armed`;
* убрать запись из `ARTIFACT_REGISTRY` → `test_both_receipts_are_freshness_tracked`;
* вернуться к неперсистящему `check_deployment_drift` →
  `test_drift_probe_refreshes_its_own_receipt`.

Времени в фикстурах нет намеренно (правило доставки, «фиксированная дата —
бомба замедленного действия»): предмет проверки — проводка, а не свежесть.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import unittest
from pathlib import Path

from spa_core.monitoring import artifact_freshness as af
from spa_core.monitoring import deployment_acceptance as acc
from spa_core.monitoring import deployment_drift_monitor as drift
from spa_core.monitoring import system_health_monitor as shm

D5 = "d5_code_integrity"
ACCEPTANCE_ID = "d5.deployment.acceptance"


def _monitor(tmp: Path) -> shm.SystemHealthMonitor:
    """Монитор, полностью посаженный в песочницу: живое `data/` не задевается."""
    (tmp / "data").mkdir(parents=True, exist_ok=True)
    return shm.SystemHealthMonitor(data_dir=str(tmp / "data"), project_root=str(tmp))


def _acceptance_doc(status: str, **over) -> dict:
    doc = {
        "status": status,
        "entrypoints_total": 79,
        "entrypoint_imports_ok": 66,
        "reasons": ["измерено фикстурой"],
    }
    doc.update(over)
    return doc


class AcceptanceWiringTest(unittest.TestCase):
    """Домен d5 обязан ЗАДАВАТЬ вопрос, а не только уметь его задать."""

    def setUp(self):
        self._tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self.mon = _monitor(self._tmp)
        self._real_run = acc.run_acceptance
        self.addCleanup(setattr, acc, "run_acceptance", self._real_run)
        self.calls: list = []

    def _stub(self, status: str = acc.OK, raises: BaseException | None = None):
        def _fake(**kwargs):
            self.calls.append(kwargs)
            if raises is not None:
                raise raises
            return _acceptance_doc(status)
        acc.run_acceptance = _fake

    # ── проводка ───────────────────────────────────────────────────────────
    def test_d5_asks_whether_the_fleet_can_start(self):
        """Снять вызов из `check_d5_code_integrity` — и этот тест краснеет."""
        self._stub()
        ids = [r.id for r in self.mon.check_d5_code_integrity()]
        self.assertIn(ACCEPTANCE_ID, ids,
                      "домен «Code Integrity» не спрашивает, способен ли флот "
                      "стартовать: {}".format(ids))
        self.assertTrue(self.calls, "сторож назван, но не позван")

    def test_wired_next_to_drift_and_neither_replaces_the_other(self):
        """Три вопроса — три сторожа: drift не отвечает за способность стартовать."""
        self._stub()
        ids = [r.id for r in self.mon.check_d5_code_integrity()]
        self.assertIn("d5.deployment.drift", ids)
        self.assertIn(ACCEPTANCE_ID, ids)

    # ── вердикт доезжает наружу ────────────────────────────────────────────
    def test_critical_reaches_the_domain(self):
        """Мёртвый флот обязан выйти из домена как CRITICAL, а не утонуть."""
        self._stub(acc.CRITICAL)
        res = {r.id: r for r in self.mon.check_d5_code_integrity()}[ACCEPTANCE_ID]
        self.assertEqual(shm.CRITICAL, res.status)

    def test_warning_is_not_rounded_to_ok(self):
        self._stub(acc.WARNING)
        res = self.mon._probe_deployment_acceptance(D5)
        self.assertEqual(shm.WARNING, res.status)

    def test_ok_is_ok(self):
        self._stub(acc.OK)
        res = self.mon._probe_deployment_acceptance(D5)
        self.assertEqual(shm.OK, res.status)
        self.assertIn("79", res.title)

    def test_unknown_verdict_is_not_a_pass(self):
        """Fail-CLOSED (инв. #2): незнакомый статус — «не измерено», не зачёт."""
        acc.run_acceptance = lambda **kw: _acceptance_doc("SOMETHING_NEW")
        res = self.mon._probe_deployment_acceptance(D5)
        self.assertEqual(shm.WARNING, res.status)

    def test_a_raising_guard_never_breaks_the_monitor(self):
        """Упавший сторож — WARNING домена, а не падение всего прогона."""
        self._stub(raises=RuntimeError("boom"))
        res = self.mon._probe_deployment_acceptance(D5)
        self.assertEqual(shm.WARNING, res.status)
        self.assertIn("boom", res.error or "")

    # ── квитанция ──────────────────────────────────────────────────────────
    def test_probe_leaves_a_receipt_on_disk(self):
        """Без файла «сторож молчит» неотличимо от «сторож согласен»."""
        acc.run_acceptance = self._real_run
        self.mon._probe_deployment_acceptance(D5)
        receipt = self._tmp / "data" / acc.STATE_FILENAME
        self.assertTrue(receipt.is_file(),
                        "приёмка отработала, а квитанции нет — снаружи сторожа не видно")
        doc = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual("deployment_acceptance", doc.get("monitor"))

    def test_receipt_lands_in_the_monitors_own_data_dir(self):
        """Квитанция ложится туда, куда монитор пишет остальное, — не в живое data/."""
        acc.run_acceptance = self._real_run
        self.mon._probe_deployment_acceptance(D5)
        self.assertEqual(
            [acc.STATE_FILENAME],
            [p.name for p in (self._tmp / "data").glob("deployment_*.json")])

    # ── ловушка ложной тишины ──────────────────────────────────────────────
    def test_default_tree_keeps_the_worktree_guard_armed(self):
        """Каталог по умолчанию НЕ называется явно — иначе снимается вопрос «чьё дерево».

        `run_acceptance` решает по `data_dir is None`, мерит ли она живое дерево
        прода или git-checkout. Передать каталог всегда — значит получить
        уверенное «просроченных артефактов нет», посчитанное по worktree, где
        mtime свеж ПО ПОСТРОЕНИЮ (комментарий `_data_dir_for`). Адресат при этом
        тот же самый, так что молча «упростить до всегда явного» ничего бы не
        сломало на глаз — сломался бы ровно заслон, и молча.
        """
        self.assertIsNone(self.mon._acceptance_data_dir(),
                          "дефолтный каталог назван явно — заслон worktree снят")
        self._stub()
        self.mon._probe_deployment_acceptance(D5)
        self.assertIsNone(self.calls[0]["data_dir"])
        self.assertEqual(Path(self._tmp), Path(self.calls[0]["repo_root"]))
        self.assertTrue(self.calls[0]["write"])

    def test_data_dir_pointed_elsewhere_is_passed_through(self):
        """Каталог, отличный от `<project_root>/data`, обязан доехать до приёмки."""
        elsewhere = self._tmp / "sandbox_data"
        elsewhere.mkdir()
        mon = shm.SystemHealthMonitor(data_dir=str(elsewhere), project_root=str(self._tmp))
        self._stub()
        mon._probe_deployment_acceptance(D5)
        self.assertEqual(elsewhere, self.calls[0]["data_dir"])


class DriftReceiptTest(unittest.TestCase):
    """`data/deployment_drift.json` протух на 19 суток: проверку звали, файл — нет."""

    def setUp(self):
        self._tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self.mon = _monitor(self._tmp)
        real = drift.check_deployment_drift
        self.addCleanup(setattr, drift, "check_deployment_drift", real)
        drift.check_deployment_drift = lambda **kw: drift.DriftReport(
            status=drift.OK, remote_ref="origin/main", reasons=["измерено фикстурой"])

    def test_drift_probe_refreshes_its_own_receipt(self):
        """Вернуться к неперсистящему `check_deployment_drift` — и тест краснеет."""
        res = self.mon._probe_deployment_drift(D5)
        self.assertEqual(shm.OK, res.status)
        receipt = self._tmp / "data" / drift.STATE_FILENAME
        self.assertTrue(receipt.is_file(),
                        "проверку дрейфа зовут, а её квитанцию не обновляет никто — "
                        "ровно то состояние, в котором файл простоял 19 суток")
        self.assertEqual("deployment_drift",
                         json.loads(receipt.read_text(encoding="utf-8")).get("monitor"))


class ReceiptsAreWatchedTest(unittest.TestCase):
    """Незарегистрированная квитанция протухает молча — это и есть класс аварии."""

    def test_both_receipts_are_freshness_tracked(self):
        by_path = {a.path: a for a in af.ARTIFACT_REGISTRY}
        for fname in (acc.STATE_FILENAME, drift.STATE_FILENAME):
            with self.subTest(artifact=fname):
                self.assertIn(fname, by_path,
                              "{} не в ARTIFACT_REGISTRY — его молчание неотличимо "
                              "от согласия".format(fname))
                self.assertTrue(by_path[fname].producer.strip(),
                                "у артефакта обязан быть НАЗВАННЫЙ производитель "
                                "(подотчётность, ADR-154/158)")

    def test_producer_declares_what_it_produces(self):
        """Контракт ОБЪЯВЛЯЮТ, а не выводят: обе квитанции — в `PRODUCES` агента."""
        for fname in (acc.STATE_FILENAME, drift.STATE_FILENAME):
            with self.subTest(artifact=fname):
                self.assertIn("data/" + fname, shm.PRODUCES)


if __name__ == "__main__":
    unittest.main()
