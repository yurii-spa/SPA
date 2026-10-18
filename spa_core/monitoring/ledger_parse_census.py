"""Перепись ПОВТОРНОГО РАЗБОРА хеш-лент у читающих моделей (заказ G777 п. 1).

Цикл #893 ([ADR-777]) нашёл и снял один случай: читающая модель
``research_factory.read.latest()`` разбирала ``data/research_factory/ledger.jsonl``
(52 108 460 Б) **4 958 раз** за один вызов, и лекарство ADR-763 было вкручено в ОДНУ
точку входа, а не в саму модель. Заказ G777 п. 1 был сформулирован как «НЕ ИЗМЕРЕНО»:
*«прочие хеш-ленты (investment_cio, capital_shadow, sleeve_aggressive) имеют свои
читающие модели, и переехали ли они на тот же порядок — не измерено»*.

## Ответ на заказ (замер 2026-10-18, живое ``data/`` хоста)

===================  ==============  ==========  ========  ==========  ==========
лента                       байт     разбор, с   открытий   цена, с    запас, ×
===================  ==============  ==========  ========  ==========  ==========
research_factory         52 108 460      0.2147          2      0.429        2.3
capital_shadow            1 464 682      0.0041          5      0.021       48.8
investment_cio              892 441      0.0025          3      0.008      133.3
sleeve_aggressive            27 120      0.0002          1      0.000     5000.0
===================  ==============  ==========  ========  ==========  ==========

**Переехали — НЕТ, и переехать не могли:** порядок ADR-777 (область
:func:`spa_core.utils.hash_ledger.read_cache`) живёт в ОДНОЙ реализации ленты, а в
дереве их ЧЕТЫРЕ, и три из них не импортируют ``hash_ledger`` вовсе — у каждой свой
разборщик (``investment_cio/ledger.py::read_all``, ``capital_shadow/ledger.py::read_all``,
``strategy_lab/sleeve/composer.py::load_ledger``). Это стоячий класс «одно правило — одна
копия», и названный тут замер — его цена сегодня.

**Но дефекта у трёх сегодня НЕТ, и причина — не их устройство.** Они дешевы потому, что
их ФАЙЛЫ малы: 892 КБ и 1,4 МБ против 52 МБ. Размер файла есть свойство МИРА (сколько
дней накопилось), а не кода: лента append-only и не усыхает никогда. Поэтому цена каждого
такого читателя растёт сама, без единой правки, и ровно так созрел дефект
research_factory — он был невидим недели и нашёлся только тем, что тест встал на 27 минут.

**Что этот прибор добавляет к ADR-777.** У ADR-777 остался запас **2.3×** — наименьший в
населении, в двадцать раз меньше следующего, — и об этом не говорит сегодня ни один
сторож. Прибор переводит медленный рост в ЧИСЛО: «во сколько раз лента вправе вырасти,
прежде чем ОДИН вызов вида перестанет укладываться в бюджет».

## Как мерится «открытие» — ДВЕ двери, и это не придирка

Разбор считается у самого файла, а не у имён функций: число открытий ленты за один вызов
вида. Иначе прибор знал бы, где у каждой из четырёх реализаций лежит кэш, и разошёлся бы
с ними при первой правке. Дверей, однако, ДВЕ, и подменять надо обе:

* ``builtins.open`` — так читают три реализации (``with open(path) as f``);
* ``io.open`` — так читает ``pathlib`` (``Path.read_text``), то есть
  ``sleeve/composer.py::load_ledger``.

``io.open is builtins.open`` даёт ``True`` — это ОДИН объект, — но ``pathlib`` зовёт его
через пространство имён модуля ``io``, поэтому подмена одного ``builtins.open`` его НЕ
видит. Замер: при подменённом только ``builtins.open`` вид рукава даёт **0 открытий** при
49 прочитанных строках. Ноль тут означал бы «не читает файл», а правда — «дверь не
смотрели».

Отсюда правило третьего исхода, и оно самопроверяющее (инв. #17): **ноль открытий при
непустом ответе вида есть НЕ ИЗМЕРЕНО с названной причиной**, а не «измерено и равно
нулю». Пятая дверь (``os.open`` + ``os.read``) закрытой не объявляется — она объявляется
НЕНАБЛЮДАЕМОЙ, и член, читающий через неё, попадёт в третий исход, а не в тишину.

## Бюджет и порог запаса — РЕШЕНИЯ, и названы как решения

:data:`REPARSE_BUDGET_S` = 1.0 с на ОДИН вызов вида. Это решение, а не замер: вид зовут
многократно внутри одной сборки и одного теста, и при секунде на вызов цена становится
минутами предписанного прогона — ровно тем признаком, которым дефект research_factory и
обнаружился.

:data:`MIN_GROWTH_FACTOR` = 4.0. Тоже решение: менее чем четырёхкратный запас означает,
что обычный рост append-only ленты съест его без единой правки кода.

Упорядочивание членов по запасу от этих двух чисел НЕ зависит — зависит только граница
находки. Поэтому в отчёте печатаются и запас, и оба числа, по которым он посчитан.

## Замкнутость населения

Пятая лента не вправе появиться молча. Население объявлено ДВАЖДЫ и сверяется:

* :data:`LEDGERS` — четыре ленты со своими видами и объявленным числом открытий;
* :data:`LEDGER_CODE_FILES` — файлы, несущие литерал ``"ledger.jsonl"``.

Расхождение второго с деревом краснит сторожа (``test_ledger_parse_census.py``) — тот же
порядок, что у ``read.VIEW_ENTRY_POINTS`` (ADR-777).

ADVISORY: прибор только ЧИТАЕТ. Ни RiskPolicy, ни стоп-кран, ни живой трек, ни ленты он не
трогает; чинить он тоже ничего не умеет.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import builtins
import importlib
import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[2]

#: РЕШЕНИЕ (не замер): сколько секунд ОДИН вызов вида вправе потратить на разбор своей
#: ленты. Причина — в докстроке модуля: вид зовут многократно за сборку, и секунда на
#: вызов становится минутами предписанного прогона.
REPARSE_BUDGET_S = 1.0

#: РЕШЕНИЕ (не замер): во сколько раз лента обязана иметь право вырасти, не выйдя за
#: бюджет. Меньший запас обычный рост append-only ленты съедает без правок кода.
MIN_GROWTH_FACTOR = 4.0

F_MARGIN_SHORT = "growth_margin_below_floor"
F_OPENS_DRIFTED = "opens_per_view_drifted"

U_VIEW_RAISED = "view_raised"
U_LEDGER_ABSENT = "ledger_absent"
U_DOOR_NOT_WATCHED = "zero_opens_with_a_non_empty_answer"
U_VIEW_UNRESOLVED = "view_unresolved"


@dataclass(frozen=True)
class Member:
    """Одна пара «лента ↔ читающий её вид»."""

    id: str
    ledger: str
    view: str | Callable
    declared_opens: int
    opens_reason: str
    scoped_door: bool
    scoped_reason: str


#: Объявленное население. `declared_opens` у каждого члена — ЗАМЕР 2026-10-18 с названной
#: причиной; расхождение в ЛЮБУЮ сторону есть находка, потому что у каждого числа причина,
#: и исчезновение необходимого разбора так же значимо, как появление лишнего.
LEDGERS: Tuple[Member, ...] = (
    Member(
        id="research_factory",
        ledger="research_factory/ledger.jsonl",
        view="spa_core.research_factory.read:latest",
        declared_opens=2,
        opens_reason=("два НАЗВАННЫХ числа (ADR-777): свежий verify(), который кэш не "
                      "обслуживает принципиально, плюс один разбор на всех помощников вида"),
        scoped_door=True,
        scoped_reason="читающая модель открывает область hash_ledger.read_cache (ADR-777)",
    ),
    Member(
        id="capital_shadow",
        ledger="capital_shadow/ledger.jsonl",
        view="spa_core.capital_shadow.read:latest",
        declared_opens=5,
        opens_reason=("своя реализация ledger.read_all БЕЗ кэша: каждый зов разбирает файл "
                      "заново; пять зовов за вид — замер, не проект"),
        scoped_door=False,
        scoped_reason="hash_ledger не импортируется — области нет, кэша нет",
    ),
    Member(
        id="investment_cio",
        ledger="investment_cio/ledger.jsonl",
        view="spa_core.investment_cio.read:latest",
        declared_opens=3,
        opens_reason=("своя реализация ledger.read_all БЕЗ кэша; три зова за вид — замер, "
                      "не проект"),
        scoped_door=False,
        scoped_reason="hash_ledger не импортируется — области нет, кэша нет",
    ),
    Member(
        id="sleeve_aggressive",
        ledger="sleeve_aggressive/ledger.jsonl",
        view="spa_core.strategy_lab.sleeve.composer:load_ledger",
        declared_opens=1,
        opens_reason=("читатель один и разбирает один раз; читает через pathlib "
                      "(Path.read_text) — именно он доказывает, что дверей ДВЕ"),
        scoped_door=False,
        scoped_reason="hash_ledger не импортируется — области нет, кэша нет",
    ),
)

#: Вторая, НЕЗАВИСИМАЯ запись населения: файлы дерева, несущие литерал имени ленты.
#: Сверяется со деревом сторожем — пятая лента не вправе появиться молча.
LEDGER_CODE_FILES: Tuple[str, ...] = (
    "spa_core/capital_shadow/contract.py",
    "spa_core/investment_cio/contract.py",
    "spa_core/research_factory/contract.py",
    "spa_core/strategy_lab/sleeve/composer.py",
    "spa_core/utils/hash_ledger.py",
)

LEDGER_LITERAL = '"ledger.jsonl"'

#: Единственное исключение из обхода, и причина у него названа: прибор, который СПРАШИВАЕТ
#: о литерале имени ленты, обязан нести этот литерал в себе — иначе он не мог бы спросить.
#: Молчаливого списка исключений у этой переписи нет; это одно, и оно печатается в отчёте.
SELF_REL = "spa_core/monitoring/ledger_parse_census.py"


def ledger_code_files(tree_root: Optional[Path] = None) -> List[str]:
    """Файлы НЕ-тестового кода, несущие литерал имени ленты — замером по дереву.

    Отвечает на вопрос «сколько лент знает КОД», отдельно от вопроса «сколько лент знает
    этот модуль». Два ответа и сверяются; совпадение их — не тавтология, потому что
    добывались они по-разному.
    """
    root = Path(tree_root or _ROOT)
    found: List[str] = []
    for base in ("spa_core", "scripts"):
        base_dir = root / base
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in f"/{rel}":
                continue
            if rel == SELF_REL:
                continue  # см. SELF_REL: причина исключения названа там, а не «и так понятно»
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if LEDGER_LITERAL in text:
                found.append(rel)
    return found


def resolve_view(member: Member) -> Tuple[Optional[Callable], Optional[str]]:
    """Вид как вызываемое. Неразрешимый вид — третий исход с причиной, не исключение."""
    if callable(member.view):
        return member.view, None
    try:
        mod_name, _, attr = str(member.view).partition(":")
        if not attr:
            return None, f"{U_VIEW_UNRESOLVED}: в «{member.view}» нет имени функции после ':'"
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, attr, None)
        if not callable(fn):
            return None, f"{U_VIEW_UNRESOLVED}: {member.view} не вызываемое"
        return fn, None
    except Exception as exc:  # noqa: BLE001 — причина обязана быть НАЗВАНА, а не съедена
        return None, f"{U_VIEW_UNRESOLVED}: {type(exc).__name__}: {exc}"


def count_opens(target: Path, call: Callable[[], object]) -> Tuple[int, object, Optional[str]]:
    """Сколько раз за ОДИН вызов ``call`` открывается файл ``target`` — по ОБЕИМ дверям.

    ``io.open is builtins.open`` истинно (один объект), но ``pathlib`` зовёт его через
    пространство имён ``io``, поэтому подмена одной двери другую не видит. Замерено на
    ``sleeve/composer.py::load_ledger``: только ``builtins.open`` даёт 0 открытий при 49
    прочитанных строках.
    """
    try:
        want = str(target.resolve())
    except OSError:  # pragma: no cover — путь без доступа к родителю
        want = str(target)
    hits = {"n": 0}
    real_builtin, real_io = builtins.open, io.open

    def make(real):
        def hook(file, *a, **k):
            try:
                if str(Path(file).resolve()) == want:
                    hits["n"] += 1
            except (OSError, TypeError, ValueError):
                pass
            return real(file, *a, **k)
        return hook

    builtins.open = make(real_builtin)
    io.open = make(real_io)
    try:
        answer = call()
        err = None
    except Exception as exc:  # noqa: BLE001 — вид упал ⇒ третий исход с причиной
        answer, err = None, f"{U_VIEW_RAISED}: {type(exc).__name__}: {exc}"
    finally:
        builtins.open, io.open = real_builtin, real_io
    return hits["n"], answer, err


def parse_seconds(path: Path, *, rounds: int = 3) -> Optional[float]:
    """Сколько стои́т ОДИН разбор ленты — замером, не оценкой. Лучшее из ``rounds``
    прогонов: шум машины завышает, и завышенная цена дала бы завышенную тревогу."""
    best: Optional[float] = None
    for _ in range(max(1, rounds)):
        t0 = time.perf_counter()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        json.loads(line)
        except (OSError, ValueError):
            return None
        took = time.perf_counter() - t0
        best = took if best is None else min(best, took)
    return best


def _answer_is_empty(answer: object) -> bool:
    """Пустой ответ вида. Пустота — законный ответ (ленты может не быть), и тогда ноль
    открытий есть ЗАМЕР. Непустой ответ при нуле открытий — наоборот, улика о двери."""
    if answer is None:
        return True
    if isinstance(answer, (list, tuple, set, dict, str)):
        return len(answer) == 0
    return False


def measure(data_dir: Path | str, *, members: Sequence[Member] = LEDGERS,
            budget_s: float = REPARSE_BUDGET_S,
            min_factor: float = MIN_GROWTH_FACTOR,
            tree_root: Optional[Path] = None,
            parse_rounds: int = 3) -> dict:
    """Замер по населению. Три исхода у КАЖДОГО члена различимы (инв. #17)."""
    data = Path(data_dir)
    rows: List[dict] = []
    for m in members:
        row: dict = {
            "id": m.id,
            "ledger": m.ledger,
            "declared_opens": m.declared_opens,
            "opens_reason": m.opens_reason,
            "scoped_door": m.scoped_door,
            "scoped_reason": m.scoped_reason,
            "opens": None,
            "bytes": None,
            "parse_s": None,
            "cost_s": None,
            "growth_factor": None,
            "unmeasured": None,
            "findings": [],
        }
        path = data / m.ledger
        fn, why = resolve_view(m)
        if fn is None:
            row["unmeasured"] = why
            rows.append(row)
            continue
        if not path.exists():
            row["unmeasured"] = f"{U_LEDGER_ABSENT}: {path}"
            rows.append(row)
            continue
        row["bytes"] = path.stat().st_size
        opens, answer, err = count_opens(path, lambda fn=fn: fn(data))
        if err:
            row["unmeasured"] = err
            rows.append(row)
            continue
        row["opens"] = opens
        if opens == 0 and not _answer_is_empty(answer):
            row["unmeasured"] = (
                f"{U_DOOR_NOT_WATCHED}: вид ответил непусто, а ни одна наблюдаемая дверь "
                f"({LEDGER_LITERAL} через builtins.open / io.open) не открывалась — "
                f"значит читает мимо них (например os.open), и ноль тут НЕ есть замер")
            rows.append(row)
            continue
        parse_s = parse_seconds(path, rounds=parse_rounds)
        if parse_s is None:
            row["unmeasured"] = f"{U_LEDGER_ABSENT}: цена разбора не измерена — {path} не прочитан"
            rows.append(row)
            continue
        row["parse_s"] = parse_s
        row["cost_s"] = opens * parse_s
        if opens != m.declared_opens:
            row["findings"].append({
                "kind": F_OPENS_DRIFTED,
                "text": (f"открытий за вид {opens} против объявленных {m.declared_opens} "
                         f"— у объявленного числа есть причина: {m.opens_reason}"),
            })
        if row["cost_s"] > 0:
            row["growth_factor"] = budget_s / row["cost_s"]
            if row["growth_factor"] < min_factor:
                row["findings"].append({
                    "kind": F_MARGIN_SHORT,
                    "text": (f"запас роста {row['growth_factor']:.1f}× ниже порога "
                             f"{min_factor:.1f}× — лента append-only и не усыхает, "
                             f"поэтому бюджет {budget_s:.2f} с будет пройден без единой "
                             f"правки кода"),
                })
        else:
            # Цена строго нулевая бывает только при нуле открытий у пустого ответа:
            # запас тогда не «бесконечен», а НЕ ОПРЕДЕЛЁН, и выдавать его числом нельзя.
            row["growth_factor"] = None
        rows.append(row)

    declared_files = sorted(LEDGER_CODE_FILES)
    tree_files = sorted(ledger_code_files(tree_root))
    doc = {
        "budget_s": budget_s,
        "min_growth_factor": min_factor,
        "data_dir": str(data),
        "rows": rows,
        "population": {
            "declared": len(members),
            "code_files_declared": declared_files,
            "code_files_in_tree": tree_files,
            "code_files_undeclared": [f for f in tree_files if f not in declared_files],
            "code_files_missing": [f for f in declared_files if f not in tree_files],
        },
        "measured": [r for r in rows if not r["unmeasured"]],
        "unmeasured": [r for r in rows if r["unmeasured"]],
    }
    doc["findings"] = [dict(f, id=r["id"]) for r in rows for f in r["findings"]]
    return doc


def format_report(doc: dict) -> List[str]:
    out = [f"— повторный разбор хеш-лент у читающих моделей (заказ G777 п. 1) —",
           f"   каталог: {doc['data_dir']}",
           f"   РЕШЕНИЯ (не замеры): бюджет {doc['budget_s']:.2f} с на вызов вида · "
           f"порог запаса {doc['min_growth_factor']:.1f}×"]
    for r in sorted(doc["rows"], key=lambda x: (x["growth_factor"] is None,
                                                x["growth_factor"] or 0.0)):
        if r["unmeasured"]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {r['id']}: {r['unmeasured']}")
            continue
        door = "область кэша ЕСТЬ" if r["scoped_door"] else "области кэша НЕТ"
        factor = "—" if r["growth_factor"] is None else f"{r['growth_factor']:.1f}×"
        out.append(f"   {r['id']}: {r['bytes']:,} Б · разбор {r['parse_s']:.4f} с · "
                   f"открытий {r['opens']} · цена {r['cost_s']:.3f} с · запас {factor} · {door}")
    findings = doc["findings"]
    if findings:
        out.append(f"   🔴 НАХОДОК {len(findings)}:")
        for f in findings:
            out.append(f"      [{f['kind']}] {f['id']}: {f['text']}")
    else:
        out.append("   ✅ у каждого члена открытий столько, сколько объявлено, и запас выше порога")
    pop = doc["population"]
    if pop["code_files_undeclared"] or pop["code_files_missing"]:
        out.append(f"   ⚠️ население КОДА разошлось с объявленным: "
                   f"не объявлено {pop['code_files_undeclared']} · "
                   f"объявлено и отсутствует {pop['code_files_missing']}")
    else:
        out.append(f"   население замкнуто: лент {pop['declared']}, файлов кода "
                   f"{len(pop['code_files_in_tree'])} — объявленное и найденное совпали "
                   f"(единственное исключение обхода НАЗВАНО: {SELF_REL} — прибор несёт "
                   f"литерал по построению)")
    out.append("   НЕ ДОКЛАДЫВАЕТ: читает ли кто-то ленту через os.open (такой член уйдёт в "
               "третий исход, а не в тишину) · сколько РАЗ за сборку зовут сам вид · "
               "верна ли сама лента (это вопрос verify(), не этого прибора)")
    out.append("   ADVISORY: прибор только ЧИТАЕТ (ничего не чинит, ни один гейт его не читает)")
    return out


def exit_code(doc: dict) -> int:
    """Вердикт в код возврата, ОТДЕЛЬНОЙ функцией — чтобы отображение «три исхода → три
    числа» проверялось тестом прямо, а не через настоящее население и настоящие ленты.

    Порядок намеренный: **НЕ ИЗМЕРЕНО сильнее находки**. Слепой член означает, что про
    часть населения мы не знаем ничего, и выдать код находки (то есть «измерено, вот что
    нашли») было бы ровно подменой третьего исхода вторым (инв. #17).
    """
    pop = doc["population"]
    if doc["unmeasured"]:
        return 2
    if doc["findings"] or pop["code_files_undeclared"] or pop["code_files_missing"]:
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись повторного разбора хеш-лент у читающих моделей (заказ G777 п. 1)")
    ap.add_argument("--data-dir", default=str(_ROOT / "data"),
                    help="каталог data/ с лентами (ЧИТАЕТСЯ, не правится)")
    ap.add_argument("--tree-root", default=str(_ROOT))
    ap.add_argument("--budget-s", type=float, default=REPARSE_BUDGET_S)
    ap.add_argument("--min-factor", type=float, default=MIN_GROWTH_FACTOR)
    ap.add_argument("--parse-rounds", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = measure(args.data_dir, budget_s=args.budget_s, min_factor=args.min_factor,
                  tree_root=Path(args.tree_root), parse_rounds=args.parse_rounds)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1, default=str))
    else:
        print("\n".join(format_report(doc)))
    return exit_code(doc)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
