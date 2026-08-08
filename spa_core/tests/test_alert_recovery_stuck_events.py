"""Тревога должна уметь ЗАКОНЧИТЬСЯ — иначе следующая настоящая беззвучна.

ADR-070 п.4 (решение владельца 2026-08-07, вариант A). Уведомления владельцу
устроены по перелому: `ok → bad` — одно сообщение, пока «плохо» — тишина,
`bad → ok` — одно «✅». Обратный переход в коде умели объявлять ровно четыре
отправителя (`cycle_gap`, `system_critical`, `agent_health_critical`,
`core_agent_down`). У остальных был вход и не было выхода, и замер в проде
показал, чем это кончилось:

    kill_switch     bad с 2026-07-04, entry_pushed: false
    rules_critical  bad с 2026-07-08
    golive_ready    bad, ни один отправитель его не резолвит

Первая строка — самая дорогая: сработай стоп-кран завтра, push_policy честно
увидел бы «уже плохо» и промолчал. Причём первое сообщение тогда ТОЖЕ не дошло —
ровно тот класс, который мы закрываем месяц: система уверена, что сообщила.

Каждый тест ниже — положительный контроль: он воспроизводит именно это
застрявшее состояние и на неисправленном коде краснеет. Проверки идут В ОБЕ
СТОРОНЫ: выздоровление объявляется, когда измерено, и НЕ объявляется, когда
измерить не удалось (иначе мы заменили бы одну ложь другой).

Пороги стоп-крана (SOFT −5% / HARD −10%) и RiskPolicy здесь не участвуют —
это слой уведомлений. Транспорт замокан, живое состояние не трогается.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.telegram import push_policy


# ── общая оснастка ───────────────────────────────────────────────────────────
def _write_push_state(tg_dir: Path, events: dict) -> None:
    tg_dir.mkdir(parents=True, exist_ok=True)
    (tg_dir / push_policy.PUSH_STATE_FILENAME).write_text(
        json.dumps({"schema_version": 1, "source": "test", "events": events,
                    "ceiling": {}}),
        encoding="utf-8",
    )


def _read_push_state(tg_dir: Path) -> dict:
    doc = json.loads((tg_dir / push_policy.PUSH_STATE_FILENAME).read_text())
    return doc.get("events", {})


class _PushHarness(unittest.TestCase):
    """Изолированный каталог состояния + перехваченный транспорт."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tg_dir = Path(self._tmp.name) / "telegram"
        self.tg_dir.mkdir(parents=True, exist_ok=True)
        self.sent: list[str] = []
        self._patches = [
            mock.patch.object(push_policy, "_DEFAULT_TG_DIR", self.tg_dir),
            mock.patch.object(push_policy, "_send",
                              lambda text: (self.sent.append(text), True)[1]),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(self._teardown)

    def _teardown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    @property
    def data_dir(self) -> Path:
        return Path(self._tmp.name)


# ═══════════════════════════════════════════════════════════════════════════
# A. golive_ready — веха это не «состояние плохо», а разовое событие
# ═══════════════════════════════════════════════════════════════════════════
class TestGoliveMilestoneIsOneShot(_PushHarness):
    """Хорошая новость, записанная как «плохо», глушит следующую хорошую новость.

    `golive_ready` шлют только две точки — обе объявляют ВЕХУ (дней трека,
    APY выше порога, гейт 26/26). Это не условие, которое портится и чинится:
    выздоровлению здесь неоткуда взяться, и ни один отправитель его не звал.
    Значит лечится не resolve'ом, а честной одноразовостью — как `pilot_request`.
    Повтора не будет: обе точки уже дедуплицируют вехи по id в своём файле.
    """

    def test_stale_bad_state_does_not_silence_a_new_milestone(self):
        # Замер прода: ключ висит в «плохо», доставленный вход, никто не резолвит.
        _write_push_state(self.tg_dir, {
            "golive_ready": {"state": "bad",
                             "last_ts": "2026-08-07T09:10:50+00:00",
                             "entry_pushed": True},
        })
        sent = push_policy.push_critical(
            "golive_ready", "CRITICAL", "SPA Milestone", "30 дней трека")
        self.assertTrue(sent, "веха проглочена застрявшим состоянием «плохо»")
        self.assertEqual(len(self.sent), 1)

    def test_two_milestones_in_a_row_both_reach_the_owner(self):
        self.assertTrue(push_policy.push_critical(
            "golive_ready", "CRITICAL", "SPA Milestone", "веха 1"))
        self.assertTrue(push_policy.push_critical(
            "golive_ready", "CRITICAL", "SPA Milestone", "веха 2"))
        self.assertEqual(len(self.sent), 2)

    def test_milestone_never_records_a_persistent_bad_state(self):
        push_policy.push_critical(
            "golive_ready", "CRITICAL", "SPA Milestone", "веха")
        rec = _read_push_state(self.tg_dir)["golive_ready"]
        self.assertEqual(rec["state"], "ok")
        self.assertTrue(rec.get("oneshot"))

    def test_daily_ceiling_still_applies_to_milestones(self):
        """Одноразовость снимает дедуп, а не потолок — иначе это дыра в защите."""
        for i in range(3):
            push_policy.push_critical(
                "golive_ready", "CRITICAL", "SPA Milestone", f"веха {i}",
                daily_ceiling=2)
        self.assertEqual(len(self.sent), 3)  # 2 вехи + одно «ещё события»
        self.assertIn("лимит", self.sent[-1])

    def test_kill_switch_is_NOT_one_shot(self):
        """Контроль в обратную сторону: дедуп длящегося стоп-крана не тронут.

        Если бы «починка» сделала одноразовыми все ключи, стоп-кран снова
        стучался бы каждые 5 минут — ровно то, что чинил edge-trigger.
        """
        self.assertTrue(push_policy.push_critical(
            "kill_switch", "CRITICAL", "Kill", "сработал"))
        self.assertFalse(push_policy.push_critical(
            "kill_switch", "CRITICAL", "Kill", "сработал"))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(_read_push_state(self.tg_dir)["kill_switch"]["state"], "bad")


# ═══════════════════════════════════════════════════════════════════════════
# B. kill_switch — выздоровление объявляет threat_reactor
# ═══════════════════════════════════════════════════════════════════════════
# Точный снимок прода на 2026-08-08: тревога о срабатывании 04.07 висит в
# «плохо», и её первое сообщение владельцу НЕ ДОШЛО.
_PROD_STUCK_KILL_SWITCH = {
    "kill_switch": {"state": "bad",
                    "last_ts": "2026-07-04T23:18:27+00:00",  # FROZEN-DATE-OK: исторический инцидент
                    "entry_pushed": False},
}


class TestKillSwitchRecovery(_PushHarness):

    def setUp(self) -> None:
        super().setUp()
        from spa_core.monitoring import threat_reactor
        self.tr = threat_reactor
        self.data = self.data_dir
        p = mock.patch.object(threat_reactor, "_DATA", self.data)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, threats=None):
        with mock.patch.object(self.tr, "_detect_threats",
                               return_value=list(threats or [])):
            return self.tr.run_reactor()

    # ── прямая сторона: измерено «снят» + угроз нет ⇒ одно «✅» ──────────────
    def test_stuck_alert_is_resolved_when_switch_off_and_no_threats(self):
        _write_push_state(self.tg_dir, _PROD_STUCK_KILL_SWITCH)
        report = self._run(threats=[])
        self.assertEqual(report["kill_switch_state"], self.tr.KS_CLEAR)
        self.assertTrue(report["alert_pending_before_run"])
        self.assertTrue(report["alert_resolved"], "тревога так и осталась висеть")
        self.assertIsNone(report["recovery_held_back"])
        self.assertEqual(_read_push_state(self.tg_dir)["kill_switch"]["state"], "ok")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("✅", self.sent[0])

    def test_resolve_says_out_loud_that_the_first_alarm_never_arrived(self):
        """Нельзя закрывать тревогу так, будто владелец её видел, — он её не получил."""
        _write_push_state(self.tg_dir, _PROD_STUCK_KILL_SWITCH)
        self._run(threats=[])
        self.assertIn("не дошло", self.sent[0])
        self.assertIn("2026-07-04", self.sent[0])

    def test_after_recovery_the_next_firing_sounds_again(self):
        """Смысл всей правки: следующая настоящая тревога снова звучит."""
        _write_push_state(self.tg_dir, _PROD_STUCK_KILL_SWITCH)
        self._run(threats=[])
        # Именно ПЕРЕЛОМ, а не повторная попытка недоставленного входа: без
        # выздоровления ключ остаётся «плохо», и следующее срабатывание уедет
        # как retry — оно прозвучит один раз и снова заклинит.
        self.assertEqual(_read_push_state(self.tg_dir)["kill_switch"]["state"], "ok")
        self.sent.clear()
        fired = push_policy.push_critical(
            "kill_switch", "CRITICAL", "Kill", "новое срабатывание")
        self.assertTrue(fired, "новая тревога снова проглочена")
        self.assertEqual(len(self.sent), 1)

    # ── обратная сторона: не измерено ⇒ НЕ объявляем ────────────────────────
    def test_no_recovery_while_a_threat_is_standing(self):
        _write_push_state(self.tg_dir, _PROD_STUCK_KILL_SWITCH)
        report = self._run(threats=["depeg CRITICAL: usdc dev 3.0%"])
        self.assertFalse(report["alert_resolved"])
        self.assertEqual(report["recovery_held_back"], "threats_still_present")
        self.assertEqual(_read_push_state(self.tg_dir)["kill_switch"]["state"], "bad")

    def test_no_recovery_while_the_kill_switch_is_still_on(self):
        _write_push_state(self.tg_dir, _PROD_STUCK_KILL_SWITCH)
        (self.data / "kill_switch_active.json").write_text(
            json.dumps({"active": True, "reason": "test"}), encoding="utf-8")
        report = self._run(threats=[])
        self.assertEqual(report["kill_switch_state"], self.tr.KS_ACTIVE)
        self.assertFalse(report["alert_resolved"])
        self.assertEqual(report["recovery_held_back"], "kill_switch_state_active")

    def test_unreadable_state_is_unknown_and_blocks_the_recovery(self):
        """Файл, который не удалось прочитать, — не доказательство, что всё хорошо."""
        _write_push_state(self.tg_dir, _PROD_STUCK_KILL_SWITCH)
        (self.data / "kill_switch_active.json").write_text("{не json", encoding="utf-8")
        with mock.patch("spa_core.governance.kill_switch.KillSwitchChecker",
                        side_effect=OSError("checker unavailable")):
            report = self._run(threats=[])
        self.assertEqual(report["kill_switch_state"], self.tr.KS_UNKNOWN)
        self.assertFalse(report["alert_resolved"])
        self.assertEqual(report["recovery_held_back"], "kill_switch_state_unknown")
        self.assertEqual(self.sent, [])
        self.assertEqual(_read_push_state(self.tg_dir)["kill_switch"]["state"], "bad")

    def test_nothing_pending_means_no_message_at_all(self):
        _write_push_state(self.tg_dir, {"kill_switch": {"state": "ok",
                                                        "last_ts": "2026-08-01T00:00:00+00:00"}})
        report = self._run(threats=[])
        self.assertFalse(report["alert_pending_before_run"])
        self.assertFalse(report["alert_resolved"])
        self.assertEqual(self.sent, [])

    def test_dry_run_never_touches_the_alert_state(self):
        _write_push_state(self.tg_dir, _PROD_STUCK_KILL_SWITCH)
        with mock.patch.object(self.tr, "_detect_threats", return_value=[]):
            report = self.tr.run_reactor(dry_run=True)
        self.assertFalse(report["alert_resolved"])
        self.assertEqual(self.sent, [])
        self.assertEqual(_read_push_state(self.tg_dir)["kill_switch"]["state"], "bad")

    # ── измерение состояния стоп-крана само по себе ─────────────────────────
    def test_absent_file_is_measured_clear_not_unknown(self):
        """«Стоп-кран выключен» = файла нет. Это измерение, а не незнание."""
        with mock.patch("spa_core.governance.kill_switch.KillSwitchChecker",
                        side_effect=OSError("checker unavailable")):
            self.assertEqual(self.tr._kill_switch_state(), self.tr.KS_CLEAR)

    def test_activation_path_is_unchanged_by_the_unknown_state(self):
        """Нечитаемый файл НЕ должен мешать включить защиту — только объявить выздоровление."""
        (self.data / "kill_switch_active.json").write_text("{не json", encoding="utf-8")
        with mock.patch("spa_core.governance.kill_switch.KillSwitchChecker",
                        side_effect=OSError("checker unavailable")):
            self.assertEqual(self.tr._kill_switch_state(), self.tr.KS_UNKNOWN)
            self.assertFalse(self.tr._kill_switch_active())

    def test_unreadable_push_state_never_manufactures_a_recovery(self):
        (self.tg_dir / push_policy.PUSH_STATE_FILENAME).write_text("{битый",
                                                                   encoding="utf-8")
        report = self._run(threats=[])
        self.assertFalse(report["alert_pending_before_run"])
        self.assertFalse(report["alert_resolved"])
        self.assertEqual(self.sent, [])


# ═══════════════════════════════════════════════════════════════════════════
# C. rules_critical — выздоровление объявляет rules_watchdog
# ═══════════════════════════════════════════════════════════════════════════
_PROD_STUCK_RULES = {
    "rules_critical": {"state": "bad",
                       "last_ts": "2026-07-08T17:42:21+00:00",  # FROZEN-DATE-OK: исторический инцидент
                       "entry_pushed": True},
}


class TestRulesWatchdogRecovery(_PushHarness):

    def setUp(self) -> None:
        super().setUp()
        from spa_core.monitoring import rules_watchdog
        self.rw = rules_watchdog

    def _result(self, name, status):
        return self.rw.CheckResult(name, status, f"{name}: {status}")

    def _run(self, statuses):
        checks = [(lambda n=n, s=s: self._result(n, s)) for n, s in statuses]
        for fn, (n, _s) in zip(checks, statuses):
            fn.__name__ = f"check_{n}"  # type: ignore[attr-defined]
        with mock.patch.object(self.rw, "RULES_TO_CHECK", checks):
            return self.rw.run_watchdog(write=False, send_alert=True)

    def _report(self, statuses):
        """run_watchdog возвращает код возврата — отчёт снимаем из записи."""
        captured = {}
        real = self.rw._atomic_write

        def spy(path, payload):
            captured["report"] = payload[-1] if isinstance(payload, list) else payload
            return None

        checks = [(lambda n=n, s=s: self._result(n, s)) for n, s in statuses]
        for fn, (n, _s) in zip(checks, statuses):
            fn.__name__ = f"check_{n}"  # type: ignore[attr-defined]
        with mock.patch.object(self.rw, "RULES_TO_CHECK", checks), \
             mock.patch.object(self.rw, "_atomic_write", spy), \
             mock.patch.object(self.rw, "_load_json", return_value=[]):
            self.rw.run_watchdog(write=True, send_alert=True)
        assert real is not None
        return captured["report"]

    def test_stuck_alert_is_resolved_on_a_fully_clean_run(self):
        _write_push_state(self.tg_dir, _PROD_STUCK_RULES)
        report = self._report([("position_limits", "OK"), ("t1_concentration", "OK")])
        self.assertEqual(report["overall"], "OK")
        self.assertTrue(report["alert_pending_before_run"])
        self.assertTrue(report["alert_resolved"])
        self.assertIsNone(report["recovery_held_back"])
        self.assertEqual(_read_push_state(self.tg_dir)["rules_critical"]["state"], "ok")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("✅", self.sent[0])

    def test_unmeasured_rule_blocks_the_recovery(self):
        """SKIPPED — это «не проверено», а не «прошло»: закрывать тревогу нечем."""
        _write_push_state(self.tg_dir, _PROD_STUCK_RULES)
        report = self._report([("position_limits", "OK"),
                               ("adapter_status", "SKIPPED")])
        self.assertEqual(report["overall"], "UNCHECKED")
        self.assertFalse(report["alert_resolved"])
        self.assertEqual(report["recovery_held_back"], "overall_unchecked")
        self.assertEqual(self.sent, [])
        self.assertEqual(_read_push_state(self.tg_dir)["rules_critical"]["state"], "bad")

    def test_breach_still_present_blocks_the_recovery(self):
        _write_push_state(self.tg_dir, _PROD_STUCK_RULES)
        report = self._report([("position_limits", "CRITICAL")])
        self.assertFalse(report["alert_resolved"])
        self.assertEqual(report["recovery_held_back"], "breach_still_present")

    def test_warning_alone_blocks_the_recovery(self):
        _write_push_state(self.tg_dir, _PROD_STUCK_RULES)
        report = self._report([("position_limits", "WARNING")])
        self.assertFalse(report["alert_resolved"])
        self.assertEqual(report["recovery_held_back"], "overall_warning")

    def test_nothing_pending_means_no_message_at_all(self):
        _write_push_state(self.tg_dir, {"rules_critical": {"state": "ok",
                                                           "last_ts": "2026-08-01T00:00:00+00:00"}})
        report = self._report([("position_limits", "OK")])
        self.assertFalse(report["alert_pending_before_run"])
        self.assertFalse(report["alert_resolved"])
        self.assertEqual(self.sent, [])

    def test_after_recovery_the_same_breach_sounds_again(self):
        """Отпечаток инцидента спасает только ДРУГОЕ нарушение.

        Тот же самый набор правил, сорвавшийся повторно, даёт тот же отпечаток —
        и без выздоровления он навсегда «всё ещё плохо». Поэтому здесь висит
        именно тот отпечаток, который придёт снова.
        """
        _write_push_state(self.tg_dir, {
            "rules_critical": {"state": "bad",
                               "last_ts": "2026-07-08T17:42:21+00:00",  # FROZEN-DATE-OK: исторический инцидент
                               "entry_pushed": True,
                               "fingerprint": "position_limits"},
        })
        self._report([("position_limits", "OK")])
        self.assertEqual(_read_push_state(self.tg_dir)["rules_critical"]["state"], "ok")
        self.sent.clear()
        rc = self._run([("position_limits", "CRITICAL")])
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.sent), 1, "новое нарушение снова проглочено")
        self.assertIn("🚨", self.sent[0])

    def test_no_alert_flag_keeps_the_recovery_silent_too(self):
        """--no-alert обязан молчать в обе стороны, иначе прогон говорит за нас."""
        _write_push_state(self.tg_dir, _PROD_STUCK_RULES)
        with mock.patch.object(self.rw, "RULES_TO_CHECK", []):
            self.rw.run_watchdog(write=False, send_alert=False)
        self.assertEqual(self.sent, [])
        self.assertEqual(_read_push_state(self.tg_dir)["rules_critical"]["state"], "bad")


# ═══════════════════════════════════════════════════════════════════════════
# D. храповик: у каждого Tier-1 ключа-СОСТОЯНИЯ должен быть выход
# ═══════════════════════════════════════════════════════════════════════════
class TestEveryStatefulKeyHasAnExit(unittest.TestCase):
    """Сторож класса дефекта, а не одного его случая.

    Вход у ключа появляется сам собой (кто-то зовёт `push_critical`), выход —
    только осознанно. Именно эта асимметрия и породила четыре застрявших
    события. Ключ, который умеет «плохо», обязан уметь и «хорошо»: либо у него
    есть отправитель, зовущий `resolve`, либо он одноразовый (веха/лид), либо
    он назван здесь явным исключением с причиной.
    """

    # Ключи без выхода, признанные осознанно (не «забыли», а «пока некому»).
    KNOWN_EXITLESS = {
        # peg/red_flag: вход даёт peg_monitor/alert_dispatcher по HELD-протоколу;
        # у них есть per-incident fingerprint, поэтому НОВЫЙ инцидент звучит и без
        # resolve. Отдельная карточка на честное выздоровление — вне ADR-070 п.4.
        "peg_break", "red_flag",
        # cycle_failed: вход из cycle_runner; выход по смыслу даёт cycle_gap
        # (пропуск цикла), который резолвится. Не дублируем.
        "cycle_failed",
        # architecture_conformance_critical: fingerprint = множество находок,
        # другой набор = новый инцидент; выход добавляется в контуре ADR-066.
        "architecture_conformance_critical",
    }

    RESOLVED_BY_SENDERS = {
        "cycle_gap", "system_critical", "agent_health_critical",
        "core_agent_down", "kill_switch", "rules_critical",
        # telegram_down (ADR-077): сторож Телеграма объявляет и поломку, и выздоровление.
        "telegram_down",
        # checkpoint_failed: чекпойнт объявляет и провал, и возврат к норме.
        "checkpoint_failed",
    }

    def test_every_whitelisted_key_can_leave_the_bad_state(self):
        for key in sorted(push_policy.TIER1_WHITELIST):
            with self.subTest(key=key):
                has_exit = (key in self.RESOLVED_BY_SENDERS
                            or key in push_policy.ONESHOT_KEYS
                            or key in self.KNOWN_EXITLESS)
                self.assertTrue(
                    has_exit,
                    f"ключ {key!r} умеет «плохо» и не умеет «хорошо» — "
                    f"следующая тревога по нему будет беззвучной. Добавь resolve "
                    f"у отправителя, сделай ключ одноразовым или назови "
                    f"исключение с причиной в KNOWN_EXITLESS.",
                )

    def test_the_exit_lists_do_not_drift_from_the_whitelist(self):
        """Список исключений не должен переживать сам ключ (иначе он врёт молча)."""
        named = self.RESOLVED_BY_SENDERS | self.KNOWN_EXITLESS | set(push_policy.ONESHOT_KEYS)
        self.assertEqual(named - set(push_policy.TIER1_WHITELIST), set())

    def test_resolvers_named_here_really_exist_in_the_code(self):
        """Проверяем УТВЕРЖДЕНИЕ, а не список: у каждого имени есть вызов resolve."""
        repo = Path(__file__).resolve().parents[2]
        senders = {
            "cycle_gap": "spa_core/paper_trading/cycle_gap_monitor.py",
            "system_critical": "spa_core/monitoring/system_health_monitor.py",
            "agent_health_critical": "spa_core/monitoring/agent_health_monitor.py",
            "core_agent_down": "spa_core/monitoring/self_heal.py",
            "kill_switch": "spa_core/monitoring/threat_reactor.py",
            "rules_critical": "spa_core/monitoring/rules_watchdog.py",
            "telegram_down": "spa_core/monitoring/telegram_health.py",
            "checkpoint_failed": "scripts/checkpoint_7day.py",
        }
        self.assertEqual(set(senders), self.RESOLVED_BY_SENDERS)
        for key, rel in senders.items():
            with self.subTest(key=key):
                src = (repo / rel).read_text(encoding="utf-8")
                self.assertIn("push_policy.resolve(", src,
                              f"{rel} назван резолвером {key!r}, а resolve не зовёт")
                self.assertIn(f'"{key}"', src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
