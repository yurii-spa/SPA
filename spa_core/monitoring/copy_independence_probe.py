"""Зонд копий: есть ли у правила ЗУБЫ и поймают ли расхождение двух копий.

Заказ **G43, п. 2** приказа владельца «Portfolio CIO» (хвост ADR-418).

## Вопрос

Перепись `rule_second_copy_census` находит пары «сторож × исполнитель», у
которых совпали имя и КОНСТАНТНОЕ значение, а двери от сторожа к исполнителю
нет. Часть таких пар — одно правило в двух копиях, часть — совпадение двух
независимых решений (`SEED = 42` у теста и у `monte_carlo`). Прежде прибор
честно говорил «предмет НЕ доказан» и оставлял пару в остатке. Заказ
потребовал снять гипотезу «совпадение» ЗАМЕРОМ.

## Способ заказа проверен ЗАМЕРОМ и опровергнут им же

Заказ назвал способ дословно: *«подменить значение у ИСПОЛНИТЕЛЯ и посмотреть,
меняется ли вердикт сторожа. Не меняется ⇒ копии независимы»*. Прибор этот
замер делает (поле `executor_mutation_changed`) — а вывод из него неверен, и
неверен в обе стороны:

* пара попадает в находку ИМЕННО ТОГДА, когда сторож не достаёт исполнителя
  ни одной из четырёх дверей. У такого сторожа вердикт не может зависеть от
  значения у исполнителя ПО ПОСТРОЕНИЮ — «не изменился» здесь истинно почти
  тождественно и не различает ничего;
* «не изменился» есть описание ВРЕДА, а не невинности: молчаливое расхождение
  копий — это ровно тот случай, когда правка одной стороны не краснит другую.
  Объявить его независимостью значило бы снять с учёта самые опасные пары.

**Самопроверка заказа на его же образце.** Пара `tests/test_preflight.py` ×
`scripts/preflight_day1.py` приведена в п. 1 того же заказа как ОБРАЗЕЦ
общего предмета — и по правилу п. 2 получила бы ярлык «независимы». Один
заказ даёт об одной паре два противоположных вердикта; разрешать это надо
замером, а не выбором, и замер выше разрешает.

## Что зонд мерит на самом деле — ДВА разных вопроса, и их нельзя смешивать

Вопрос «одно ли это правило» есть вопрос о СМЫСЛЕ двух чисел, и ни один
динамический опыт его не решает: значения у пары равны по определению
находки, поэтому подстановка одного вместо другого ничего не меняет ни в
одну сторону. Зонд отвечает на два соседних вопроса, которые решаются:

1. **Есть ли у правила на стороне сторожа ЗУБЫ?** Подменить константу У
   СТОРОЖА и прогнать его. Вердикт не изменился ⇒ `verdict_insensitive`.

   **Это НЕ «константа не читается», и поправка стои́т замера.** Первая
   редакция называла исход так — и сняла бы с учёта пять пар; перечитывание
   сторожей показало, что ВСЕ ПЯТЬ константу читают (`random.Random(SEED)`,
   `for d in SCAN_DIRS`), а нечувствителен их вердикт. Вопрос «читается ли
   имя» статический, и отвечает на него перепись (`constant_is_loaded`); зонд
   мерит чувствительность и только её. С учёта `verdict_insensitive` пару НЕ
   снимает.
2. **Покраснеет ли сторож, если правят исполнителя?** Подменить значение у
   ИСПОЛНИТЕЛЯ (способ, названный заказом дословно). Не покраснел ⇒
   `drift_silent`: копии могут разойтись молча — это ВРЕД, и пара остаётся на
   учёте. Покраснел ⇒ `drift_loud`: расхождение будет поймано.

Обе оси меряются ВСЕГДА, и это тоже поправка: первая редакция обрывала опыт
на нечувствительном стороже и оставляла ось вреда неизмеренной у половины
населения — молчание выглядело бы ответом.

Прогонов до пяти: база · до двух перемен у сторожа · до двух у исполнителя.
Перемен ДВЕ и они противоположны (`mutate_values`): одна слабая перемена
оставила бы порог `>= MIN_ADAPTERS` зелёным и объявила живое правило
беззубым. Каждый прогон — в одноразовом дереве, после каждого файл
возвращается и сверяется по sha.

## Три исхода различимы (инв. #17)

`verdict_insensitive` · `drift_silent` · `drift_loud` — вердикты. Всё остальное есть
**`unmeasured` с названной причиной**, и вердиктом не притворяется: нет
pytest (спрошен ОТДЕЛЬНЫМ вопросом, потому что рабочий прогон выходит
ненулевым, когда нашёл падение); сторож красен на базе; перемены того же
рода не получить; подмена не применилась; координата не единственна; сторона
изменена в рабочем дереве и одноразовое дерево несёт не её; прогон не
уложился в срок.

**Предмет владельца зонд не трогает.** Пара, чьё значение равно порогу
RiskPolicy (`owner_subject`), пропускается с причиной: граница ADR-285
проходит по предмету, и «в одноразовом дереве же» её не отменяет.

## Почему одноразовое дерево, а не правка на месте

Мутационная батарея, убитая на полпути, оставляет дерево изменённым — этот
класс в репозитории уже случался. Здесь правка невозможна по построению:
зонд заводит отдельное дерево (`git worktree add --detach`) на sha рабочего
и снимает его в конце. Рабочее дерево не открывается на запись ни разу.

Обратная сторона названа: одноразовое дерево несёт HEAD, а не рабочую копию.
Сторона с незакоммиченной правкой поэтому НЕ измеряется (`unmeasured`), а не
измеряется «почти та же».
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import rule_second_copy_census as census  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = census.PROBE_LEDGER
PRODUCER = "spa_core/monitoring/copy_independence_probe.py"

VERDICT_INSENSITIVE = census.PROBE_INSENSITIVE       # "verdict_insensitive"
VERDICT_DRIFT_SILENT = census.PROBE_DRIFT_SILENT    # "drift_silent"
VERDICT_DRIFT_LOUD = census.PROBE_DRIFT_LOUD        # "drift_loud"
VERDICT_UNMEASURED = "unmeasured"
_VERDICTS = (VERDICT_INSENSITIVE, VERDICT_DRIFT_SILENT, VERDICT_DRIFT_LOUD,
             VERDICT_UNMEASURED)

#: Срок одного прогона сторожа. Не уложился ⇒ «не измерено», а не «не изменился».
RUN_TIMEOUT_S = 600

#: Префикс одноразовых деревьев. По нему же опознаётся дерево, оставшееся от
#: убитого опыта.
TREE_PREFIX = "spa_copy_probe_"


class NotMeasured(RuntimeError):
    """Зонд не смог поставить опыт — третий исход, а не пустой вердикт."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def mutate_values(text: str) -> List[str]:
    """ДВЕ противоположные сильные перемены значения — или пустой список.

    Одной перемены мало, и это не осторожность, а разбор направления ошибки.
    Сторож вида ``assert len(x) >= MIN_ADAPTERS`` на перемене ``10 → 11``
    остался бы ЗЕЛЁНЫМ (адаптеров 36), и зонд объявил бы константу
    непрочитанной — то есть снял бы с учёта живую пару. Ошибка в опасную
    сторону лечится второй переменой в ПРОТИВОПОЛОЖНУЮ сторону: константа
    считается прочитанной, если вердикт сдвинула ХОТЬ ОДНА.

    Обратная ошибка (сильная перемена краснит сторожа по причине, не связанной
    с правилом) оставляет пару НА учёте — она безопасна и названа вслух.
    """
    try:
        value = ast.literal_eval(text)
    except Exception:  # noqa: BLE001 — значение не литерал
        return []
    if isinstance(value, bool):
        return [repr(not value)]
    if isinstance(value, (int, float)):
        big = type(value)(value + 1_000_000)
        small = type(value)(value - 1_000_000)
        return [repr(big), repr(small)]
    if isinstance(value, str):
        return [repr(value + "_PROBE_MUTANT"), repr("")]
    if isinstance(value, (tuple, list, set, frozenset)):
        empty = {tuple: "()", list: "[]", set: "set()", frozenset: "frozenset()"}
        grown = list(value) + ["_PROBE_MUTANT"]
        if isinstance(value, tuple):
            bigger = repr(tuple(grown))
        elif isinstance(value, list):
            bigger = repr(grown)
        elif isinstance(value, frozenset):
            bigger = f"frozenset({set(grown)!r})"
        else:
            bigger = repr(set(grown))
        return [empty[type(value)], bigger]
    if isinstance(value, dict):
        return ["{}", repr({**value, "_PROBE_MUTANT": 1})]
    if value is None:
        return [repr("_PROBE_MUTANT")]
    return []


def _toplevel_assign(tree: ast.Module, name: str) -> List[ast.stmt]:
    """ВСЕ присваивания имени на верхнем уровне. Их обязано быть ровно одно."""
    out: List[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                out.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == name and node.value is not None:
            out.append(node)
    return out


def replace_constant(source: str, name: str, replacement: str) -> str:
    """Заменить ПРИСВАИВАНИЕ имени целиком, по координате AST.

    Замена идёт по координате узла, а не поиском текста: имя встречается в
    файле многократно (в утверждениях, в сообщениях), и текстовая замена
    попала бы не туда. Координата обязана быть ЕДИНСТВЕННОЙ — иначе неясно,
    какое из присваиваний есть правило, и опыт не ставится.
    """
    tree = ast.parse(source)
    nodes = _toplevel_assign(tree, name)
    if len(nodes) != 1:
        raise NotMeasured(
            f"присваиваний `{name}` на верхнем уровне {len(nodes)}, а не одно — "
            f"координата не единственна, опыт не ставится")
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = (node.end_lineno or node.lineno)
    head = "".join(lines[:start])
    tail = "".join(lines[end:])
    return head + replacement.rstrip("\n") + "\n" + tail


def _run(cmd: List[str], *, cwd: Path, timeout: int = RUN_TIMEOUT_S) -> Tuple[int, str]:
    env = dict(os.environ, SPA_ENV="ci", PYTHONHASHSEED="0", SPA_PROBE="1")
    env.pop("PYTEST_CURRENT_TEST", None)
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1, f"прогон не уложился в {timeout} с"
    return proc.returncode, (proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:]


def pytest_available(tree: Path) -> Tuple[bool, str]:
    """ОТДЕЛЬНЫЙ вопрос «инструмент есть?».

    Спрашивать его кодом возврата рабочего прогона нельзя: рабочий pytest
    выходит ненулевым именно тогда, когда что-то нашёл, и «инструмента нет»
    стало бы неотличимо от «тест упал».
    """
    code, out = _run([sys.executable, "-m", "pytest", "--version"], cwd=tree, timeout=120)
    return code == 0, out.strip().splitlines()[-1] if out.strip() else ""


def run_guard(tree: Path, guard_rel: str) -> Tuple[int, str]:
    return _run([sys.executable, "-m", "pytest", guard_rel, "-q", "-p", "no:randomly"],
                cwd=tree)


def probe_pair(tree: Path, row: dict, *, baselines: Dict[str, Tuple[int, str]]) -> dict:
    """Один опыт: до пяти прогонов сторожа в ОДНОРАЗОВОМ дереве.

    ``baselines`` — общий кэш базовых прогонов: один сторож встречается в
    нескольких парах, и гонять его базу заново значило бы платить временем за
    тот же ответ.
    """
    guard_rel, exec_rel = row["guard"], row["executor"]
    name, value = row["name"], row["value"]
    entry = {
        "key": census.probe_key(row),
        "guard": guard_rel, "executor": exec_rel, "name": name, "value": value,
        "guard_sha": sha256(tree / guard_rel),
        "executor_sha": sha256(tree / exec_rel),
        "verdict": VERDICT_UNMEASURED,
        "evidence": "",
    }

    if row.get("remedy") == census.REMEDY_OWNER:
        entry["evidence"] = ("предмет владельца (величина равна порогу RiskPolicy) — "
                             "зонд его не трогает, граница ADR-285 по ПРЕДМЕТУ")
        return entry

    guard_path, exec_path = tree / guard_rel, tree / exec_rel
    try:
        guard_src = guard_path.read_text(encoding="utf-8")
        exec_src = exec_path.read_text(encoding="utf-8")
    except OSError as exc:
        entry["evidence"] = f"сторона не прочитана в одноразовом дереве: {exc}"
        return entry

    mutants = mutate_values(value)
    if not mutants:
        entry["evidence"] = f"другого значения того же рода не получить из `{value}`"
        return entry
    entry["mutants"] = mutants

    if guard_rel not in baselines:
        baselines[guard_rel] = run_guard(tree, guard_rel)
    base_code, base_out = baselines[guard_rel]
    entry["baseline_code"] = base_code
    if base_code != 0:
        entry["evidence"] = (f"сторож НЕ зелен на базе (код {base_code}) — изменение "
                             f"вердикта мерить не от чего: {base_out.strip()[-300:]}")
        return entry

    # ОБЕ оси меряются всегда. Первая редакция обрывала опыт на
    # нечувствительном стороже — и тем оставляла ось вреда неизмеренной у
    # половины населения, выдавая молчание за ответ.
    try:
        changed_guard, guard_codes = _side_changes_verdict(
            guard_path, guard_src, name, value, mutants, tree, guard_rel,
            entry["guard_sha"], base_code)
        changed_exec, exec_codes = _side_changes_verdict(
            exec_path, exec_src, name, value, mutants, tree, guard_rel,
            entry["executor_sha"], base_code)
    except NotMeasured as exc:
        entry["evidence"] = str(exc)
        return entry

    entry["guard_mutation_codes"] = guard_codes
    entry["guard_mutation_changed"] = changed_guard
    entry["executor_mutation_codes"] = exec_codes
    entry["executor_mutation_changed"] = changed_exec

    if not changed_guard:
        entry["verdict"] = VERDICT_INSENSITIVE
        entry["evidence"] = (
            f"НИ ОДНА из {len(mutants)} противоположных перемен СОБСТВЕННОЙ "
            f"константы сторожа не изменила его вердикт (коды {guard_codes} "
            f"против базы {base_code}) ⇒ у правила на стороне сторожа НЕТ ЗУБОВ. "
            f"Это НЕ «константа не читается»: читается ли она — вопрос "
            f"статический, и отвечает на него перепись")
        return entry
    if changed_exec:
        entry["verdict"] = VERDICT_DRIFT_LOUD
        entry["evidence"] = (
            f"вердикт сторожа чувствителен к своей константе И краснеет от правки "
            f"исполнителя (коды {exec_codes} против базы {base_code}) ⇒ "
            f"расхождение копий будет поймано")
        return entry
    entry["verdict"] = VERDICT_DRIFT_SILENT
    entry["evidence"] = (
        f"вердикт сторожа чувствителен к своей константе, но НИ ОДНА перемена у "
        f"ИСПОЛНИТЕЛЯ его не меняет (коды {exec_codes} = база {base_code}) ⇒ копии "
        f"способны разойтись МОЛЧА. Это вред, а не независимость")
    return entry


def _side_changes_verdict(path: Path, original: str, name: str, value: str,
                          mutants: List[str], tree: Path, guard_rel: str,
                          expected_sha: Optional[str],
                          base_code: int) -> Tuple[bool, List[int]]:
    """Сдвинула ли ХОТЬ ОДНА перемена вердикт сторожа. Возврат сверяется по sha.

    Перебор прекращается на первой сдвинувшей: ответ уже получен, а лишний
    прогон стои́т минуты. «Ни одна не сдвинула» требует ВСЕХ перемен — иначе
    вывод опирался бы на непоставленный опыт.
    """
    codes: List[int] = []
    for mutant in mutants:
        mutated = replace_constant(original, name, f"{name} = {mutant}")
        applied = census.toplevel_constants(ast.parse(mutated)).get(name)
        # Молча не применившаяся перемена даёт «вердикт не изменился» и
        # выглядит как ответ — поэтому применение проверяется, а не считается.
        if applied is None or applied == value:
            raise NotMeasured(
                f"перемена `{mutant}` у {path.name} не применилась "
                f"(значение осталось `{value}`)")
        path.write_text(mutated, encoding="utf-8")
        try:
            code, _ = run_guard(tree, guard_rel)
        finally:
            path.write_text(original, encoding="utf-8")
            if sha256(path) != expected_sha:
                raise NotMeasured(
                    f"одноразовое дерево не восстановлено после опыта над "
                    f"{path} — дальнейшие опыты недостоверны")
        codes.append(code)
        if code != base_code:
            return True, codes
    return False, codes


def stale_disposable_trees(root: Path, *, prefix: str = TREE_PREFIX) -> List[str]:
    """Одноразовые деревья прошлых опытов, оставшиеся висеть.

    Снимать их прибор НЕ вправе: с тем же префиксом может идти соседний живой
    опыт, и «прибрался» означало бы «убил чужой замер». Поэтому он называет —
    ровно как сторож, который не чинит.

    ``prefix`` — СВОЙ префикс зовущего зонда, а не общий: соседний зонд
    (`vacuous_guard_probe`, ADR-420) заводит деревья под своим именем, и
    умолчание здесь назвало бы ему чужие деревья, а свои — никогда. Вторую
    копию этой функции заводить нельзя (ADR-417/418), поэтому у неё параметр.
    """
    code, out = _run(["git", "worktree", "list", "--porcelain"], cwd=root, timeout=120)
    if code != 0:
        return []
    return [line.split(" ", 1)[1].strip() for line in out.splitlines()
            if line.startswith("worktree ") and prefix in line]


def _dirty(root: Path, rel: str) -> bool:
    code, out = _run(["git", "status", "--porcelain", "--", rel], cwd=root, timeout=120)
    return code != 0 or bool(out.strip())


def measure(root: Path, *, now: Optional[dt.datetime] = None,
            limit: Optional[int] = None,
            rows: Optional[List[dict]] = None) -> dict:
    """Журнал зонда по всем находкам переписи.

    Одноразовое дерево заводится ЗДЕСЬ (`git worktree add --detach` на sha
    рабочего) и снимается в `finally`. Отключаемого пути нет намеренно: ветка
    «взять чужое дерево», которой не пользуется ни один тест, была бы
    непроверенной дверью к правке на месте.
    """
    root = Path(root).resolve()
    if rows is None:
        doc = census.measure(root)
        rows = [r for r in (doc.get("rows") or [])
                if r["verdict"] in census.FINDING_CLASSES]
    if limit is not None:
        rows = rows[:limit]

    code, head = _run(["git", "rev-parse", "HEAD"], cwd=root, timeout=120)
    if code != 0:
        raise NotMeasured(f"sha рабочего дерева не прочитан: {head.strip()}")
    head = head.strip().splitlines()[-1]

    # Опыт, убитый на полпути, не оставляет РАБОЧЕЕ дерево изменённым — но
    # одноразовое остаётся висеть (замер 19.09: так и случилось дважды).
    # Прибор его не снимает молча и не снимает вовсе: чужое живое дерево с тем
    # же префиксом снять значило бы убить соседний опыт. Он его НАЗЫВАЕТ.
    stale = stale_disposable_trees(root)

    tmp = Path(tempfile.mkdtemp(prefix=TREE_PREFIX))
    entries: List[dict] = []
    try:
        tmp.rmdir()         # git worktree add требует НЕсуществующий путь
        code, out = _run(["git", "worktree", "add", "--detach", str(tmp), head],
                         cwd=root, timeout=RUN_TIMEOUT_S)
        if code != 0:
            raise NotMeasured(f"одноразовое дерево не заведено: {out.strip()[-300:]}")
        available, version = pytest_available(tmp)
        if not available:
            raise NotMeasured(f"pytest недоступен в одноразовом дереве: {version}")

        baselines: Dict[str, Tuple[int, str]] = {}
        for row in rows:
            dirty = [s for s in ("guard", "executor") if _dirty(root, row[s])]
            if dirty:
                entries.append({
                    "key": census.probe_key(row), "guard": row["guard"],
                    "executor": row["executor"], "name": row["name"],
                    "value": row["value"],
                    "guard_sha": sha256(root / row["guard"]),
                    "executor_sha": sha256(root / row["executor"]),
                    "verdict": VERDICT_UNMEASURED,
                    "evidence": (
                        f"сторона {', '.join(dirty)} изменена в рабочем дереве — "
                        f"одноразовое дерево несёт HEAD, то есть НЕ её")})
                continue
            entries.append(probe_pair(tmp, row, baselines=baselines))
    finally:
        _run(["git", "worktree", "remove", "--force", str(tmp)],
             cwd=root, timeout=RUN_TIMEOUT_S)

    counts = {v: 0 for v in _VERDICTS}
    for entry in entries:
        counts[entry.get("verdict", VERDICT_UNMEASURED)] += 1
    changed = len([e for e in entries if e.get("executor_mutation_changed")])
    measured = len([e for e in entries if e.get("executor_mutation_changed") is not None])
    return {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "MEASURED" if entries else "EMPTY",
        "question": "есть ли у правила ЗУБЫ на стороне сторожа и поймают ли расхождение копий",
        "tree_sha": head,
        "pairs": len(entries),
        "counts": counts,
        "stale_disposable_trees": stale,
        # Замер, названный ЗАКАЗОМ дословно, — и его вырожденность видна числом.
        "executor_mutation_changed_verdict": changed,
        "executor_mutation_measured": measured,
        "entries": entries,
        "what_it_does_not_prove": [
            "что `drift_silent` означает независимость копий — он означает ровно обратное: расхождение НЕ будет поймано",
            "что `drift_loud` называет виновную сторону — он говорит лишь, что краснота придёт",
            "что `verdict_insensitive` означает «константа не читается» — она читается у всех пяти пар замера 19.09 (`random.Random(SEED)`); измерена ЧУВСТВИТЕЛЬНОСТЬ ВЕРДИКТА, а не факт чтения",
            "что пара, не измеренная зондом, независима — `unmeasured` есть третий исход и на учёт пару ВОЗВРАЩАЕТ",
            "что дерево опыта есть рабочее дерево — одноразовое несёт HEAD, и сторона с незакоммиченной правкой НЕ измеряется",
            "что смысл двух совпавших чисел один или разный — этого не решает ни один динамический опыт, и зонд такого вердикта не выносит",
        ],
    }


def report(doc: dict) -> List[str]:
    status = str(doc.get("status"))
    if status == "UNMEASURED":
        return [f"НЕ ИЗМЕРЕНО — {observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    counts = observed(doc, "counts", kind=dict) or {}
    out = [
        f"зонд копий (заказ G43 п. 2): {status} · пар {doc.get('pairs')} · "
        f"вердикт нечувствителен {counts.get(VERDICT_INSENSITIVE)} · снос врозь МОЛЧА "
        f"{counts.get(VERDICT_DRIFT_SILENT)} · снос врозь с краснотой "
        f"{counts.get(VERDICT_DRIFT_LOUD)} · НЕ ИЗМЕРЕНО "
        f"{counts.get(VERDICT_UNMEASURED)}",
        f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}",
        f"[ДЕРЕВО ОПЫТА] одноразовое, sha {str(doc.get('tree_sha'))[:12]} — рабочее "
        f"дерево на запись не открывалось ни разу"
        + (f"; ОСТАЛИСЬ ВИСЕТЬ от прошлых опытов: "
           f"{len(doc.get('stale_disposable_trees') or [])} (снимать их прибор не "
           f"вправе — рядом может идти чужой опыт)"
           if doc.get("stale_disposable_trees") else ""),
        f"[СПОСОБ ЗАКАЗА] подмена у исполнителя сдвинула вердикт у "
        f"{doc.get('executor_mutation_changed_verdict')} пар из "
        f"{doc.get('executor_mutation_measured')} измеренных — «не сдвинула» здесь "
        f"почти тождественно истинно (сторож не достаёт исполнителя по построению) "
        f"и описывает ВРЕД, а не независимость",
    ]
    for entry in doc.get("entries") or []:
        out.append(f"[{entry.get('verdict')}] {entry.get('name')} = {entry.get('value')} "
                   f"— сторож {entry.get('guard')} против исполнителя "
                   f"{entry.get('executor')}: {entry.get('evidence')}")
    out.append("НЕ ДОКЛАДЫВАЕТ: происхождение совпавших чисел; виновную сторону у "
               "`coupled`; независимость пары, которую не измерил")
    return out


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True,
        limit: Optional[int] = None,
        now: Optional[dt.datetime] = None) -> dict:
    root = Path(root)
    # Журнал ложится РЯДОМ С КОДОМ (см. census.PROBE_LEDGER), а не в `data/`:
    # он есть замер исходников дерева и годен ровно для sha своих сторон.
    target = Path(dest) if dest is not None else root / ARTIFACT
    try:
        doc = measure(root, now=now, limit=limit)
    except (NotMeasured, census.NotMeasured) as exc:
        # Отказ ПЕРЕПИСИ — тоже «не измерено», а не трассировка: третий исход
        # обязан быть исходом на любой глубине, иначе он им не является.
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "reason": str(exc),
            "entries": [],
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") != "UNMEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="зонд независимости: совпадение или одно правило в двух копиях (G43 п. 2)")
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    outcome = run(Path(args.root), dest=Path(args.out) if args.out else None,
                  write=not args.no_write, limit=args.limit)
    doc = outcome["doc"]
    for line in report(doc):
        print(line)
    if str(doc.get("status")) == "UNMEASURED":
        return 2
    counts = doc.get("counts") or {}
    # Код 1 — «есть что назвать», а не авария: не измеренная пара и пара со
    # сносом врозь молча обе требуют строки в цикле.
    return 1 if (counts.get(VERDICT_UNMEASURED)
                 or counts.get(VERDICT_DRIFT_SILENT)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
