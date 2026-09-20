"""Зонд вырожденности: остаётся ли сторож ЗЕЛЁНЫМ с опустошённым входом-перечнем.

Заказ **G44, п. 1** приказа владельца «Portfolio CIO» (хвост ADR-419).
Координата другая, чем у ADR-419: там пара «сторож × исполнитель», здесь —
**сторож и его вход**. Перепись населения — `vacuous_guard_census`; зонд
только ставит опыт и пишет журнал, а вердикт строки собирает перепись.

## Опыт

В ОДНОРАЗОВОМ дереве (`git worktree add --detach` на sha рабочего):

1. база: прогон сторожа как есть. Не зелен ⇒ `unmeasured` — сдвиг вердикта
   мерить не от чего (и «красный сторож» здесь не вердикт о вырожденности);
2. перечень заменяется ПУСТЫМ ЛИТЕРАЛОМ ТОГО ЖЕ РОДА (правило живёт в
   переписи, `empty_literal`; здесь его копии нет — ADR-418);
3. применение перемены ПРОВЕРЯЕТСЯ разбором: молча не применившаяся правка
   дала бы «вердикт не изменился» и выглядела бы ответом;
4. прогон. Зелено ⇒ `vacuous_pass`: сторож осмотрел ноль и не сказал об этом
   ничего. Красно ⇒ `refuses_empty`, и вместе с кодом записываются ИМЕНА
   упавших тестов: приписать красноту потребителю перечня или соседу —
   вопрос переписи, а не зонда;
5. файл возвращается и СВЕРЯЕТСЯ ПО SHA. Несовпадение — громкий отказ, а не
   продолжение: дальнейшие опыты в таком дереве недостоверны.

Рабочее дерево на запись не открывается ни разу.

## Почему не всё население сразу

Входов-перечней в дереве 432 при 247 сторожах; один опыт стои́т до двух
прогонов pytest. Зонд поэтому берёт ВЫБОРКУ, и правило выборки — часть
замера, а не удобство:

* **все** строки, у которых пустота достижима БЕЗ правки исходника
  (`reachable_absent_path`) — это подкласс, где вред не гипотетический;
* **случайная выборка** из остальных с НАЗВАННЫМ зерном — чтобы доля класса
  на всём населении оценивалась числом, а не суждением (тот же приём, что у
  замера разрешающей способности в ADR-419).

Строка, до которой зонд не дошёл, остаётся у переписи `unmeasured` — третьим
исходом, а не «исправной».

## Третий исход (инв. #17)

`unmeasured` с названной причиной: нет pytest (спрошен ОТДЕЛЬНЫМ вопросом —
рабочий прогон выходит ненулевым, когда нашёл падение); сторож красен или
ничего не собрал на базе; пустого литерала того же рода не получить; перемена
не применилась; координата присваивания не единственна; прогон не уложился в
срок; сторож изменён в рабочем дереве (одноразовое несёт HEAD, то есть не его).
"""

from __future__ import annotations

# --- РАЗЗАТЕНЕНИЕ stdlib. Обязано стоять ВЫШЕ всех ввозов, и это замер ------
# Запуск ПО ПУТИ делает `sys.path[0]` каталогом скрипта, а в
# `spa_core/monitoring/` живёт свой `signal.py` (RTMR, ADR-053). Тогда
# `import signal` внутри `subprocess` достаёт НАШ модуль, а не стандартный —
# и это не видно ничем, пока не сработает ИМЕННО путь отказа:
# `subprocess.run(..., timeout=)` по срабатыванию срока зовёт `process.kill()`
# → `signal.SIGKILL` → `AttributeError`. То есть падает не прогон, а ТРЕТИЙ
# ИСХОД — «не измерено, прогон не уложился в срок», ради которого срок и
# поставлен. Замер 19.09 (цикл #638): прогон зонда так и умер на 52-й строке
# из 100, журнал не записан. Контроль в обе стороны — в
# `spa_core/tests/test_vacuous_guard_probe.py`.
# Чинится ОДИН вход — этот. Тот же фитиль у соседей по каталогу (136 модулей
# с `__main__`, включая `copy_independence_probe.py`) НАЗВАН карточкой, а не
# починен прицепом: у переименования `signal.py` свой радиус и свой предмет.
import os  # noqa: E402
import sys  # noqa: E402

# Сравнение идёт по REALPATH, а не по abspath, и это тоже замер: с Python 3.11
# `sys.path[0]` есть РАЗЫМЕНОВАННЫЙ каталог скрипта, тогда как `abspath`
# символических ссылок не разыменовывает. На macOS, где `/tmp` есть ссылка на
# `/private/tmp`, версия с `abspath` не убирала каталог ВООБЩЕ — то есть
# «починка» молча не чинила. Поймано собственным контролем, а не рассуждением.
_HERE = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
sys.path[:] = [p for p in sys.path
               if os.path.realpath(p or os.getcwd()) != _HERE]
# ---------------------------------------------------------------------------

import argparse
import ast
import datetime as dt
import random
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import vacuous_guard_census as census  # noqa: E402
# Проводка опыта (среда прогона, одноразовое дерево, замена по координате AST,
# отдельный вопрос о наличии pytest) берётся у зонда ADR-419 ВВОЗОМ: второй
# копии этих правил в репозитории быть не должно (ADR-418).
from spa_core.monitoring import copy_independence_probe as base  # noqa: E402
from spa_core.monitoring import rule_second_copy_census as rules  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = census.PROBE_LEDGER
PRODUCER = "spa_core/monitoring/vacuous_guard_probe.py"

NotMeasured = base.NotMeasured
TREE_PREFIX = "spa_vacuous_probe_"

VERDICT_VACUOUS = census.VERDICT_VACUOUS
VERDICT_REFUSES = census.VERDICT_REFUSES
VERDICT_UNMEASURED = census.VERDICT_UNMEASURED

#: Срок одного прогона сторожа. Не уложился ⇒ «не измерено», а не «зелено».
RUN_TIMEOUT_S = 420

#: Зерно случайной выборки. Названо здесь, а не выбрано на бегу: замер обязан
#: воспроизводиться, иначе доля класса — не число, а впечатление.
SAMPLE_SEED = 20260919
DEFAULT_SAMPLE = 70

#: Итоговая строка pytest. Число при СЛОВЕ читается из неё же — разбор один
#: на все слова сводки (`passed`, `error`, `skipped`), потому что правило тут
#: одно, а второй его копии быть не должно (ADR-417/418).
_SUMMARY_LINE = re.compile(r"(in \d+(\.\d+)?s\b|no tests ran)")

#: Коды возврата pytest, при которых вердикта о вырожденности НЕТ.
#: 5 — «не собрано ни одного теста»: это не «краснеет», и зелёным тоже не
#: является. 2/3/4 — прерывание, внутренняя ошибка, ошибка употребления.
_NO_VERDICT_CODES = {2: "прогон прерван", 3: "внутренняя ошибка pytest",
                     4: "ошибка употребления pytest", 5: "не собрано ни одного теста"}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def run_guard(tree: Path, guard_rel: str) -> Tuple[int, str]:
    """Прогон сторожа с КОРОТКОЙ СВОДКОЙ упавших (`-rf`).

    Имена упавших тестов нужны переписи, чтобы отличить «покраснел
    потребитель перечня» от «покраснел сосед». Без них приписывание пришлось
    бы выдумывать.
    """
    return base._run(
        [sys.executable, "-m", "pytest", guard_rel, "-q", "--tb=no", "-rf",
         "-p", "no:randomly"],
        cwd=tree, timeout=RUN_TIMEOUT_S)


def failed_tests(output: str) -> Optional[List[str]]:
    """Имена упавших тестов из короткой сводки pytest; ``None`` — вход обрезан.

    Форма строки: ``FAILED path::test_name - сообщение``. Разбор намеренно
    буквальный: выдуманное имя хуже отсутствующего, поэтому всё, что не
    начинается с ``FAILED ``, не читается вовсе.

    **Третий исход обязателен, и он не косметика (ADR-427).** Перечень
    ``FAILED`` живёт ПЕРЕД итоговой сводкой, а проводка режет голову — значит
    у многословного сторожа часть имён не доходит. Укороченный перечень
    ошибается ровно в одну сторону: имя потребителя из него ВЫПАДАЕТ, и
    приписывание переворачивается с «покраснел потребитель» на «покраснел не
    тот тест», то есть выдумывает находку. Поэтому обрезанный вход отвечает
    ``None``, а не коротким списком.
    """
    if base.output_truncated(output):
        return None
    out: List[str] = []
    for line in (output or "").splitlines():
        line = line.strip()
        if not line.startswith("FAILED "):
            continue
        ident = line[len("FAILED "):].split(" - ", 1)[0].strip()
        if ident:
            out.append(ident)
    return out


def summary_count(output: str, word: str = "passed") -> Optional[int]:
    """Число при СЛОВЕ в итоговой сводке pytest; ``None`` — сводка не разобрана.

    Читается ИМЕННО итоговая строка (`… in 0.12s` либо `no tests ran`): слова
    «passed» в выводе хватает где угодно, а сводка одна. Сводка есть, а слова
    в ней нет ⇒ НОЛЬ (так выглядит целиком пропущенный файл); сводки нет
    вовсе ⇒ ``None``, и это третий исход, а не ноль.

    Слово — параметр, а не константа модуля: тот же разбор нужен соседнему
    зонду для слова `error` (сломанный сбор тестов), и вторая копия правила
    «где живёт сводка» была бы ровно тем дефектом, который меряет ADR-417.
    """
    summary = None
    for line in reversed((output or "").splitlines()):
        stripped = line.strip().strip("=").strip()
        if _SUMMARY_LINE.search(stripped):
            summary = stripped
            break
    if summary is None:
        return None
    match = re.search(rf"(\d+) {re.escape(word)}", summary)
    return int(match.group(1)) if match else 0


def passed_count(output: str) -> Optional[int]:
    """Сколько тестов ПРОШЛО по короткой сводке pytest; ``None`` — не разобрано.

    Отдельный вопрос от кода возврата, и он существен: файл, у которого все
    тесты ПРОПУЩЕНЫ, выходит нулём и на базе, и с опустошённым перечнем —
    зонд объявил бы его вырожденным, хотя он не выполнил ни одного утверждения
    ни разу. Это ошибка в ОПАСНУЮ сторону (выдуманная находка), и лечится она
    отдельным вопросом «а сторож вообще работал?».
    """
    return summary_count(output, "passed")


def select(rows: List[dict], *, sample: Optional[int] = DEFAULT_SAMPLE,
           seed: int = SAMPLE_SEED, everything: bool = False) -> List[dict]:
    """Кого зондировать: весь опасный подкласс + случайная выборка из остальных.

    Правило выборки НАЗВАНО и воспроизводимо (зерно — константа модуля).
    ``everything=True`` берёт всё население: так гоняется положительный
    контроль на маленьком контуре, где выборка была бы бессмысленна.
    """
    if everything or sample is None:
        return list(rows)
    reachable = [r for r in rows
                 if r.get("empty_without_edit") == census.EMPTY_REACHABLE]
    rest = [r for r in rows
            if r.get("empty_without_edit") != census.EMPTY_REACHABLE]
    rng = random.Random(seed)
    drawn = rng.sample(rest, min(sample, len(rest)))
    chosen = reachable + drawn
    chosen.sort(key=lambda r: r["key"])
    return chosen


def probe_row(tree: Path, row: dict, *,
              baselines: Dict[str, Tuple[int, str]]) -> dict:
    """Один опыт: до двух прогонов сторожа в ОДНОРАЗОВОМ дереве."""
    guard_rel, name = row["guard"], row["name"]
    entry = {
        "key": row["key"], "guard": guard_rel, "name": name,
        "value": row["value"], "guard_sha": row.get("guard_sha"),
        "verdict": VERDICT_UNMEASURED, "evidence": "", "failed_tests": [],
    }
    empty = row.get("empty_literal") or census.empty_literal(row["value"])
    if not empty:
        entry["evidence"] = f"пустого литерала того же рода не получить из `{row['value']}`"
        return entry
    entry["empty_literal"] = empty

    path = tree / guard_rel
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        entry["evidence"] = f"сторож не прочитан в одноразовом дереве: {exc}"
        return entry
    expected_sha = base.sha256(path)

    if guard_rel not in baselines:
        baselines[guard_rel] = run_guard(tree, guard_rel)
    base_code, base_out = baselines[guard_rel]
    entry["baseline_code"] = base_code
    entry["baseline_passed"] = passed_count(base_out)
    if base_code == 0 and entry["baseline_passed"] == 0:
        entry["evidence"] = ("сторож на базе не выполнил НИ ОДНОГО теста (всё "
                             "пропущено или ничего не собрано) — «зелёный с пустым "
                             "перечнем» тут ничего не значит")
        return entry
    if base_code < 0:
        # Срок — не краснота: «сторож НЕ зелен» о не уложившемся прогоне было бы
        # утверждением о стороже, которого никто не наблюдал.
        entry["evidence"] = (f"прогон сторожа на базе не уложился в "
                             f"{RUN_TIMEOUT_S} с — НЕ ИЗМЕРЕНО")
        return entry
    if base_code != 0:
        why = _NO_VERDICT_CODES.get(base_code, f"код {base_code}")
        entry["evidence"] = (f"сторож НЕ зелен на базе ({why}) — вырожденность мерить "
                             f"не от чего: {base_out.strip()[-200:]}")
        return entry

    try:
        mutated = base.replace_constant(original, name, f"{name} = {empty}")
    except NotMeasured as exc:
        entry["evidence"] = str(exc)
        return entry
    applied_src = rules.toplevel_constants(ast.parse(mutated)).get(name)
    if not census.is_empty_literal(applied_src):
        # Молча не применившаяся перемена дала бы «сторож зелен» и выглядела
        # бы вердиктом. Поэтому применение ПРОВЕРЯЕТСЯ разбором, а не
        # считается состоявшимся.
        entry["evidence"] = (f"опустошение `{name}` не применилось — после правки "
                             f"значение `{applied_src}`")
        return entry

    path.write_text(mutated, encoding="utf-8")
    try:
        code, out = run_guard(tree, guard_rel)
    finally:
        path.write_text(original, encoding="utf-8")
        if base.sha256(path) != expected_sha:
            raise NotMeasured(
                f"одноразовое дерево не восстановлено после опыта над {guard_rel} — "
                f"дальнейшие опыты недостоверны")
    entry["empty_code"] = code
    if code == 0:
        entry["verdict"] = VERDICT_VACUOUS
        entry["evidence"] = (
            f"сторож ЗЕЛЁН с пустым `{name}` ({row.get('size')} эл. → {empty}): "
            f"осмотрено ноль, и об этом не сказано ничего")
        return entry
    if code in _NO_VERDICT_CODES:
        entry["evidence"] = (f"{_NO_VERDICT_CODES[code]} на опустошённом перечне — "
                             f"это не вердикт о вырожденности")
        return entry
    if code < 0:
        entry["evidence"] = out.strip()[-200:] or f"прогон не уложился в {RUN_TIMEOUT_S} с"
        return entry
    entry["verdict"] = VERDICT_REFUSES
    names = failed_tests(out)
    entry["failed_tests"] = names
    entry["evidence"] = (
        f"сторож краснеет с пустым `{name}` (код {code}); упали "
        + ("— перечень имён ОБРЕЗАН проводкой, приписывать нечему"
           if names is None else f"{names or '— имена не разобраны'}"))
    return entry


def measure(root: Path, *, now: Optional[dt.datetime] = None,
            sample: Optional[int] = DEFAULT_SAMPLE, seed: int = SAMPLE_SEED,
            everything: bool = False,
            rows: Optional[List[dict]] = None) -> dict:
    root = Path(root).resolve()
    if rows is None:
        rows = census.measure(root)["rows"]
    chosen = select(rows, sample=sample, seed=seed, everything=everything)

    code, head = base._run(["git", "rev-parse", "HEAD"], cwd=root, timeout=120)
    if code != 0:
        raise NotMeasured(f"sha рабочего дерева не прочитан: {head.strip()}")
    head = head.strip().splitlines()[-1]

    # Префикс СВОЙ: умолчание соседа назвало бы его деревья, а наши — никогда
    # (найдено собственным тестом; ровно та же слепота, что и у измеряемого класса).
    stale = base.stale_disposable_trees(root, prefix=TREE_PREFIX)
    tmp = Path(tempfile.mkdtemp(prefix=TREE_PREFIX))
    entries: List[dict] = []
    try:
        tmp.rmdir()  # git worktree add требует НЕсуществующий путь
        code, out = base._run(["git", "worktree", "add", "--detach", str(tmp), head],
                              cwd=root, timeout=RUN_TIMEOUT_S)
        if code != 0:
            raise NotMeasured(f"одноразовое дерево не заведено: {out.strip()[-300:]}")
        available, version = base.pytest_available(tmp)
        if not available:
            raise NotMeasured(f"pytest недоступен в одноразовом дереве: {version}")

        baselines: Dict[str, Tuple[int, str]] = {}
        for number, row in enumerate(chosen, 1):
            # Ход опыта виден снаружи: прогон идёт минутами, и «зонд молчит»
            # не должно быть неотличимо от «зонд завис».
            print(f"[{number}/{len(chosen)}] {row['key']}", file=sys.stderr, flush=True)
            if base._dirty(root, row["guard"]):
                entries.append({
                    "key": row["key"], "guard": row["guard"], "name": row["name"],
                    "value": row["value"], "guard_sha": row.get("guard_sha"),
                    "verdict": VERDICT_UNMEASURED, "failed_tests": [],
                    "evidence": ("сторож изменён в рабочем дереве — одноразовое "
                                 "дерево несёт HEAD, то есть НЕ его")})
                continue
            entries.append(probe_row(tmp, row, baselines=baselines))
    finally:
        base._run(["git", "worktree", "remove", "--force", str(tmp)],
                  cwd=root, timeout=RUN_TIMEOUT_S)

    counts = {v: 0 for v in (VERDICT_VACUOUS, VERDICT_REFUSES, VERDICT_UNMEASURED)}
    for entry in entries:
        counts[entry.get("verdict", VERDICT_UNMEASURED)] += 1
    reachable_probed = len([
        e for e in entries
        if any(r["key"] == e["key"]
               and r.get("empty_without_edit") == census.EMPTY_REACHABLE
               for r in chosen)])
    return {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "MEASURED" if entries else "EMPTY",
        "question": "зелен ли сторож с ОПУСТОШЁННЫМ входом-перечнем",
        "tree_sha": head,
        "population": len(rows),
        "probed": len(entries),
        "sample_rule": (
            "всё население" if (everything or sample is None) else
            f"все строки с достижимой пустотой + случайная выборка {sample} из "
            f"остальных, зерно {seed}"),
        "sample_seed": seed,
        "reachable_probed": reachable_probed,
        "counts": counts,
        "stale_disposable_trees": stale,
        "entries": entries,
        "what_it_does_not_prove": [
            "что `refuses_empty` назвал виновным сам потребитель перечня — имена упавших тестов записаны, приписывает их перепись",
            "что строка, до которой зонд не дошёл, исправна: она остаётся `unmeasured` у переписи",
            "что дерево опыта есть рабочее дерево — одноразовое несёт HEAD, и сторож с незакоммиченной правкой НЕ измеряется",
            "что зелёный сторож на пустом перечне неверен по существу — он лишь не различает «нарушений нет» и «никуда не смотрели»",
        ],
    }


def report(doc: dict, *, max_rows: int = 25) -> List[str]:
    status = str(doc.get("status"))
    if status == "UNMEASURED":
        return [f"НЕ ИЗМЕРЕНО — {observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    counts = observed(doc, "counts", kind=dict) or {}
    out = [
        f"зонд вырожденности (заказ G44 п. 1): {status} · зондировано "
        f"{doc.get('probed')} из {doc.get('population')} · ВЫРОЖДЕН "
        f"{counts.get(VERDICT_VACUOUS)} · краснеет {counts.get(VERDICT_REFUSES)} · "
        f"НЕ ИЗМЕРЕНО {counts.get(VERDICT_UNMEASURED)}",
        f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}",
        f"[ВЫБОРКА] {doc.get('sample_rule')}",
        f"[ДЕРЕВО ОПЫТА] одноразовое, sha {str(doc.get('tree_sha'))[:12]} — рабочее "
        f"дерево на запись не открывалось ни разу"
        + (f"; ОСТАЛИСЬ ВИСЕТЬ от прошлых опытов: "
           f"{len(doc.get('stale_disposable_trees') or [])}"
           if doc.get("stale_disposable_trees") else ""),
    ]
    for entry in (doc.get("entries") or []):
        if entry.get("verdict") == VERDICT_VACUOUS:
            out.append(f"[{entry['verdict']}] {entry['guard']} · {entry['name']}: "
                       f"{entry.get('evidence')}")
    return out[:max_rows + 4]


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True, sample: Optional[int] = DEFAULT_SAMPLE,
        seed: int = SAMPLE_SEED, everything: bool = False,
        rows: Optional[List[dict]] = None,
        now: Optional[dt.datetime] = None) -> dict:
    root = Path(root)
    target = Path(dest) if dest is not None else root / ARTIFACT
    try:
        doc = measure(root, now=now, sample=sample, seed=seed,
                      everything=everything, rows=rows)
    except (NotMeasured, census.NotMeasured) as exc:
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED", "reason": str(exc), "entries": [],
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") != "UNMEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="зонд вырожденности сторожей на пустом входе (G44 п. 1)")
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    ap.add_argument("--seed", type=int, default=SAMPLE_SEED)
    ap.add_argument("--all", action="store_true",
                    help="зондировать ВСЁ население (долго; для малых контуров)")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    outcome = run(Path(args.root), dest=Path(args.out) if args.out else None,
                  write=not args.no_write, sample=args.sample, seed=args.seed,
                  everything=args.all)
    doc = outcome["doc"]
    for line in report(doc):
        print(line)
    if str(doc.get("status")) == "UNMEASURED":
        return 2
    # Инвариант #17 у САМОГО кода возврата: `doc.get("counts") or {}` делал
    # «поля нет» и «находок ноль» ОДНИМ И ТЕМ ЖЕ успехом — пусто давало
    # ложь, ложь давала код 0, и зовущему скрипту различить два исхода
    # было нечем. Три исхода (измерено · измерено и равно нулю · не
    # измерено) обязаны быть различимы там, где их читают, а читают их
    # по коду возврата. Найдено храповиком `test_absent_observation_ratchet`,
    # красневшим на чистом `origin/main` тремя тестами (цикл #642).
    counts = observed(doc, "counts", kind=dict)
    if counts is None:
        print("НЕ ИЗМЕРЕНО — в артефакте нет поля `counts`: "
              "отсутствие наблюдения кодом 0 не выдаётся")
        return 2
    return 1 if (counts.get(VERDICT_VACUOUS) or counts.get(VERDICT_UNMEASURED)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
