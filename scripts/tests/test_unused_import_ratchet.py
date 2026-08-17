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
  * 2026-08-17 (цикл #278): «инструмента нет» больше не читается как «ноль».
    НАМЕРЕННОЕ ИЗМЕНЕНИЕ ПРОВЕРОК (инвариант #16, журнал ``docs/journal/2026-W34.md``),
    и оно СТРОЖЕ прежнего, а не мягче. ``_unused_import_count()`` возвращал ``0``,
    когда ``pyflakes`` в окружении отсутствует (``No module named pyflakes`` →
    пустой stdout → ноль строк «imported but unused»). Отсюда две беды сразу:
      - ``test_money_path_unused_imports_le_ceiling`` был **fail-OPEN**: ``0 <= 36``
        зеленел, ничего не измерив, — храповик молча переставал кусаться;
      - ``test_ceiling_is_tight`` краснел с ВРЕДНЫМ советом «Lower CEILING to 0»;
        послушавшийся получил бы ложно затянутый храповик, который на машине
        с pyflakes краснеет на 36 законных ре-экспортах — и его бы выключили.
    Теперь отсутствие инструмента — ОТКАЗ ИЗМЕРЯТЬ (``PyflakesUnavailable``), оба
    производных теста говорят «не измерено» и не судят. Fail-CLOSED сохранён
    соседом: ``test_pyflakes_available`` продолжает КРАСНЕТЬ, когда инструмента нет,
    так что молчания не возникает — исчезает только ложный вердикт и ложный совет.
    CEILING не тронут. Карточка: ``inbox-hrapovik-importov-sovetuet-zatyanut-seby``.

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
    """Инструмент замера недоступен ⇒ числа НЕТ.

    Отдельный тип нужен ровно затем, чтобы «не измерено» нельзя было спутать
    с измеренным нулём: раньше оба выглядели как ``0``.
    """


def _pyflakes_probe() -> subprocess.CompletedProcess:
    """Спросить у окружения, есть ли pyflakes. Один вызов — один ответ."""
    return subprocess.run(
        [sys.executable, "-m", "pyflakes", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _unused_import_count() -> int:
    """Run pyflakes over the money-path dirs; count 'imported but unused'.

    Поднимает :class:`PyflakesUnavailable`, если инструмента нет. Возвращать
    здесь ``0`` — это выдавать «не смогли посмотреть» за «нечего смотреть»:
    храповик зеленел, ничего не измерив, и советовал затянуть себя до нуля.
    """
    probe = _pyflakes_probe()
    if probe.returncode != 0:
        raise PyflakesUnavailable(
            "pyflakes недоступен — числа неиспользуемых импортов НЕТ. "
            f"stderr: {(probe.stderr or '').strip()!r}"
        )
    targets = [str(REPO / d) for d in MONEY_PATH_DIRS]
    result = subprocess.run(
        [sys.executable, "-m", "pyflakes", *targets],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=120,
    )
    # pyflakes exits non-zero when it finds warnings — that's expected.
    out = result.stdout
    return sum(1 for line in out.splitlines() if "imported but unused" in line)


def _count_or_refuse_to_judge() -> int:
    """Число — или отказ судить. Никогда «0 вместо ответа»."""
    try:
        return _unused_import_count()
    except PyflakesUnavailable as exc:
        pytest.skip(
            f"не измерено: {exc}. Потолок НЕ трогать по непроведённому замеру — "
            "об отсутствии инструмента громко докладывает test_pyflakes_available."
        )


class TestUnusedImportRatchet:
    def test_pyflakes_available(self):
        """pyflakes must be importable — the ratchet depends on it."""
        proc = _pyflakes_probe()
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


class TestMissingToolIsNotZero:
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ к находке 17.08 (цикл #278).

    Авария дословно: ``pyflakes`` в окружении нет, stdout пуст, счёт строк
    «imported but unused» = **0** — и это читалось как измеренный ноль. Отсюда
    ``test_ceiling_is_tight`` печатал совет «Lower CEILING to 0», а
    ``test_money_path_unused_imports_le_ceiling`` зеленел, ничего не измерив.

    Контроль НЕ зависит от того, установлен ли pyflakes на этой машине: он
    подменяет ЗОНД. На коде до починки оба теста ниже КРАСНЫЕ (функция вернёт
    ``0`` вместо отказа), после — зелёные.
    """

    NO_MODULE = "/usr/bin/python3: No module named pyflakes\n"

    @staticmethod
    def _absent(monkeypatch):
        def fake_probe():
            return subprocess.CompletedProcess(
                args=["python3", "-m", "pyflakes", "--version"], returncode=1,
                stdout="", stderr=TestMissingToolIsNotZero.NO_MODULE)
        monkeypatch.setattr(sys.modules[__name__], "_pyflakes_probe", fake_probe)

    def test_absent_tool_refuses_instead_of_reporting_zero(self, monkeypatch):
        self._absent(monkeypatch)
        with pytest.raises(PyflakesUnavailable):
            _unused_import_count()

    def test_absent_tool_never_advises_lowering_the_ceiling(self, monkeypatch):
        """Ровно то сообщение, которое было вредным, не должно родиться."""
        self._absent(monkeypatch)
        # `Skipped` наследуется от BaseException — ловить `Exception` мало:
        # тест сам бы «пропустился» и выглядел безобидно.
        with pytest.raises(pytest.skip.Exception) as caught:
            _count_or_refuse_to_judge()
        text = str(caught.value)
        assert "не измерено" in text, text
        assert "Lower CEILING" not in text, text

    def test_present_tool_still_counts(self, monkeypatch):
        """Обратный контроль: при живом инструменте счёт по-прежнему считается.

        Без него «отказ» мог бы стать новым молчанием — тест зеленел бы оттого,
        что функция не считает НИКОГДА.
        """
        monkeypatch.setattr(
            sys.modules[__name__], "_pyflakes_probe",
            lambda: subprocess.CompletedProcess(args=[], returncode=0,
                                                stdout="3.2.0\n", stderr=""))
        out = ("a.py:1:1 'json' imported but unused\n"
               "b.py:2:1 'os' imported but unused\n"
               "c.py:3:1 local variable 'x' is assigned to but never used\n")
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1,
                                                        stdout=out, stderr=""))
        assert _unused_import_count() == 2

    def test_ceiling_is_untouched(self):
        """Потолок 36 — предмет храповика, а не этой починки."""
        assert CEILING == 36
