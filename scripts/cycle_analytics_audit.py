#!/usr/bin/env python3
# LLM_FORBIDDEN
"""
cycle_analytics_audit — ОБЯЗАТЕЛЬНЫЙ шаг цикла оркестратора: ежедневный
дифференциальный аудит протокол-слепоты, прогнанный В ПЕСОЧНИЦЕ.

ЗАЧЕМ (решение владельца 2026-08-24, вариант 2 карточки
`owner-decision-ezhednevnuyu-proverku-analitiki-nekomu-g`; ADR-130).
Директива владельца 03.08: аналитический слой обязан работать примерно на 90 %,
и мерить это обязан ЕЖЕДНЕВНЫЙ прогон `scripts/audit_protocol_blindness.py`.
20.08 выяснилось, что сам аудит молча простоял 13 суток и метрика не сдвинулась
ни на один модуль. Цикл #367 закрыл ПОЛОВИНУ — сторож свежести
(`spa_core/monitoring/analytics_audit_freshness.py`) теперь КРАСНЕЕТ, если аудит
не мерили дольше суток. Вторую половину закрывает этот файл: у прогона появился
исполнитель — сам цикл оркестратора.

ПОЧЕМУ ПЕСОЧНИЦА, А НЕ ПРОСТО ЗАПУСК. Аудит гоняет 479 модулей через тот же
`_ModuleAdapter`, что и прод, а модули пишут свои рабочие логи ОТНОСИТЕЛЬНО корня
репозитория. Замер 24.08 в чистом дереве: один прогон меняет **29 файлов**
состояния (27 в `data/`, 2 в `spa_core/data/`). В боевом дереве (`~/Documents/SPA_Claude`)
там живёт трек — запуск оттуда загадил бы живое состояние. Поэтому прогон идёт
в копии, а обратно возвращается РОВНО ОДИН файл — машиночитаемая разметка
`spa_core/analytics/_protocol_blindness.py` (это код, он доезжает в прод обычным
синком `spa_core/`, без нового агента и без деплоя).

ЧТО ИМЕННО ДЕЛАЕТ ШАГ:
  1. спрашивает сторожа свежести, мерили ли протокол-слепоту за такт (30 ч);
     свежо и без `--force` ⇒ прогона нет (шаг дешёвый, его не жалко в каждом цикле);
  2. иначе — делает песочницу (копия `spa_core/`, `scripts/`, `data/` без `__pycache__`),
     гоняет в ней аудит с `--emit-markup`;
  3. кладёт обновлённую разметку в рабочее дерево цикла (`--into`) — чтобы она
     уехала на origin ТЕМ ЖЕ пушем, что и остальная работа цикла.

КОДЫ ВОЗВРАТА (как у `deployment_acceptance`, чтобы не заводить второй словарь):
  0 — доставлять нечего: аудит свежий, либо разметка после прогона не изменилась;
  1 — разметка ОБНОВИЛАСЬ и лежит в `--into`: её надо доставить пушем этого цикла;
  2 — прогнать не удалось (или отказ по безопасности) — fail-CLOSED, «молча ок» не бывает.

ОТКАЗЫ (fail-CLOSED, всегда код 2 — ни один из них не «продолжаем осторожно»):
  * песочница совпадает с судимым деревом либо вложена в него (и наоборот) —
    это и есть та самая авария «прогон в живом дереве», только под другим именем;
  * песочница уже существует и непуста (без `--reuse-sandbox`) — чужие байты
    в песочнице делают вердикт нечитаемым;
  * в судимом дереве нет `scripts/audit_protocol_blindness.py`;
  * сам аудит вернул ненулевой код или не оставил разметки.

Инварианты: stdlib-only · детерминированно · LLM запрещён · advisory (НИКОГДА не
гейтит исполнение, RiskPolicy и стоп-кран) · `now` — вход, а не окружение ·
в судимое дерево пишется РОВНО один путь, `data/` не трогается никогда.
"""
# LLM_FORBIDDEN

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Каталоги, которые нужны аудиту: код (`spa_core`, `scripts`) и состояние, которое
# модули читают (`data`). Замер 24.08: этого набора достаточно — аудит проходит
# 479 модулей и выдаёт те же классы, что и в полном дереве.
SANDBOX_DIRS = ("spa_core", "scripts", "data")

MARKUP_REL = "spa_core/analytics/_protocol_blindness.py"
AUDIT_REL = "scripts/audit_protocol_blindness.py"

# ── Перепись внетировых модулей (аудит 90 % от 2026-08-29) ────────────────────
#
# Аудит тиров отвечает «как работают те, кого мы меряем». Он НЕ отвечает, кого мы
# не меряем вовсе, — и три недели подряд это число росло незамеченным: модулей вне
# всех тиров было 67 (20.08), 82 (27.08), 83 (29.08). Пока они не названы, знаменатель
# метрики 90 % — не оценка, а незнание, выдающее себя за оценку.
#
# Перепись живёт в ТОМ ЖЕ шаге и в ТОЙ ЖЕ песочнице по одной причине: вопрос
# «вырос ли корпус за пределы измеряемого» обязан задаваться ровно так же часто,
# как основной замер. Отдельный агент был бы четвёртым сторожем, который однажды
# молча встанет, — ровно тем, из-за чего этот шаг и появился.
CENSUS_REL = "spa_core/analytics/_untiered_census.py"
CENSUS_TOOL_REL = "scripts/audit_untiered_analytics.py"

# Самопроверка генератора реестров списания: `--verify C` требует, чтобы генератор
# воспроизвёл доставленный руками `_tier_c_writeoff.py` ПОИМЁННО. Гоняется ежедневно
# не ради ритуала: разойтись могут обе стороны — и генератор, и реестр, — а узнать об
# этом надо ДО того, как тем же генератором разметят следующий тир.
WRITEOFF_TOOL_REL = "scripts/generate_tier_writeoff.py"

# Не копируем мусор сборки: он и объёмнее исходников, и делает песочницу
# недетерминированной (чужой `.pyc` старше правки — известный класс).
COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")

OK = 0
NEEDS_DELIVERY = 1
REFUSED = 2


class AuditStepError(RuntimeError):
    """Отказ шага. Текст — то, что сессия увидит и по чему будет действовать."""


def _is_within(inner: Path, outer: Path) -> bool:
    """`inner` лежит внутри `outer` (или это он сам) — по РАЗРЕШЁННЫМ путям."""
    try:
        inner.resolve().relative_to(outer.resolve())
        return True
    except ValueError:
        return False


def check_sandbox_target(source: Path, sandbox: Path, *, reuse: bool = False) -> None:
    """Отказать ДО прогона, если песочница не изолирует. Ничего не возвращает."""
    src = Path(source).resolve()
    box = Path(sandbox).resolve()

    if box == src:
        raise AuditStepError(
            "песочница совпадает с судимым деревом — это прогон в живом дереве, "
            "а он меняет 29 файлов состояния (там живёт трек)"
        )
    if _is_within(box, src) or _is_within(src, box):
        raise AuditStepError(
            f"песочница {box} и судимое дерево {src} вложены друг в друга — "
            "изоляции нет, прогон загадит судимое дерево"
        )
    if box.exists() and any(box.iterdir()) and not reuse:
        raise AuditStepError(
            f"песочница {box} уже существует и непуста — чужие байты делают вердикт "
            "нечитаемым; удалите её или передайте --reuse-sandbox осознанно"
        )
    if not (src / AUDIT_REL).is_file():
        raise AuditStepError(f"в судимом дереве нет {AUDIT_REL}: {src}")


def make_sandbox(source: Path, sandbox: Path, *, dirs=SANDBOX_DIRS,
                 reuse: bool = False) -> Path:
    """Скопировать в песочницу ровно то, что нужно аудиту. → путь песочницы."""
    check_sandbox_target(source, sandbox, reuse=reuse)
    src = Path(source).resolve()
    box = Path(sandbox).resolve()
    box.mkdir(parents=True, exist_ok=True)
    for name in dirs:
        origin = src / name
        if not origin.is_dir():
            # Каталога может не быть (напр. `data/` в свежем worktree) — это не
            # авария: аудит сам создаст, что ему нужно, ВНУТРИ песочницы.
            continue
        target = box / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(origin, target, ignore=COPY_IGNORE, symlinks=True)
    return box


def run_audit(sandbox: Path, *, tier: str = "B", python: Optional[str] = None,
              timeout: float = 600.0) -> subprocess.CompletedProcess:
    """Прогнать аудит ВНУТРИ песочницы (cwd = песочница, чтобы логи легли туда же)."""
    box = Path(sandbox).resolve()
    report = box / "analytics_audit_report.json"
    cmd = [python or sys.executable, str(box / AUDIT_REL),
           "--tier", tier, "--out", str(report)]
    if tier == "B":
        cmd.append("--emit-markup")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(cmd, cwd=str(box), capture_output=True, text=True,
                          timeout=timeout, env=env)


def markup_stamp(tree: Path) -> Optional[str]:
    """Отметка `AUDIT_GENERATED_AT` разметки дерева (или `None`, если её нет)."""
    from spa_core.monitoring import analytics_audit_freshness as guard
    return guard.read_markup(Path(tree).resolve() / MARKUP_REL).get("stamp_raw")


def assert_markup_produced(sandbox: Path, stamp_before: Optional[str]) -> None:
    """Доказать, что разметку произвёл ЭТОТ прогон, а не копирование песочницы.

    Без этой проверки «аудит отчитался кодом 0, но разметки не написал» было бы
    неотличимо от «написал то же самое»: в песочницу разметка попадает копией
    судимого дерева, поэтому её ПРИСУТСТВИЕ ничего не доказывает — доказывает
    только сдвинутая отметка. Тот же класс, что «сторож, сверяющий копии, слеп».
    """
    if not (Path(sandbox).resolve() / MARKUP_REL).is_file():
        raise AuditStepError(
            f"аудит не оставил разметки {MARKUP_REL} в песочнице — прогон не состоялся"
        )
    stamp_after = markup_stamp(sandbox)
    if stamp_after is None:
        raise AuditStepError(
            "у разметки в песочнице нет разбираемой отметки AUDIT_GENERATED_AT — "
            "продукт прогона не подтверждён"
        )
    if stamp_after == stamp_before:
        raise AuditStepError(
            "аудит вернул код 0, но отметку разметки не сдвинул — это КОПИЯ, "
            "принесённая в песочницу, а не продукт прогона (fail-CLOSED)"
        )


def deliver_markup(sandbox: Path, into: Path) -> bool:
    """Перенести разметку из песочницы в дерево цикла. → изменилась ли она.

    Переносится РОВНО ОДИН файл. Всё остальное, что прогон нагадил в песочнице
    (те самые 29 файлов состояния), остаётся в песочнице и умирает вместе с ней.
    """
    produced = Path(sandbox).resolve() / MARKUP_REL
    if not produced.is_file():
        raise AuditStepError(
            f"аудит не оставил разметки {MARKUP_REL} в песочнице — прогон не состоялся"
        )
    target = Path(into).resolve() / MARKUP_REL
    new_text = produced.read_text(encoding="utf-8")
    old_text = target.read_text(encoding="utf-8") if target.is_file() else None
    if old_text == new_text:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, target)                     # атомарно, инвариант #5
    return True


def deliver_file(sandbox: Path, into: Path, rel: str) -> bool:
    """Перенести ОДИН сгенерированный файл из песочницы в дерево. → изменился ли он.

    Обобщение `deliver_markup`: та же атомарность и та же граница «переносится ровно
    один файл, остальное умирает вместе с песочницей». Заведено, чтобы перепись
    доставлялась тем же способом, а не своей копией правил."""
    produced = Path(sandbox).resolve() / rel
    if not produced.is_file():
        raise AuditStepError(f"прогон не оставил {rel} в песочнице — он не состоялся")
    target = Path(into).resolve() / rel
    new_text = produced.read_text(encoding="utf-8")
    old_text = target.read_text(encoding="utf-8") if target.is_file() else None
    if old_text == new_text:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, target)                     # атомарно, инвариант #5
    return True


def run_census(sandbox: Path, *, python: Optional[str] = None,
               timeout: float = 900.0) -> subprocess.CompletedProcess:
    """Перепись внетировых модулей ВНУТРИ песочницы (она тоже исполняет модули)."""
    box = Path(sandbox).resolve()
    cmd = [python or sys.executable, str(box / CENSUS_TOOL_REL),
           "--out", str(box / "untiered_census_report.json"), "--emit-markup"]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(cmd, cwd=str(box), capture_output=True, text=True,
                          timeout=timeout, env=env)


def run_writeoff_selfcheck(sandbox: Path, *, python: Optional[str] = None,
                           timeout: float = 900.0) -> subprocess.CompletedProcess:
    """Положительный контроль генератора реестров: воспроизводит ли он Tier-C."""
    box = Path(sandbox).resolve()
    cmd = [python or sys.executable, str(box / WRITEOFF_TOOL_REL), "--verify", "C"]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(cmd, cwd=str(box), capture_output=True, text=True,
                          timeout=timeout, env=env)


def writeoff_selfcheck_verdict(sandbox: Path, *, python: Optional[str] = None) -> tuple:
    """→ (код, текст вердикта). Не бросает: самопроверка соседа шаг не роняет.

    Три исхода, а не два: сошлось · НЕ сошлось · НЕ ИЗМЕРЕНО (инструмента нет,
    прогон не запустился). Третий обязателен — иначе отсутствие проверки было бы
    неотличимо от её успеха, и это ровно тот fail-open, из-за которого сторожа
    и перестают что-либо значить."""
    tool = Path(sandbox).resolve() / WRITEOFF_TOOL_REL
    if not tool.is_file():
        return None, f"НЕ ИЗМЕРЕНО: в дереве нет {WRITEOFF_TOOL_REL}"
    try:
        proc = run_writeoff_selfcheck(sandbox, python=python)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"НЕ ИЗМЕРЕНО: {type(exc).__name__}: {exc}"
    if proc.returncode == 0:
        return 0, "воспроизводит доставленный _tier_c_writeoff.py"
    return proc.returncode, (
        f"НЕ СОШЁЛСЯ: {(proc.stderr or proc.stdout or '').strip()[-400:]}")


def freshness(source: Path, *, now: Optional[datetime] = None,
              budget_hours: Optional[float] = None) -> dict:
    """Вердикт сторожа свежести о судимом дереве (импорт отложен: stdlib-путь)."""
    from spa_core.monitoring import analytics_audit_freshness as guard
    kwargs = {"now": now}
    if budget_hours is not None:
        kwargs["budget_hours"] = budget_hours
    return guard.build_status(Path(source).resolve() / MARKUP_REL, **kwargs)


def run_step(source: Path, into: Path, *, sandbox: Optional[Path] = None,
             tier: str = "B", force: bool = False, keep_sandbox: bool = False,
             reuse_sandbox: bool = False, now: Optional[datetime] = None,
             budget_hours: Optional[float] = None,
             python: Optional[str] = None) -> dict:
    """Весь шаг целиком. → отчёт-словарь (в нём же `exit_code`). Не бросает наружу."""
    src = Path(source).resolve()
    dst = Path(into).resolve()
    now = now or datetime.now(timezone.utc)
    report: dict = {
        "llm_forbidden": True,
        "deterministic": True,
        "advisory": True,
        "derived_at": now.isoformat(),
        "source": str(src),
        "into": str(dst),
        "tier": tier,
        "forced": bool(force),
        "ran_audit": False,
        "markup_changed": False,
        "sandbox": None,
        "exit_code": OK,
    }

    before = freshness(src, now=now, budget_hours=budget_hours)
    report["freshness_before"] = {"status": before.get("status"),
                                  "age_hours": before.get("age_hours"),
                                  "reason": before.get("reason")}

    if before.get("status") == "FRESH" and not force:
        report["decision"] = (
            f"аудит мерили {before.get('age_hours')}ч назад при такте "
            f"{before.get('max_age_hours')}ч — прогон не нужен"
        )
        return report

    report["decision"] = (
        "прогон нужен: " + str(before.get("reason") or before.get("status"))
        if not force else "прогон запрошен явно (--force)"
    )

    box_holder = None
    if sandbox is None:
        box_holder = tempfile.mkdtemp(prefix="spa_analytics_audit_")
        box = Path(box_holder)
    else:
        box = Path(sandbox)
    report["sandbox"] = str(box)

    try:
        make_sandbox(src, box, reuse=reuse_sandbox)
        stamp_before = markup_stamp(box)
        report["markup_stamp_before"] = stamp_before
        proc = run_audit(box, tier=tier, python=python)
        report["ran_audit"] = True
        report["audit_returncode"] = proc.returncode
        report["audit_stdout"] = (proc.stdout or "").strip()[-2000:]
        if proc.returncode != 0:
            report["exit_code"] = REFUSED
            report["error"] = (
                f"аудит вернул код {proc.returncode}: "
                f"{(proc.stderr or '').strip()[-600:]}"
            )
            return report
        if tier != "B":
            # Разметку даёт только Tier B — для остальных тиров шаг честно
            # сообщает, что доставлять нечего, и НЕ выдаёт это за замер Tier B.
            report["decision"] += f"; tier={tier} разметки не производит"
            return report
        assert_markup_produced(box, stamp_before)
        report["markup_stamp_after"] = markup_stamp(box)
        changed = deliver_markup(box, dst)
        report["markup_changed"] = changed

        # ── перепись внетировых: кого мы не меряем вовсе ──────────────────────
        census = run_census(box, python=python)
        report["census_returncode"] = census.returncode
        report["census_stdout"] = (census.stdout or "").strip()[-600:]
        if census.returncode != 0:
            report["exit_code"] = REFUSED
            report["error"] = (
                f"перепись внетировых вернула код {census.returncode}: "
                f"{(census.stderr or '').strip()[-600:]}")
            return report
        census_changed = deliver_file(box, dst, CENSUS_REL)
        report["census_changed"] = census_changed

        # ── самопроверка генератора реестров списания ─────────────────────────
        # Отказ здесь НЕ роняет шаг: генератор ничего не производит в этом прогоне,
        # и обрушить ежедневный замер слепоты из-за его самопроверки значило бы
        # заглушить нужный сигнал ради соседнего. Но вердикт записывается, и он
        # виден — «не измерено» здесь не притворяется «сошлось».
        rc, verdict = writeoff_selfcheck_verdict(box, python=python)
        report["writeoff_selfcheck_returncode"] = rc
        report["writeoff_selfcheck"] = verdict

        report["exit_code"] = (NEEDS_DELIVERY if (changed or census_changed) else OK)
    except AuditStepError as exc:
        report["exit_code"] = REFUSED
        report["error"] = str(exc)
        return report
    except (OSError, subprocess.SubprocessError) as exc:
        report["exit_code"] = REFUSED
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report
    finally:
        if box_holder is not None and not keep_sandbox:
            shutil.rmtree(box_holder, ignore_errors=True)

    after = freshness(dst, now=now, budget_hours=budget_hours)
    report["freshness_after"] = {"status": after.get("status"),
                                 "age_hours": after.get("age_hours"),
                                 "reason": after.get("reason")}
    return report


def _render(report: dict) -> str:
    lines: List[str] = []
    code = report.get("exit_code", REFUSED)
    head = {OK: "✅", NEEDS_DELIVERY: "📦", REFUSED: "⛔"}.get(code, "⛔")
    lines.append(f"{head} шаг «ежедневный аудит аналитики» — код {code}")
    fb = report.get("freshness_before") or {}
    lines.append(f"   свежесть до: {fb.get('status')} ({fb.get('reason')})")
    lines.append(f"   решение: {report.get('decision')}")
    if report.get("ran_audit"):
        lines.append(f"   песочница: {report.get('sandbox')}")
        out = report.get("audit_stdout") or ""
        for row in out.splitlines():
            lines.append(f"   аудит: {row}")
    if report.get("error"):
        lines.append(f"   ОТКАЗ: {report['error']}")
    if code == NEEDS_DELIVERY:
        lines.append(
            f"   ДОСТАВИТЬ: {MARKUP_REL} обновлён в {report.get('into')} — "
            "уехать должен ЭТИМ же пушем цикла (иначе прод не двигается)"
        )
    fa = report.get("freshness_after")
    if fa:
        lines.append(f"   свежесть после: {fa.get('status')} ({fa.get('age_hours')}ч)")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[2])
    ap.add_argument("--source", default=str(REPO_ROOT),
                    help="дерево, чей аналитический слой судим (по умолчанию — своё)")
    ap.add_argument("--into", default=None,
                    help="куда положить обновлённую разметку (по умолчанию — --source)")
    ap.add_argument("--sandbox", default=None,
                    help="каталог песочницы (по умолчанию — временный, удаляется)")
    ap.add_argument("--tier", default="B", choices=["A", "B", "C"])
    ap.add_argument("--force", action="store_true",
                    help="гнать аудит даже если сторож говорит FRESH")
    ap.add_argument("--keep-sandbox", action="store_true")
    ap.add_argument("--reuse-sandbox", action="store_true")
    ap.add_argument("--budget-hours", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    report = run_step(
        Path(args.source), Path(args.into or args.source),
        sandbox=Path(args.sandbox) if args.sandbox else None,
        tier=args.tier, force=args.force, keep_sandbox=args.keep_sandbox,
        reuse_sandbox=args.reuse_sandbox, budget_hours=args.budget_hours,
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(_render(report))
    return int(report.get("exit_code", REFUSED))


if __name__ == "__main__":
    sys.exit(main())
