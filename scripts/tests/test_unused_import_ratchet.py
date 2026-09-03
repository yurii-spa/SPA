"""
scripts/tests/test_unused_import_ratchet.py — Sprint T10 (2026-06-27)

Unused-import RATCHET over SPA's MONEY-PATH + actively-edited dirs.

Runs ``pyflakes`` over the money-path packages and counts the
``imported but unused`` warnings. Asserts the count stays ``<=`` a pinned
ceiling — a one-way ratchet so it can only go DOWN, never up. This guards
against an accidental re-introduction of dead imports on the code that
actually moves capital (cycle/allocator/risk/api-routers/strategy-lab/alerts).

  Mirrors the ceiling style of ``tests/test_dead_code_resolved.py`` —
  a regression guardrail, NOT a hard zero.

─── Pinned count history ─────────────────────────────────────────────────────
  * 2026-06-27 (Sprint T10): cleaned 126 → 36. Ceiling pinned at **36**.
  * 2026-08-01 (цикл #74): count had drifted to **70** and this test was RED — but
    nobody saw it, because no workflow ran ``scripts/tests/`` at all (both ran only
    ``tests/`` and ``spa_core/tests/``). Cleaned back to **70 → 36**; CEILING was NOT
    touched — the observed count was brought back to what this docstring already
    promised, which is the only direction invariant #16 allows. The 34 extra split
    into: 28 genuinely dead imports (unused ``typing`` names, ``json``, ``math``,
    ``decimal.Decimal``, ``dataclasses.field``, and 6 unused module/name imports) —
    removed after checking, for each, that no other module pulls it and that the
    imported module has no import-time side effects; plus 6 in
    ``spa_core/strategy_lab/underwriting/__init__.py`` — a DELIBERATE re-export that
    carried only ``# noqa: F401``, which flake8 honours and pyflakes (what this test
    actually runs) does not; it now also declares ``__all__``, the same convention
    the list below names. The directory is now run by both workflows, so this ratchet
    finally bites; recurrence of the class is gated by
    ``spa_core/tests/test_ci_covers_every_test_dir.py``.
    Карточка: ``agent-ci-never-runs-scripts-tests-dir``.
  * 2026-08-10 (цикл #190): count had drifted to **38** and this test was RED on clean
    ``origin/main`` — the first recurrence AFTER the dir became CI-covered, so this time
    the ratchet is what reported it (цикл #189 found it red, not a human). Both extras were
    genuinely dead names, and in BOTH the module stays imported via other names on the SAME
    statement — so removal cannot change any import-time side effect, which is the one
    hazard this cleanup has to rule out:
      - ``spa_core/paper_trading/shadow_trigger_eval.py`` — ``from datetime import date as
        _date``; ``_date`` occurred exactly ONCE in the file (its own import line) and no
        importer pulls it. Arrived with d1faaf6f5 (Y3 shadow-trigger reconciliation).
      - ``spa_core/strategy_lab/swarm/rank_demotion_forward.py`` — ``EXPECTED_BOOKS``
        re-imported from ``dwell_hysteresis_forward``; not in this module's ``__all__``, and
        every reader in the repo reaches it through ``dwell_hysteresis_forward`` directly
        (``dh.EXPECTED_BOOKS``), never through ``rank_demotion_forward``. Arrived with
        c7daaa257 (paper-модуль рангового демоушена).
    Back to **36** — the count this docstring already promised. CEILING NOT touched
    (инв. #16: the observed count came down to the pin, the pin did not come up to it).
    Карточка: ``inbox-hrapovik-neispolzuemyh-importov-krasnyi``.

Why the floor is 36 and not 0 — every remaining warning is a DELIBERATE,
documented re-export / back-compat surface that MUST stay (removing it would
break ``from <module> import X`` callers/tests byte-for-byte):

  * spa_core/alerts/__init__.py        (1)  — ``telegram_client`` re-exported as a
       package attribute so tests can monkeypatch
       ``spa_core.alerts.telegram_client.send_message`` (``# noqa: F401``).
  * spa_core/alerts/risk_monitor.py    (24) — threshold-constant + alert-class
       re-export block from ``apy_feed_monitors`` kept byte-for-byte so the ~10
       test files + export_data that do ``from alerts.risk_monitor import <CONST>``
       keep working (``# noqa: F401``).
  * spa_core/paper_trading/cycle_runner.py (10) — documented back-compat surface;
       tests do ``from ...cycle_runner import <name>`` for the extracted
       _cycle_io / equity / cycle_reporting helpers (``# noqa: F401``).
  * spa_core/risk/scoring_engine.py    (1)  — ``import urllib.error`` kept
       intentionally for exception-handler safety; pyflakes flags only the
       redundant binding.

To LOWER the ceiling: clean more genuinely-unused imports, then drop CEILING to
the new observed count. To RAISE it: don't — that defeats the ratchet. If a NEW
legitimate re-export must be added, document it here and bump CEILING by exactly
that count, with a dated note above.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Money-path + actively-edited dirs under ratchet.
MONEY_PATH_DIRS = [
    "spa_core/paper_trading/",
    "spa_core/allocator/",
    "spa_core/risk/",
    "spa_core/api/routers/",
    "spa_core/strategy_lab/",
    "spa_core/alerts/",
]

# Pinned ceiling — 2026-06-27 (Sprint T10): observed 36 after the clean.
# RATCHET: this may only ever be LOWERED, never raised (see module docstring).
CEILING = 36


class PyflakesUnavailable(RuntimeError):
    """Инструмент замера недоступен — «не смотрели» ≠ «нечего смотреть» (#465).

    До #465 отсутствие `pyflakes` давало ЧИСЛО 0, и оба производных теста читали
    его как замер:

    * `test_money_path_unused_imports_le_ceiling` **ЗЕЛЕНЕЛ** (`0 <= 36`) — храповик
      молча переставал кусаться, ничего не измерив. Это fail-OPEN, и он тише
      красного теста, поэтому опаснее;
    * `test_ceiling_is_tight` КРАСНЕЛ с советом «Lower CEILING to 0 so the ratchet
      stays tight» — то есть предлагал зафиксировать ноль, которого никто не мерил.
      Послушавшийся получил бы ЛОЖНО ЗАТЯНУТЫЙ храповик: на машине с pyflakes он
      краснеет на 36 настоящих импортах, и его выключают. Ловушка инварианта #16
      наоборот — не ослабление, а фальшивое усиление.

    Тот же класс, что и `_free_pid` в `spa_core/tests/test_cycle_lock_watch.py`
    (тот же цикл): предпосылка не обеспечена ⇒ говорим об этом ВСЛУХ, а не судим.

    Карточка `inbox-hrapovik-importov-sovetuet-zatyanut-seby` числила это
    починенным циклом #278 — перемер #465 показал, что на `origin/main` правки нет
    ВОВСЕ (последнее касание файла — #191). Отчёту карточки не верить, мерить.
    """


def _pyflakes_probe(run=None):
    """`(есть ли инструмент, чем именно отказал)`. `run` — ВХОД, умолчание = настоящий ОС-вызов."""
    runner = run if run is not None else subprocess.run
    try:
        proc = runner(
            [sys.executable, "-m", "pyflakes", "--version"],
            capture_output=True, text=True, timeout=30,
        )
    except OSError as exc:                              # интерпретатор/среда не отвечают
        return False, f"{exc.__class__.__name__}: {exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip() or f"rc={proc.returncode}"
    return True, ""


def _unused_import_count(run=None) -> int:
    """Run pyflakes over the money-path dirs; count 'imported but unused'.

    Инструмента нет ⇒ `PyflakesUnavailable`, а НЕ ноль (см. класс выше).
    """
    runner = run if run is not None else subprocess.run
    ok, why = _pyflakes_probe(run=runner)
    if not ok:
        raise PyflakesUnavailable(
            f"pyflakes недоступен — считать неиспользуемые импорты нечем: {why}")
    targets = [str(REPO / d) for d in MONEY_PATH_DIRS]
    result = runner(
        [sys.executable, "-m", "pyflakes", *targets],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=120,
    )
    # pyflakes exits non-zero when it finds warnings — that's expected.
    out = result.stdout
    return sum(1 for line in out.splitlines() if "imported but unused" in line)


def _count_or_refuse_to_judge(run=None) -> int:
    """Число — либо ОТКАЗ СУДИТЬ с названной причиной. Молчания здесь нет.

    Отказ не создаёт дыры: сосед `test_pyflakes_available` продолжает краснеть на
    отсутствие инструмента — это и есть fail-CLOSED. Здесь же важно ДРУГОЕ: ни один
    вердикт о потолке не выносится по непроведённому замеру.
    """
    try:
        return _unused_import_count(run=run)
    except PyflakesUnavailable as exc:
        pytest.fail(f"НЕ ИЗМЕРЕНО: {exc}. Потолок CEILING={CEILING} не подтверждён и "
                    f"не опровергнут — менять его по этому прогону НЕЛЬЗЯ.")


class TestUnusedImportRatchet:
    def test_pyflakes_available(self):
        """pyflakes must be importable — the ratchet depends on it."""
        proc = subprocess.run(
            [sys.executable, "-m", "pyflakes", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, (
            "pyflakes is not available — the unused-import ratchet cannot run. "
            f"stderr: {proc.stderr.strip()!r}"
        )

    def test_money_path_unused_imports_le_ceiling(self):
        """Unused-import count over money-path dirs must stay <= the pinned ceiling.

        This is a one-way ratchet: it can only go down. A FAILURE means new
        unused imports were introduced on the capital-moving code path — remove
        them (do NOT raise CEILING).
        """
        count = _count_or_refuse_to_judge()
        assert count <= CEILING, (
            f"Unused-import count on money-path dirs rose to {count} "
            f"(ceiling {CEILING}). New dead imports were introduced — remove them. "
            f"Do NOT raise the ceiling; the ratchet only goes down."
        )

    def test_ceiling_is_tight(self):
        """The ceiling must not drift far above the actual count.

        If the real count has dropped well below CEILING, LOWER the ceiling so
        the ratchet keeps biting. Allow a small buffer (4) for transient churn.
        """
        count = _count_or_refuse_to_judge()
        assert count >= CEILING - 4, (
            f"Unused-import count dropped to {count}, well under the ceiling "
            f"{CEILING}. Lower CEILING to {count} so the ratchet stays tight."
        )


# ── Положительные контроли к третьему исходу «НЕ ИЗМЕРЕНО» (#465) ────────────
#
# Метод тот же, что у `_free_pid` в `spa_core/tests/test_cycle_lock_watch.py`
# (тот же цикл): двери к окружению — ВХОД, поэтому «инструмента нет» можно
# воспроизвести, не ломая машину. Умолчание `run=None` = настоящий `subprocess.run`,
# так что штатный прогон побайтово прежний.

class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _tool_missing(cmd, **kw):
    """Окружение без pyflakes — дословно то, что печатает python3 -m pyflakes."""
    return _Proc(returncode=1, stderr="No module named pyflakes\n")


def _tool_present(count):
    """Окружение С pyflakes, докладывающее ровно `count` неиспользуемых импортов."""
    def run(cmd, **kw):
        if "--version" in cmd:
            return _Proc(returncode=0, stdout="3.4.0\n")
        body = "".join(f"x.py:{i}:1 'os' imported but unused\n" for i in range(count))
        return _Proc(returncode=1 if count else 0, stdout=body)
    return run


def test_missing_tool_is_refused_not_counted_as_zero():
    """Ядро находки: без инструмента был ЧИСЛОМ 0, стал ОТКАЗОМ."""
    with pytest.raises(PyflakesUnavailable) as err:
        _unused_import_count(run=_tool_missing)
    assert "No module named pyflakes" in str(err.value)


def test_unmeasured_run_never_advises_lowering_the_ceiling():
    """Совет «Lower CEILING to 0» по непроведённому замеру больше не звучит.

    Ловим `BaseException`: и `pytest.fail`, и `pytest.skip` поднимают потомков
    `BaseException`, а не `AssertionError`. Если сюда однажды вернут `skip`, исход
    стал бы «skipped» — контроль замолчал бы ровно от того дефекта, против которого
    написан.
    """
    try:
        got = _count_or_refuse_to_judge(run=_tool_missing)
    except BaseException as exc:                        # noqa: B036 — см. докстринг
        msg = str(exc)
        assert "НЕ ИЗМЕРЕНО" in msg, f"отказ обязан НАЗЫВАТЬ себя, а сказал: {msg!r}"
        assert "Lower CEILING" not in msg, (
            "вердикт о потолке вынесен по непроведённому замеру — ровно находка карточки")
        assert type(exc).__name__ != "Skipped", (
            "«не измерено» снова стало неотличимо от «прошло»: вернулся скип")
    else:
        raise AssertionError(
            f"без pyflakes счёт не измеряется, а вернулось число {got} — fail-OPEN жив")


def test_ceiling_verdicts_still_bite_when_the_tool_is_there():
    """Обратная сторона: «всегда отказывать» было бы зелёным на контроле выше.

    С инструментом счёт настоящий, и оба вердикта выносятся как раньше.
    """
    assert _count_or_refuse_to_judge(run=_tool_present(36)) == 36
    assert _count_or_refuse_to_judge(run=_tool_present(0)) == 0


def test_probe_separates_absent_tool_from_a_noisy_but_working_one():
    """`pyflakes` пишет находки в stdout и выходит НЕнулевым — это не «его нет».

    Проба спрашивает `--version` именно поэтому: путать «инструмент нашёл 36 штук»
    с «инструмента нет» — значит вернуть ту же подмену с другой стороны.
    """
    assert _pyflakes_probe(run=_tool_present(36))[0] is True
    ok, why = _pyflakes_probe(run=_tool_missing)
    assert ok is False and "No module named pyflakes" in why
