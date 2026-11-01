#!/usr/bin/env python3
# LLM_FORBIDDEN
"""Контрольный прогон CI по шардам: план · свод · сравнение (`.github/workflows/ci-control.yml`).

**Почему он нужен (замер 2026-10-16).** Из последних 30 прогонов `SPA CI` (`ci.yml`) ни один
не дошёл до вердикта: 28 пушевых СНЯТЫ следующим пушем (`concurrency: spa-ci-${ref}-push`,
`cancel-in-progress`), единственный расписанный (38873867566, джоба 116884127339, `9b7e6442f`)
шёл 08:28→14:28Z и был убит 6-часовым пределом джобы Actions на `[ 94%]` шага
`spa_core/tests/` — 97 знаков `F`, ни одного имени (`-q`). В `SPA Tests` (`test.yml`) тот же
шаг в расписанном прогоне 38877303508 снят `timeout-minutes: 240` (09:09→13:09Z). То есть
полный набор в ОДНУ джобу не помещается по построению, а пушевые прогоны вытесняют друг
друга раньше, чем успевают дойти. Порог джобы поднимать некуда (360 мин — потолок GitHub),
а `--timeout` на тест — не тот орган (инв. #16).

**Что делает этот модуль.** Режет ТО ЖЕ население, что предписанная команда `CLAUDE.md`,
на шарды по ФАЙЛУ (детерминированно, по измеренному весу), а затем сводит результаты шардов
в один вердикт с ТРЕМЯ исходами — и третий исход здесь главный:

* ``GREEN`` — каждый шард отчитался, союз шардов == населению, каждый тест получил исход,
  упавших нет;
* ``RED`` — всё измерено, и упавшие НАЗВАНЫ поимённо (с шардом);
* ``INCOMPLETE`` — хоть один шард отсутствует / снят / отменён / без записи, или союз ≠
  населению, или у какого-то теста нет исхода. Никогда не зелёный (инв. #17).

Подкоманды::

    plan      --collected F --weights W --shards N --budget-min M --sha S --out-dir D
    aggregate --manifest-dir D --shards-dir S [--needs-result R] --out-json J --out-md M
    compare   BASE.json HEAD.json [--out-json J]
    weights   [--stream F]... [--junit F]... [--root R] --out W
    run-shard --files F --exit-file E [--max-resumes K] -- <аргументы pytest>

**Сравнение с прошлым прогоном (как классифицировать упавшие).** Отчёты живут АРТЕФАКТАМИ
(`ci-control-report`, 90 дней), в git не кладутся. Чтобы сказать про упавший тест «новый»
или «старый», нужен отчёт ДРУГОЙ версии в ТОМ ЖЕ окружении (тот же воркфлоу, python
major.minor, корни, SPA_ENV, PYTHONHASHSEED — иначе `compare` честно отвечает NOT
COMPARABLE)::

    # id артефактов двух прогонов: GET /repos/yurii-spa/SPA/actions/runs/<run>/artifacts
    #   (имя ci-control-report); скачать: GET …/actions/artifacts/<id>/zip → report.json
    python3 scripts/ci_control.py compare base/report.json head/report.json --out-json cmp.json

Код возврата: 0 — новых нет и всё измерено; 1 — есть NEW; 2 — несравнимы ИЛИ часть упавших
головы в базе НЕ ИЗМЕРЕНА (`not_obtained`), ИЛИ голова сама INCOMPLETE. Первый прогон
(39003158532, f0f1ce803, INCOMPLETE) — база для следующего расписанного (каждые 6 ч);
упавшие тесты базы, которых в голове нет среди упавших и которые там измерены, идут в
`fixed`.

**Доигрывание шарда (`run-shard`).** Внутренняя ошибка pytest (`INTERNALERROR`, код 3) или
гибель процесса на одном тесте не имеет права стоить остатка шарда (прогон 39003158532:
шард 2, 4320 тестов без исхода). `run-shard` гоняет pytest; при аварийном конце берёт
собранное шардом (`collected.jsonl`) минус получившие исход в потоковой записи, тест,
исполнявшийся в момент аварии, записывает в ту же запись как `error: pytest internal error`
(названо, не выброшено и НЕ перезапускается), а остаток доигрывает новой сессией pytest на
тех же файлах с `SPA_PYTEST_RESUME_ONLY` (сборка та же, исполняются только перечисленные),
дописывая в ту же запись. Попыток доигрывания — не больше `--max-resumes` (3); кто так и не
получил исхода — INCOMPLETE, как раньше. Порог на тест не меняется.

Только stdlib (инв. #4). Источник записей шардов — `spa_core.ci.pytest_stream_record`
(строка на событие, сброс после каждой) и `spa_core.ci.pytest_collect_manifest`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPORT_SCHEMA = "spa-ci-control-report/1"
MANIFEST_SCHEMA = "spa-ci-control-manifest/1"
WEIGHTS_SCHEMA = "spa-ci-control-weights/1"

GREEN, RED, INCOMPLETE = "GREEN", "RED", "INCOMPLETE"
EXIT = {GREEN: 0, RED: 1, INCOMPLETE: 2}

PASSED, SKIPPED, FAILED, ERROR = "passed", "skipped", "failed", "error"
_RANK = {PASSED: 1, SKIPPED: 2, FAILED: 3, ERROR: 4}

#: Результаты `needs.<job>.result`, при которых шард НЕ дал ответа. `failure` сюда не входит:
#: шард с упавшими тестами — красный, а не отсутствующий.
_UNANSWERED_RESULTS = ("cancelled", "skipped")

SHARD_DIR_PREFIX = "ctl-shard-"

#: Файлы, которые шард обязан оставить. Имя — часть контракта с воркфлоу.
STREAM_FILE = "stream.jsonl"
COLLECTED_FILE = "collected.jsonl"
EXIT_FILE = "exit.json"
SHARD_FILE = "shard.json"
#: junit-запись шарда. Пишется В КОНЦЕ сессии; доигранная попытка (`run_shard`) кладёт
#: свою под `junit-resume-<k>.xml`, поэтому читать надо ОБРАЗЕЦ, а не одно имя: прочти
#: только `junit.xml` — и у доигранного шарда причины падений исчезли бы молча.
JUNIT_FILE = "junit.xml"
JUNIT_GLOB = "junit*.xml"

#: Ось причин красного (ADR-891). Схема объявлена ОТДЕЛЬНО от схемы отчёта: читатель,
#: встретивший отчёт БЕЗ этого блока, обязан сказать «НЕ ИЗМЕРЕНО: отчёт старше оси»,
#: а не показать ноль (инв. #17).
CAUSE_SCHEMA = "spa-ci-control-cause-axis/1"


def _load_plugin_reader():
    """`read_manifest` из плагина — по ПУТИ, чтобы скрипт работал без `spa_core` в sys.path."""
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "spa_core" / "ci" / "pytest_collect_manifest.py"
    spec = importlib.util.spec_from_file_location("_ctl_collect_manifest", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.read_manifest


read_manifest = _load_plugin_reader()


def file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


# ── потоковая запись шарда ───────────────────────────────────────────────────

def load_stream(path: str) -> dict:
    """Разобрать запись `pytest_stream_record`. Нет файла ⇒ ``present=False`` (не «ноль»)."""
    out = {"present": False, "session": False, "end": None, "outcomes": {}, "msgs": {},
           "unfinished": [], "t0": None, "t1": None, "file_wall": {}, "bad_lines": 0}
    if not os.path.exists(path):
        return out
    out["present"] = True
    started: list[tuple[float, str]] = []
    finished: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                out["bad_lines"] += 1          # оборванная последняя строка — не повод терять остальные
                continue
            kind = ev.get("e")
            t = ev.get("t")
            if isinstance(t, (int, float)):
                out["t0"] = t if out["t0"] is None else min(out["t0"], t)
                out["t1"] = t if out["t1"] is None else max(out["t1"], t)
            if kind == "session":
                out["session"] = True
                out["end"] = None      # конец обязан принадлежать ПОСЛЕДНЕЙ сессии (доигрывание)
            elif kind == "end":
                out["end"] = ev
            elif kind == "start":
                started.append((float(t or 0.0), ev.get("n", "")))
            elif kind in ("ok", "skip", "fail"):
                n = ev.get("n", "")
                if kind == "ok":
                    outcome = PASSED
                elif kind == "skip":
                    outcome = SKIPPED
                else:
                    outcome = FAILED if ev.get("w") == "call" else ERROR
                    if ev.get("msg"):
                        out["msgs"].setdefault(n, ev.get("msg"))
                prev = out["outcomes"].get(n)
                if prev is None or _RANK[outcome] > _RANK[prev]:
                    out["outcomes"][n] = outcome
                finished.add(n)
    out["unfinished"] = [n for _, n in started if n not in finished]
    # Стена на файл: от старта теста до старта следующего. Последний тест шарда
    # меряется до конца сессии, если конец есть; иначе — не меряется (нет конца).
    wall: dict[str, float] = {}
    end_t = out["end"].get("t") if out["end"] else None
    for i, (t, n) in enumerate(started):
        nxt = started[i + 1][0] if i + 1 < len(started) else end_t
        if nxt is None:
            continue
        wall[file_of(n)] = wall.get(file_of(n), 0.0) + max(0.0, float(nxt) - t)
    out["file_wall"] = {k: round(v, 3) for k, v in wall.items()}
    return out


# ── ось причин красного (ADR-891) ────────────────────────────────────────────

class CauseDoorAbsent(Exception):
    """Дверь опознания причины не ввезена. Это НЕ «причин нет» и НЕ «причин ноль»."""


def _load_cause_door():
    """`failure_cause_census` по ПУТИ — та же причина, что у :func:`_load_plugin_reader`.

    Свод зовут из джобы, где `spa_core` в `sys.path` не объявлен; ввоз по имени пакета
    ответил бы «причин нет» там, где дверь просто не нашлась.
    """
    import importlib.util
    path = (Path(__file__).resolve().parents[1] / "spa_core" / "monitoring"
            / "failure_cause_census.py")
    if not path.is_file():
        raise CauseDoorAbsent(f"двери опознания причины нет по пути {path}")
    spec = importlib.util.spec_from_file_location("_ctl_failure_cause", path)
    if spec is None or spec.loader is None:
        raise CauseDoorAbsent(f"{path} не загружается: загрузчика нет")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:                                        # noqa: BLE001
        raise CauseDoorAbsent(f"{path} не ввезён "
                              f"({type(exc).__name__}: {exc})") from exc
    for need in ("census_from_path", "fork_of", "junit_name", "READ_OK",
                 "PHASES", "CAUSE_CLASSES", "SITE_CLASSES"):
        if not hasattr(module, need):
            raise CauseDoorAbsent(f"{path} не несёт `{need}` — это не та дверь")
    return module


def _attempt_of(path: Path) -> tuple:
    """Номер попытки по имени junit-записи: `junit.xml` — нулевая, `junit-resume-<k>` — k-я."""
    stem = path.stem
    if stem == "junit":
        return (0, stem)
    tail = stem.rsplit("-", 1)[-1]
    return ((int(tail) if tail.isdigit() else 10 ** 6), stem)


def _cause_of(failure) -> dict:
    """Причина ОДНОГО падения в виде, который уедет в отчёт. Копии правила нет."""
    return {"kind": failure.kind, "skeleton": failure.skeleton,
            "coarse": failure.coarse, "site": failure.site,
            "class": failure.cause_class, "phase": failure.phase,
            "site_class": failure.site_class}


def cause_axis(plan: list[dict], shards_dir: Path, failures: list[dict],
               *, door=None, top: int = 12) -> dict:
    """Ось причин, которая НЕ ВПРАВЕ уронить отчёт прогона (ADR-891).

    Ось ДОБАВОЧНАЯ: вердикт, население и имена упавших от неё не зависят. Поэтому
    любая её немочь — третий исход С НАЗВАННОЙ ПРИЧИНОЙ, а не исключение наружу: свод
    зовут один раз в конце прогона, и павший на оси свод отдал бы ПУСТОЙ отчёт, то есть
    потерял бы и те имена, что уже измерены. Это дороже отсутствия причин.

    Найдено СВОИМ контролем до доставки (`test_ci_cause_axis.py`): дверь, переданная
    входом и павшая ПОЗЖЕ ввоза, проходила мимо охраны ввоза и улетала из `aggregate`.

    Строки падений на третьем исходе остаются БЕЗ ключа `cause`: «причину не опознали»
    (`cause = None`) и «причину не мерили» — разные состояния, и записать второе первым
    значило бы соврать ровно тем способом, против которого ось и заведена (инв. #17).
    """
    try:
        return _cause_axis_measured(plan, shards_dir, failures, door=door, top=top)
    except CauseDoorAbsent as exc:
        why = str(exc)
    except Exception as exc:                                        # noqa: BLE001
        why = (f"ось причин не снята ({type(exc).__name__}: {exc}) — вердикт, население "
               f"и имена упавших этим НЕ отменяются")
    for row in failures:
        row.pop("cause", None)
    return {"schema": CAUSE_SCHEMA, "status": "unmeasured", "why": why,
            "population": len(failures)}


def _cause_axis_measured(plan: list[dict], shards_dir: Path, failures: list[dict],
                         *, door=None, top: int = 12) -> dict:
    """ПРИЧИНА каждого падения — ось, которой у отчёта свода не было (ADR-891).

    **Зачем (заказ G887 п. 3 карточки приказа «Portfolio CIO»).** До 01.11 строка
    `failures` отчёта несла `nodeid`, исход, шард и `msg` — а `msg` есть ПЕРВАЯ строка
    потоковой записи, то есть `файл:строка: in <тест>`. Это МЕСТО, а не причина.
    Замер на прогоне 41280181541 (`126a2ec2a`, 79 падений в 50 файлах): причина
    восстановима у **79 из 79** — она лежала в `junit.xml` ТОГО ЖЕ артефакта шарда,
    который свод уже скачивает и читает ради потоковой записи, и выбрасывалась.
    Вред не косметический: «79 красных» читается как «79 поломок», и по этому числу
    решают, брать ли набор в работу. Тот же замер даёт вилку дефектов **54…78**, то
    есть множитель 1,01…1,46× — слабый, но крупнейшее семейство несёт **10** падений,
    и без причины его не видно ВОВСЕ: десять лежат в пяти РАЗНЫХ файлах, а перепись
    по файлам показывает пять одиночек и одну тройку.

    **Опознаёт ЕДИНСТВЕННАЯ дверь** — `spa_core/monitoring/failure_cause_census.py`
    (ADR-675). Своя копия разбора здесь означала бы два ответа на один вопрос и
    расхождение молча (класс ADR-220); поэтому и перевод `nodeid` → имя junit берётся
    у неё же (`junit_name`), а не пишется рядом.

    **ТРИ ИСХОДА РАЗЛИЧИМЫ (инв. #17).** `measured` — ось снята (в том числе снята и
    population равна нулю: зелёный прогон опознавать нечего) · `unmeasured` — дверь не
    ввезена ИЛИ junit-записи нет ни у одного шарда, и у исхода НАЗВАНА причина.
    «Причину не опознали» НИКОГДА не записывается нулём: падение без причины ложится
    в `unattributed` ПОИМЕННО, а шард без записи — в `shards_without_record`.

    **Запись шарда может не дойти, и это свойство записи, а не причины.** junit пишется
    В КОНЦЕ сессии (ADR-474): снятый шард своей записи не оставляет. Поэтому читается
    ОБРАЗЕЦ ``junit*.xml`` — доигранная попытка кладёт свою запись отдельным файлом, —
    а отсутствие записи у шарда называется своим именем и не уменьшает население.
    """
    door = door or _load_cause_door()

    read_ok: list[int] = []
    absent: list[int] = []
    without_record: list[int] = []
    unreadable: list[list] = []
    found: dict[str, object] = {}
    deaths: list[dict] = []
    victims: dict[str, int] = {}
    records = 0
    agreed = disagreed = stream_absent = 0
    for sh in plan:
        i = sh.get("shard")
        d = shards_dir / f"{SHARD_DIR_PREFIX}{i}"
        if not d.is_dir():
            absent.append(i)
            continue
        paths = sorted(d.glob(JUNIT_GLOB), key=_attempt_of)
        if not paths:
            without_record.append(i)
            continue
        stream = d / STREAM_FILE
        shard_read = False
        for path in paths:
            records += 1
            try:
                census = door.census_from_path(
                    path, stream=stream if stream.exists() else None)
            except Exception as exc:                                # noqa: BLE001
                unreadable.append([i, path.name, f"{type(exc).__name__}: {exc}"])
                continue
            if census.read != door.READ_OK:
                unreadable.append([i, path.name, census.reason])
                continue
            shard_read = True
            agreed += census.stream_agreed
            disagreed += census.stream_disagreed
            stream_absent += census.stream_absent_for
            # ОБМОРОК СЕССИИ (ADR-892) — РОД, а не провал теста. У события две
            # стороны, и обе лежат в этом же артефакте: junit несёт сам обморок
            # (`pytest::internal`), потоковая запись — ЖЕРТВУ (поле `w`). Берём обе
            # ЗДЕСЬ, а не у `exit.json`: его читает `aggregate`, и второй читатель
            # того же файла разошёлся бы с первым молча (класс ADR-220).
            death = census.session_record
            if death is not None:
                deaths.append({"shard": i, "kind": death.kind,
                               "skeleton": death.skeleton, "message": death.message})
            for name in census.session_victims:
                victims.setdefault(name, i)
            for failure in census.failures:
                if failure.is_session_death:
                    continue

                # ПОСЛЕДНЯЯ попытка главнее: доигранная сессия (`run_shard`) гоняет
                # тест заново, и её причина — та, что стои́т. Порядок задаётся
                # `_attempt_of`, а не алфавитом: по алфавиту `junit-resume-1.xml`
                # оказывается РАНЬШЕ `junit.xml` (дефис меньше точки), и правило
                # «кто первый» случайно совпало бы с нужным, не будучи им.
                found[failure.nodeid] = failure
        if shard_read:
            read_ok.append(i)
    if not read_ok and failures:
        return {"schema": CAUSE_SCHEMA, "status": "unmeasured",
                "why": (f"ни один шард плана не отдал читаемой junit-записи "
                        f"(шардов {len(plan)}: без каталога {len(absent)}, без записи "
                        f"{len(without_record)}, нечитаемых записей {len(unreadable)}) — "
                        f"причины {len(failures)} падений НЕ ИЗМЕРЕНЫ, это не ноль"),
                "population": len(failures),
                "shards_read": [], "shards_absent": absent,
                "shards_without_record": without_record, "shards_unreadable": unreadable}

    attributed: list = []
    unattributed: list[str] = []
    victim_rows: list[str] = []
    for row in failures:
        nodeid = row.get("nodeid")
        jname = door.junit_name(nodeid) if isinstance(nodeid, str) else None
        failure = found.get(jname) if jname is not None else None
        if failure is not None:
            row["cause"] = _cause_of(failure)
            attributed.append(failure)
            continue
        if jname is not None and jname in victims:
            # ЖЕРТВА ОБМОРОКА (ADR-892): junit-записи у неё нет не потому, что
            # запись неполна, а потому, что сессия умерла, НЕ ДОПИСАВ её. Причина
            # названа — и это причина ДРУГОГО РОДА: обморок инструмента, а не
            # дефект теста. Поэтому строка причину несёт, а в `attributed` и в
            # вилку дефектов жертва НЕ идёт.
            shard = victims[jname]
            death = next((d for d in deaths if d.get("shard") == shard),
                         deaths[0] if deaths else {})
            row["cause"] = {"session_death": True, "shard": shard,
                            "kind": death.get("kind"),
                            "skeleton": death.get("skeleton")}
            victim_rows.append(nodeid)
            continue
        row["cause"] = None
        unattributed.append(nodeid if isinstance(nodeid, str) else repr(nodeid))

    declared = {door.junit_name(r.get("nodeid")) for r in failures
                if isinstance(r.get("nodeid"), str)}
    # Запись обморока в `found` не попадает ВОВСЕ (выше), поэтому `record_only`
    # отвечает на свой вопрос — «чьё падение junit числит, а отчёт нет». До ADR-892
    # сюда падал `pytest::internal`, и читатель говорил «две записи одного прогона
    # СПОРЯТ»: утверждение ЛОЖНОЕ — записи СОГЛАСНЫ, просто одна из них не про тест.
    record_only = sorted(set(found) - declared)

    from collections import Counter
    kinds = Counter((f.kind or "«тип не назван»") for f in attributed)
    classes = Counter(f.cause_class for f in attributed)
    phases = Counter(f.phase for f in attributed)
    sites = Counter(f.site_class for f in attributed)
    fork = door.fork_of(attributed)
    # Тождество учёта считается по ОБЪЯВЛЕННОМУ перечню имён, а не суммой счётчика:
    # сумма значений счётчика равна населению ВСЕГДА, то есть неопровержима, и род вне
    # перечня исчезал бы из печатаемой строки молча (урок ADR-675).
    n = len(attributed)
    identities = {
        "phases": sum(phases.get(k, 0) for k in door.PHASES) == n,
        "cause_classes": sum(classes.get(k, 0) for k in door.CAUSE_CLASSES) == n,
        "site_classes": sum(sites.get(k, 0) for k in door.SITE_CLASSES) == n,
        # Перечень РОДОВ исхода атрибуции (ADR-892): опознано · жертва обморока ·
        # не опознано. Сумма обязана равняться населению падений; род, забытый в
        # этом перечне, исчезал бы из печатаемой строки молча — ровно тот дефект,
        # что ADR-675 нашёл у фаз.
        "roster": n + len(victim_rows) + len(unattributed) == len(failures),
    }
    return {
        "schema": CAUSE_SCHEMA, "status": "measured",
        "population": len(failures), "attributed": n,
        "session_deaths": deaths, "session_deaths_n": len(deaths),
        "session_victims": victim_rows[:50], "session_victims_n": len(victim_rows),
        "unattributed": unattributed[:50], "unattributed_n": len(unattributed),
        "record_only": record_only[:50], "record_only_n": len(record_only),
        "shards_read": read_ok, "shards_absent": absent,
        "shards_without_record": without_record, "shards_unreadable": unreadable,
        "records_read": records,
        "kinds": dict(kinds.most_common()),
        "cause_classes": dict(sorted(classes.items())),
        "phases": dict(sorted(phases.items())),
        "site_classes": dict(sorted(sites.items())),
        "identities_hold": identities,
        "stream_agreed": agreed, "stream_disagreed": disagreed,
        "stream_absent_for": stream_absent,
        "fork": {"population": fork.population, "lower": fork.lower, "upper": fork.upper,
                 "cause_groups": fork.cause_groups, "coarse_groups": fork.coarse_groups,
                 "merged_by_evidence": fork.merged_by_evidence,
                 "largest_component": fork.largest_component},
        "top": [[kind, skeleton, count] for (kind, skeleton), count in fork.groups[:top]],
    }


# ── веса ─────────────────────────────────────────────────────────────────────

def _junit_file(classname: str, root: Path) -> str | None:
    parts = classname.split(".")
    for i in range(len(parts), 0, -1):
        cand = "/".join(parts[:i]) + ".py"
        if (root / cand).is_file():
            return cand
    return None


def build_weights(streams: list[str], junits: list[str], root: Path, source: dict) -> dict:
    files: dict[str, float] = {}
    tests = 0
    total = 0.0
    for path in streams:
        rec = load_stream(path)
        for f, w in rec["file_wall"].items():
            files[f] = round(files.get(f, 0.0) + w, 3)
            total += w
        tests += len(rec["outcomes"])
    for path in junits:
        for case in ET.parse(path).getroot().iter("testcase"):
            f = _junit_file(case.get("classname", ""), root)
            if f is None:
                continue
            d = float(case.get("time") or 0.0)
            files[f] = round(files.get(f, 0.0) + d, 3)
            total += d
            tests += 1
    per_test = round(total / tests, 4) if tests else None
    return {"schema": WEIGHTS_SCHEMA, "source": source, "unit": "seconds of wall per test file",
            "per_test_fallback_s": per_test, "measured_files": len(files),
            "files": dict(sorted(files.items()))}


# ── план ─────────────────────────────────────────────────────────────────────

def make_plan(collected: list[str], collect_errors: list[dict], weights: dict, shards: int,
              budget_s: float) -> dict:
    """Детерминированное разбиение по файлу: LPT по весу, ничья — по пути, затем по номеру шарда.

    Порядок файлов ВНУТРИ шарда — порядок сборки предписанного прогона (порядок населения),
    чтобы относительный порядок тестов не менялся.
    """
    if shards < 1:
        raise ValueError("число шардов обязано быть ≥ 1")
    order: list[str] = []
    counts: dict[str, int] = {}
    for n in collected:
        f = file_of(n)
        if f not in counts:
            order.append(f)
            counts[f] = 0
        counts[f] += 1
    global_errors = []
    for err in collect_errors:
        path = err.get("n", "")
        if path.endswith(".py") and "::" not in path:
            if path not in counts:
                order.append(path)
                counts[path] = 0
        else:
            global_errors.append(err)      # каталог / conftest: шардом не лечится, это красное
    per_test = float(weights.get("per_test_fallback_s") or 0.2)
    known = weights.get("files") or {}
    est: dict[str, float] = {}
    estimated = 0
    for f in order:
        if f in known:
            est[f] = float(known[f])
        else:
            est[f] = max(1.0, counts[f] * per_test)
            estimated += 1
    load = [0.0] * shards
    assign: dict[str, int] = {}
    for f in sorted(order, key=lambda p: (-est[p], p)):
        i = min(range(shards), key=lambda k: (load[k], k))
        assign[f] = i
        load[i] += est[f]
    plan = []
    for i in range(shards):
        files = [f for f in order if assign[f] == i]
        plan.append({"shard": i, "files": files, "tests": sum(counts[f] for f in files),
                     "est_s": round(load[i], 1)})
    worst = max(load) if load else 0.0
    return {"files": order, "tests_per_file": counts, "global_collect_errors": global_errors,
            "shards": plan, "est_total_s": round(sum(load), 1), "est_max_shard_s": round(worst, 1),
            "budget_s": budget_s, "estimated_files": estimated, "within_budget": worst <= budget_s}


def cmd_plan(args) -> int:
    got = read_manifest(args.collected)
    if got["collected"] is None:
        print(f"CI-CONTROL PLAN: INCOMPLETE — перечня населения нет: {got['why']}")
        return 2
    if not got["collected"] and not got["collect_errors"]:
        print("CI-CONTROL PLAN: INCOMPLETE — собрано ноль тестов: пустое население неотличимо "
              "от сломанной сборки (инв. #17)")
        return 2
    weights = json.loads(Path(args.weights).read_text(encoding="utf-8"))
    plan = make_plan(got["collected"], got["collect_errors"], weights, args.shards,
                     args.budget_min * 60.0)
    manifest = {
        "schema": MANIFEST_SCHEMA, "sha": args.sha,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "env": _env_fingerprint(args.roots),
        "roots": args.roots, "population": len(got["collected"]),
        "collected": got["collected"], "collect_errors": got["collect_errors"],
        "weights_source": weights.get("source"), **plan,
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    for sh in plan["shards"]:
        (out / f"shard-{sh['shard']}.txt").write_text("\n".join(sh["files"]) + "\n",
                                                      encoding="utf-8")
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write(f"shards={json.dumps([s['shard'] for s in plan['shards']])}\n")
    print(f"population {manifest['population']} tests in {len(plan['files'])} files · "
          f"{args.shards} shards · est. max shard {plan['est_max_shard_s'] / 60:.1f} min "
          f"(budget {args.budget_min} min) · files without measured weight: "
          f"{plan['estimated_files']}")
    for sh in plan["shards"]:
        print(f"  shard {sh['shard']:>2}: {len(sh['files']):>4} files {sh['tests']:>6} tests "
              f"est {sh['est_s'] / 60:6.1f} min")
    if not plan["within_budget"]:
        print("CI-CONTROL PLAN: INCOMPLETE — оценка самого тяжёлого шарда больше бюджета; "
              "прибавить шардов, а не поднимать границу")
        return 2
    return 0


def _env_fingerprint(roots: list[str]) -> dict:
    import platform
    try:
        import pytest  # noqa: F401 — версия входит в окружение прогона
        pv = pytest.__version__
    except Exception:                                         # pragma: no cover
        pv = None
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "system": platform.system(), "runner_os": os.environ.get("RUNNER_OS"),
            "image": os.environ.get("ImageOS"), "pytest": pv,
            "SPA_ENV": os.environ.get("SPA_ENV"), "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"), "roots": list(roots)}


# ── свод ─────────────────────────────────────────────────────────────────────

def aggregate(manifest: dict | None, shards_dir: Path, needs_result: str | None = None,
              run: dict | None = None) -> dict:
    incomplete: list[dict] = []
    report: dict = {"schema": REPORT_SCHEMA, "verdict": None, "run": run or {},
                    "sha": (manifest or {}).get("sha"), "env": (manifest or {}).get("env"),
                    "incomplete": incomplete}
    if manifest is None or manifest.get("schema") != MANIFEST_SCHEMA:
        incomplete.append({"shard": None, "reason": "манифеста населения нет или он не того вида — "
                                                    "сравнивать результаты шардов не с чем"})
        report.update(verdict=INCOMPLETE, totals=None, failures=[], collect_errors=[],
                      not_obtained=[], population=[], non_passed={}, shards=[], file_wall_s={},
                      cause_axis={"schema": CAUSE_SCHEMA, "status": "unmeasured",
                                  "why": "плана шардов нет — чьи записи читать, "
                                         "неизвестно; причины НЕ ИЗМЕРЕНЫ",
                                  "population": 0})
        return report

    population: list[str] = list(manifest.get("collected") or [])
    files: list[str] = list(manifest.get("files") or [])
    plan: list[dict] = list(manifest.get("shards") or [])
    if needs_result and needs_result in _UNANSWERED_RESULTS:
        incomplete.append({"shard": None,
                           "reason": f"джоба шардов закончилась как «{needs_result}» — ответа нет"})

    # 1. союз списков шардов == населению по файлам, без дублей
    listed: list[str] = [f for sh in plan for f in sh.get("files", [])]
    from collections import Counter
    dup = sorted(f for f, c in Counter(listed).items() if c > 1)
    if dup:
        incomplete.append({"shard": None, "reason": f"файл назначен в несколько шардов: {dup[:20]}"})
    lost = sorted(set(files) - set(listed))
    extra = sorted(set(listed) - set(files))
    if lost:
        incomplete.append({"shard": None,
                           "reason": f"союз шардов ≠ населению: {len(lost)} файлов не назначены "
                                     f"ни одному шарду: {lost[:20]}"})
    if extra:
        incomplete.append({"shard": None,
                           "reason": f"союз шардов ≠ населению: {len(extra)} файлов вне населения: "
                                     f"{extra[:20]}"})
    pop_files = {file_of(n) for n in population}
    if not pop_files <= set(files):
        incomplete.append({"shard": None, "reason": "манифест противоречив: у тестов есть файлы вне "
                                                    "списка файлов"})

    by_file: dict[str, list[str]] = {}
    for n in population:
        by_file.setdefault(file_of(n), []).append(n)

    outcomes: dict[str, str] = {}
    owner: dict[str, int] = {}
    msgs: dict[str, str] = {}
    collect_errors = [dict(e, shard=None) for e in manifest.get("collect_errors") or []]
    shard_rows: list[dict] = []
    file_wall: dict[str, float] = {}
    present_dirs = {p.name for p in shards_dir.iterdir()} if shards_dir.is_dir() else set()

    for sh in plan:
        i = sh["shard"]
        problems: list[str] = []
        d = shards_dir / f"{SHARD_DIR_PREFIX}{i}"
        present_dirs.discard(d.name)
        row = {"shard": i, "files": len(sh.get("files", [])), "tests": sh.get("tests"),
               "est_s": sh.get("est_s"), "wall_s": None, "exit": None, "problems": problems,
               "unfinished": []}
        shard_rows.append(row)
        if not d.is_dir():
            problems.append("артефакта шарда нет (шард не отчитался)")
            continue
        meta = d / SHARD_FILE
        if meta.exists():
            try:
                declared = json.loads(meta.read_text(encoding="utf-8")).get("shard")
            except ValueError:
                declared = "<битый>"
            if str(declared) != str(i):
                problems.append(f"артефакт ctl-shard-{i} называет себя шардом {declared}")
        planned = [n for f in sh.get("files", []) for n in by_file.get(f, [])]
        got = read_manifest(str(d / COLLECTED_FILE))
        if got["collected"] is None:
            problems.append(f"перечня собранного нет: {got['why']}")
        else:
            missing = sorted(set(planned) - set(got["collected"]))
            surplus = sorted(set(got["collected"]) - set(planned))
            if missing:
                problems.append(f"шард не собрал {len(missing)} тестов населения: {missing[:10]}")
            if surplus:
                problems.append(f"шард собрал {len(surplus)} тестов вне населения: {surplus[:10]}")
        for err in got["collect_errors"]:
            collect_errors.append(dict(err, shard=i))
        rec = load_stream(str(d / STREAM_FILE))
        if not rec["present"]:
            problems.append("потоковой записи нет")
        elif rec["end"] is None:
            problems.append("сессия pytest не дошла до конца (снят, отменён или убит)")
        row["unfinished"] = rec["unfinished"][:20]
        if rec["t0"] is not None and rec["t1"] is not None:
            row["wall_s"] = round(rec["t1"] - rec["t0"], 1)
        for f, w in rec["file_wall"].items():
            file_wall[f] = w
        shard_fails = 0
        planned_set = set(planned)
        for n, o in rec["outcomes"].items():
            if n not in planned_set:
                continue                 # вне населения — уже названо выше как surplus
            outcomes[n] = o
            owner[n] = i
            if o in (FAILED, ERROR):
                shard_fails += 1
                if n in rec["msgs"]:
                    msgs[n] = rec["msgs"][n]
        exit_path = d / EXIT_FILE
        code = None
        exit_doc: dict = {}
        if exit_path.exists():
            try:
                exit_doc = json.loads(exit_path.read_text(encoding="utf-8"))
                code = exit_doc.get("exit")
            except ValueError:
                code = None
        row["exit"] = code
        # Доигрывание (`run-shard`): сколько сессий понадобилось и на ком падал pytest.
        row["attempts"] = len(exit_doc.get("attempts") or []) or None
        row["crashed_on"] = [n for c in exit_doc.get("crashes") or [] for n in c.get("tests") or []]
        for c in exit_doc.get("crashes") or []:
            if not c.get("tests"):
                problems.append(f"pytest прервался (exit {c.get('exit')}, попытка {c.get('attempt')}) "
                                "между тестами — аварию некому приписать")
        if code is None:
            problems.append("кода возврата pytest нет (шаг снят до записи)")
        elif code not in (0, 1):
            problems.append(f"pytest вернул {code} — прогон прерван, а не измерен")
        elif code == 1 and shard_fails == 0 and not got["collect_errors"]:
            problems.append("pytest сказал «упало», а ни одного упавшего имени в записи нет")
        elif code == 0 and shard_fails:
            problems.append(f"pytest сказал «зелёно», а запись называет {shard_fails} упавших")
    for name in sorted(present_dirs):
        if name.startswith(SHARD_DIR_PREFIX):
            incomplete.append({"shard": None, "reason": f"артефакт {name} не принадлежит плану"})

    for row in shard_rows:
        for p in row["problems"]:
            incomplete.append({"shard": row["shard"], "reason": p})

    not_obtained = [n for n in population if n not in outcomes]
    if not_obtained:
        incomplete.append({"shard": None,
                           "reason": f"{len(not_obtained)} тестов населения без исхода "
                                     "(не получено)"})
    shard_of_file = {f: sh["shard"] for sh in plan for f in sh.get("files", [])}
    failures = [{"nodeid": n, "outcome": outcomes[n], "shard": owner.get(n),
                 "msg": msgs.get(n, "")}
                for n in population if outcomes.get(n) in (FAILED, ERROR)]
    for e in collect_errors:
        if e.get("shard") is None:
            e["shard"] = shard_of_file.get(e.get("n"))
    # Ошибка сборки, увиденная и манифестом, и шардом, — одна ошибка.
    seen: set[str] = set()
    uniq_ce = []
    for e in collect_errors:
        if e["n"] in seen:
            continue
        seen.add(e["n"])
        uniq_ce.append(e)
    counts = {k: 0 for k in (PASSED, SKIPPED, FAILED, ERROR)}
    for o in outcomes.values():
        counts[o] += 1
    totals = {"population": len(population), "files": len(files), **counts,
              "not_obtained": len(not_obtained), "collect_errors": len(uniq_ce),
              "shards_planned": len(plan),
              "shards_complete": sum(1 for r in shard_rows if not r["problems"])}
    if incomplete:
        verdict = INCOMPLETE
    elif failures or uniq_ce:
        verdict = RED
    else:
        verdict = GREEN
    # Ось причин (ADR-891): `cause_axis` ДОПИСЫВАЕТ `cause` в сами строки `failures`,
    # поэтому зовётся до `report.update` — иначе в отчёт уехал бы прежний список.
    axis = cause_axis(plan, shards_dir, failures)
    report.update(verdict=verdict, totals=totals, failures=failures, collect_errors=uniq_ce,
                  not_obtained=not_obtained, population=population,
                  non_passed={n: o for n, o in outcomes.items() if o != PASSED},
                  shards=shard_rows, file_wall_s=dict(sorted(file_wall.items())),
                  cause_axis=axis)
    return report


def cause_line(axis) -> str:
    """ОДНА строка про ось причин — ЕДИНСТВЕННАЯ копия этого правила.

    Её читают и `report.md` свода, и перепись читателя вердикта (`ci_control_verdict.py`
    берёт эту функцию ПО ПУТИ, а не пишет свою): две копии разошлись бы молча — одна
    сказала бы «причин нет», другая «не измерено», и спорящие строки хуже отсутствия
    строки. НЕ ИЗМЕРЕНО ⇒ СЛОВА с причиной, никогда ноль (инв. #17).
    """
    if not isinstance(axis, dict):
        return ("ось причин НЕ ИЗМЕРЕНА: блока `cause_axis` в отчёте нет ВОВСЕ — "
                "отчёт собран сводом старше ADR-891, и «причин нет» здесь НЕ "
                "утверждается")
    if axis.get("status") != "measured":
        return (f"ось причин НЕ ИЗМЕРЕНА: {axis.get('why') or 'причина не названа'}")
    pop = axis.get("population")
    if not pop:
        return "причин опознавать нечего: падений не объявлено (измерено и равно нулю)"
    fork = axis.get("fork") or {}
    kinds = axis.get("kinds") or {}
    top = axis.get("top") or []
    parts = [f"причины: опознано {axis.get('attributed')} из {pop}"]
    # ОБМОРОК СЕССИИ печатается ПЕРЕД «без причины» намеренно: это РОД, а не остаток.
    # Жертва обморока причину имеет, и причина у неё НЕ ДЕФЕКТ ТЕСТА — читатель,
    # увидевший её среди «без причины», пошёл бы чинить тест (ADR-892).
    if axis.get("session_deaths_n"):
        deaths = axis.get("session_deaths") or []
        who = ", ".join(str(d.get("shard")) for d in deaths)
        first = deaths[0] if deaths else {}
        parts.append(f"СЕССИЯ УМЕРЛА внутренне у шард(ов) {who} "
                     f"({first.get('kind') or '«тип не назван»'}: "
                     f"{str(first.get('skeleton') or '«сообщения нет»')[:80]}); "
                     f"под обмороком падени(й) {axis.get('session_victims_n') or 0} — "
                     f"это обморок ИНСТРУМЕНТА, а не дефекты теста, и в вилку они "
                     f"не входят"
                     + (f" (поимённо: "
                        f"{', '.join(axis.get('session_victims') or [])[:200]})"
                        if axis.get("session_victims") else ""))
    elif axis.get("session_victims_n"):
        parts.append(f"ЖЕРТВ обморока {axis['session_victims_n']}, а самой записи "
                     f"обморока ни у одного шарда НЕТ — потоковая запись и junit "
                     f"расходятся, и это находка о ЗАПИСИ")
    if axis.get("unattributed_n"):
        parts.append(f"БЕЗ причины {axis['unattributed_n']} "
                     f"(поимённо: {', '.join(axis.get('unattributed') or [])[:200]})")
    if axis.get("record_only_n"):
        parts.append(f"в junit есть, а отчёт не числит упавшими {axis['record_only_n']}")
    if kinds:
        parts.append("типы: " + " · ".join(f"{k} {v}" for k, v in list(kinds.items())[:6]))
    if fork.get("population"):
        parts.append(f"дефектов НЕ МЕНЬШЕ {fork.get('lower')} и НЕ БОЛЬШЕ "
                     f"{fork.get('upper')} (крупнейшее семейство "
                     f"{fork.get('largest_component')}; считано по "
                     f"{fork.get('population')} опознанн(ым) провал(ам) теста)")
    if top:
        kind, skeleton, count = top[0]
        parts.append(f"крупнейшая причина ×{count}: {kind}: {str(skeleton)[:120]}")
    bad = [k for k, ok in (axis.get("identities_hold") or {}).items() if not ok]
    if bad:
        parts.append(f"ТОЖДЕСТВО УЧЁТА НАРУШЕНО у {', '.join(sorted(bad))} — род вне "
                     f"объявленного перечня исчезает из этой строки молча")
    if axis.get("shards_without_record") or axis.get("shards_unreadable"):
        parts.append(f"шардов без junit-записи {len(axis.get('shards_without_record') or [])}, "
                     f"нечитаемых записей {len(axis.get('shards_unreadable') or [])}")
    return "; ".join(parts)


def render_md(report: dict, limit: int = 200) -> str:
    v = report["verdict"]
    lines = [f"# CI control run — {v}", ""]
    lines.append(f"- SHA: `{report.get('sha')}`")
    run = report.get("run") or {}
    if run.get("url"):
        lines.append(f"- Run: {run['url']}")
    env = report.get("env") or {}
    if env:
        lines.append(f"- Env: python {env.get('python')} · pytest {env.get('pytest')} · "
                     f"{env.get('image') or env.get('system')} · SPA_ENV={env.get('SPA_ENV')} · "
                     f"PYTHONHASHSEED={env.get('PYTHONHASHSEED')}")
    t = report.get("totals")
    if t:
        lines += ["", "| population | passed | failed | error | skipped | not obtained | "
                      "collect errors | shards complete |",
                  "|---|---|---|---|---|---|---|---|",
                  f"| {t['population']} | {t['passed']} | {t['failed']} | {t['error']} | "
                  f"{t['skipped']} | {t['not_obtained']} | {t['collect_errors']} | "
                  f"{t['shards_complete']}/{t['shards_planned']} |"]
    if report["incomplete"]:
        lines += ["", "## INCOMPLETE — why", ""]
        for item in report["incomplete"]:
            where = "global" if item["shard"] is None else f"shard {item['shard']}"
            lines.append(f"- [{where}] {item['reason']}")
    lines += ["", "## Cause axis (ADR-891)", "", f"- {cause_line(report.get('cause_axis'))}"]
    if report.get("failures"):
        lines += ["", f"## Failed / error ({len(report['failures'])})", ""]
        for f in report["failures"][:limit]:
            cause = f.get("cause")
            why = ("" if "cause" not in f else
                   (f" — ПРИЧИНА НЕ ОПОЗНАНА" if cause is None else
                    f" — {cause.get('kind') or '«тип не назван»'}: {cause.get('skeleton')}"))
            lines.append(f"- `{f['nodeid']}` — {f['outcome']} (shard {f['shard']})"
                         + (f" — {f['msg']}" if f.get("msg") else "") + why)
        if len(report["failures"]) > limit:
            lines.append(f"- … and {len(report['failures']) - limit} more (full list in JSON)")
    if report.get("collect_errors"):
        lines += ["", "## Collection errors", ""]
        for e in report["collect_errors"]:
            lines.append(f"- `{e['n']}` (shard {e.get('shard')}) — {e.get('msg', '')}")
    if report.get("not_obtained"):
        lines += ["", f"## Not obtained ({len(report['not_obtained'])}, first 50)", ""]
        lines += [f"- `{n}`" for n in report["not_obtained"][:50]]
    if report.get("shards"):
        lines += ["", "## Shards", "", "| shard | files | tests | est min | wall min | exit | "
                                       "problems |", "|---|---|---|---|---|---|---|"]
        for r in report["shards"]:
            wall = "—" if r["wall_s"] is None else f"{r['wall_s'] / 60:.1f}"
            est = "—" if r.get("est_s") is None else f"{r['est_s'] / 60:.1f}"
            exit_cell = f"{r['exit']}" + (f" ({r['attempts']} sessions)" if (r.get("attempts") or 0) > 1
                                          else "")
            lines.append(f"| {r['shard']} | {r['files']} | {r['tests']} | {est} | {wall} | "
                         f"{exit_cell} | {'; '.join(r['problems']) or '—'} |")
    return "\n".join(lines) + "\n"


def cmd_aggregate(args) -> int:
    mpath = Path(args.manifest_dir) / "manifest.json"
    manifest = None
    if mpath.exists():
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except ValueError:
            manifest = None
    run = {"id": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
           "event": os.environ.get("GITHUB_EVENT_NAME")}
    if os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_REPOSITORY") and run["id"]:
        run["url"] = (f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
                      f"/actions/runs/{run['id']}")
    report = aggregate(manifest, Path(args.shards_dir), args.needs_result, run)
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    md = render_md(report)
    Path(args.out_md).write_text(md, encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(md)
    t = report.get("totals") or {}
    print(f"CI-CONTROL VERDICT: {report['verdict']} · sha {report.get('sha')} · "
          f"failed {t.get('failed')} · error {t.get('error')} · not obtained "
          f"{t.get('not_obtained')} · shards {t.get('shards_complete')}/{t.get('shards_planned')}")
    for item in report["incomplete"][:30]:
        where = "global" if item["shard"] is None else f"shard {item['shard']}"
        print(f"  INCOMPLETE [{where}] {item['reason']}")
    for f in report.get("failures", [])[:50]:
        print(f"  {f['outcome'].upper()} [shard {f['shard']}] {f['nodeid']}")
    return EXIT[report["verdict"]]


# ── сравнение двух вердиктов ─────────────────────────────────────────────────

NEW, PRE_EXISTING, NOT_OBTAINED = "new", "pre_existing", "not_obtained"


def compare(base: dict, head: dict) -> dict:
    """Классифицировать упавшие ГОЛОВЫ относительно БАЗЫ: new / pre_existing / not_obtained.

    * ``pre_existing`` — в базе тот же тест тоже упал/ошибся;
    * ``new`` — в базе тест ИЗМЕРЕН и прошёл/пропущен, либо его в населении базы не было
      (новый тест, который падает, — новая поломка, а не старая);
    * ``not_obtained`` — в базе тест был в населении, но исхода не получил: сказать
      «новое» или «старое» НЕЛЬЗЯ, и это называется словом, а не догадкой.

    Сравнимость — предусловие: одна схема, одно окружение (python major.minor, корни,
    SPA_ENV, PYTHONHASHSEED). Несравнимые отчёты ⇒ ``comparable=False`` и ни одной метки.
    """
    reasons = []
    for name, rep in (("base", base), ("head", head)):
        if rep.get("schema") != REPORT_SCHEMA:
            reasons.append(f"{name}: не отчёт контрольного прогона")
    if not reasons:
        eb, eh = base.get("env") or {}, head.get("env") or {}
        for key in ("roots", "SPA_ENV", "PYTHONHASHSEED", "workflow", "implementation"):
            if eb.get(key) != eh.get(key):
                reasons.append(f"окружение различается: {key} {eb.get(key)!r} ≠ {eh.get(key)!r}")
        pb = ".".join(str(eb.get("python") or "").split(".")[:2])
        ph = ".".join(str(eh.get("python") or "").split(".")[:2])
        if pb != ph:
            reasons.append(f"окружение различается: python {pb} ≠ {ph}")
    out = {"comparable": not reasons, "why_not": reasons, "base_sha": base.get("sha"),
           "head_sha": head.get("sha"), "base_verdict": base.get("verdict"),
           "head_verdict": head.get("verdict"), NEW: [], PRE_EXISTING: [], NOT_OBTAINED: [],
           "fixed": [], "head_not_obtained": len(head.get("not_obtained") or [])}
    if reasons:
        return out
    base_missing = set(base.get("not_obtained") or [])
    base_np = base.get("non_passed") or {}
    head_np = head.get("non_passed") or {}
    for f in head.get("failures") or []:
        n = f["nodeid"]
        if n in base_missing:
            out[NOT_OBTAINED].append(n)
        elif base_np.get(n) in (FAILED, ERROR):
            out[PRE_EXISTING].append(n)
        else:                          # измерен и прошёл, либо нового теста в базе не было
            out[NEW].append(n)
    head_pop = set(head.get("population") or [])
    head_missing = set(head.get("not_obtained") or [])
    for f in base.get("failures") or []:
        n = f["nodeid"]
        if n in head_pop and n not in head_missing and head_np.get(n) not in (FAILED, ERROR):
            out["fixed"].append(n)
    return out


def cmd_compare(args) -> int:
    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    head = json.loads(Path(args.head).read_text(encoding="utf-8"))
    res = compare(base, head)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    if not res["comparable"]:
        print("CI-CONTROL COMPARE: NOT COMPARABLE — " + "; ".join(res["why_not"]))
        return 2
    print(f"CI-CONTROL COMPARE {res['base_sha']} ({res['base_verdict']}) → "
          f"{res['head_sha']} ({res['head_verdict']}): new {len(res[NEW])} · pre-existing "
          f"{len(res[PRE_EXISTING])} · not obtained {len(res[NOT_OBTAINED])} · fixed "
          f"{len(res['fixed'])}")
    for key in (NEW, NOT_OBTAINED):
        for n in res[key][:100]:
            print(f"  {key.upper()} {n}")
    if res[NEW]:
        return 1
    if res[NOT_OBTAINED] or res["head_verdict"] == INCOMPLETE:
        return 2
    return 0


# ── шард с доигрыванием после аварии pytest ─────────────────────────────────

STREAM_ENV = "SPA_PYTEST_STREAM"          # = spa_core.ci.pytest_stream_record.STREAM_ENV
MANIFEST_ENV = "SPA_PYTEST_MANIFEST"      # = spa_core.ci.pytest_collect_manifest.MANIFEST_ENV
RESUME_ENV = "SPA_PYTEST_RESUME_ONLY"     # = spa_core.ci.pytest_stream_record.RESUME_ENV
INTERNAL_WHEN = "internal"                # `w` синтетической записи: не call ⇒ ERROR в своде
INTERNAL_MSG = "pytest internal error"

#: Коды, после которых сессию НЕ доигрывают: 0/1 — измерено; 4 — ошибка вызова (повтор
#: даст то же); 5 — ничего не собрано. Всё остальное (3 INTERNALERROR, 2 прерван,
#: отрицательный/>128 — процесс убит) — авария.
_NO_RESUME_CODES = (0, 1, 4, 5)


def _stream_tail(path: str, offset: int) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        fh.seek(offset)
        for raw in fh:
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
    return out


def _size(path: str) -> int:
    return os.path.getsize(path) if os.path.exists(path) else 0


def _append_events(path: str, events: list[dict]) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        for ev in events:
            ev.setdefault("t", round(time.time(), 3))
            fh.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")


def run_shard(files: list[str], pytest_args: list[str], stream: str, manifest: str,
              junit: str | None, max_resumes: int = 3, pytest_cmd: list[str] | None = None,
              env: dict | None = None, cwd: str | None = None) -> dict:
    """Прогнать шард; после аварии pytest доиграть остаток. Вернуть сводку попыток.

    Сводка: ``{"exit": итоговый код, "attempts": [...], "crashes": [...], "remaining": N}``.
    Итоговый код: последняя сессия измерила остаток (0/1) ⇒ 1, если в записи есть хоть один
    упавший/ошибка (тест аварии — ошибка всегда), иначе её код; остаток не доигран ⇒ код
    аварийной сессии — свод назовёт это INCOMPLETE.
    """
    cmd = list(pytest_cmd or [sys.executable, "-m", "pytest"])
    base_env = dict(os.environ if env is None else env)
    base_env.pop(RESUME_ENV, None)
    out_dir = os.path.dirname(os.path.abspath(manifest))
    attempts: list[dict] = []
    crashes: list[dict] = []
    remaining: list[str] | None = None
    code = None
    # Список файлов шарда — через файл аргументов pytest (`@путь`), а не в командной
    # строке: тысячи имён в `sys.argv` видит каждый тест, читающий argv процесса
    # (`cartographer/brief.py` пишет команду в манифест прогона и честно краснел на
    # имени файла со словом «token», чего предписанный прогон каталогами не даёт).
    listing = os.path.join(out_dir, "shard-files.txt")
    Path(listing).write_text("\n".join(files) + "\n", encoding="utf-8")
    for k in range(max_resumes + 1):
        e = dict(base_env)
        e[STREAM_ENV] = stream
        args = ([f"@{listing}"] if files else []) + list(pytest_args)
        if k == 0:
            e[MANIFEST_ENV] = manifest
            if junit:
                args.append(f"--junitxml={junit}")
        else:
            keep = os.path.join(out_dir, f"resume-{k}.txt")
            Path(keep).write_text("\n".join(remaining or []) + "\n", encoding="utf-8")
            e[RESUME_ENV] = keep
            e[MANIFEST_ENV] = os.path.join(out_dir, f"collected-resume-{k}.jsonl")
            if junit:
                root, ext = os.path.splitext(junit)
                args.append(f"--junitxml={root}-resume-{k}{ext or '.xml'}")
        offset = _size(stream)
        code = subprocess.run(cmd + args, env=e, cwd=cwd).returncode
        tail = _stream_tail(stream, offset)
        ended = any(ev.get("e") == "end" for ev in tail)
        attempt = {"attempt": k, "exit": code, "session_end": ended,
                   "requested": None if k == 0 else len(remaining or [])}
        attempts.append(attempt)
        if code in _NO_RESUME_CODES and ended:
            break
        # Авария: тест, начатый в ЭТОЙ сессии и не получивший исхода, — тот, на котором упали.
        started, finished = [], set()
        for ev in tail:
            if ev.get("e") == "start":
                started.append(ev.get("n", ""))
            elif ev.get("e") in ("ok", "skip", "fail"):
                finished.add(ev.get("n", ""))
        running = [n for n in started if n not in finished]
        why = (f"{INTERNAL_MSG} (pytest exit {code}"
               + ("" if ended else ", session end missing")
               + ") while this test was running or being reported — not re-run")
        _append_events(stream, [{"e": "fail", "n": n, "w": INTERNAL_WHEN, "d": 0.0,
                                 "msg": why} for n in running])
        crashes.append({"attempt": k, "exit": code, "session_end": ended,
                        "tests": running})
        got = read_manifest(manifest)
        if got["collected"] is None:
            attempt["resume"] = f"нечего доигрывать: перечня собранного нет ({got['why']})"
            break
        done = set(load_stream(stream)["outcomes"])
        left = [n for n in got["collected"] if n not in done]
        if remaining is not None and not running and len(left) >= len(remaining):
            attempt["resume"] = "доигрывание не продвинулось — остановлено"
            remaining = left
            break
        remaining = left
        if not remaining:
            break
        if k == max_resumes:
            attempt["resume"] = f"предел доигрываний ({max_resumes}) исчерпан"
    final = code
    if crashes:
        last = attempts[-1]
        unnamed = [c for c in crashes if not c["tests"]]
        resolved = (last["exit"] in (0, 1) and last["session_end"]) or remaining == []
        if unnamed:
            final = unnamed[0]["exit"]   # авария, которую некому приписать, — не измерено
        elif resolved:
            outcomes = load_stream(stream)["outcomes"].values()
            final = 1 if any(o in (FAILED, ERROR) for o in outcomes) else 0
    return {"exit": final, "attempts": attempts, "crashes": crashes,
            "resumed": len(attempts) > 1,
            "remaining": None if remaining is None else len(remaining)}


def cmd_run_shard(args) -> int:
    files = [f for f in Path(args.files).read_text(encoding="utf-8").split() if f]
    extra = list(args.pytest_args or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    stream = os.environ.get(STREAM_ENV)
    manifest = os.environ.get(MANIFEST_ENV)
    if not stream or not manifest:
        print(f"CI-CONTROL RUN-SHARD: отказ — нужны {STREAM_ENV} и {MANIFEST_ENV}: без них "
              "запись и доигрывание невозможны")
        return 2
    res = run_shard(files, extra, stream, manifest, args.junit, args.max_resumes)
    Path(args.exit_file).parent.mkdir(parents=True, exist_ok=True)
    Path(args.exit_file).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    for c in res["crashes"]:
        print(f"CI-CONTROL RUN-SHARD: авария pytest (exit {c['exit']}) в попытке {c['attempt']}; "
              f"названы ошибкой: {c['tests'] or 'НИКТО (между тестами)'}")
    print(f"CI-CONTROL RUN-SHARD: попыток {len(res['attempts'])} · итоговый код {res['exit']} · "
          f"без исхода осталось {res['remaining']}")
    return int(res["exit"]) if isinstance(res["exit"], int) and 0 <= res["exit"] < 256 else 3


def cmd_weights(args) -> int:
    source = {"note": args.note or "", "streams": args.stream or [], "junits": args.junit or []}
    w = build_weights(args.stream or [], args.junit or [], Path(args.root), source)
    Path(args.out).write_text(json.dumps(w, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"weights: {w['measured_files']} files, fallback {w['per_test_fallback_s']} s/test")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("--collected", required=True)
    pl.add_argument("--weights", required=True)
    pl.add_argument("--shards", type=int, required=True)
    pl.add_argument("--budget-min", type=float, required=True)
    pl.add_argument("--sha", required=True)
    pl.add_argument("--roots", nargs="+", required=True)
    pl.add_argument("--out-dir", required=True)
    pl.add_argument("--github-output")
    ag = sub.add_parser("aggregate")
    ag.add_argument("--manifest-dir", required=True)
    ag.add_argument("--shards-dir", required=True)
    ag.add_argument("--needs-result")
    ag.add_argument("--out-json", required=True)
    ag.add_argument("--out-md", required=True)
    ag.add_argument("--summary")
    cp = sub.add_parser("compare")
    cp.add_argument("base")
    cp.add_argument("head")
    cp.add_argument("--out-json")
    wt = sub.add_parser("weights")
    wt.add_argument("--stream", action="append")
    wt.add_argument("--junit", action="append")
    wt.add_argument("--root", default=".")
    wt.add_argument("--note")
    wt.add_argument("--out", required=True)
    rs = sub.add_parser("run-shard")
    rs.add_argument("--files", required=True, help="файл со списком тест-файлов шарда")
    rs.add_argument("--exit-file", required=True)
    rs.add_argument("--junit")
    rs.add_argument("--max-resumes", type=int, default=3)
    rs.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)
    return {"plan": cmd_plan, "aggregate": cmd_aggregate, "compare": cmd_compare,
            "weights": cmd_weights, "run-shard": cmd_run_shard}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
