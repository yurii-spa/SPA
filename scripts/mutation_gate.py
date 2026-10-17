#!/usr/bin/env python3
# LLM_FORBIDDEN
"""scripts/mutation_gate.py — a small, fast, deterministic MUTATION-TESTING gate
over SPA's CRITICAL money-path modules (Cutover-Bulletproof WS-6.3).

THE META-CHECK
==============
Property / fuzz / chaos suites prove the code does the right thing on the inputs
they try. But how do we know those tests would CATCH a real regression? A
mutation tester answers that empirically: it deliberately BREAKS the code (flips
an operator, nudges a constant), re-runs the tests, and checks a test FAILS. A
mutant the tests still PASS through is a SURVIVOR — a hole where a real bug of
that exact shape would slip past CI undetected.

This gate runs a CURATED, hand-picked set of high-value mutations against the four
most safety-critical modules and asserts the surviving-mutant count stays under a
documented threshold (0 — every curated mutant must be killed). The mutations are
chosen on the EXACT fail-closed boundaries that matter (the kill-switch threshold
comparison, the RiskPolicy cap/TVL/APY bounds, the reconcile NAV/dust tolerances,
the gate-chain ordering) — so a survivor is a directly meaningful coverage gap.

WHY CURATED (not blind AST-wide)
--------------------------------
A blind "mutate every operator" run produces thousands of equivalent / dead-code
mutants and takes minutes — too slow + noisy for a CI gate. We instead pin the
handful of mutations on the load-bearing safety boundaries, each with the FAST
subset of tests that should kill it. Deterministic, < ~60s, stdlib + pytest only.

CONTRACT
--------
  * INERT to source: each mutation is applied to a COPY of the file's text, the
    file is rewritten, the test subset is run, then the ORIGINAL text is restored
    in a finally (even on crash / Ctrl-C). The repo is byte-identical afterwards.
  * NEVER touches live data/ (the targeted tests are all hermetic / sandboxed).
  * Deterministic: same code → same survivor set. Exit 0 iff survivors ≤ threshold.

ОКНО ПРИБОРА — ПОЧЕМУ `finally` НЕДОСТАТОЧНО (цикл #889, заказ G772 п. 2, ADR-773)
----------------------------------------------------------------------------------
Строка «restored in a finally (even on crash / Ctrl-C)» выше ВЕРНА и НЕПОЛНА, и
разница измерена, а не рассуждена. `SIGKILL` не исполняет ни `finally`, ни
`atexit`, ни обработчик сигнала — это свойство ОС. Значит единственная копия
исходных байтов (локальная переменная `original`) умирает вместе с процессом, и
дерево остаётся держать мутанта, о котором НЕ ГОВОРИТ НИКТО.

Замер 2026-10-17 в одноразовом дереве `/private/tmp/spa_c889before`: прибор убит
`SIGKILL` через 12 с после старта ⇒ `spa_core/risk/policy.py` остался с мутацией
`risk_apy_max_bound_flip`, то есть **с отключённой верхней границей APY
единственного hard-гейта системы** (инв. #1: пул с APY > 30 % прошёл бы
RiskPolicy). При этом читатель окна отвечал «✅ ОКНА НЕТ, дерево чисто» (код 0), а
`enforce_no_delivered_mutant` пушера — «ПРОПУСТИЛ БЫ»: мутант уехал бы на `main`
молча, потому что гейт окна, доставленный ADR-772, спрашивает про ЗАПИСЬ, а этот
прибор записи не вёл вовсе. Полезная нагрузка здесь тяжелее, чем у находки #888
(там мутировалась перепись): мутируются `risk/policy.py`,
`governance/kill_switch.py`, `execution/reconciliation.py`,
`execution/gate_chain_audit.py` — ровно те файлы, которые читает дневной цикл.

Поэтому прибор НЕ ЗАВОДИТ своего учёта, а пишет ТУ ЖЕ запись
`.mutation_window/window.json`, что и `scripts/delta_mutation_run.py` (ADR-772):
окно есть свойство ДЕРЕВА, а не инструмента, и читателей у него уже три — сам
прибор (второе окно в том же дереве ОТКАЗЫВАЕТ), оба пушера (файл под открытым
окном НЕ ДОСТАВЛЯЕТСЯ, код 10) и `--window-restore` (путь наверх для дерева,
доставшегося в наследство). Вторая копия сверки разошлась бы с первой при первой
же правке формата записи.

Три исхода разведены (инв. #17): **0** — прогон измерен, выживших ≤ порога ·
**1** — прогон измерен, выжившие есть · **3** — прогон НЕ СОСТОЯЛСЯ и причина
названа (читателя окна нет на месте · в дереве уже открыто окно · байты после
прогона не сошлись со слепком). Третий исход не выдаётся ни за «чисто», ни за
«провал гейта»: отсутствие прибора есть самостоятельный ответ.

`--repo-root` существует ради правила `.claude/rules/deployment.md` § «ОКНО
МУТАЦИОННОГО ПРИБОРА»: мутационный прогон идёт в ОТДЕЛЬНОМ дереве, не в том, из
которого идёт доставка. Без этого флага прибор мог мутировать ТОЛЬКО своё дерево,
и в боевом дереве правило было неисполнимо по построению.

CLI::
    python3 scripts/mutation_gate.py            # run the gate, print the scorecard
    python3 scripts/mutation_gate.py --json     # machine-readable verdict
    python3 scripts/mutation_gate.py --threshold 0
    python3 scripts/mutation_gate.py --repo-root /tmp/spa_mut   # отдельное дерево
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYTHON = sys.executable

# Запись окна пишет и читает ОДИН объект на оба прибора — читатель живёт здесь.
_WINDOW_READER_REL = "scripts/delta_mutation_run.py"
_WINDOW_TOOL = "scripts/mutation_gate.py"
_WINDOW_TITLE = "mutation_gate (WS-6.3): кураторский набор мутантов money-path"

# Третий исход — свой код возврата: прогон НЕ СОСТОЯЛСЯ, и это не «чисто» и не «провал».
RC_PASS = 0
RC_SURVIVORS = 1
RC_NOT_MEASURED = 3


class WindowUnavailable(RuntimeError):
    """Окно прибора объявить или сверить нечем ⇒ прогон НЕ состоится (fail-CLOSED).

    Отдельный класс, а не `RuntimeError` вообще: вызывающий обязан отличать «гейт
    провалился» от «гейт не мерил» — иначе отсутствие прибора зачтётся за ответ
    (`.claude/rules/deployment.md`, урок `pyflakes` цикла #465).
    """


@dataclass
class Mutation:
    """One curated source mutation on a critical module.

    file:    path relative to repo root.
    old/new: an EXACT, UNIQUE substring swap (must appear exactly once in the
             file so the mutation is unambiguous — verified before applying).
    tests:   the fast test files that SHOULD catch this mutant.
    why:     the safety boundary this mutation attacks (for the scorecard).
    """
    file: str
    old: str
    new: str
    tests: list[str]
    why: str
    name: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# THE CURATED MUTANTS — each attacks a load-bearing fail-closed boundary.
# ──────────────────────────────────────────────────────────────────────────────
_RISK_TESTS = [
    "spa_core/tests/test_risk_policy.py",
    "spa_core/tests/test_risk_policy_properties.py",
    "spa_core/tests/test_risk_policy_gate.py",
]
_KILL_TESTS = [
    "spa_core/tests/test_kill_switch.py",
    "spa_core/tests/test_gate_mutations.py",
    "spa_core/tests/test_chaos_resilience.py",
    # WS-6.3 coverage fix: the TWO-TIER drawdown classifier boundaries
    # (classify_drawdown_pct / drawdown_tier) are pinned HERE — without these
    # two files the classifier-comparison mutants (kill_drawdown_comparison_flip
    # / kill_soft_threshold_comparison_flip) SURVIVED, because check_drawdown_
    # trigger has an independent comparison that masks the classifier on the
    # happy path. These files exercise the classifier directly at the 5%/10%
    # boundaries so a flip there is caught.
    "spa_core/tests/test_cycle_derisk_e2e.py",
    "spa_core/tests/test_pre_execution_safety.py",
]
_RECON_TESTS = [
    "spa_core/tests/test_execution_reconciliation.py",
    "spa_core/tests/test_reconcile_hardening.py",
    "spa_core/tests/test_money_path_failure_modes.py",
]
_GATE_TESTS = ["spa_core/tests/test_gate_chain_audit.py"]


MUTATIONS: list[Mutation] = [
    # ── RiskPolicy gate (spa_core/risk/policy.py) ────────────────────────────
    Mutation(
        name="risk_tvl_floor_comparison_flip",
        file="spa_core/risk/policy.py",
        old="if tvl_usd < self.config.min_tvl_usd:",
        new="if tvl_usd < self.config.min_tvl_usd and False:",
        tests=_RISK_TESTS,
        why="TVL-floor check disabled → a sub-$5M pool would pass",
    ),
    Mutation(
        name="risk_apy_max_bound_flip",
        file="spa_core/risk/policy.py",
        old="if current_apy > self.config.max_apy_for_new_position:",
        new="if current_apy > self.config.max_apy_for_new_position and False:",
        tests=_RISK_TESTS,
        why="APY upper-bound check disabled → a >30% APY would pass",
    ),
    Mutation(
        name="risk_concentration_cap_flip",
        file="spa_core/risk/policy.py",
        old="if new_conc > max_conc:",
        new="if new_conc > max_conc and False:",
        tests=_RISK_TESTS,
        why="per-protocol concentration cap disabled → over-cap would pass",
    ),
    Mutation(
        name="risk_drawdown_kill_threshold_inflate",
        file="spa_core/risk/policy.py",
        old="max_drawdown_stop: float = 0.05",
        new="max_drawdown_stop: float = 0.95",
        tests=_RISK_TESTS,
        why="kill-switch drawdown threshold inflated 5%→95% → never fires",
    ),
    Mutation(
        name="risk_finiteness_guard_removed",
        file="spa_core/risk/policy.py",
        old="if finite_violations:",
        new="if finite_violations and False:",
        tests=_RISK_TESTS,
        why="non-finite-input fail-closed guard removed → NaN inputs bypass",
    ),

    # ── Kill switch (spa_core/governance/kill_switch.py) ─────────────────────
    Mutation(
        name="kill_hard_threshold_inflate",
        file="spa_core/governance/kill_switch.py",
        old="DRAWDOWN_THRESHOLD_PCT = 10.0",
        new="DRAWDOWN_THRESHOLD_PCT = 99.0",
        tests=_KILL_TESTS,
        why="hard-kill drawdown threshold inflated 10%→99% → never fires",
    ),
    Mutation(
        name="kill_drawdown_comparison_flip",
        file="spa_core/governance/kill_switch.py",
        old="if dd >= DRAWDOWN_THRESHOLD_PCT:",
        new="if dd >= DRAWDOWN_THRESHOLD_PCT and False:",
        tests=_KILL_TESTS,
        why="hard-kill tier classifier disabled → a 50% drawdown is TIER_NONE",
    ),
    Mutation(
        name="kill_soft_threshold_comparison_flip",
        file="spa_core/governance/kill_switch.py",
        old="if dd >= SOFT_DERISK_THRESHOLD_PCT:",
        new="if dd >= SOFT_DERISK_THRESHOLD_PCT and False:",
        tests=_KILL_TESTS,
        why="soft de-risk tier disabled → a 7% drawdown classifies as NONE",
    ),

    # ── Reconciliation (spa_core/execution/reconciliation.py) ────────────────
    Mutation(
        name="recon_matches_target_force_true",
        file="spa_core/execution/reconciliation.py",
        old="matches_target = bool(finite) and (max_delta < DUST_TOLERANCE_USD)",
        new="matches_target = True",
        tests=_RECON_TESTS,
        why="intent-vs-outcome check forced True → any mismatch reconciles",
    ),
    Mutation(
        name="recon_nav_conserved_force_true",
        file="spa_core/execution/reconciliation.py",
        old="nav_conserved = bool(finite) and (abs(nav_after - expected_nav_after) <= NAV_TOLERANCE_USD)",
        new="nav_conserved = True",
        tests=_RECON_TESTS,
        why="NAV-conservation check forced True → capital creation reconciles",
    ),
    Mutation(
        name="recon_finite_guard_force_true",
        file="spa_core/execution/reconciliation.py",
        old="finite = _all_positions_finite(target, resulting)",
        new="finite = True",
        tests=_RECON_TESTS,
        why="non-finite valuation guard bypassed → NaN positions pass",
    ),
    Mutation(
        name="recon_dust_tolerance_inflate",
        file="spa_core/execution/reconciliation.py",
        old="POSITION_TOLERANCE_USD = 1.0",
        new="POSITION_TOLERANCE_USD = 1.0e12",
        tests=_RECON_TESTS,
        why="dust tolerance inflated to $1T → huge position mismatch passes",
    ),

    # ── Gate-chain audit (spa_core/execution/gate_chain_audit.py) ────────────
    Mutation(
        name="gatechain_kill_not_first",
        file="spa_core/execution/gate_chain_audit.py",
        old='KILL_SWITCH_FIRST = "Kill Switch"',
        new='KILL_SWITCH_FIRST = "Rate Limit"',
        tests=_GATE_TESTS,
        why="kill-switch-first invariant broken → kill not consulted first",
    ),
    Mutation(
        name="gatechain_simulation_nonblocking",
        file="spa_core/execution/gate_chain_audit.py",
        old='("Transaction Simulation", True),',
        new='("Transaction Simulation", False),',
        tests=_GATE_TESTS,
        why="simulation gate demoted to non-blocking → a failed sim won't block",
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# ОКНО ПРИБОРА — одна запись на оба мутирующих инструмента (ADR-772 + ADR-773)
# ──────────────────────────────────────────────────────────────────────────────
def load_window_facility(repo_root: str | None = None,
                         reader_path: str | None = None):
    """Загрузить читателя/писателя окна. Не нашёлся ⇒ :class:`WindowUnavailable`.

    Порядок поиска НАЗВАН и совпадает с порядком пушера (`mutation_window_verdict`):
    рядом с ЭТИМ файлом · в дереве прогона. Своей копии правила здесь нет намеренно —
    формат записи знает ровно один объект, и две копии разошлись бы при первой правке
    формата (ровно так 26.08 проехал второй `ADR-145`).

    `reader_path` — ВХОД: тест закрепляет и путь «читателя нет», не удаляя файл из
    настоящего дерева.
    """
    candidates = []
    if reader_path is not None:
        candidates.append(str(reader_path))
    else:
        candidates.append(str(Path(__file__).resolve().parent / "delta_mutation_run.py"))
        if repo_root is not None:
            candidates.append(os.path.join(str(repo_root), *_WINDOW_READER_REL.split("/")))
    for cand in candidates:
        if not os.path.isfile(cand):
            continue
        spec = importlib.util.spec_from_file_location("_spa_mutation_window", cand)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        # Модуль РЕГИСТРИРУЕТСЯ до исполнения намеренно: `@dataclass` внутри читателя
        # ищет свой модуль в `sys.modules[cls.__module__]`, и без записи получает
        # `None` ⇒ `AttributeError: 'NoneType' object has no attribute '__dict__'`.
        # Это не теория: ровно так отказал первый прогон этой же правки (цикл #889),
        # и отказал ВЕРНО — fail-CLOSED поймал мой собственный дефект загрузки раньше,
        # чем прибор успел тронуть хоть один файл.
        sys.modules[spec.name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:  # noqa: BLE001 — причина НАЗЫВАЕТСЯ, а не глотается
            sys.modules.pop(spec.name, None)
            raise WindowUnavailable(
                f"читатель окна {cand} есть, но не загружается: "
                f"{type(exc).__name__}: {exc} — объявить окно НЕЧЕМ") from exc
        missing = [name for name in ("open_window", "restore_window", "window_state",
                                     "install_signal_guard", "OpenWindow")
                   if not hasattr(mod, name)]
        if missing:
            raise WindowUnavailable(
                f"читатель окна {cand} загрузился, но в нём нет {', '.join(missing)} — "
                f"копия инструмента устарела, запись окна объявить НЕЧЕМ")
        return mod
    raise WindowUnavailable(
        "читателя окна нет ни по одному адресу (" + ", ".join(candidates)
        + f") — прогон НЕ состоится: без записи `{_WINDOW_READER_REL}` мутант "
          f"переживёт SIGKILL молча")


def gate_window_targets(repo_root: str) -> tuple[list[str], dict, dict]:
    """Файлы, которые тронет гейт, их реальные пути и исходные байты.

    Окно открывается на ВСЕ четыре файла разом, а не на тот, что мутируется сейчас:
    смерть приходит в любой момент прогона, и слепок нужен до ПЕРВОЙ подмены.
    """
    rels = sorted({m.file for m in MUTATIONS})
    targets: dict[str, str] = {}
    originals: dict[str, str] = {}
    for rel in rels:
        real = os.path.join(str(repo_root), *rel.split("/"))
        try:
            with open(real, encoding="utf-8") as fh:
                originals[rel] = fh.read()
        except OSError as exc:
            raise WindowUnavailable(
                f"цель мутаций {rel} не прочитана в дереве {repo_root} ({exc}) — "
                f"слепка нет, значит окно объявить НЕЧЕМ") from exc
        targets[rel] = os.path.realpath(real)
    return rels, targets, originals


def open_gate_window(dmr, repo_root: str, *, now: str | None = None,
                     pid: int | None = None, label: str | None = None) -> dict:
    """Объявить окно ДО первой подмены. Уже открыто ⇒ :class:`WindowUnavailable`.

    `spec` для записи — контракт из двух полей (`.title`, `.mutations`), а не класс
    прибора дельты: у кураторского набора файла-спецификации нет вовсе, и выдумывать
    его значило бы записать путь, которого не существует.
    """
    _rels, targets, originals = gate_window_targets(repo_root)
    spec = SimpleNamespace(title=_WINDOW_TITLE, mutations=list(MUTATIONS))
    try:
        return dmr.open_window(repo_root, spec, targets, originals, spec_path=None,
                               now=now, pid=pid, label=label, tool=_WINDOW_TOOL)
    except dmr.OpenWindow as exc:
        raise WindowUnavailable(str(exc)) from exc
    except OSError as exc:
        raise WindowUnavailable(
            f"запись окна не легла на диск в дереве {repo_root}: "
            f"{type(exc).__name__}: {exc}") from exc


def close_gate_window(dmr, repo_root: str) -> dict:
    """Сверить байты со слепком, вернуть разошедшиеся и снять запись.

    Возврат идёт ЧЕРЕЗ `restore_window`, а не отдельной проверкой: сверка и возврат
    суть одно действие, и вторая реализация сверки разошлась бы с первой. Возврат
    неполон ⇒ запись НЕ снимается и прогон объявляется НЕ ИЗМЕРЕННЫМ: дерево с
    мутантом не имеет права выглядеть чистым по мерке собственного сторожа.
    """
    out = dmr.restore_window(repo_root)
    if not out.get("measured"):
        raise WindowUnavailable(
            f"после прогона запись окна не прочитана ({out.get('reason')}) — сошлись ли "
            f"байты дерева {repo_root} со слепком, НЕ ИЗМЕРЕНО")
    if out.get("failed"):
        raise WindowUnavailable(
            "после прогона байты НЕ сошлись со слепком и возврат НЕ ПОЛОН: "
            + " · ".join(out["failed"])
            + f". Запись окна ОСТАВЛЕНА — путь наверх: python3 {_WINDOW_READER_REL} "
              f"--window-restore --repo-root {repo_root}")
    return out


@dataclass
class MutantResult:
    name: str
    file: str
    why: str
    killed: bool
    killer_tests: list[str] = field(default_factory=list)
    note: str = ""


def _run_tests(test_files: list[str], repo_root: str | None = None) -> tuple[bool, str]:
    """Run pytest over the given files; return (all_passed, short_tail).

    all_passed True iff the subset is GREEN. We deselect the randomizer for
    determinism and stop at the first failure (``-x``) so a killed mutant returns
    fast. A pytest internal error (exit >= 2 other than 1) is treated as NOT
    passing (the mutant broke import/collection — that still counts as caught).

    ``repo_root`` — ВХОД: прогон идёт в том же дереве, которое мутируется, иначе
    pytest читал бы ОДИН код, а мутант лежал бы в ДРУГОМ, и вердикт «убит» был бы
    утверждением про чужое дерево.
    """
    cmd = [
        _PYTHON, "-m", "pytest", *test_files,
        "-p", "no:randomly", "-x", "-q", "--no-header",
        "-o", "addopts=",  # ignore repo addopts (coverage etc.) for speed
    ]
    proc = subprocess.run(
        cmd, cwd=str(repo_root or _REPO_ROOT), capture_output=True, text=True,
        timeout=300
    )
    tail = (proc.stdout or "")[-400:] + (proc.stderr or "")[-200:]
    return proc.returncode == 0, tail


def _apply_mutant(m: Mutation, repo_root: str | None = None) -> MutantResult:
    """Apply ONE mutant, run its tests, restore the source. killed iff tests fail.

    A mutant is KILLED when the targeted test subset goes RED (returncode != 0)
    after the mutation. It SURVIVES when the tests still pass — a coverage hole.
    The original file text is ALWAYS restored in the finally.

    `finally` здесь — БЫСТРЫЙ путь, а не защита: `SIGKILL` его не исполняет. Защита
    лежит на диске — запись окна, открытая до первого вызова этой функции
    (:func:`open_gate_window`); см. раздел «ОКНО ПРИБОРА» в шапке модуля.
    """
    path = Path(repo_root or _REPO_ROOT) / m.file
    original = path.read_text(encoding="utf-8")

    # The swap target must appear EXACTLY ONCE (unambiguous mutation).
    count = original.count(m.old)
    if count != 1:
        return MutantResult(
            m.name, m.file, m.why, killed=False,
            note=(f"SKIP/ERROR: mutation anchor found {count}x (expected 1) — "
                  f"the source moved; update mutation_gate.py"),
        )

    mutated = original.replace(m.old, m.new, 1)
    try:
        path.write_text(mutated, encoding="utf-8")
        passed, tail = _run_tests(m.tests, repo_root=repo_root)
        killed = not passed  # tests RED on the mutant ⇒ caught
        return MutantResult(
            m.name, m.file, m.why, killed=killed,
            killer_tests=m.tests if killed else [],
            note="" if killed else f"SURVIVED — tests stayed green:\n{tail}",
        )
    finally:
        # ALWAYS restore — the repo must be byte-identical afterwards.
        path.write_text(original, encoding="utf-8")


def run_gate(threshold: int = 0, repo_root: str | None = None) -> dict:
    """Run every curated mutant and assemble the scorecard.

    A baseline is NOT re-run per-mutant for speed; instead each anchor is verified
    unique (a moved anchor is reported as an ERROR survivor so the gate fails
    loudly rather than silently skipping a critical mutation).
    """
    t0 = time.time()
    results: list[MutantResult] = []
    for m in MUTATIONS:
        results.append(_apply_mutant(m, repo_root=repo_root))

    survivors = [r for r in results if not r.killed]
    errors = [r for r in results if r.note.startswith("SKIP/ERROR")]
    return {
        "module": "mutation_gate",
        "version": "v1.0",
        "repo_root": str(Path(repo_root or _REPO_ROOT).resolve()),
        "threshold": threshold,
        "n_mutants": len(results),
        "n_killed": sum(1 for r in results if r.killed),
        "n_survivors": len(survivors),
        "n_anchor_errors": len(errors),
        "survivors": [r.name for r in survivors],
        "pass": len(survivors) <= threshold,
        "elapsed_s": round(time.time() - t0, 1),
        "results": [
            {"name": r.name, "file": r.file, "why": r.why, "killed": r.killed,
             "note": r.note}
            for r in results
        ],
    }


def _print(report: dict) -> None:
    print("=" * 74)
    print("SPA MUTATION-TESTING GATE (WS-6.3) — do our tests actually catch bugs?")
    print("=" * 74)
    for r in report["results"]:
        mark = "KILLED " if r["killed"] else "SURVIVE"
        print(f" [{mark}] {r['name']:<38} {r['file'].split('/')[-1]}")
        print(f"           {r['why']}")
        if not r["killed"] and r["note"]:
            first = r["note"].splitlines()[0]
            print(f"           ↳ {first}")
    print("-" * 74)
    print(f" mutants: {report['n_mutants']}   killed: {report['n_killed']}   "
          f"survivors: {report['n_survivors']}   (threshold ≤ {report['threshold']})")
    if report["survivors"]:
        print(f" SURVIVING MUTANTS (coverage holes): {', '.join(report['survivors'])}")
    print(f" elapsed: {report['elapsed_s']}s")
    win = report.get("window")
    if win:
        print(f" ОКНО ПРИБОРА: снято={win['closed']} · файлов {len(win['files'])} · "
              f"возвращено после прогона {len(win['restored_after_run'])} · "
              f"и так целы {len(win['already_clean_after_run'])}")
    print(f" GATE: {'PASS' if report['pass'] else 'FAIL'}")
    print("=" * 74)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="SPA mutation-testing gate (WS-6.3) — assert the test suite "
                    "catches deliberate bugs on the critical money-path modules.")
    p.add_argument("--threshold", type=int, default=0,
                   help="max surviving mutants allowed (default 0)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--repo-root", default=None,
                   help="дерево, в котором идёт мутационный прогон (по умолчанию — своё). "
                        "Правило `.claude/rules/deployment.md`: прогон — в ОТДЕЛЬНОМ "
                        "дереве, не в том, из которого идёт доставка")
    args = p.parse_args(argv)

    root = str(Path(args.repo_root or _REPO_ROOT).resolve())

    # Окно — ПЕРЕД первой подменой, и его недоступность есть ТРЕТИЙ ИСХОД, а не
    # разрешение мутировать без записи: прогон без окна оставил бы после SIGKILL
    # отключённый порог RiskPolicy, о котором не сказал бы никто (замер #889).
    try:
        dmr = load_window_facility(root)
        dmr.install_signal_guard()
        record = open_gate_window(dmr, root)
    except WindowUnavailable as exc:
        print(f"🚫 НЕ ИЗМЕРЕНО — окно мутационного прибора: {exc}", file=sys.stderr)
        return RC_NOT_MEASURED

    try:
        report = run_gate(threshold=args.threshold, repo_root=root)
    finally:
        closed = None
        close_error = None
        try:
            closed = close_gate_window(dmr, root)
        except WindowUnavailable as exc:
            close_error = str(exc)
    if close_error is not None:
        print(f"🚫 НЕ ИЗМЕРЕНО — окно мутационного прибора: {close_error}",
              file=sys.stderr)
        return RC_NOT_MEASURED

    report["window"] = {
        "tool": _WINDOW_TOOL,
        "opened_at": record.get("opened_at"),
        "run_label": record.get("run_label"),
        "files": [item["file"] for item in record.get("files", [])],
        "restored_after_run": list(closed.get("restored", [])),
        "already_clean_after_run": list(closed.get("already_clean", [])),
        "closed": bool(closed.get("closed")),
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print(report)
    return RC_PASS if report["pass"] else RC_SURVIVORS


if __name__ == "__main__":
    raise SystemExit(main())
