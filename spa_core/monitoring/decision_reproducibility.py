"""decision_reproducibility.py — один снимок, N процессов: тот же ли ответ?

Вопрос владельца, который никто не мерил
========================================
ТЗ «Portfolio CIO» ставит его дословно, и дважды:

* §38-блок задания: «**100 запусков на одном snapshot.** Expected: идентичный
  calculation output.»
* §49 «Acceptance criteria» → «**Determinism. Calculations reproducible.**»

До цикла #501 на этот вопрос не отвечал НИ ОДИН сторож — ни один даже не задавал
его. Соседи честно отвечают на свои и мимо:

| вопрос | кто отвечает | чего НЕ проверяет |
|---|---|---|
| два артефакта говорят одно? | ``adapter_feed_divergence`` | повторяем ли расчёт вообще |
| ранжируем по наблюдённому? | ``capital_evidence_coverage`` | то же |
| надо ли перекладывать? | ``rebalance_trigger`` (ADR-240) | то же |
| ключи не о одном ли пуле? | ``pool_identity_collision`` | то же |

«Воспроизводим» — не украшение. Невоспроизводимый расчёт означает, что объяснить
книгу нечем: снимок сохранён (``Auditability`` того же §49), а прогнать его заново
и получить ту же раскладку нельзя, то есть **разбор любого спорного дня
невозможен по построению**. И наоборот: пока расчёт воспроизводим, каждое
расхождение книги со снимком — настоящая находка, а не шум.

Что модуль НЕ делает
====================
Не двигает капитал, не гейтит исполнение, не трогает RiskPolicy и не решает, какая
из разошедшихся раскладок верна. **Только называет.** Прогон идёт в ПЕСОЧНИЦЕ —
копии снимка в ``tempfile``; живое ``data/`` не читается на запись и не меняется
(проверено ``test_run_does_not_touch_the_live_data_dir``).

Главное решение дизайна: ЧАСЫ ОБЪЯВЛЕНЫ ПОИМЁННО, а не угаданы
==============================================================
Наивная форма проверки — «сложить весь ответ в хеш и сравнить» — на живом коде
даёт ЛОЖНЫЙ отказ, и это замер, а не рассуждение. Цикл #501, 06.09, тюнер,
12 процессов с разными ``PYTHONHASHSEED``:

    хешей всего ответа: 12 из 12 РАЗНЫХ  → «не воспроизводимо», CRITICAL
    единственное различие: "timestamp": "…08:18:22.237634" vs "…08:18:22.306049"

То есть первая же честная попытка ответить на вопрос владельца ответила бы
**неверно, в сторону тревоги**, и следующая сессия начала бы чинить исправный
расчёт. После исключения одного поля: **100 запусков из 100 — один хеш.**

Соблазн лечить это регуляркой («выкинуть всё, что похоже на дату») — вторая
ловушка, ХУЖЕ первой, потому что она молчаливая. У аллокатора в ответе есть
``feed_coverage.as_of`` — карта «протокол → отметка НАБЛЮДЕНИЯ», то есть кусок
ВХОДА, а не часы производителя. Регулярка съела бы её вместе с настоящими
часами, и прогон на подменённом снимке читался бы как «тот же ответ». Поэтому:

* объявляется **точный список** имён (``ClockFields``) — только верхний уровень,
  только те, что производитель штампует собой;
* всё, что не объявлено и различается, — **находка**, без исключений;
* объявленное поле, которое НЕ различается ни в одном прогоне, тоже называется
  (``stale_clock_declaration``, INFO): либо производитель перестал штамповать
  время, либо объявление лишнее — в обоих случаях это молча растущее слепое
  пятно, и обнаружить его можно только тут.

Третий исход
============
``UNCHECKED`` — самостоятельный вердикт с НАЗВАННОЙ причиной, а не тихое ``OK``
и не скип: не собралась песочница, упал дочерний процесс, ``runs < 2`` (одного
прогона мало по построению — сравнивать не с чем). Класс «не измерено, выданное
за ответ» разобран в ``.claude/rules/deployment.md``; повторять его сторожем,
написанным ПРОТИВ него, было бы смешно.

Что этот ответ НЕ покрывает — находка цикла #732 (ADR-515)
==========================================================
Зелёный ответ выше есть утверждение ВСЕОБЩЕЕ: читатель сводки §49 понимает его
как «расчёты системы воспроизводимы». А спрашивается он у населения из ДВУХ
субъектов, набранного руками в ``SUBJECTS``, и сверить это население с
поверхностью, которая на самом деле решает книги, до #732 не пробовал никто.
Замер 29.09 на живом дереве (``decider_coverage``):

    спрошены о воспроизводимости : allocator.py · allocation_tuner.py
    current_positions.json  $101 447.25 ← allocator.py (спрошен)
                                        ← portfolio_rebalancer.py (НЕ спрошен)
    hy_paper_trading.json    $99 624.17 ← hy_cycle.py (НЕ спрошен)
    lp_paper_trading.json   $100 281.23 ← lp_cycle.py (НЕ спрошен)
    ─────────────────────────────────────────────────────────────────────
    капитал, чья решающая поверхность спрошена ЦЕЛИКОМ: $0.00 из $301 352.65

Ни одна книга не покрыта полностью, а двух третей капитала вопрос не касался
вовсе. Это НЕ «расчёты не воспроизводимы»: про ``hy_cycle`` и ``lp_cycle`` не
известно НИЧЕГО, и подавать их молчание зеленью значило бы вывернуть инвариант
#17 наизнанку. Поэтому вердикт КРИТЕРИЯ (``criterion_verdict``) отделён от
``overall`` и несёт замер покрытия рядом, а «не спрошен» — отдельное значение, а
не ноль.

Побочный замер, который стоит своей строки
==========================================
Оба субъекта заявляют себя read-only относительно капитала (докстринг тюнера:
«Строго read-only относительно капитала»). Заявление проверяется здесь же:
снимок песочницы сверяется до и после КАЖДОГО прогона. Замер 06.09 — оба
субъекта не тронули ни одного из 543 файлов. Запись под ``save=False`` была бы
находкой (``side_effect``, WARN): не движение капитала, но и не то, что написано
на упаковке.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPORT_REL = "data/decision_reproducibility.json"

#: Сколько процессов поднимать по умолчанию. Владелец просил 100; 100 полных
#: прогонов аллокатора — это ~200 с, то есть не то, что уместно вешать на
#: ежечасный мост. Умолчание 3 отвечает на вопрос «расходится ли вообще»
#: (расхождение от порядка обхода множеств проявляется на ЛЮБОЙ паре разных
#: ``PYTHONHASHSEED``, ему не нужны сотни), а дословный опыт владельца
#: доступен одной командой: ``--runs 100``. Число прогонов ПИШЕТСЯ в отчёт —
#: чтобы «3» никогда не читалось как «100».
DEFAULT_RUNS = 3

#: Порог сравнения долларов — ЧИСЛЕННЫЙ (цент), ничьим решением не является:
#: доли копейки берутся из округления сумм книг, а не из политики.
_COVERAGE_EPS_USD = 0.01


# ── чей мерой объявлен этот прибор ───────────────────────────────────────────

#: Критерий §49 ТЗ «Portfolio CIO», мерой которого объявлен ЭТОТ прибор.
#: Проба `card_acceptance` сверяет объявление ПО ЯКОРЮ («§49 Determinism»), а не
#: подстрокой: подстрока «Determinism» совпала бы с любой заметкой о
#: детерминизме (ADR-333).
CRITERION = ("§49 Determinism — «Calculations reproducible» (+ тело ТЗ §38: "
             "«100 запусков на одном snapshot → идентичный calculation output»)")

CRITERION_SATISFIED = "SATISFIED"
CRITERION_NOT_SATISFIED = "NOT_SATISFIED"
CRITERION_UNMEASURED = "UNMEASURED"

#: Ось находки: каким УТВЕРЖДЕНИЕМ она отвечает на вопрос критерия.
#:
#: `found`      — утверждение СУЩЕСТВОВАНИЯ: один снимок дал разные ответы.
#:                Неполнота материала рядом такую находку не отменяет.
#: `unobserved` — сравнение состоялось НЕ ПОЛНОСТЬЮ: поле объявлено часами и
#:                вычтено из сравнения, а часами на прогонах не оказалось —
#:                значит расхождение В ЭТОМ ПОЛЕ сторож увидеть не мог. Третий
#:                исход, а не зелень.
#: `context`    — факт об устройстве субъекта, а не ответ о воспроизводимости
#:                (запись под `save=False`: песочницы у прогонов РАЗНЫЕ, и на
#:                сравнение ответов такая запись не влияет).
AXIS_FOUND = "found"
AXIS_UNOBSERVED = "unobserved"
AXIS_CONTEXT = "context"

#: Вид находки → ось. Перечень ЗАКРЫТ: вид, которого здесь нет, обрывает вердикт
#: критерия третьим исходом с названным именем вида. Классифицировать новый вид
#: молча значило бы решить за автора, существование это или его отсутствие.
#:
#: Таблица живёт У ПРИБОРА, а не у пробы: виды порождает он, и вторая копия
#: таблицы рядом с пробой разъехалась бы с ними молча (урок цикла #730).
FINDING_AXIS = {
    "not_reproducible": AXIS_FOUND,
    "stale_clock_declaration": AXIS_UNOBSERVED,
    "side_effect": AXIS_CONTEXT,
}

#: Вердикт ОДНОГО субъекта, при котором вопрос считается ЗАДАННЫМ И ОТВЕЧЕННЫМ.
#: `CRITICAL` сюда входит намеренно: «расчёт не воспроизводим» — это ответ, а не
#: молчание. `UNCHECKED` не входит: вопрос задали, ответа нет.
ANSWERED_VERDICTS = ("OK", "CRITICAL")


class Subject:
    """Один воспроизводимый расчёт: как его позвать и чем он штампует время.

    ``clock_fields`` — ИМЕНА полей ВЕРХНЕГО уровня, значение которых производитель
    берёт с настенных часов. Список объявляется здесь и нигде больше; всё
    остальное сравнивается как есть. Про цену ошибки в обе стороны — докстринг
    модуля.
    """

    def __init__(self, key: str, title: str, clock_fields: tuple[str, ...], code: str):
        self.key = key
        self.title = title
        self.clock_fields = tuple(clock_fields)
        self.code = code


#: Что именно считаем воспроизводимым. Оба субъекта зовутся ровно так, как их
#: зовёт живой путь (``cycle_runner`` Step 2 / Step tuner), и оба получают
#: ЯВНЫЕ пути в песочницу — иначе они ушли бы в ``data/`` своего дерева
#: (класс, измеренный в `_adapter_class_gate`).
_ALLOCATOR_CODE = """
import json, os, sys
from dataclasses import asdict
SB = os.environ["SPA_DATA_DIR"]
from spa_core.allocator.allocator import StrategyAllocator
snap = json.load(open(os.path.join(SB, "adapter_orchestrator_status.json")))
# Снимок пришпилен: живой фид не опрашивается вовсе, иначе замер отвечал бы на
# вопрос «стоит ли рынок на месте», а не «повторяем ли расчёт».
provider = {}
for a in snap.get("adapters", []):
    p, v = a.get("protocol"), a.get("apy_pct")
    if p and v is not None:
        provider[p] = float(v) / 100.0
r = StrategyAllocator(
    status_path=os.path.join(SB, "adapter_orchestrator_status.json"),
    risk_scores_path=os.path.join(SB, "risk_scores.json"),
    adapter_status_path=os.path.join(SB, "adapter_status.json"),
    comparison_path=os.path.join(SB, "strategy_comparison.json"),
    live_apy_provider=provider,
).allocate()
sys.stdout.write(json.dumps(asdict(r), sort_keys=True, ensure_ascii=False, default=str))
"""

_TUNER_CODE = """
import json, os, sys
SB = os.environ["SPA_DATA_DIR"]
from spa_core.tuner.allocation_tuner import run_allocation_tuner
r = run_allocation_tuner(data_dir=SB, save=False)
sys.stdout.write(json.dumps(r.to_dict(), sort_keys=True, ensure_ascii=False, default=str))
"""

SUBJECTS: tuple[Subject, ...] = (
    Subject(
        key="allocator",
        title="StrategyAllocator.allocate() — раскладка, которую судит гейт",
        # `timestamp` — единственное, что аллокатор штампует собой
        # (`allocator.py`: `ts = datetime.now(timezone.utc).isoformat()`).
        # `feed_coverage.as_of` НЕ здесь и не будет: это отметка НАБЛЮДЕНИЯ из
        # снимка, то есть вход. См. докстринг модуля.
        clock_fields=("timestamp",),
        code=_ALLOCATOR_CODE,
    ),
    Subject(
        key="tuner",
        title="AllocationTuner.optimize() — оптимум, с которым сравнивают книгу",
        clock_fields=("timestamp",),
        code=_TUNER_CODE,
    ),
)

#: Что копируется в песочницу. Верхнеуровневые ``*.json`` каталога ``data/``:
#: 13 МБ, 543 файла, копия занимает доли секунды. Подкаталоги (история,
#: ``investment_os/``) не копируются — субъекты их не читают, а вес там основной.
_SNAPSHOT_GLOB = ".json"


def _iter_snapshot_files(data_dir: str):
    try:
        names = sorted(os.listdir(data_dir))
    except OSError:
        return
    for name in names:
        if not name.endswith(_SNAPSHOT_GLOB):
            continue
        path = os.path.join(data_dir, name)
        if os.path.isfile(path):
            yield name, path


def _build_sandbox(data_dir: str, dest: str) -> int:
    """Свежая копия снимка на ОДИН прогон. Возвращает число скопированных файлов.

    Копия, а не жёсткая ссылка: ссылка мгновенна, но ``open(..., "w")`` пишет
    СКВОЗЬ неё в живой файл. Экономить здесь значило бы поставить сторожа,
    способного испортить то, что он сторожит.
    """
    os.makedirs(dest, exist_ok=True)
    n = 0
    for name, path in _iter_snapshot_files(data_dir):
        shutil.copy2(path, os.path.join(dest, name))
        n += 1
    return n


def _digest(data_dir: str) -> dict[str, tuple[int, int]]:
    """``{имя: (размер, mtime_ns)}`` — дёшево и достаточно, чтобы увидеть запись."""
    out: dict[str, tuple[int, int]] = {}
    for name, path in _iter_snapshot_files(data_dir):
        try:
            st = os.stat(path)
        except OSError:                                      # pragma: no cover
            continue
        out[name] = (st.st_size, st.st_mtime_ns)
    return out


def _default_runner(subject: Subject, sandbox: str, root: str, seed: int,
                    timeout: float) -> tuple[int, str, str]:
    """Поднять ОТДЕЛЬНЫЙ процесс. Разные ``PYTHONHASHSEED`` — не придирка.

    Порядок обхода множеств в CPython зависит от соли хеша, и живой дневной
    цикл её НЕ пришпиливает (``PYTHONHASHSEED=0`` стои́т только в тестовой
    команде CLAUDE.md). Значит вопрос «тот же ли ответ завтра» — это вопрос
    «тот же ли ответ при другой соли», и задавать его надо явно.

    N2 (ADR-580 §C8 REVIEW_2, 2026-10-05): субпроцесс импортирует дерево через
    переставленный ``PYTHONPATH`` — ровно форма, которую
    `test_sandbox_wiring_ratchet.py` ловит у ВСЕХ соседей; эта функция была
    единственным явным allow-list исключением. Реальный риск, названный самим
    allow-list, был не в отсутствии маркера, а в том, что `SPA_LIVE_ROOT=root`
    совпал бы с прод-деревом на КАЖДОМ боевом прогоне (здесь `root` по
    умолчанию — живое дерево, как и у `python_reader_clock_doors` до F7).
    Решение — не отсутствие маркера, а то, НА ЧТО он указывает: `SPA_LIVE_ROOT`
    здесь ведёт в ту же одноразовую `sandbox`, что и `SPA_DATA_DIR`, а не в
    `root` — поэтому `live_root()`, если его позовёт код субъекта, вернёт
    песочницу, а не прод, и `SandboxLeakError` не поднимется НИКОГДА, будь
    `root` хоть прод-деревом, хоть одноразовой копией.
    """
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    env["SPA_DATA_DIR"] = sandbox
    env["SPA_SANDBOX"] = "1"
    env["SPA_LIVE_ROOT"] = sandbox
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", subject.code],
        cwd=root, env=env, capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def strip_clock(doc: dict, clock_fields) -> tuple[dict, dict]:
    """``(ответ без объявленных часов, снятые значения)``.

    Только верхний уровень — намеренно. Вложенное поле с тем же именем
    (``feed_coverage.as_of`` и его родня) остаётся под сравнением: объявление
    часов не имеет права превращаться в глушилку по имени.
    """
    stripped = {k: v for k, v in doc.items() if k not in clock_fields}
    removed = {k: doc[k] for k in clock_fields if k in doc}
    return stripped, removed


def _canon(doc) -> str:
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, default=str)


def _first_differences(docs: list[dict], limit: int = 6) -> list[str]:
    """Поимённые различия первого расходящегося прогона против нулевого.

    Голое «хеши разные» отправляет следующего читателя искать вручную; поле,
    названное вслух, — это уже адрес починки.
    """
    base = docs[0]
    out: list[str] = []
    for i, other in enumerate(docs[1:], start=1):
        for key in sorted(set(base) | set(other)):
            if _canon(base.get(key)) != _canon(other.get(key)):
                a, b = _canon(base.get(key))[:120], _canon(other.get(key))[:120]
                out.append(f"прогон 0 против {i}: поле `{key}`: {a} ≠ {b}")
                if len(out) >= limit:
                    return out
        if out:
            break
    return out


def _measure(subject: Subject, data_dir: str, root: str, runs: int,
             timeout: float, runner) -> dict:
    """Один субъект: N прогонов, сравнение, побочные записи. Никогда не бросает."""
    res: dict = {
        "key": subject.key,
        "title": subject.title,
        "runs_requested": runs,
        "runs_completed": 0,
        "clock_fields_declared": list(subject.clock_fields),
        "verdict": "UNCHECKED",
        "reason": None,
        "distinct_outputs": None,
        "differences": [],
        "clock_fields_varying": [],
        "side_effects": [],
        "snapshot_files": None,
    }
    if runs < 2:
        res["reason"] = (f"runs={runs}: сравнивать не с чем — воспроизводимость "
                         f"это утверждение о ДВУХ прогонах минимум")
        return res

    docs: list[dict] = []
    removed_per_run: list[dict] = []
    tmp = tempfile.mkdtemp(prefix="spa_repro_")
    try:
        for i in range(runs):
            sandbox = os.path.join(tmp, f"run{i}")
            try:
                n_files = _build_sandbox(data_dir, sandbox)
            except OSError as e:                             # pragma: no cover
                res["reason"] = f"песочница не собрана: {e}"
                return res
            if not n_files:
                res["reason"] = (f"снимок пуст: в `{data_dir}` нет ни одного "
                                 f"верхнеуровневого *.json — сравнивать нечего")
                return res
            res["snapshot_files"] = n_files
            before = _digest(sandbox)
            try:
                rc, out, err = runner(subject, sandbox, root, 1000 + i, timeout)
            except Exception as e:                # noqa: BLE001 — субпроцесс не смеет ронять сторожа
                res["reason"] = (f"прогон {i} не отработал: "
                                 f"{e.__class__.__name__}: {e}")
                return res
            if rc != 0:
                res["reason"] = (f"прогон {i} вышел с кодом {rc}: "
                                 f"{(err or '').strip()[-300:] or 'stderr пуст'}")
                return res
            try:
                doc = json.loads(out)
            except ValueError as e:
                res["reason"] = (f"прогон {i} не отдал разбираемый JSON ({e}); "
                                 f"первые 200 символов stdout: {out[:200]!r}")
                return res
            if not isinstance(doc, dict):
                res["reason"] = f"прогон {i} отдал {type(doc).__name__}, а не объект"
                return res
            after = _digest(sandbox)
            touched = sorted(k for k in set(before) | set(after)
                             if before.get(k) != after.get(k))
            if touched:
                # `.append`, а не `.extend`: строка — тоже итерируемое, и
                # `extend` разложил бы сообщение на символы. Поймано
                # `test_a_subject_writing_under_save_false_is_named` (102 WARN
                # вместо 1) — счётчик находок оказался длиной сообщения.
                res["side_effects"].append(
                    f"прогон {i} записал в песочницу: {', '.join(touched[:8])}"
                    + (f" … и ещё {len(touched) - 8}" if touched[8:] else "")
                )
            stripped, removed = strip_clock(doc, subject.clock_fields)
            docs.append(stripped)
            removed_per_run.append(removed)
            res["runs_completed"] = i + 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    hashes = {_canon(d) for d in docs}
    res["distinct_outputs"] = len(hashes)

    # Объявленные часы, которые НЕ дрожат, — тоже находка (см. докстринг).
    for name in subject.clock_fields:
        values = {_canon(r.get(name)) for r in removed_per_run}
        if len(values) > 1:
            res["clock_fields_varying"].append(name)

    if len(hashes) == 1:
        res["verdict"] = "OK"
    else:
        res["verdict"] = "CRITICAL"
        res["differences"] = _first_differences(docs)
    return res


# ── покрытие РЕШАЮЩЕЙ ПОВЕРХНОСТИ: у кого вопрос вообще спрашивали ───────────
#
# Находка цикла #732, из-за которой этот раздел и написан.
#
# Зелёный ответ прибора («один снимок — один ответ») есть утверждение ВСЕОБЩЕЕ:
# читатель сводки §49 понимает его как «расчёты системы воспроизводимы». А
# спрашивается он у населения из ДВУХ субъектов, набранного руками в `SUBJECTS`,
# и сверить это население с поверхностью, которая на самом деле решает книги, до
# #732 не пробовал никто. Замер 29.09 на живом дереве:
#
#     спрошены о воспроизводимости : allocator.py · allocation_tuner.py
#     книги и их решатели          : current_positions.json $101 447.25
#                                      ← allocator.py (спрошен)
#                                      ← portfolio_rebalancer.py (НЕ спрошен)
#                                    hy_paper_trading.json  $99 624.17
#                                      ← hy_cycle.py (НЕ спрошен)
#                                    lp_paper_trading.json  $100 281.23
#                                      ← lp_cycle.py (НЕ спрошен)
#     капитал, чья решающая поверхность спрошена ЦЕЛИКОМ: $0.00 из $301 352.65
#
# То есть ни одна книга не покрыта полностью, а двух третей капитала вопрос не
# касался вовсе. Это НЕ «расчёты не воспроизводимы»: про `hy_cycle` и `lp_cycle`
# не известно НИЧЕГО, и подавать их молчание зеленью — ровно инвариант #17
# наизнанку. Поэтому «не спрошен» здесь отдельное значение, а не ноль.
#
# Почему население не сверяется с САМИМ СОБОЙ. Прибор мог бы проверить, что в
# `SUBJECTS` два субъекта и оба измерены, — и ответ был бы тавтологичным: список
# сверялся бы со списком. Знаменатель обязан приходить ИЗВНЕ, от того, кто
# считает доллары, поэтому берётся уже существующая перепись решателей
# (`cio_decision_owner_census`, мера критерия §49 `Architecture`). Своей копии
# разбора «кто пишет книгу» здесь нет намеренно (§3 ТЗ: не дублировать).
#
# Числа у этого раздела и у критерия `Architecture` РАЗНЫЕ, и ни одно не
# поправка к другому: `Architecture` спрашивает «покрывает ли ОДНО решение весь
# капитал», этот раздел — «спрошен ли о воспроизводимости решатель каждой
# книги». Совпадает только прибор населения.

#: Перепись решателей книг: кто пишет какую книгу и сколько в ней капитала.
#: Имя объявлено СТРОКОЙ, а не зашито импортом в теле замера: контроль подменяет
#: перепись и убеждается, что знаменатель приходит ИЗВНЕ, а не из этого файла.
CENSUS_MODULE = "spa_core.monitoring.cio_decision_owner_census"

#: Как называется положение книги относительно вопроса. Перечень закрыт.
BOOK_ASKED = "asked"                 # каждый решатель книги спрошен
BOOK_PARTLY = "partly_asked"         # спрошен не каждый — назван поимённо
BOOK_UNASKED = "unasked"             # не спрошен ни один
BOOK_UNDETERMINED = "no_decider"     # решателя книги перепись не назвала вовсе


def _census_runner(census=None):
    """Перепись решателей — ВХОД, а не импорт в теле. Возврат — вызываемое."""
    if census is not None:
        return census
    import importlib
    return importlib.import_module(CENSUS_MODULE).run_census


def subject_modules(code: str, root: str) -> set[str]:
    """Модули РЕПОЗИТОРИЯ, которые субъект зовёт по имени.

    Выводится РАЗБОРОМ кода субъекта, а не объявлением рядом с ним: объявление
    «этот субъект спрашивает такой-то модуль» разъехалось бы с кодом молча, и
    покрытие стало бы функцией чьей-то записки. Разбор не удался ⇒ исключение,
    которое вызывающий обязан превратить в третий исход, а не в пустое множество:
    «субъект не зовёт ни одного модуля» и «код субъекта не разобран» чинятся
    разным.

    Считаются только имена ВЕРХНЕГО уровня вызова (`import` / `from … import`).
    Транзитивную цепочку прибор не обходит намеренно: `allocate()` внутри зовёт
    десятки модулей, и записать их все в «спрошенные» значило бы объявить
    спрошенным всё, к чему субъект прикоснулся, — ответ на вопрос «что
    исполнилось», а не «чей расчёт мы сравнивали».
    """
    import ast
    found: set[str] = set()
    tree = ast.parse(code)
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        for dotted in names:
            stem = dotted.replace(".", os.sep)
            if os.path.isfile(os.path.join(root, stem + ".py")):
                found.add(stem.replace(os.sep, "/") + ".py")
            elif os.path.isfile(os.path.join(root, stem, "__init__.py")):
                found.add(stem.replace(os.sep, "/") + "/__init__.py")
    return found


def decider_coverage(report: dict, *, root: str, data_dir: str,
                     subjects: tuple[Subject, ...] | None = None,
                     census=None, now: dt.datetime | None = None) -> dict:
    """Какой доли КАПИТАЛА решатель вообще спрошен о воспроизводимости.

    Знаменатель — доллары книг из живой переписи решателей; числитель — книги, у
    которых спрошен КАЖДЫЙ решатель. Каждый, а не «хоть один»: книгу
    ``current_positions.json`` пишут двое, и воспроизводимость одного из них не
    делает воспроизводимой запись книги (fail-CLOSED, `.claude/rules/risk-engine.md`).

    Три исхода разведены и ни один не подменяется нулём:

    * ``measured=False`` — перепись не разобрана, население субъектов спорит с
      артефактом, код субъекта не разобран. Про долю НЕ ИЗМЕРЕНО ничего;
    * книга без названного решателя — ``no_decider``, собственная сумма;
    * книга, чей решатель не спрошен, — ``unasked``: это не «не воспроизводим».
    """
    # Списки артефакта читаются ЧЕСТНО: отсутствие списка — не пустой список.
    # «Субъектов не измеряли» и «в артефакте нет раздела об измерениях» чинятся
    # разным, а второе, прочитанное как первое, дало бы покрытие «ноль» без
    # единого замера (инв. #17).
    rows_measured = observed(report, "measurements", kind=list)
    if rows_measured is None:
        return {"measured": False, "reason": (
            "в артефакте нет списка `measurements` — кого спрашивали, НЕ "
            "ИЗМЕРЕНО, и это не «не спрашивали никого»")}
    keys_in_report = [m.get("key") for m in rows_measured if isinstance(m, dict)]
    answered = {m.get("key") for m in rows_measured
                if isinstance(m, dict) and m.get("verdict") in ANSWERED_VERDICTS}
    pool = SUBJECTS if subjects is None else subjects
    by_key = {s.key: s for s in pool}

    # Население субъектов у артефакта и у прибора обязано совпадать. Разошлось —
    # третий исход: артефакт мог быть снят другим списком, и тогда «спрошен» тут
    # значит «спрошен КОГДА-ТО», а не «спрошен этим прибором».
    missing = sorted(k for k in keys_in_report if k not in by_key)
    extra = sorted(k for k in by_key if k not in keys_in_report)
    if missing or extra:
        return {"measured": False, "reason": (
            f"население субъектов артефакта и прибора РАСХОДИТСЯ (в артефакте нет "
            f"{extra or '—'}, у прибора нет {missing or '—'}) — «спрошен» отсюда "
            f"означало бы разное для разных субъектов")}

    asked_modules: set[str] = set()
    for key in sorted(answered):
        try:
            asked_modules |= subject_modules(by_key[key].code, root)
        except SyntaxError as exc:
            return {"measured": False, "reason": (
                f"код субъекта {key!r} не разобран ({exc}) — какой модуль он "
                f"спрашивает, НЕ ИЗМЕРЕНО")}

    try:
        census_report = _census_runner(census)(
            data_dir, repo_root=root, now=now)
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return {"measured": False, "reason": (
            f"перепись решателей не отработала: {type(exc).__name__}: {exc}")}
    if not isinstance(census_report, dict) or not census_report.get("measured"):
        why = (census_report or {}).get("reason") if isinstance(census_report, dict) \
            else f"перепись вернула {type(census_report).__name__}"
        return {"measured": False, "reason": (
            f"перепись решателей не измерила: {why} — знаменателя в долларах нет")}

    # «Перепись молчит о решателях» и «решателей ноль» — разное, и второе,
    # прочитанное как первое, объявило бы КАЖДУЮ книгу беспризорной.
    rows_coverage = observed(census_report, "coverage", kind=list)
    rows_books = observed(census_report, "books", kind=list)
    if rows_coverage is None or rows_books is None:
        missing = ", ".join(n for n, v in (("coverage", rows_coverage),
                                           ("books", rows_books)) if v is None)
        return {"measured": False, "reason": (
            f"перепись решателей не назвала раздел(ы) `{missing}` — это НЕ "
            f"«решателей/книг ноль», а «о них не сказано ничего»")}

    deciders: dict[str, list[str]] = {}
    for row in rows_coverage:
        named = observed(row, "books", kind=list)
        if named is None:
            return {"measured": False, "reason": (
                f"у строки переписи ({str(row)[:60]}) нет списка книг — какую "
                f"книгу решает этот модуль, НЕ ИЗМЕРЕНО")}
        for book in named:
            deciders.setdefault(book, []).append(str(row.get("producer")))

    books: list[dict] = []
    sums = {BOOK_ASKED: 0.0, BOOK_PARTLY: 0.0, BOOK_UNASKED: 0.0,
            BOOK_UNDETERMINED: 0.0}
    for book in rows_books:
        rel = observed(book, "artifact", kind=str)
        usd = observed(book, "capital_usd", kind=(int, float))
        if rel is None or usd is None:
            # Ноль сюда не подставляется НИКОГДА: непрочитанная книга,
            # посчитанная за $0, молча УМЕНЬШИЛА бы знаменатель, и доля
            # спрошенного капитала выросла бы от того, что книгу не прочли.
            return {"measured": False, "reason": (
                f"у книги переписи ({str(book)[:60]}) не прочитаны "
                f"`artifact`/`capital_usd` — знаменатель в долларах НЕ ИЗМЕРЕН")}
        usd = float(usd)
        producers = sorted(set(deciders.get(rel) or []))
        unasked = [p for p in producers if p not in asked_modules]
        if not producers:
            state = BOOK_UNDETERMINED
        elif not unasked:
            state = BOOK_ASKED
        elif len(unasked) == len(producers):
            state = BOOK_UNASKED
        else:
            state = BOOK_PARTLY
        sums[state] += usd
        books.append({"artifact": rel, "capital_usd": round(usd, 2),
                      "state": state, "producers": producers,
                      "unasked": unasked})

    total = round(sum(b["capital_usd"] for b in books), 2)
    # Субъект, не решающий ни одной книги, — не дефект, но и не покрытие: тюнер
    # считает оптимум, с которым книгу СРАВНИВАЮТ. Называется вслух, чтобы
    # «субъектов два» не читалось как «решателей спрошено два».
    all_deciders = {p for ps in deciders.values() for p in ps}
    idle = sorted(m for m in asked_modules if m not in all_deciders)
    return {
        "measured": True, "reason": None,
        "asked_modules": sorted(asked_modules),
        "answered_subjects": sorted(answered),
        "books": books,
        "total_capital_usd": total,
        "fully_asked_usd": round(sums[BOOK_ASKED], 2),
        "partly_asked_usd": round(sums[BOOK_PARTLY], 2),
        "unasked_usd": round(sums[BOOK_UNASKED], 2),
        "no_decider_usd": round(sums[BOOK_UNDETERMINED], 2),
        "asked_share": (round(sums[BOOK_ASKED] / total, 5) if total > 0 else None),
        "asked_modules_deciding_nothing": idle,
    }


def criterion_verdict(report: dict, *, root: str, data_dir: str,
                      subjects: tuple[Subject, ...] | None = None,
                      census=None, now: dt.datetime | None = None) -> dict:
    """Вердикт КРИТЕРИЯ §49 `Determinism` — и почему он НЕ есть ``overall``.

    ``overall`` у этого прибора — лестница ТЯЖЕСТИ для здоровья артефакта, и
    третий исход стои́т в ней ВЫШЕ ``CRITICAL`` намеренно. Для здоровья верно;
    для вердикта критерия тот же порядок был бы ложью в другую сторону: находка
    «один снимок дал разные ответы» есть утверждение СУЩЕСТВОВАНИЯ, и
    непрочитанный рядом субъект её не отменяет (урок #730, ADR-513).

    Порядок разрешения:

    1. вид находки не объявлен осью ⇒ третий исход с именем вида;
    2. находка оси ``found`` ⇒ ``NOT_SATISFIED`` независимо от неполноты;
    3. артефакт сам называет неизмеренных субъектов (``unchecked``) либо есть
       находка оси ``unobserved`` ⇒ третий исход: сравнение состоялось не
       полностью;
    4. покрытие решающей поверхности НЕ ИЗМЕРЕНО ⇒ третий исход с причиной;
    5. покрытие измерено и НЕ полно ⇒ ``NOT_SATISFIED``: воспроизводимость
       предъявлена не про тот капитал, о котором спрашивает критерий. Это
       измеренное красное, а не «нечем измерить», и прятать его за третьим
       исходом значило бы вернуть инв. #17 наизнанку;
    6. иначе ЗЕЛЁНЫЙ путь, и только на нём спрашивается законность: развёрнут ли
       вообще капитал. «Расчёт воспроизводим» про пустые книги — тишина мёртвого
       дерева, а не ответ о системе.
    """
    coverage = decider_coverage(report, root=root, data_dir=data_dir,
                                subjects=subjects, census=census, now=now)
    base = {"criterion": CRITERION, "coverage": coverage}

    rows_findings = observed(report, "findings", kind=list)
    if rows_findings is None:
        return dict(base, status=CRITERION_UNMEASURED, found=[], unobserved=[],
                    reason=("в артефакте нет списка `findings` — «находок нет» "
                            "и «о находках не сказано» здесь НЕРАЗЛИЧИМЫ, а "
                            "второе, прочитанное как первое, и есть зелень "
                            "из ничего"))

    found: list[str] = []
    unobserved: list[str] = []
    for finding in rows_findings:
        kind = str((finding or {}).get("kind"))
        axis = FINDING_AXIS.get(kind)
        if axis is None:
            return dict(base, status=CRITERION_UNMEASURED, found=[],
                        unobserved=[], reason=(
                            f"у находки {kind!r} не объявлена ось (`FINDING_AXIS`) — "
                            f"отнести её к существованию или к его отсутствию "
                            f"молча нельзя"))
        if axis == AXIS_FOUND:
            found.append(kind)
        elif axis == AXIS_UNOBSERVED:
            unobserved.append(kind)

    base = dict(base, found=sorted(set(found)), unobserved=sorted(set(unobserved)))

    if found:
        return dict(base, status=CRITERION_NOT_SATISFIED, reason=(
            "один снимок дал РАЗНЫЕ ответы: " + ", ".join(sorted(set(found)))
            + " — находка существования, и неполнота населения рядом её не отменяет"))
    rows_unchecked = observed(report, "unchecked", kind=list)
    if rows_unchecked is None:
        return dict(base, status=CRITERION_UNMEASURED, reason=(
            "в артефакте нет списка `unchecked` — были ли неизмеренные субъекты, "
            "сказать нечем"))
    unchecked = list(rows_unchecked)
    if unchecked or unobserved:
        why = list(unchecked) + [f"находка {k}" for k in sorted(set(unobserved))]
        return dict(base, status=CRITERION_UNMEASURED, reason=(
            "сравнение состоялось НЕ полностью: " + "; ".join(why)))
    if not coverage.get("measured"):
        return dict(base, status=CRITERION_UNMEASURED, reason=(
            f"кого именно спрашивали, сверить с решающей поверхностью не вышло: "
            f"{coverage.get('reason')}"))
    if not observed(report, "measurements", kind=list):
        return dict(base, status=CRITERION_UNMEASURED, reason=(
            "субъектов не измерено ни одного — «воспроизводимо» отсюда было бы "
            "утверждением о пустом населении"))
    total = observed(coverage, "total_capital_usd", kind=(int, float))
    if total is None:
        return dict(base, status=CRITERION_UNMEASURED, reason=(
            "перепись сказала «измерено», но суммы капитала в ней нет — "
            "знаменателя нет, и ноль вместо него не подставляется"))
    total = float(total)
    if total <= 0:
        return dict(base, status=CRITERION_UNMEASURED, reason=(
            "книги пусты (капитал $0) — «расчёт воспроизводим» отсюда было бы "
            "тишиной мёртвого дерева, а не ответом о системе"))
    if coverage["fully_asked_usd"] < total - _COVERAGE_EPS_USD:
        named = "; ".join(
            f"{b['artifact']} ${b['capital_usd']:,.2f} — не спрошен(ы) "
            f"{', '.join(b['unasked']) or 'решатель не назван'}"
            for b in coverage["books"] if b["state"] != BOOK_ASKED)
        return dict(base, status=CRITERION_NOT_SATISFIED, reason=(
            f"воспроизводимость предъявлена не про тот капитал: спрошена целиком "
            f"решающая поверхность ${coverage['fully_asked_usd']:,.2f} из "
            f"${total:,.2f}, у остального решатель о воспроизводимости НЕ "
            f"СПРОШЕН (это не «расчёт расходится» — про него не известно ничего): "
            f"{named}"))
    return dict(base, status=CRITERION_SATISFIED, reason=(
        f"каждый решатель каждой книги спрошен и ответил одним ответом на один "
        f"снимок: ${total:,.2f} капитала, субъектов {len(coverage['answered_subjects'])}"))


def run(root: str = REPO_ROOT, runs: int = DEFAULT_RUNS, write: bool = True,
        data_dir: str | None = None, now: dt.datetime | None = None,
        subjects: tuple[Subject, ...] | None = None,
        runner=None, timeout: float = 180.0, census=None) -> dict:
    """Замерить воспроизводимость и вернуть отчёт (он же пишется в ``REPORT_REL``)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    base = data_dir or os.path.join(root, "data")
    subjects = SUBJECTS if subjects is None else subjects
    runner = runner or _default_runner

    findings: list[dict] = []
    unchecked: list[str] = []
    measured: list[dict] = []

    for s in subjects:
        m = _measure(s, base, root, runs, timeout, runner)
        measured.append(m)
        if m["verdict"] == "UNCHECKED":
            unchecked.append(f"{s.key}: {m['reason']}")
            continue
        if m["verdict"] == "CRITICAL":
            findings.append({
                "severity": "CRITICAL",
                "subject": s.key,
                "kind": "not_reproducible",
                "message": (
                    f"{s.key}: {m['distinct_outputs']} РАЗНЫХ ответа на "
                    f"{m['runs_completed']} прогонах ОДНОГО снимка — расчёт не "
                    f"воспроизводим (§49 ТЗ CIO). "
                    + ("; ".join(m["differences"][:2]) if m["differences"] else "")
                ),
            })
        for name in m["clock_fields_declared"]:
            if name not in m["clock_fields_varying"]:
                findings.append({
                    "severity": "INFO",
                    "subject": s.key,
                    "kind": "stale_clock_declaration",
                    "message": (
                        f"{s.key}: поле `{name}` объявлено часами производителя, но "
                        f"на {m['runs_completed']} прогонах НЕ различалось — либо "
                        f"производитель перестал штамповать время, либо объявление "
                        f"лишнее. Лишнее объявление это слепое пятно: настоящее "
                        f"расхождение в этом поле сторож не увидит"
                    ),
                })
        for msg in m["side_effects"]:
            findings.append({
                "severity": "WARN",
                "subject": s.key,
                "kind": "side_effect",
                "message": (f"{s.key} заявлен read-only, но {msg} — под `save=False` "
                            f"запись не объявлена"),
            })

    counts = {"critical": 0, "warn": 0, "info": 0, "unchecked": len(unchecked)}
    for f in findings:
        counts[str(f["severity"]).lower()] = counts.get(str(f["severity"]).lower(), 0) + 1

    overall = "OK"
    if counts["unchecked"]:
        overall = "UNCHECKED"
    elif counts["critical"]:
        overall = "CRITICAL"
    elif counts["warn"]:
        overall = "WARN"
    elif counts["info"]:
        overall = "INFO"

    report = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": counts,
        "runs": runs,
        "subjects_measured": [m["key"] for m in measured],
        "measurements": measured,
        "findings": findings,
        "unchecked": unchecked,
        # Вердикт КРИТЕРИЯ §49, а НЕ `overall`: почему они разные — докстринг
        # `criterion_verdict`. Читается пробой `card_acceptance`
        # (`determinism_recomputation_is_reproducible`), и то же правило считает
        # его она же — по прочитанному артефакту, без повторного подъёма
        # процессов. Одно правило, одна копия.
        "criterion": criterion_verdict(
            {"measurements": measured, "findings": findings,
             "unchecked": unchecked},
            root=root, data_dir=base, subjects=subjects, census=census, now=now),
        "note": (
            "ADVISORY. Отвечает на §49 ТЗ CIO «Determinism: calculations "
            "reproducible» и на дословный опыт владельца «100 запусков на одном "
            "snapshot». Капитал по этому вердикту НЕ двигается; прогон идёт в "
            "песочнице (копия снимка), живое data/ не меняется."
        ),
    }
    if write:
        atomic_save(report, os.path.join(root, REPORT_REL))
    return report


def _main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                    help=f"сколько процессов поднять (по умолчанию {DEFAULT_RUNS}; "
                         f"дословный опыт владельца — 100)")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)

    rep = run(root=args.root, runs=args.runs, write=not args.no_save,
              data_dir=args.data_dir)
    print(f"decision_reproducibility: {rep['overall']} "
          f"(critical={rep['counts']['critical']} warn={rep['counts']['warn']} "
          f"info={rep['counts']['info']} unchecked={rep['counts']['unchecked']}) "
          f"· прогонов {rep['runs']} · субъектов {len(rep['subjects_measured'])}")
    for m in rep["measurements"]:
        print(f"   {m['key']}: {m['verdict']} · разных ответов "
              f"{m['distinct_outputs']} на {m['runs_completed']} прогонах")
        if m["reason"]:
            print(f"      причина: {m['reason']}")
        for d in m["differences"][:4]:
            print(f"      {d}")
    for u in rep["unchecked"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    cr = rep["criterion"]
    print(f"   [§49 Determinism] {cr['status']}: {cr['reason']}")
    cov = cr["coverage"]
    if cov.get("measured"):
        print(f"      решающая поверхность: спрошена целиком у "
              f"${cov['fully_asked_usd']:,.2f} из ${cov['total_capital_usd']:,.2f}; "
              f"частично ${cov['partly_asked_usd']:,.2f} · не спрошена "
              f"${cov['unasked_usd']:,.2f} · решатель не назван "
              f"${cov['no_decider_usd']:,.2f}")
        for b in cov["books"]:
            print(f"      [КНИГА] {b['artifact']} ${b['capital_usd']:,.2f} — "
                  f"{b['state']}; решатели {', '.join(b['producers']) or '—'}"
                  + (f"; НЕ спрошены {', '.join(b['unasked'])}" if b["unasked"] else ""))
    else:
        print(f"      [НЕ ИЗМЕРЕНО] покрытие решающей поверхности: {cov.get('reason')}")
    return {"OK": 0, "INFO": 0, "WARN": 1, "CRITICAL": 1, "UNCHECKED": 2}[rep["overall"]]


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(_main())
