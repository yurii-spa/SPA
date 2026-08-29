"""artifact_contract.py — агент ОБЪЯВЛЯЕТ, что производит; сверка с тем, что он пишет.

Зачем это, а не вывод из кода. ADR-154 ставит диагноз: пропущена ступень **контракта**.
28.08 сессия попробовала обойтись без неё — вывести производителя артефакта из кода разбором
синтаксиса. Замер на эталоне (27 артефактов с уже объявленным производителем): верно 13,
НЕВЕРНО 1, не смог 13; по задаче — однозначный ответ у 15 агентов из 69. А семья `io_*`
недостижима в принципе: `investment_os/harness.py` пишет ``f"{self.agent_key}.json"``, и имени
артефакта не существует как строки нигде в коде.

Вывод, ради которого написан этот модуль: **контракт нельзя вывести — его объявляют.**
Попытка вывести его из кода это та же догадка, что и оркестрация без контрактов, только
этажом ниже: числа получаются уверенные на вид и неверные в одном случае из четырнадцати.

Объявление — константа модульного уровня точки входа агента::

    PRODUCES = ("data/agent_health.json", "data/agent_registry.json")

Читается РАЗБОРОМ, а не импортом: импорт исполняет модуль (побочные эффекты, сеть, запись
файлов), и сторож, чтобы посмотреть на агента, запускал бы его.

Сверка даёт ТРИ исхода, а не два (иначе сторож врёт про целую семью):

* ``confirmed``  — объявлено И запись видна в коде: контракт подтверждён независимо;
* ``unmeasured`` — объявлено, но записи не видно НИГДЕ в замыкании. Это НЕ нарушение:
  так выглядит harness-семья, где имя собирается на лету. «Не измерено» ≠ «не пишет»;
* ``contradiction`` — видна запись артефакта, который агент НЕ объявил. Вот это дефект:
  либо объявление отстало, либо агент пишет мимо контракта.

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
from pathlib import Path

from spa_core.monitoring.artifact_io_scan import WRITE, scan_file

DECLARATION = "PRODUCES"
# Второе объявление: файлы, которые модуль ПИШЕТ, но продуктом не являются —
# собственное состояние между прогонами, разовая копия при миграции, демо-ветка.
# Понадобилось 29.08: `findings_bridge` пишет своё состояние `findings_bridge_state.json`,
# а `cycle_runner` — `equity_curve_daily.demo_backup.json`, которого в проде НЕТ ВОВСЕ
# (пишется только при переходе с демо-кривой на настоящую). Объявить их продуктами
# значило бы завести вечную находку о протухании файла, которого никто не ждёт;
# промолчать — оставить вечное противоречие. Верный ответ — третье: СКАЗАТЬ, что
# запись есть и продуктом не является.
#
# Это МОЖЕТ стать глушилкой, и потому: (1) список виден грепом в одном месте,
# (2) его размер лежит в отчёте рядом с вердиктом, (3) артефакт, попавший в ОБА
# объявления сразу, — сам по себе противоречие (автор не решил, продукт это или нет).
INTERNAL = "INTERNAL_WRITES"

CONFIRMED = "confirmed"
DECLARED_NONE = "declared_none"
UNMEASURED = "unmeasured"
CONTRADICTION = "contradiction"
UNDECLARED = "undeclared"


def declared_produces(py_file: str | Path) -> tuple[str, ...] | None:
    """Объявление `PRODUCES` модуля. None — объявления НЕТ (это не пустой кортеж).

    Разница существенна: `PRODUCES = ()` значит «автор сказал: ничего не произвожу»,
    а отсутствие значит «никто не высказывался». Второе — работа, первое — ответ.
    """
    return _declared_tuple(py_file, DECLARATION)


def _declared_tuple(py_file: str | Path, name: str) -> tuple[str, ...] | None:
    """Кортеж строк, объявленный именем `name` на верхнем уровне модуля.

    None — имени нет вовсе; пустой кортеж — есть и пуст. Разбор `ast`, не импорт:
    импортировать точку входа агента значит его ЗАПУСТИТЬ.
    """
    p = Path(py_file)
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        val = node.value
        if isinstance(val, (ast.Tuple, ast.List)):
            out = [e.value for e in val.elts
                   if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            return tuple(out)
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            return (val.value,)
    return None


def declared_internal(py_file: str | Path) -> tuple[str, ...]:
    """`INTERNAL_WRITES` модуля — разбором, не импортом (импорт исполнил бы агента)."""
    got = _declared_tuple(py_file, INTERNAL)
    return got or ()


def _written_here(module: str, repo: Path) -> set[str]:
    """Артефакты, которые пишет СОБСТВЕННЫЙ модуль агента.

    Замыкание импортов для вердикта НЕ годится, и это измерено: по замыканию
    17 агентов из 19 объявили «противоречие», из них ни одного настоящего —
    `push_state.json` и `digest_queue.json` пишет ОБЩАЯ библиотека алертов,
    попадающая в замыкание почти каждого агента, а у `daily_cycle` замыкание
    тянет пол-системы (36 «чужих» артефактов). Общая запись — не продукт агента.

    По собственному модулю точность на эталоне была ПОЛНОЙ (ни одного неверного
    приписывания), поэтому вердикт судит именно его.
    """
    out: set[str] = set()
    f = repo / (module.replace(".", "/") + ".py")
    if f.is_file():
        for art, kinds in scan_file(f).items():
            if WRITE in kinds:
                out.add(art.split("/")[-1])
    return out


def check_agent(label: str, module: str, repo: Path) -> dict:
    """Сверка объявления агента с тем, что видно в коде. Никогда не бросает."""
    f = repo / (module.replace(".", "/") + ".py")
    decl = declared_produces(f) if f.is_file() else None
    if decl is None:
        return {"label": label, "module": module, "verdict": UNDECLARED,
                "declared": None, "note": "нет объявления PRODUCES — контракт не высказан"}
    if decl == ():
        # Автор ОТВЕТИЛ «ничего не произвожу». Это не то же, что «измерить не удалось»:
        # первое закрывает вопрос, второе его заводит. Без отдельного исхода шесть
        # агентов с ясным ответом выглядели бы как невыясненные (замер 28.08).
        return {"label": label, "module": module, "verdict": DECLARED_NONE, "declared": [],
                "note": "объявлено ЯВНО: артефактов не производит — метрикой качества "
                        "обязан стать другой признак (доступность / факт отправки)"}
    written = _written_here(module, repo)
    internal = declared_internal(f) if f.is_file() else ()
    both = sorted({d.split("/")[-1] for d in decl} & {i.split("/")[-1] for i in internal})
    if both:
        return {"label": label, "module": module, "verdict": CONTRADICTION,
                "declared": list(decl), "undeclared_writes": both,
                "note": "артефакт объявлен И продуктом, И внутренней записью — "
                        "автор не решил, чем он является"}
    # ПРЕДЕЛ, который надо знать читателю вердикта: сравнение идёт по БАЗОВОМУ имени,
    # потому что в коде путь чаще всего собирается на лету (`ddir / "x.json"`), и
    # каталог статически не известен. В репозитории есть одноимённые файлы в разных
    # каталогах — `data/market_regime.json` пишет дневной цикл «в свой ddir» (MP-534,
    # cycle_runner.py), а `data/investment_os/market_regime.json` — аналитик
    # `io_market_regime`. Поэтому `confirmed` здесь значит «имя совпало», а НЕ
    # «каталог проверен»; для `contradiction` этого достаточно (написано имя, которого
    # нет в контракте вовсе), для полной сверки путей нужен рантайм.
    decl_base = {d.split("/")[-1] for d in decl}
    internal_base = {i.split("/")[-1] for i in internal}
    extra = sorted(a for a in written - decl_base - internal_base if a)
    if extra:
        return {"label": label, "module": module, "verdict": CONTRADICTION,
                "declared": list(decl), "undeclared_writes": extra,
                "note": "собственный модуль агента пишет артефакт, которого нет в объявлении"}
    if decl_base & written:
        return {"label": label, "module": module, "verdict": CONFIRMED,
                "declared": list(decl), "internal_writes": sorted(internal),
                "note": "объявление подтверждено записью, видной в коде"}
    return {"label": label, "module": module, "verdict": UNMEASURED,
            "declared": list(decl),
            "note": "записи не видно в коде (имя может собираться на лету) — "
                    "НЕ измерено, а не «не пишет»"}


def audit(entry_modules: dict[str, str], repo: Path) -> dict:
    rows = [check_agent(l, m, repo) for l, m in sorted(entry_modules.items())]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"total": len(rows), "counts": counts, "rows": rows}


def audit_fleet(repo: Path | None = None) -> dict:
    """Аудит контрактов всего флота. Публичная точка входа для сторожей.

    Живой потребитель — `architecture_conformance` (проверка B7): он берёт отсюда
    ТОЛЬКО противоречия как находки, остальные исходы кладёт строкой отчёта.
    """
    r = repo or Path(__file__).resolve().parents[2]
    return audit(_entry_modules(r), r)


def _entry_modules(repo: Path) -> dict[str, str]:
    """Точки входа агентов — тем же разбором обёрток, что и паспорт (одно имя — один объект)."""
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location(
        "_fap", repo / "scripts" / "fill_agent_passports.py")
    fap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fap)
    agents = json.loads((repo / "architecture" / "manifest.json").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for a in agents.get("agents", []):
        m = fap.module_of(a.get("program"))
        if m:
            out[a["label"]] = m
    return out


def main() -> int:
    """Отчёт о состоянии контрактов флота. Ничего не пишет и никого не гасит.

    Подключено к живому сторожу 29.08 (`architecture_conformance`, проверка B7),
    после того как объявления появились у большинства флота. Условие подключения
    было именно таким: пока объявлений не было, сигнал такого объёма стал бы
    потоком находок владельцу. В сторож уходят ТОЛЬКО противоречия; `unmeasured`
    и `undeclared` — строка отчёта, не тревога.
    """
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(description="контракт агента: объявлено против написанного")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[2]
    r = audit_fleet(repo)
    if args.json:
        print(_json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    print(f"агентов с читаемой точкой входа: {r['total']}")
    for k in (CONFIRMED, DECLARED_NONE, UNMEASURED, CONTRADICTION, UNDECLARED):
        print(f"  {k:14} {r['counts'].get(k, 0)}")
    for row in r["rows"]:
        if row["verdict"] == CONTRADICTION:
            print(f"\n  ПРОТИВОРЕЧИЕ {row['label']}: пишет {row['undeclared_writes']}, "
                  f"объявлено {row['declared']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
