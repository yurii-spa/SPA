"""Различает ли отчёт готовности «судить НЕЧЕМ» от «писателя НЕТ» — замер трёх
исходов (ADR-881, заказ G879 п. 1 (в)).

Остаток ADR-878/879. Те решения переписали ТРИ критерия go-live так, чтобы они
спрашивали писателя, и завели у ``CategoryScore`` отдельный перечень
``items_unmeasured``. У перечня не оказалось ПИСАТЕЛЯ: все остальные артефакты
отчёт читает общей дверью ``GoLiveReadinessReport._read_json``, а она по
объявлению отдаёт ``{}`` **на любую ошибку** — то есть склеивает три разных
состояния мира в одно:

    файла на диске НЕТ            → писатель не писал (это ОТВЕТ);
    файл есть, но не читается     → судить нечем (ТРЕТИЙ исход);
    файл есть и говорит «нет»     → измерено и равно нулю.

Инвариант #17 требует, чтобы все три были РАЗЛИЧИМЫ у любого производителя
числа. Отчёт готовности к живым деньгам — производитель числа ``total_score`` и
вердикта ``READY``/``NOT_READY``, и читает его владелец.

**Направление склейки названо вслух.** Замер 31.10 на боевом содержимом
(12 присутствующих артефактов из 16 объявленных): счёт не вырос НИ РАЗУ — битый
артефакт роняет балл так же, как отсутствующий, то есть сама СТАВКА fail-CLOSED
и в опасную сторону не смотрит. Предмет находки другой: читателю сообщается
ПРИЧИНА «писателя нет / проверь файл», когда на самом деле файл есть и его не
удалось разобрать. Действие по неверной причине и есть цена.

**Мера двусторонняя и ОДНА.** Сцена одна, и она СВОЯ (синтетическая): прибор не
смотрит в боевое ``data/`` — иначе его вердикт зависел бы от того, что сегодня
лежит на машине, а в CI не мерил бы ничего. Каждый артефакт сцены проверяется
двумя сценами, различие между которыми РОВНО одно:

    битый   — файл ЕСТЬ, байты не разбираются как JSON ⇒ обязан быть НАЗВАН
              в ``items_unmeasured``;
    нет     — файла НЕТ ⇒ обязан быть НЕ назван там (отсутствие есть ответ,
              его место — ``items_pending``).

Зелень одной стороны ничего не доказывает: перечень, в который валится ВСЁ,
различать исходы не умеет так же, как и пустой.

Только stdlib. Прибор ничего не чинит и не пишет за пределами своей сцены.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

#: Исходы меры. Различимы (инвариант #17): «сцена не поднялась» никогда не
#: выдаётся за «читатель слеп» и наоборот.
THREE_OK = "measured"
THREE_BLIND = "blind"
THREE_UNMEASURED = "unmeasured"


def _scene(root: Path, now: datetime) -> list[str]:
    """Выложить сцену и вернуть перечень артефактов, которые в ней ЕСТЬ.

    Содержимое намеренно минимальное и ПОЛОЖИТЕЛЬНОЕ: предмет меры — не счёт
    сцены, а то, умеет ли читатель назвать НЕРАЗОБРАННЫЙ артефакт. Сцена, где
    артефакт и так ничего не даёт, мерила бы сама себя.
    """
    fresh = (now - timedelta(hours=1.0)).isoformat()
    day = (now - timedelta(hours=1.0)).date().isoformat()

    laid: dict[str, Any] = {
        "data/golive_status.json": {
            "timestamp": fresh, "ready_for_live": False,
            "criteria": {f"c{i}": {"passed": True} for i in range(29)},
        },
        "data/gate_status.json": {
            "timestamp": fresh, "kill_switch_status": "LOCKED",
            "status": "paper", "blocked": False,
        },
        "data/kill_switch_status.json": {"timestamp": fresh, "triggered": False},
        "data/pre_launch_validation.json": {
            "timestamp": fresh, "pass_rate": 0.95, "checks": [], "passed": 19,
            "total": 20,
        },
        "data/paper_evidence.json": {
            "days": [{"date": day, "strategy_id": "S7", "apy_pct": 5.6}],
            "evidence_points": 12.0,
        },
        "data/paper_evidence_history.json": {
            "schema_version": "1.0", "history": [], "SEED_DATA": False,
        },
        "data/equity_curve_daily.json": {
            "daily": [{"date": day, "equity": 100_000.0} for _ in range(10)],
            "summary": {"num_days": 10},
        },
        "data/current_positions.json": {
            "capital_usd": 100_000.0, "is_demo": False, "positions": [],
        },
        "data/paper_trading_status.json": {
            "virtual_capital": 100_000.0, "is_demo": False, "timestamp": fresh,
        },
        "data/capital_config.json": {
            "capital": {"starting_capital_usd": 100_000}, "timestamp": fresh,
        },
        "data/paper/evidence_v2.json": {"total_points": 31.0, "timestamp": fresh},
        "data/backtest/source_pipeline.json": {
            "sources": {f"s{i}": "clean_included" for i in range(6)},
        },
        "data/backtest/pre_paper_backtest_gate.json": {
            "passed": True, "gate_passed": True, "timestamp": fresh,
        },
        "data/backtest/paper_ready_gate.json": {
            "passed": True, "gate_passed": True, "timestamp": fresh,
        },
        "data/backtest/owner_paper_acceptance.json": {
            "accepted": True, "accepted_by": "@yurii", "accepted_at": fresh,
        },
        "data/backtest/owner_paper_acceptance_gate.json": {
            "passed": True, "timestamp": fresh,
        },
    }
    for rel, payload in laid.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return sorted(laid)


def _named_unmeasured(root: Path, factory: Callable[[str], Any]) -> set[str]:
    """Имена файлов, НАЗВАННЫЕ отчётом в ``items_unmeasured`` (все категории)."""
    report = factory(str(root))
    doc = report.to_dict()
    named: set[str] = set()
    for cat in doc["categories"]:
        for line in cat["items_unmeasured"]:
            named.add(str(line))
    # Срок готовности — ЧИСЛО вне категорий, и его «судить нечем» живёт своим
    # полем. Спросить только категории значило бы объявить слепой дверь,
    # которая как раз НАЗВАЛА причину.
    for line in doc.get("estimated_days_unmeasured", ()) or ():
        named.add(str(line))
    return named


def _published_surface() -> str:
    """Исходный текст методов отчёта, ДОСТИЖИМЫХ из `to_dict`.

    Третий исход МЕРЫ, а не предмета. Часть артефактов читают только прежние
    (v9) оценщики, которых `_get_categories` больше не зовёт, — у такого
    артефакта в публикуемом отчёте нет читателя ВОВСЕ, и объявить его
    «неразличённым» значило бы назвать слепой дверь, которая его не видит.

    Вопрос задан СТАТИЧЕСКИ и намеренно: спросить про читателей ленту исходов
    самой двери значило бы сверять подопытное с самим собой — читатель, у
    которого ленты нет вовсе (дословная прежняя редакция), объявил бы «читателей
    нет ни у чего» и получил бы зелёный вердикт. Это ровно тот fail-OPEN,
    который мера обязана ловить.

    **Чем мера слаба, сказано вслух:** путь, собранный в рантайме, в тексте не
    появится. Для разделения двух причин этого достаточно; за полноту перечня
    поверхностей мера не отвечает.
    """
    import ast

    from spa_core.analytics import golive_readiness_report as grr

    source = Path(grr.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "GoLiveReadinessReport")
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}

    reachable: set[str] = set()
    frontier = ["to_dict"]
    while frontier:
        name = frontier.pop()
        if name in reachable or name not in methods:
            continue
        reachable.add(name)
        for node in ast.walk(methods[name]):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"):
                frontier.append(node.func.attr)

    return "\n".join(
        ast.get_source_segment(source, methods[name]) or "" for name in sorted(reachable)
    )


def _is_read_by(surface: str, rel: str) -> bool:
    """Назван ли артефакт в тексте публикуемой поверхности.

    Сверяются ВСЕ отрезки пути после ``data/``: `data/paper/evidence_v2.json`
    собирается как ``"paper" / "evidence_v2.json"``, и спросить только про
    последний отрезок значило бы спутать его с одноимённым соседом.
    """
    parts = [seg for seg in Path(rel).parts if seg not in ("data", "backtest")]
    return all(f'"{seg}"' in surface for seg in parts)


def _default_factory(base_dir: str) -> Any:
    from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport
    return GoLiveReadinessReport(base_dir=base_dir)


def drive_three_outcomes(
    now: datetime | None = None,
    factory: Callable[[str], Any] | None = None,
) -> dict:
    """Две сцены на КАЖДЫЙ артефакт. → вердикт меры.

    ``factory`` принимается ради положительного контроля: подменив её на
    читателя с прежней защитной дверью, батарея обязана получить
    ``THREE_BLIND`` — мера, зелёная и на старом коде, не доказывала бы ничего.

    ``THREE_OK`` — КАЖДЫЙ артефакт назван при битых байтах и НЕ назван при
    отсутствии файла. ``THREE_BLIND`` — хоть один не различён, и каждый такой
    назван поимённо с направлением. ``THREE_UNMEASURED`` — сцену поднять не
    удалось, и это НЕ «слеп».
    """
    at = now or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    make = factory or _default_factory

    rows: list[dict] = []
    try:
        with tempfile.TemporaryDirectory(prefix="adr880_") as tmp:
            root = Path(tmp)
            laid = _scene(root, at)
            surface = _published_surface()
            for rel in laid:
                path = root / rel
                original = path.read_bytes()

                path.write_bytes(b"{ \xd1\x8d\xd1\x82\xd0\xbe \xd0\xbd\xd0\xb5 JSON")
                broken = _named_unmeasured(root, make)

                path.unlink()
                gone = _named_unmeasured(root, make)

                path.write_bytes(original)
                stem = Path(rel).name
                rows.append({
                    "artifact": rel,
                    "has_published_reader": _is_read_by(surface, rel),
                    "named_when_broken": any(stem in line for line in broken),
                    "named_when_absent": any(stem in line for line in gone),
                })
    except Exception as exc:                                        # noqa: BLE001
        return {"kind": THREE_UNMEASURED,
                "reason": f"сцена не поднялась: {type(exc).__name__}: {exc}"}

    if not rows:
        return {"kind": THREE_UNMEASURED,
                "reason": "сцена не выложила ни одного артефакта — мерить нечего"}

    blind: list[str] = []
    no_reader: list[str] = []
    for row in rows:
        if not row["has_published_reader"]:
            no_reader.append(
                f"{row['artifact']}: читателя в публикуемом отчёте НЕТ — его "
                f"читают только прежние (v9) оценщики, которых "
                f"`_get_categories` не зовёт")
            continue
        if not row["named_when_broken"]:
            blind.append(
                f"{row['artifact']}: неразобранный артефакт НЕ НАЗВАН — «судить "
                f"нечем» уехало в тот же перечень, что «писателя нет»")
        elif row["named_when_absent"]:
            blind.append(
                f"{row['artifact']}: ОТСУТСТВИЕ названо «не измерено» — "
                f"ответ выдан за неизмерение, склейка с другой стороны")

    verdict = {
        "kind": THREE_BLIND if blind else THREE_OK,
        "artifacts": len(rows),
        "with_published_reader": sum(1 for r in rows if r["has_published_reader"]),
        "distinguished": sum(
            1 for r in rows
            if r["has_published_reader"] and r["named_when_broken"]
            and not r["named_when_absent"]),
        "rows": rows,
        "blind": blind,
        "no_published_reader": no_reader,
    }
    if blind:
        verdict["reason"] = "; ".join(blind[:4]) + (
            f" (и ещё {len(blind) - 4})" if len(blind) > 4 else "")
    return verdict


if __name__ == "__main__":                                          # pragma: no cover
    import sys
    report = drive_three_outcomes()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit({THREE_OK: 0, THREE_BLIND: 1, THREE_UNMEASURED: 2}[report["kind"]])
