"""Кто и на каком доказательстве ГАСИТ тревогу «core agent down» (ADR-070 п.13).

ЧЕМ ТРЕВОГА ГАСИЛАСЬ. Класс `core_agent_down` общий: поднимают его `watchdog` и
`self_heal`, а право ПОГАСИТЬ принадлежало `self_heal` (own-28) — по ОДНОЙ своей
чистой проверке. Ходит он раз в 300 с (`scripts/com.spa.self_heal.plist`), то
есть инцидент закрывал через пять минут ровно тот компонент, который агента и
реанимировал, — раньше, чем его успевал увидеть хоть один часовой снимок пульса
(`scripts/com.spa.agent_health.plist`: 3600 с).

Хуже формы была цена. `push_policy._push_critical_impl` в ветке `resolved`
смотрит только на `state == "bad"` и НЕ смотрит на `entry_pushed`. А
`entry_pushed: false` — «входную тревогу владельцу так и не доставили» — это
замеренное в проде состояние (ADR-070 п.4: `kill_switch` висел таким с 04.07).
Поэтому раннее гашение не просто закрывало инцидент: оно СНИМАЛО повторную
попытку доставки и присылало владельцу «✅ восстановлено» от болезни, о которой
ему не сказали. Тревога, которая не доходит, хуже отсутствующей — она создаёт
уверенность.

РЕШЕНИЕ ВЛАДЕЛЬЦА 2026-08-07 (ADR-070 п.13, заменяет own-28): гасит
`agent_health`, и только по ДВУМ ЧИСТЫМ СНИМКАМ ПОДРЯД — «консервативнее
рекомендации».

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — `test_self_heal_no_longer_muffles_the_alarm`: он
воспроизводит ИМЕННО гашение (push_policy держит `bad` + недоставленную входную
тревогу, флот на снимке жив) и КРАСНЕЕТ на нефикшеном коде, где `self_heal`
гасил. Остальные тесты закрепляют новую власть и её fail-CLOSED-края.

# FROZEN-DATE-OK: injected-clock — все часы этого файла ВХОД (`now=`), и отметки
# снимков собираются от того же якоря (`_NOW ± timedelta`). Обе стороны времени
# закреплены, календарь на вердикт не влияет (`.claude/rules/deployment.md`,
# предпочтение №1).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.monitoring.agent_health_monitor import (
    CORE_AGENT_DOWN_CLEAN_SNAPSHOTS,
    CORE_AGENT_DOWN_KEY,
    core_agent_clean_streak,
    core_agent_snapshot_clean,
    maybe_resolve_core_agent_down,
)

_NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

_PENDING_DELIVERED = {
    "state": "bad",
    "fingerprint": "com.spa.daily_cycle",
    "entry_pushed": True,
}
_PENDING_UNDELIVERED = {
    "state": "bad",
    "fingerprint": "com.spa.daily_cycle",
    "entry_pushed": False,
}


def _agent(label: str, status: str = ahm.OK, loaded: bool = True) -> dict:
    return {"label": label, "status": status, "loaded": loaded}


def _snapshot(agents, *, now=_NOW, streak=None) -> dict:
    doc = {
        "timestamp": now.isoformat(),
        "stale_after_minutes": ahm.SNAPSHOT_STALE_MIN,
        "healthy_count": sum(1 for a in agents if a["status"] == ahm.OK),
        "agents": list(agents),
    }
    if streak is not None:
        doc["core_agent_clean_streak"] = streak
    return doc


_CLEAN = [_agent("com.spa.daily_cycle"), _agent("com.spa.apiserver")]
_DIRTY = [_agent("com.spa.daily_cycle", ahm.CRITICAL), _agent("com.spa.apiserver")]


# ===========================================================================
# 1. Что считается ЧИСТЫМ снимком (fail-CLOSED: «не измерено» ≠ «чисто»)
# ===========================================================================
class TestSnapshotCleanliness(unittest.TestCase):

    def test_no_critical_agent_is_clean(self):
        clean, reason = core_agent_snapshot_clean(_snapshot(_CLEAN))
        self.assertTrue(clean)
        self.assertIn("2", reason)

    def test_a_critical_agent_is_not_clean_and_is_named(self):
        clean, reason = core_agent_snapshot_clean(_snapshot(_DIRTY))
        self.assertFalse(clean)
        self.assertIn("com.spa.daily_cycle", reason)

    def test_snapshot_without_agents_is_not_clean(self):
        """Плисты не видны — это НЕ «все живы»."""
        clean, reason = core_agent_snapshot_clean(_snapshot([]))
        self.assertFalse(clean)
        self.assertIn("НЕ ИЗМЕРЕНО", reason)

    def test_nothing_loaded_is_not_clean(self):
        """launchctl промолчал: ни одного `loaded` ⇒ доказательства жизни нет."""
        agents = [_agent("com.spa.daily_cycle", loaded=False)]
        clean, reason = core_agent_snapshot_clean(_snapshot(agents))
        self.assertFalse(clean)
        self.assertIn("launchctl", reason)


# ===========================================================================
# 2. «Два ПОДРЯД» — счёт цепочки
# ===========================================================================
class TestCleanStreak(unittest.TestCase):

    def test_first_clean_snapshot_counts_one(self):
        streak, clean, _ = core_agent_clean_streak(_snapshot(_CLEAN), None, _NOW)
        self.assertEqual(streak, 1)
        self.assertTrue(clean)

    def test_second_consecutive_clean_snapshot_counts_two(self):
        prev = _snapshot(_CLEAN, now=_NOW - timedelta(minutes=60), streak=1)
        streak, clean, _ = core_agent_clean_streak(_snapshot(_CLEAN), prev, _NOW)
        self.assertEqual(streak, 2)
        self.assertTrue(clean)

    def test_a_dirty_snapshot_resets_the_chain(self):
        prev = _snapshot(_CLEAN, now=_NOW - timedelta(minutes=60), streak=5)
        streak, clean, _ = core_agent_clean_streak(_snapshot(_DIRTY), prev, _NOW)
        self.assertEqual(streak, 0)
        self.assertFalse(clean)

    def test_a_gap_in_the_chain_restarts_the_count(self):
        """Умер сам монитор (авария 2026-08-05) — «подряд» не было.

        Без этого «два снимка подряд» выродились бы в «два снимка когда-нибудь».
        """
        prev = _snapshot(_CLEAN, now=_NOW - timedelta(hours=8), streak=1)
        streak, _, reason = core_agent_clean_streak(_snapshot(_CLEAN), prev, _NOW)
        self.assertEqual(streak, 1)
        self.assertIn("подряд", reason)

    def test_unparseable_previous_timestamp_restarts_the_count(self):
        prev = _snapshot(_CLEAN, streak=1)
        prev["timestamp"] = "не дата"
        streak, _, reason = core_agent_clean_streak(_snapshot(_CLEAN), prev, _NOW)
        self.assertEqual(streak, 1)
        self.assertIn("заново", reason)


# ===========================================================================
# 3. Само гашение: порог, доказательство, честность
# ===========================================================================
class TestResolveAuthority(unittest.TestCase):

    def _run(self, streak, record, *, raises=False):
        from spa_core.telegram import push_policy

        calls: list = []
        report = _snapshot(_CLEAN)
        report["core_agent_clean_streak"] = streak
        kw = ({"side_effect": RuntimeError("state unreadable")} if raises
              else {"return_value": dict(record) if record else {}})
        with mock.patch.object(push_policy, "current_record", **kw), \
                mock.patch.object(
                    push_policy, "resolve",
                    side_effect=lambda *a, **k: (calls.append(a), True)[1]):
            out = maybe_resolve_core_agent_down(report)
        return out, calls

    def test_one_clean_snapshot_is_not_enough(self):
        """Сердце решения владельца: одного снимка мало — это и был прежний порог."""
        self.assertEqual(CORE_AGENT_DOWN_CLEAN_SNAPSHOTS, 2)
        out, calls = self._run(1, _PENDING_DELIVERED)
        self.assertIsNone(out)
        self.assertEqual(calls, [])

    def test_two_clean_snapshots_resolve_and_name_the_incident(self):
        out, calls = self._run(2, _PENDING_DELIVERED)
        self.assertIsNotNone(out)
        self.assertTrue(out["sent"])
        self.assertEqual(len(calls), 1)
        key, _title, body = calls[0]
        self.assertEqual(key, CORE_AGENT_DOWN_KEY)
        self.assertIn("com.spa.daily_cycle", body)   # что было
        self.assertIn("2", body)                     # сколько снимков

    def test_undelivered_entry_is_said_out_loud(self):
        """Гасим — но НЕ молча: владельцу говорят, что тревога тогда не дошла."""
        out, calls = self._run(2, _PENDING_UNDELIVERED)
        self.assertFalse(out["entry_delivered"])
        self.assertIn("НЕ ДОШЛА", calls[0][2])

    def test_nothing_pending_means_silence(self):
        """Нечего гасить ⇒ ни пуша, ни поля в отчёте, ни записи состояния."""
        out, calls = self._run(2, {"state": "ok"})
        self.assertIsNone(out)
        self.assertEqual(calls, [])

    def test_unreadable_push_state_does_not_resolve(self):
        """fail-CLOSED: «не смогли посмотреть» ≠ «можно гасить»."""
        out, calls = self._run(2, None, raises=True)
        self.assertIsNone(out)
        self.assertEqual(calls, [])


# ===========================================================================
# 4. Проводка в `run()`: цепочка живёт в самом снимке
# ===========================================================================
class TestMonitorWiring(unittest.TestCase):

    def test_two_hourly_runs_resolve_on_the_second(self):
        import tempfile
        from pathlib import Path

        from spa_core.telegram import push_policy

        resolves: list = []

        def _resolve(key, *a, **k):
            # `_push_via_policy` гасит СВОЙ ключ `agent_health_critical` — он к
            # этому классу отношения не имеет, считаем только core_agent_down.
            if key == CORE_AGENT_DOWN_KEY:
                resolves.append((key,) + a)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with mock.patch.object(push_policy, "current_record",
                                   return_value=dict(_PENDING_DELIVERED)), \
                    mock.patch.object(push_policy, "resolve", side_effect=_resolve), \
                    mock.patch.object(push_policy, "push_critical", return_value=False), \
                    mock.patch.object(ahm, "refresh_if_stale", return_value={}):

                def _run_at(now):
                    mon = ahm.AgentHealthMonitor(data_dir=data_dir,
                                                 launch_agents_dir=data_dir,
                                                 now=now)
                    with mock.patch.object(
                        ahm.AgentHealthMonitor, "collect",
                        return_value=_snapshot(_CLEAN, now=now),
                    ):
                        return mon.run(send=True)

                first = _run_at(_NOW)
                self.assertEqual(first["core_agent_clean_streak"], 1)
                self.assertNotIn("core_agent_down_resolved", first)
                self.assertEqual(resolves, [])

                second = _run_at(_NOW + timedelta(minutes=60))
                self.assertEqual(second["core_agent_clean_streak"], 2)
                self.assertTrue(second["core_agent_down_resolved"]["sent"])
                self.assertEqual(len(resolves), 1)


# ===========================================================================
# 5. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — воспроизводит САМО ГАШЕНИЕ
# ===========================================================================
class TestSelfHealNoLongerMuffles(unittest.TestCase):
    """Красный на нефикшеном коде: там `self_heal` гасил тревогу сам.

    Сцена дословно та, в которой own-28 звал resolve: флот на снимке жив, цикл
    свежий, прогон ничего не чинил, а `push_policy` держит `bad` по
    `core_agent_down` — причём с `entry_pushed: false`, то есть владелец о
    тревоге ещё НЕ ЗНАЕТ. До ADR-070 п.13 отсюда уходило «✅ восстановлено», и
    повторная попытка доставки входной тревоги пропадала вместе с состоянием.
    """

    def test_self_heal_no_longer_muffles_the_alarm(self):
        from spa_core.monitoring import self_heal
        from spa_core.telegram import push_policy

        resolves: list = []
        patches = [
            mock.patch.object(push_policy, "current_record",
                              return_value=dict(_PENDING_UNDELIVERED)),
            mock.patch.object(push_policy, "resolve",
                              side_effect=lambda *a, **k: (resolves.append(a), True)[1]),
            # герметичность: ни launchctl, ни диска, ни сети
            mock.patch.object(self_heal, "_bootstrap", return_value=True),
            mock.patch.object(self_heal, "_kickstart", return_value=True),
            mock.patch.object(self_heal, "_recover_cycle", return_value=True),
            mock.patch.object(self_heal, "_save", return_value=True),
            mock.patch.object(self_heal, "_save_revival_history", return_value=None),
            mock.patch.object(self_heal, "_send_telegram", return_value=None),
            mock.patch.object(self_heal, "_revival_history", return_value={}),
            mock.patch.object(self_heal, "_http_up", return_value=True),
            mock.patch.object(self_heal, "_served_cycle_age_hours", return_value=None),
            # живой флот + свежий цикл = прежнее условие гашения выполнено
            mock.patch.object(self_heal, "_expected_labels",
                              return_value=["com.spa.rules_watchdog"]),
            mock.patch.object(self_heal, "_loaded_labels",
                              return_value={"com.spa.rules_watchdog": 4321}),
            mock.patch.object(self_heal, "_must_be_resident", return_value=True),
            mock.patch.object(self_heal, "_last_cycle_age_hours", return_value=1.0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        report = self_heal.run_self_heal(dry_run=False)

        self.assertEqual(resolves, [],
                         "self_heal снова гасит core_agent_down — ADR-070 п.13 откачен")
        self.assertNotIn("core_agent_down_resolved", report)


if __name__ == "__main__":
    unittest.main()
