#!/usr/bin/env python3
# LLM_FORBIDDEN
"""scripts/measure_acceptance_contention.py — морят ли два предписанных прогона друг друга.

**Зачем (карточка `inbox-dva-predpisannyh-progona-ryadom-drug-druga-morya`, цикл #226).**
Приёмка каждого цикла — ДВА полных предписанных прогона: свой и контрольный на чистом
`origin/main` того же sha. На рабочем Mac 14.08 запущенные рядом, они почти остановились:
**~2 байта лога за 15 минут** против **18 332 байт за 60 с** у одиночного, оба в состоянии
`R` на одном и том же месте (8 %). Снятие одного вернуло второму скорость немедленно.

Карточка требовала ровно одного — **замера, а не догадки**: «у этого класса („сторож/прогон
упирается в общий путь вне дерева") уже было слишком много правдоподобных диагнозов,
оказавшихся неверными».

**Что этот файл НЕ делает.** Он не ускоряет тесты, не сужает предписанный набор и не
переписывает протокол. Он отвечает на ОДИН вопрос числом: во что обходится соседство.
Решение «сериализовать замком» либо «гонять рядом» принимается ПО ЕГО ВЫВОДУ на той машине,
где приёмка идёт, — потому что ответ от машины зависит, и это измерено:

| Машина | 1 прогон | 2 прогона рядом | вердикт |
|---|---|---|---|
| Mac Mini владельца (карточка, 14.08) | 18 КБ/мин | ~2 байта / 15 мин | `starves` |
| Linux-контейнер 4 vCPU / 16 ГБ (17.08) | 472.5 с | 477.7 с (обе копии) | `scales` |

Один и тот же набор, противоположные ответы. Правило «всегда по очереди», записанное в
протокол по первой строке, стоило бы второй машине **ровно двукратной** потери пропускной
способности приёмки — а медленная приёмка и есть механизм, которым мы теряем работу
(#210 / #212 / #220 / #224 умерли между «сделал» и «доставил»).

**Fail-CLOSED (инвариант #2).** Не завершившаяся копия, отсутствующее дерево, нулевое время —
вердикт `unmeasured` и код возврата 2. «Не измерено» никогда не выдаётся за «не морят»:
именно так сторожа и глохнут.

**Время — вход, а не окружение** (`.claude/rules/deployment.md`): арифметику вердикта делает
чистая функция над УЖЕ измеренными длительностями, а часы инъектируются параметром `clock`.
Поэтому тесты этого файла не зависят от календаря и от скорости машины.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

# ── Вердикты ──────────────────────────────────────────────────────────────────
# Порядок — от «соседство выгодно» к «соседство вредно».
SCALES = "scales"          # рядом почти не мешают: wall ≈ одиночного
SHARES = "shares"          # делят машину: медленнее одиночного, но быстрее очереди
STARVES = "starves"        # морят: рядом ХУЖЕ, чем по очереди ⇒ нужен замок
UNMEASURED = "unmeasured"  # fail-CLOSED

# Насколько wall параллельного прогона может превысить одиночный, чтобы это ещё
# считалось «масштабируется». 25 % — не подгонка под замер: ниже этого порога разница
# укладывается в шум соседних процессов на общей машине (в контейнере 17.08 рядом жил
# чужой полный прогон, и обе руки эксперимента несли его одинаково).
SCALES_TOLERANCE = 0.25


@dataclass(frozen=True)
class Run:
    """Одна копия прогона: где шла, сколько шла, чем кончилась."""

    tree: str
    seconds: float
    returncode: object          # int либо "TIMEOUT"
    log_bytes: int = 0

    @property
    def finished(self) -> bool:
        return isinstance(self.returncode, int)


@dataclass(frozen=True)
class Verdict:
    """Ответ на вопрос карточки — числом и словом."""

    verdict: str
    solo_seconds: float
    parallel_wall: float
    n: int
    sequential_total: float
    speedup: float              # во сколько раз соседство быстрее очереди
    reason: str
    runs: Sequence[Run] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "solo_seconds": round(self.solo_seconds, 1),
            "parallel_wall_seconds": round(self.parallel_wall, 1),
            "n": self.n,
            "sequential_total_seconds": round(self.sequential_total, 1),
            "speedup_vs_queue": round(self.speedup, 2),
            "reason": self.reason,
            "runs": [
                {"tree": r.tree, "seconds": round(r.seconds, 1),
                 "returncode": r.returncode, "log_bytes": r.log_bytes}
                for r in self.runs
            ],
        }


def judge(solo_seconds: float, parallel_wall: float, n: int,
          runs: Sequence[Run] = ()) -> Verdict:
    """Чистая арифметика вердикта над УЖЕ измеренными длительностями.

    Ни часов, ни подпроцессов — поэтому проверяется положительными контролями на числах
    настоящих аварий, а не на скорости машины, где идут тесты.

    ``solo_seconds``   — сколько идёт ОДИН прогон, когда он один.
    ``parallel_wall``  — сколько идут N копий, запущенных рядом (по самой долгой).
    """
    if n < 2:
        return Verdict(UNMEASURED, solo_seconds, parallel_wall, n, 0.0, 0.0,
                       "соседство измеряется минимум двумя копиями", tuple(runs))
    if solo_seconds <= 0 or parallel_wall <= 0:
        return Verdict(UNMEASURED, solo_seconds, parallel_wall, n, 0.0, 0.0,
                       "нулевая либо отрицательная длительность — измерять нечего",
                       tuple(runs))
    unfinished = [r for r in runs if not r.finished]
    if unfinished:
        return Verdict(
            UNMEASURED, solo_seconds, parallel_wall, n, 0.0, 0.0,
            "не все копии завершились ("
            + ", ".join(f"{r.tree}:{r.returncode}" for r in unfinished)
            + ") — незавершённый прогон не имеет права читаться как «не морят»",
            tuple(runs),
        )

    sequential_total = solo_seconds * n
    speedup = sequential_total / parallel_wall

    if parallel_wall > sequential_total:
        reason = (
            f"копий рядом: {n} — идут {parallel_wall:.1f} с — ДОЛЬШЕ, чем те же {n} "
            f"по очереди ({sequential_total:.1f} с). Соседство отнимает больше, чем даёт: "
            "приёмку надо сериализовать замком."
        )
        return Verdict(STARVES, solo_seconds, parallel_wall, n, sequential_total,
                       speedup, reason, tuple(runs))

    if parallel_wall <= solo_seconds * (1.0 + SCALES_TOLERANCE):
        reason = (
            f"копий рядом: {n} — идут {parallel_wall:.1f} с против {solo_seconds:.1f} с у "
            f"одиночного — соседство почти бесплатно, пропускная способность выше очереди "
            f"в {speedup:.2f} раза. Сериализовать замком значило бы её потерять."
        )
        return Verdict(SCALES, solo_seconds, parallel_wall, n, sequential_total,
                       speedup, reason, tuple(runs))

    reason = (
        f"копий рядом: {n} — идут {parallel_wall:.1f} с: медленнее одиночного "
        f"({solo_seconds:.1f} с), но быстрее очереди ({sequential_total:.1f} с) — "
        f"выигрыш {speedup:.2f} раза. Замок не нужен, машина просто делится."
    )
    return Verdict(SHARES, solo_seconds, parallel_wall, n, sequential_total,
                   speedup, reason, tuple(runs))


# ── Исполнение замера ─────────────────────────────────────────────────────────

def _launch(tree: Path, pytest_args: Sequence[str], log: Path):
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", *pytest_args, "-q", "-p", "no:cacheprovider"],
        cwd=str(tree), stdout=handle, stderr=subprocess.STDOUT,
    )
    return proc, handle


def measure(trees: Sequence[Path], pytest_args: Sequence[str], timeout: float,
            log_dir: Path, clock: Callable[[], float] = time.monotonic) -> list[Run]:
    """Запустить по копии прогона в каждом дереве ОДНОВРЕМЕННО и замерить каждую.

    ``clock`` инъектируется, чтобы длительности были входом теста, а не свойством машины.

    **Что означает `Run.seconds`.** Это время от ОБЩЕГО старта фазы до момента, когда копию
    дождались, — копии ждутся по порядку, поэтому у завершившейся раньше значение может быть
    завышено до момента снятия предыдущей. На вердикт это не влияет: он считается по
    `max(seconds)`, а максимум верен всегда (последняя дождавшаяся копия — и есть самая
    долгая либо равна ей). Читать отдельное значение как «столько шла именно эта копия»
    нельзя, и поэтому здесь это сказано, а не подразумевается.
    """
    started = clock()
    live = []
    for i, tree in enumerate(trees):
        proc, handle = _launch(tree, pytest_args, log_dir / f"run{i}.log")
        live.append((tree, proc, handle, log_dir / f"run{i}.log"))

    results: list[Run] = []
    for tree, proc, handle, log in live:
        left = max(1.0, timeout - (clock() - started))
        try:
            proc.wait(timeout=left)
            rc: object = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            rc = "TIMEOUT"
        handle.close()
        results.append(Run(tree=tree.name, seconds=clock() - started,
                           returncode=rc,
                           log_bytes=log.stat().st_size if log.exists() else 0))
    return results


def run_measurement(trees: Sequence[Path], pytest_args: Sequence[str], timeout: float,
                    log_dir: Path,
                    clock: Callable[[], float] = time.monotonic) -> Verdict:
    """Полный протокол: сперва одиночный прогон, затем N рядом. Порядок важен —
    одиночный замеряется на ТОЙ ЖЕ фоновой нагрузке, иначе арифметика сравнивает разное."""
    missing = [t for t in trees if not t.is_dir()]
    if missing:
        return Verdict(UNMEASURED, 0.0, 0.0, len(trees), 0.0, 0.0,
                       "нет рабочих деревьев: " + ", ".join(str(m) for m in missing))

    solo = measure(trees[:1], pytest_args, timeout, log_dir / "solo", clock)
    if not solo or not solo[0].finished:
        rc = solo[0].returncode if solo else "нет результата"
        return Verdict(UNMEASURED, 0.0, 0.0, len(trees), 0.0, 0.0,
                       f"одиночный прогон не завершился ({rc}) — базы для сравнения нет",
                       tuple(solo))

    side_by_side = measure(trees, pytest_args, timeout, log_dir / "parallel", clock)
    parallel_wall = max((r.seconds for r in side_by_side), default=0.0)
    return judge(solo[0].seconds, parallel_wall, len(trees), side_by_side)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Морят ли предписанные прогоны друг друга — замер, а не догадка.")
    parser.add_argument("--tree", action="append", required=True, type=Path,
                        help="рабочее дерево для одной копии; указывать ≥2 раза")
    parser.add_argument("--timeout", type=float, default=7200.0,
                        help="бюджет на фазу, секунд (по умолчанию 2 ч)")
    parser.add_argument("--log-dir", type=Path, required=True,
                        help="куда класть логи копий (НЕ в data/)")
    parser.add_argument("--json", action="store_true", help="вывод машинно-читаемым JSON")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER,
                        help="аргументы pytest после --, по умолчанию предписанный набор")
    args = parser.parse_args(argv)

    pytest_args = [a for a in args.pytest_args if a != "--"] or [
        "spa_core/tests/", "tests/", "scripts/tests/",
        "spa_core/analytics/gross_of/", "research/cards/",
    ]
    verdict = run_measurement(args.tree, pytest_args, args.timeout, args.log_dir)

    if args.json:
        print(json.dumps(verdict.as_dict(), ensure_ascii=False, indent=1))
    else:
        print(f"ВЕРДИКТ: {verdict.verdict}")
        print(verdict.reason)
        for run in verdict.runs:
            print(f"  {run.tree:32s} {run.seconds:8.1f} с  rc={run.returncode}")

    return {SCALES: 0, SHARES: 0, STARVES: 1, UNMEASURED: 2}[verdict.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
