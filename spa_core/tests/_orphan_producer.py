"""_orphan_producer.py — у объявленного продукта есть ли КОД, который его пишет.

Вопрос, на который не отвечал никто. У артефакта во флоте три разных сторожа, и
каждый честно отвечает на СВОЙ вопрос:

* `architecture_conformance` B2 — «файл лежит на диске и свежий?»;
* `architecture_conformance` B3 — «его кто-нибудь читает?»;
* `artifact_contract` (B7) — «агент ОБЪЯВИЛ то, что пишет?».

Ни один не спрашивает **«а есть ли на свете вызов, который его вычисляет?»** — и
07.09 в эту щель провалился целый измеритель. ADR-257 построил
`spa_core/monitoring/cio_outcome_independence.py`, внёс артефакт в манифест ДВУМЯ
записями, назвал потребителя в шаге 0-офис, оставил зелёными 37 тестов — и не
добавил ни одного производящего вызова. Файл не появился НИ РАЗУ. Сторожа
сказали: «отсутствует на диске» (WARN, неотличимо от «агент ещё не ходил») и
«код и манифест называют разный продукт» (WARN). Ни один не сказал, что писать
его некому.

И `artifact_contract` не мог: его вердикт — **на агента, а не на артефакт**.
Замер 08.09 по этому дереву: у 34 агентов с вердиктом `confirmed` объявлено 83
артефакта, а запись видна у 45 — у `com.spa.decision_loop` **1 из 25**. Одной
видимой записи достаточно, чтобы подтвердить объявление из двадцати пяти строк.

## Что меряется здесь

Для КАЖДОГО активного артефакта манифеста: существует ли не-тестовый модуль,
который его пишет, и достижим ли этот модуль хоть откуда-нибудь.

Три исхода, а не два:

* ``REACHABLE``  — писатель есть, и он либо сам точка входа агента, либо его
  импортирует не-тестовый модуль;
* ``ORPHAN``     — писатель есть, но **ни один** его писатель не является точкой
  входа и не импортирован ничем, кроме тестов. Это и есть дефект: код живой
  только под pytest;
* ``UNMEASURED`` — записи не видно вовсе (имя собирается на лету — так устроена
  семья `io_*`, `harness.py` пишет ``f"{agent_key}.json"``) либо базовое имя
  неоднозначно. **Не находка.** «Не измерено» ≠ «не пишет».

## Почему точка входа освобождена от импортёра

Первая редакция этого измерителя объявила сиротами `rules_watchdog` и
`intraday_equity` — оба ЛОЖНО: launchd зовёт такой модуль ПО ИМЕНИ, импортёр ему
не нужен и не будет нужен. Признак «его никто не импортирует» без этой поправки
меряет не достижимость, а способ запуска.

## Почему тестовый импортёр НЕ спасает

Это сердце проверки. У `cio_outcome_independence` был импортёр — его собственный
тест, и тесты были зелёные. Модуль, который зовут только тесты, в проде не
исполняется никогда; засчитывать такой импорт значило бы построить прибор,
который сегодняшний дефект называет здоровьем.

Только stdlib, никаких часов, никаких pid, никакого `data/`: предмет — дерево
исходников, поэтому вердикт воспроизводим на любом хосте.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
from pathlib import Path

from spa_core.monitoring.artifact_io_scan import WRITE, scan_file

REACHABLE = "REACHABLE"
ORPHAN = "ORPHAN"
UNMEASURED = "UNMEASURED"

#: Каталоги, в которых живёт исполняемый код флота. `tests/` сюда не входит
#: НАМЕРЕННО — см. «Почему тестовый импортёр НЕ спасает».
CODE_DIRS = ("spa_core", "scripts")


def _is_test(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def source_files(repo: Path) -> list[tuple[str, Path]]:
    """Пары «имя модуля → файл» для всего НЕ-тестового кода флота."""
    out: list[tuple[str, Path]] = []
    for d in CODE_DIRS:
        for p in sorted((repo / d).rglob("*.py")):
            if _is_test(p.relative_to(repo)):
                continue
            out.append((p.relative_to(repo).with_suffix("").as_posix().replace("/", "."), p))
    return out


def _imports(path: Path) -> set[str]:
    """Имена модулей, ввезённые файлом. Разбор, а не текст."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return set()
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
            # `from spa_core.monitoring import X` — модулем является и `...monitoring.X`
            for a in n.names:
                out.add(f"{n.module}.{a.name}")
        elif isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name)
    return out


def entry_modules(repo: Path) -> set[str]:
    """Точки входа агентов — тем же разбором обёрток, что паспорт и `artifact_contract`.

    Одно имя — один объект: своей копии таблицы здесь нет намеренно (§3 ТЗ
    владельца — не заводить параллельных моделей).
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_fap_orphan", repo / "scripts" / "fill_agent_passports.py")
    if spec is None or spec.loader is None:  # pragma: no cover — дерево без скрипта
        return set()
    fap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fap)
    man = json.loads((repo / "architecture" / "manifest.json").read_text(encoding="utf-8"))
    out = set()
    for a in man.get("agents", []):
        m = fap.module_of(a.get("program"))
        if m:
            out.add(m)
    return out


def measure(repo: Path, *, sources=None, entries=None, manifest=None) -> dict:
    """Вердикт по каждому активному артефакту манифеста.

    Всё, что можно принять за окружение, принимается ВХОДОМ: состав исходников,
    состав точек входа и сам манифест. Умолчание у каждого — настоящее дерево;
    контроли подают своё и потому не зависят от хоста.
    """
    repo = Path(repo)
    srcs = list(source_files(repo)) if sources is None else [(m, Path(p)) for m, p in sources]
    ents = entry_modules(repo) if entries is None else set(entries)
    man = manifest if manifest is not None else json.loads(
        (repo / "architecture" / "manifest.json").read_text(encoding="utf-8"))

    imported: set[str] = set()
    for name, path in srcs:
        for m in _imports(path):
            if m != name:
                imported.add(m)

    w_full: dict[str, list[str]] = {}
    w_base: dict[str, list[tuple[str, str]]] = {}
    for name, path in srcs:
        try:
            scanned = scan_file(path)
        except Exception:  # noqa: BLE001 — нечитаемый файл не есть вердикт об артефакте
            continue
        for art, kinds in scanned.items():
            if WRITE not in kinds:
                continue
            w_full.setdefault(art, []).append(name)
            w_base.setdefault(art.split("/")[-1], []).append((art, name))

    # Базовое имя годится ТОЛЬКО когда оно однозначно. `market_regime.json` живёт
    # и в `data/`, и в `data/investment_os/` — привязка по базовому имени назвала
    # бы писателем дневной цикл вместо аналитика (ровно эту ошибку выдала первая
    # редакция замера).
    ambiguous = {b for b, v in w_base.items() if len({a for a, _ in v}) > 1}
    declared_bases: dict[str, set[str]] = {}
    for a in man.get("artifacts", []):
        if a.get("status") == "active":
            declared_bases.setdefault(a["path"].split("/")[-1], set()).add(a["path"])
    ambiguous |= {b for b, v in declared_bases.items() if len(v) > 1}

    rows = []
    for a in man.get("artifacts", []):
        if a.get("status") != "active":
            continue
        path = a["path"]
        base = path.split("/")[-1]
        writers = list(w_full.get(path, ()))
        how = "полный путь"
        if not writers and base not in ambiguous:
            writers = [n for _, n in w_base.get(base, ())]
            how = "базовое имя (однозначно)"
        if not writers:
            rows.append({
                "path": path, "producer": a.get("producer"), "verdict": UNMEASURED,
                "writers": [], "orphans": [], "how": how,
                "reason": ("базовое имя неоднозначно" if base in ambiguous else
                           "литерала пути нет в не-тестовом коде — имя может "
                           "собираться на лету (семья io_*)"),
            })
            continue
        orphans = [w for w in writers if w not in ents and w not in imported]
        verdict = ORPHAN if len(orphans) == len(writers) else REACHABLE
        rows.append({
            "path": path, "producer": a.get("producer"), "verdict": verdict,
            "writers": writers, "orphans": orphans, "how": how,
            "reason": ("ни один писатель не является точкой входа и не импортирован "
                       "не-тестовым кодом" if verdict == ORPHAN else ""),
        })

    counts = {v: sum(1 for r in rows if r["verdict"] == v)
              for v in (REACHABLE, ORPHAN, UNMEASURED)}
    return {"population": len(rows), "counts": counts, "rows": rows,
            "entries": len(ents), "sources": len(srcs)}


def orphans(report: dict) -> list[dict]:
    return [r for r in report["rows"] if r["verdict"] == ORPHAN]
