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
    """
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    env["SPA_DATA_DIR"] = sandbox
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


def run(root: str = REPO_ROOT, runs: int = DEFAULT_RUNS, write: bool = True,
        data_dir: str | None = None, now: dt.datetime | None = None,
        subjects: tuple[Subject, ...] | None = None,
        runner=None, timeout: float = 180.0) -> dict:
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
    return {"OK": 0, "INFO": 0, "WARN": 1, "CRITICAL": 1, "UNCHECKED": 2}[rep["overall"]]


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(_main())
