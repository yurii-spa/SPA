# LLM_FORBIDDEN
"""Код возврата отчётного агента отвечает за РАБОТОСПОСОБНОСТЬ, а не за вердикт.

АВАРИЯ, ВОСПРОИЗВЕДЁННАЯ ЗДЕСЬ (2026-08-08, карточка
`agent-checkpoint-7day-gate-conflict`). Владелец разрешил поставить четыре готовых
агента; три встали, `checkpoint-7day` гейт деплоя не пропустил:

    --- manual run exit=1 ---
    ❌ FAIL: manual run exited 1 (expected 0). NOT loading com.spa.checkpoint-7day.

Гейт был прав по своим правилам, и агент по своим — но правила разные. Прямой прогон
показывал, что отчёт построен ПОЛНОСТЬЮ и корректно, а код 1 означал «в проверках есть
красное» (настоящая дыра 2026-06-21 → 2026-06-30). launchd, `agent_health` и гейт читают
`last_exit` как ответ на «агент работает?». Поставь такого агента — и он вечно числился бы
`last_exit=1` с вечным WARN, то есть мы обменяли бы «агент не работает» на «агент всегда
красный», а на шум через неделю перестают смотреть.

Каждый тест ниже — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: на старом коде (`return 0 if passed else 1`)
он краснеет.

КОНТРОЛИ В ОБЕ СТОРОНЫ, чтобы это не оказалось молча выключенной проверкой (инвариант #16):
  * вердикт при коде 0 НИКУДА не девается — блок FAILURES печатается, алерт владельцу
    уходит, а ноль объявляется вслух как «отчёт построен», а не «всё зелено»;
  * настоящий сбой (нечего читать, упало посреди счёта) по-прежнему даёт НЕнулевой код,
    и гейт деплоя его по-прежнему ОТКАЗЫВАЕТСЯ пропускать;
  * код вердикта не потерян — `--verdict-exit-code` возвращает его человеку и внешнему CI.

Время — вход (`run_checkpoint(..., today=)`): окно доказанных дней судит о свежести, и
фикстура с литеральной датой при настоящих часах была бы бомбой замедленного действия
(`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "checkpoint_7day.py"
_GATE = _REPO / "scripts" / "check_agent_before_deploy.sh"

# Единственная точка, где живёт «сегодня» этих тестов. Все отметки фикстур строятся
# ОТ НЕЁ, поэтому обе стороны закреплены и календарь на тесты не влияет.
_TODAY = date(2026, 8, 17)


def _load():
    spec = importlib.util.spec_from_file_location("checkpoint_7day_exitcode", str(_SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, doc) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _make_data_dir(root: Path, *, equity: float = 100_500.0, days: int = 10) -> Path:
    """Полный набор файлов, на котором чекпойнт проходит ПОЛНОСТЬЮ (все проверки pass)."""
    d = root / "data"
    d.mkdir(parents=True, exist_ok=True)
    dates = [(_TODAY - timedelta(days=days - 1 - i)) for i in range(days)]

    _write(d / "gap_monitor.json", {
        "gap_detected": False, "active_gaps": [], "hours_since_last_entry": 3.0,
    })
    _write(d / "paper_evidence.json",
           {"days": [{"date": x.isoformat(), "equity_value": equity} for x in dates]})
    _write(d / "equity_curve_daily.json", {
        "summary": {"end_equity": equity},
        "daily": [
            {
                "date": x.isoformat(),
                "open_equity": 100_000.0 + i * 20.0,
                "close_equity": 100_000.0 + (i + 1) * 20.0,
                "equity": 100_000.0 + (i + 1) * 20.0,
                # Честные метки — те самые, по которым канонический предикат
                # (`track_evidence.is_evidenced_bar`) считает день доказанным.
                "evidenced": True, "source": "cycle",
            }
            for i, x in enumerate(dates)
        ],
    })
    _write(d / "paper_trading_status.json", {
        "current_equity": equity, "apy_today_pct": 9.0, "kill_switch_active": False,
    })
    _write(d / "tournament_ranking.json", {"strategies": [{"id": "S7", "sharpe": 0.95}]})
    _write(d / "golive_status.json", {"ready": False, "evidenced_anchor": dates[0].isoformat()})
    _write(d / "adapter_status.json", {"adapters": []})
    return d


@contextlib.contextmanager
def _recording_authority(mod):
    """Подменяет ЕДИНСТВЕННЫЙ путь уведомления (`spa_core.telegram.push_policy`).

    Записываем каждую отправку: без этого «код 0» нельзя отличить от «вердикт потерян».

    Подменяются АТРИБУТЫ уже импортированного модуля, а не запись в `sys.modules`:
    `_notify_via_push_policy` делает `from spa_core.telegram import push_policy`, то есть
    берёт атрибут пакета. Заглушка в `sys.modules` при этом висела бы в пустоте, а
    настоящий отправитель исполнялся по-настоящему — бил бы в боевой Telegram и писал в
    живое состояние дедупа (тот же дефект разобран в `tests/test_checkpoint_7day.py`).
    """
    from spa_core.telegram import push_policy

    recorded: list[tuple[str, str, str]] = []

    def _fake_push(event_key, severity, title, body, *a, **kw):
        recorded.append(("push", event_key, body))
        return True

    def _fake_resolve(event_key, title, body, *a, **kw):
        recorded.append(("resolve", event_key, body))
        return True

    def _forbidden(msg: str) -> bool:
        raise AssertionError(
            "run_checkpoint позвал notify_telegram напрямую: путей уведомления снова два"
        )

    saved = (push_policy.push_critical, push_policy.resolve, mod.notify_telegram)
    push_policy.push_critical, push_policy.resolve = _fake_push, _fake_resolve
    mod.notify_telegram = _forbidden
    try:
        yield recorded
    finally:
        push_policy.push_critical, push_policy.resolve, mod.notify_telegram = saved


class _Base(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, data_dir, **kw):
        """Прогон с перехватом stdout — печать вердикта тоже является предметом проверки."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.mod.run_checkpoint(data_dir=data_dir, today=_TODAY, **kw)
        return code, buf.getvalue()


class TestExitCodeMeansWorkable(_Base):
    """Сама авария."""

    def test_red_verdict_still_exits_zero_because_the_report_WAS_built(self):
        d = _make_data_dir(self.root, equity=50_000.0)  # ниже floor → красная проверка
        with _recording_authority(self.mod):
            code, out = self._run(d)
        self.assertEqual(code, self.mod.EXIT_OK,
                         f"агент-репортёр обязан отчитаться кодом работоспособности:\n{out}")
        self.assertEqual(self.mod.EXIT_OK, 0)

    def test_the_verdict_is_NOT_lost_when_the_code_is_zero(self):
        """Без этого «код 0» был бы молча выключенной проверкой."""
        d = _make_data_dir(self.root, equity=50_000.0)
        with _recording_authority(self.mod) as recorded:
            code, out = self._run(d)
        self.assertEqual(code, self.mod.EXIT_OK)
        self.assertIn("--- FAILURES ---", out, "красное обязано быть НАПЕЧАТАНО")
        self.assertIn("equity_floor", out)
        self.assertEqual(len(recorded), 1, f"алерт владельцу не ушёл: {recorded}")
        kind, event_key, body = recorded[0]
        self.assertEqual(kind, "push")
        self.assertEqual(event_key, "checkpoint_failed")
        self.assertIn("FAILED", body)

    def test_zero_with_red_checks_is_ANNOUNCED_not_silent(self):
        """Ноль не имеет права выглядеть как «всё зелено» — он объясняется вслух."""
        d = _make_data_dir(self.root, equity=50_000.0)
        with _recording_authority(self.mod):
            _, out = self._run(d)
        self.assertIn("ЕСТЬ КРАСНОЕ", out)
        self.assertIn("отчёт построен", out)

    def test_a_clean_run_still_exits_zero_and_resolves_the_alarm(self):
        d = _make_data_dir(self.root)
        with _recording_authority(self.mod) as recorded:
            code, out = self._run(d)
        self.assertEqual(code, self.mod.EXIT_OK, out)
        self.assertNotIn("--- FAILURES ---", out)
        self.assertEqual([r[0] for r in recorded], ["resolve"],
                         "выход из тревоги обязателен (ADR-070 п.4)")

    def test_the_verdict_code_is_still_available_on_request(self):
        """Вердикт-код не потерян: человек у терминала и внешний CI его получают."""
        d = _make_data_dir(self.root, equity=50_000.0)
        with _recording_authority(self.mod):
            code, out = self._run(d, verdict_exit_code=True)
        self.assertEqual(code, self.mod.EXIT_VERDICT_FAIL, out)
        self.assertEqual(self.mod.EXIT_VERDICT_FAIL, 1)

    def test_verdict_flag_on_a_clean_run_is_still_zero(self):
        d = _make_data_dir(self.root)
        with _recording_authority(self.mod):
            code, out = self._run(d, verdict_exit_code=True)
        self.assertEqual(code, self.mod.EXIT_OK, out)

    def test_suppressed_channel_does_not_change_the_code(self):
        """`--no-telegram` трогает канал, а не вердикт и не работоспособность."""
        d = _make_data_dir(self.root, equity=50_000.0)
        with _recording_authority(self.mod) as recorded:
            code, out = self._run(d, notify=False)
        self.assertEqual(code, self.mod.EXIT_OK, out)
        self.assertEqual(recorded, [], "канал был тронут вопреки notify=False")
        with _recording_authority(self.mod):
            code, _ = self._run(d, notify=False, verdict_exit_code=True)
        self.assertEqual(code, self.mod.EXIT_VERDICT_FAIL)


class TestGenuineBreakageStillExitsNonZero(_Base):
    """Сторона, без которой это была бы молча выключенная проверка."""

    def test_missing_data_dir_is_a_BREAKAGE_not_a_verdict(self):
        code, out = self._run(self.root / "no_such_data_dir")
        self.assertEqual(code, self.mod.EXIT_BROKEN, out)
        self.assertEqual(self.mod.EXIT_BROKEN, 2)
        self.assertIn("BROKEN", out)

    def test_a_check_that_raises_is_a_BREAKAGE(self):
        """Отчёт не построен ⇒ агент сломан. Это НЕ то же, что «в треке дыра»."""
        d = _make_data_dir(self.root)

        def boom(*a, **kw):
            raise RuntimeError("счёт упал")

        self.mod.check_sharpe = boom
        with _recording_authority(self.mod) as recorded:
            code, out = self._run(d)
        self.assertEqual(code, self.mod.EXIT_BROKEN, out)
        self.assertIn("отчёт не построен", out)
        self.assertEqual(recorded, [],
                         "сбой не имеет права уехать владельцу как обычный вердикт")

    def test_breakage_code_differs_from_the_verdict_code(self):
        """Три кода — три разных ответа; слипнись они, и различение снова исчезнет."""
        self.assertNotEqual(self.mod.EXIT_OK, self.mod.EXIT_BROKEN)
        self.assertNotEqual(self.mod.EXIT_VERDICT_FAIL, self.mod.EXIT_BROKEN)
        self.assertNotEqual(self.mod.EXIT_OK, self.mod.EXIT_VERDICT_FAIL)


# ─── Гейт деплоя: теперь пропускает репортёра и по-прежнему ловит поломку ─────

_SCHEDULED_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.spa.{name}</string>
  <key>KeepAlive</key><false/>
  <key>StartInterval</key><integer>3600</integer>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>{wrapper}</string>
  </array>
  <key>StandardOutPath</key><string>{out}</string>
  <key>StandardErrorPath</key><string>{err}</string>
</dict></plist>
"""


class TestDeployGateAndTheReporterConvention(unittest.TestCase):
    """Тот самый отказ гейта — и то, что он остаётся отказом для НАСТОЯЩЕЙ поломки.

    Гейт НЕ получает списка «доверенных агентов-репортёров»: список молча устаревает и
    стал бы дырой в fail-CLOSED гейте (карточка, вариант 2 — отклонён). Правильный
    носитель конвенции — агент; гейт лишь называет её в отказе.

    Прогон идёт с `CHECK_ONLY=1` + `SPA_GATE_REPO_ROOT` — гейт принимает подмену корня
    ТОЛЬКО в этой связке и ничего не грузит в launchd.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "logs").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()
        for name in getattr(self, "_logs", []):
            with contextlib.suppress(OSError):
                Path(name).unlink()

    def _agent(self, name: str, body: str):
        wrapper = self.root / "scripts" / f"agent_{name}.sh"
        wrapper.write_text(body, encoding="utf-8")
        wrapper.chmod(0o755)
        plist = self.root / "scripts" / f"com.spa.{name}.plist"
        plist.write_text(_SCHEDULED_PLIST.format(
            name=name, wrapper=str(wrapper),
            out=str(self.root / "logs" / f"{name}.out"),
            err=str(self.root / "logs" / f"{name}.err"),
        ), encoding="utf-8")
        self._logs = getattr(self, "_logs", []) + [f"/tmp/spa_{name}.log"]
        return name

    def _run_gate(self, name: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update({
            "CHECK_ONLY": "1",
            "SPA_GATE_REPO_ROOT": str(self.root),
            "RUN_TIMEOUT": "20",
            "KICKSTART_TIMEOUT": "5",
        })
        return subprocess.run(
            ["/bin/bash", str(_GATE), name],
            capture_output=True, text=True, env=env, timeout=180, cwd=str(self.root),
        )

    @staticmethod
    def _reporter(name: str, exit_code: int) -> str:
        """Агент-репортёр: печатает отчёт с красной проверкой и выходит `exit_code`."""
        return (
            "#!/bin/bash\n"
            f'echo "=== report built, 1 check RED ===" >> "/tmp/spa_{name}.log"\n'
            f"exit {exit_code}\n"
        )

    def test_the_incident_a_reporter_that_exits_1_is_REFUSED(self):
        """Что и случилось 08.08 — гейт прав, потому что 1 означает «сломан»."""
        name = self._agent("cpfx_verdict1", self._reporter("cpfx_verdict1", 1))
        res = self._run_gate(name)
        self.assertNotEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        self.assertIn("manual run exited 1", res.stdout + res.stderr)

    def test_the_refusal_NAMES_the_two_conventions(self):
        """Иначе следующий столкнётся с той же загадкой на пустом месте."""
        name = self._agent("cpfx_verdict1b", self._reporter("cpfx_verdict1b", 1))
        res = self._run_gate(name)
        blob = res.stdout + res.stderr
        self.assertIn("VERDICT", blob)
        self.assertIn("checkpoint_7day.py", blob)

    def test_the_FIXED_reporter_gets_PAST_the_exit_code_assertion(self):
        """Починка в агенте: отчёт построен ⇒ код 0 ⇒ гейт больше не отказывает на коде.

        Предмет проверки — РЕШЕНИЕ ГЕЙТА ПО КОДУ ВОЗВРАТА, поэтому утверждение именно
        о нём, а не о `returncode` всего гейта. Дальше по тому же пути стоит проверка
        свежести лога через `stat -f %m` — форма BSD, и на Linux (CI) она в принципе не
        доходит до конца. Требовать здесь `returncode == 0` значило бы завязать проверку
        конвенции кодов на платформу и получить красный CI по причине, не имеющей к ней
        отношения (тот же класс, что разобран в `test_deploy_gate_long_lived.py`, где
        соседний тест про run-once путь утверждает только факт запуска). На macOS путь
        проходит целиком — и это утверждается отдельно ниже.
        """
        name = self._agent("cpfx_verdict0", self._reporter("cpfx_verdict0", 0))
        res = self._run_gate(name)
        blob = res.stdout + res.stderr
        self.assertIn("manual run exit=0", blob, blob)
        self.assertNotIn("manual run exited", blob,
                         f"гейт всё ещё отказывает репортёру на коде возврата:\n{blob}")
        if sys.platform == "darwin":
            self.assertEqual(res.returncode, 0, blob)

    def test_a_genuinely_broken_agent_is_STILL_refused(self):
        """Контроль в обратную сторону: код 2 (сбой) гейт обязан по-прежнему ловить."""
        name = self._agent("cpfx_broken", self._reporter("cpfx_broken", 2))
        res = self._run_gate(name)
        self.assertNotEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        self.assertIn("manual run exited 2", res.stdout + res.stderr)


class TestTheRealAgentIsNotLongLived(unittest.TestCase):
    """`checkpoint-7day` — расписанный агент, и его МОЖНО проверять прогоном.

    Долгожитель (`KeepAlive` без расписания) проверяется БЕЗ запуска: «пробный прогон»
    поднял бы второй живой процесс рядом с продом (08.08 — второй поллер Telegram на том
    же токене). Здесь это условие названо явно, чтобы правильный путь не выбирался
    случайно.
    """

    def test_the_plist_is_scheduled_not_keepalive(self):
        plist = _REPO / "scripts" / "com.spa.checkpoint-7day.plist"
        self.assertTrue(plist.is_file(), f"{plist} отсутствует в этом чекауте")
        probe = _REPO / "scripts" / "agent_static_probe.sh"
        res = subprocess.run(
            ["/bin/bash", str(probe), "--plist-bool", "KeepAlive", str(plist)],
            capture_output=True, text=True, timeout=30,
        )
        # Контракт пробника: `true|false|dict|""`. Ключа в plist нет ⇒ пусто.
        # Читается ЗНАЧЕНИЕ, а не наличие ключа: `<key>KeepAlive</key><false/>`
        # когда-то читался как «сервер», и зависание расписанного агента гейт
        # объявлял успехом (`.claude/rules/deployment.md`).
        self.assertEqual(res.stdout.strip(), "",
                         "значение читается, а не наличие ключа")
        ll = subprocess.run(
            ["/bin/bash", str(probe), "--is-long-lived", str(plist)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(ll.returncode, 1,
                         "расписанный агент не долгожитель — его проверяют прогоном")


if __name__ == "__main__":
    unittest.main()
