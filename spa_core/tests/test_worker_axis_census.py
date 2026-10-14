"""Перепись ИЗМЕРИМОСТИ оси РАБОТНИКА (ADR-722, G721 п. 3).

ВОПРОС, который прибор закрывает: ось РАБОТНИКА стои́т на чтении ОКРУЖЕНИЯ в выводе
`ps -A -Ewww`, а оно читается далеко не у всех процессов — замер 14.10 на рабочем Маке:
**74 строки из 651** (11.4 %). Пока частота не измерена, «третий исход» оси (`unmeasured`
⇒ `unchecked`) мог бы стать ПОСТОЯННЫМ на 3–4.17 ч, и этого никто бы не заметил: карточка
`inbox-zhurnal-obyavlenii-merit-zapuskatelya-vt` (п. 3) прямо говорит, что частоту не
мерил никто.

ЧТО ИЗМЕРЕНО 14.10 (и ради чего прибор устроен именно так): слепы почти исключительно
платформенные двоичные файлы Apple (`/System` 327, `/usr` 163, `/Applications` 65,
`/bin` 9, `/sbin` 1) — и среди них `/bin/bash`, то есть ЗАПУСКАТЕЛЬ цикла
(`scripts/agent_orchestrator.sh`). Все 21 строк python флота и `claude` окружение отдают.
Иначе говоря: слепота скрывает ровно ту личность, которой ADR-720/721 перестали верить, и
НЕ скрывает работника. Это ответ, а не успокоение, и он обязан пере-меряться прибором, а
не помниться по этому тексту.

Все три двери к ОС — ВХОДЫ. Живую машину тест не спрашивает ни разу.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MARK = "orchestrator-24396-ABC"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wac():
    return _load("_t866_census", "scripts/worker_axis_census.py")


@pytest.fixture(scope="module")
def w():
    return _load("_t866_wrapper3", "scripts/claude_run_with_timeout.py")


def _scene(w, rows):
    """rows: pid → (командная строка, хвост окружения или "")."""
    snap_rows, argv = {}, {}
    for pid, (cmd, env) in rows.items():
        argv[pid] = cmd
        snap_rows[pid] = (1, "S", 10.0, f"{cmd} {env}".strip())
    readable = sum(1 for _p, (_pp, _s, _a, tail) in snap_rows.items()
                   if "=" in tail and " PATH=" in " " + tail)
    return w.Snapshot(snap_rows, readable, len(snap_rows) - readable), argv


class TestThePopulationOfReadability:
    def test_it_counts_readable_and_blind_and_names_the_blind_class(self, wac, w):
        snap, argv = _scene(w, {
            10: ("claude -p цикл", f"PATH=/bin {w.RUN_ID_VAR}={MARK}"),
            11: ("/bin/bash scripts/agent_orchestrator.sh", ""),
            12: ("/System/Library/x/Y", ""),
        })
        rep = wac.census(wrapper=w, snap=snap, argv=argv, self_pid=99)
        assert rep["env_readable"] == 1 and rep["env_blind"] == 2
        assert rep["rows_total"] == 3
        assert any("/bin/" in k for k in rep["blind_by_class"]), rep["blind_by_class"]
        assert rep["axis_measurable"] is True

    def test_a_fully_blind_table_is_a_finding_not_a_clean_pass(self, wac, w):
        """Окружение не читается НИ У КОГО ⇒ ось слепа целиком. Это и есть постоянный
        третий исход; молчать о нём значило бы выдать «не измерено» за «свободна»."""
        snap, argv = _scene(w, {11: ("/bin/bash wrapper.sh", "")})
        rep = wac.census(wrapper=w, snap=snap, argv=argv, self_pid=99)
        assert rep["axis_measurable"] is False
        assert any("слепа целиком" in f for f in wac.findings(rep)), wac.findings(rep)


class TestWhoCountsAsALauncher:
    def test_the_tool_name_and_the_label_shape_are_both_required(self, wac):
        """Положительный контроль — НАСТОЯЩЕЕ ложное срабатывание первого прогона.

        Оболочка, в чьей командной строке лежал heredoc с текстом самого прибора, была
        опознана запускателем с «меткой» ``<метка>`),`` и дала находку «работника не
        видно» из ничего. Командная строка — не личность."""
        bad = "/bin/zsh -c cat > f <<EOF ... --run-id <метка>`), ... EOF"
        label, why = wac.launcher_label(bad)
        assert label is None, label
        assert "прибор запуска" in why or "формы метки" in why, why

        good = f"python3 scripts/claude_run_with_timeout.py --run-id {MARK} -- claude"
        assert wac.launcher_label(good) == (MARK, "")

    def test_each_of_the_two_requirements_is_measured_ALONE(self, wac):
        """Два условия — две сцены. Проверять их ОДНОЙ строкой нельзя: там каждое
        условие маскирует отсутствие другого, и мутационный прогон это показал — оба
        мутанта («имя прибора не требуется» и «форма метки не проверяется») ВЫЖИЛИ на
        общей сцене, потому что строку отбрасывал всегда второй guard."""
        # имя прибора ЕСТЬ, форма метки — нет ⇒ решает проверка формы
        shape_only = (f"python3 scripts/{wac.LAUNCHER_TOOL}.py --run-id <метка>`),")
        label, why = wac.launcher_label(shape_only)
        assert label is None and "формы метки" in why, (label, why)
        # форма метки ЕСТЬ, имени прибора — нет ⇒ решает проверка имени прибора
        tool_only = f"/bin/zsh -c grep --run-id {MARK} файл"
        label, why = wac.launcher_label(tool_only)
        assert label is None and "прибор запуска" in why, (label, why)

    def test_a_tool_without_the_flag_is_not_a_launcher(self, wac):
        label, why = wac.launcher_label("python3 scripts/claude_run_with_timeout.py --help")
        assert label is None and "метки в аргументах нет" in why


class TestCanBlindnessHideAWorker:
    def test_a_live_launcher_with_a_visible_worker_is_not_a_finding(self, wac, w):
        snap, argv = _scene(w, {
            5: (f"python3 scripts/claude_run_with_timeout.py --run-id {MARK}", ""),
            10: ("claude -p цикл", f"PATH=/bin {w.RUN_ID_VAR}={MARK}"),
        })
        rep = wac.census(wrapper=w, snap=snap, argv=argv, self_pid=99)
        assert len(rep["runs"]) == 1
        assert rep["runs"][0]["visible"] is True
        assert rep["runs"][0]["worker_pids"] == [10]
        assert wac.findings(rep) == []

    def test_a_live_launcher_without_a_visible_worker_is_a_finding(self, wac, w):
        """Ровно та сцена, которой боится п. 3: запускатель жив, работника не видно."""
        snap, argv = _scene(w, {
            5: (f"python3 scripts/claude_run_with_timeout.py --run-id {MARK}", ""),
            10: ("claude -p цикл", "PATH=/bin"),
        })
        rep = wac.census(wrapper=w, snap=snap, argv=argv, self_pid=99)
        assert rep["runs"][0]["visible"] is False
        assert any("НЕ ВИДНО" in f for f in wac.findings(rep))

    def test_the_measurer_itself_is_never_reported_as_the_worker(self, wac, w):
        """Замер 14.10: 2 из 4 носителей — сам прибор. Назвать их работником значило бы
        отвечать «работа идёт» на любой вопрос о любой метке."""
        snap, argv = _scene(w, {
            5: (f"python3 scripts/claude_run_with_timeout.py --run-id {MARK}", ""),
            77: ("python3 scripts/worker_axis_census.py",
                 f"PATH=/bin {w.RUN_ID_VAR}={MARK}"),
        })
        rep = wac.census(wrapper=w, snap=snap, argv=argv, self_pid=77)
        assert rep["runs"][0]["worker_pids"] == []
        assert rep["runs"][0]["self"] == [77]

    def test_a_cmdline_origin_carrier_is_named_as_a_finding(self, wac, w):
        snap, argv = _scene(w, {
            5: (f"python3 scripts/claude_run_with_timeout.py --run-id {MARK}", ""),
            10: (f"grep {w.RUN_ID_VAR}={MARK}", "PATH=/bin"),
        })
        rep = wac.census(wrapper=w, snap=snap, argv=argv, self_pid=99)
        assert rep["runs"][0]["counts"][w.MATCH_CMDLINE] == 1
        assert any("КОМАНДНОЙ строке" in f for f in wac.findings(rep))


class TestTheThirdOutcomeIsNotAPass:
    def test_an_unavailable_ps_is_not_measured_and_not_a_skip(self, wac, w, monkeypatch):
        """Отсутствие прибора — САМОСТОЯТЕЛЬНЫЙ третий исход, а не ноль и не скип
        (урок `pyflakes`, `.claude/rules/deployment.md`)."""
        class _Boom:
            PsUnavailable = w.PsUnavailable
            Snapshot = w.Snapshot

            @staticmethod
            def argv_rows(*a, **k):
                raise w.PsUnavailable("вторая таблица не снята (сцена)")
        snap, _argv = _scene(w, {10: ("claude", "PATH=/bin")})
        with pytest.raises(wac.NotMeasured) as exc:
            wac.census(wrapper=_Boom, snap=snap)
        assert "не снят" in str(exc.value)

    def test_the_cli_returns_two_when_nothing_was_measured(self, wac, monkeypatch):
        """Код возврата различает три исхода: 0 измерено · 1 находка · 2 НЕ ИЗМЕРЕНО."""
        def _boom(*a, **k):
            raise wac.NotMeasured("сцена: прибор не ответил")
        monkeypatch.setattr(wac, "census", _boom)
        assert wac.main([]) == 2

    def test_a_missing_instrument_is_named_by_path(self, wac, tmp_path):
        with pytest.raises(wac.NotMeasured) as exc:
            wac.load_wrapper(tmp_path / "нет-такого.py")
        assert "нет прибора владения" in str(exc.value)

    def test_an_instrument_without_the_origin_axis_is_refused(self, wac, tmp_path):
        """Сторож контракта: прибор без новой оси не ввозится молча."""
        fake = tmp_path / "claude_run_with_timeout.py"
        fake.write_text("class Snapshot: pass\n", encoding="utf-8")
        with pytest.raises(wac.NotMeasured) as exc:
            wac.load_wrapper(fake)
        assert "origin_census" in str(exc.value) or "argv_rows" in str(exc.value)
