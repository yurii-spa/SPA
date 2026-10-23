"""Перепись ЦЕНЫ усечения ленты `research_factory` по ВОЗРАСТУ (заказ G787 п. 1 = G784 п. 2).

Лента `data/research_factory/ledger.jsonl` растёт темпом ≈3.6 МБ/сутки
(`ledger_parse_census`, ADR-784). Лекарство, которое называли пять циклов подряд, —
**«усечь ленту до N суток»**, и цикл #908 честно записал, почему принять его нельзя:
*«доля ответа, зависящая от записей старше суток, НЕ ИЗМЕРЕНА — это первое для
следующего захода»*. Без этого числа выбор N есть решение вслепую.

Эта перепись и есть то число. Она отвечает ровно на один вопрос:

    если оставить в ленте только последние N суток, КАКАЯ ЧАСТЬ ответа
    читающей модели перестанет быть той же?

## Почему ДВА независимых маршрута, а не один

Одного замера мало: ошибка в построении сцены неотличима от настоящей зависимости.
Поэтому каждое окно меряется ДВАЖДЫ, разными способами, и они обязаны СОЙТИСЬ:

* **дифференциальный** — собрать настоящую ленту из оставшихся записей, позвать
  настоящую читающую модель (`research_factory.read.latest` и `.cio_view`) и
  сравнить ответ с полным ПОЛИСТНО;
* **структурный** — не звать модель вовсе, а посчитать по самой ленте, у скольких
  кандидатов самый свежий `candidate_snapshot` старше окна.

Маршруты не имеют общих вычислений: первый проходит через весь код читающей модели,
второй — через один проход по строкам ленты. Расхождение означает, что прибор не
знает ответа, и тогда вердикт — **НЕ ИЗМЕРЕНО** (инв. #17), а не среднее из двух.

## Положительный контроль построения сцены

Полная пересборка цепи обязана воспроизвести вершину ЖИВОЙ ленты **байт в байт**
(`head_hash`). Сцена строится из тех же `kind`/`key`/`payload`/`at` и перехешируется
кодом самой ленты (`HashLedger._entry_hash`), поэтому совпадение вершины — не
совпадение чисел, а доказательство, что сцена есть та же лента. Не совпало ⇒
**НЕ ИЗМЕРЕНО**: все остальные числа прибора в этом случае говорят о чужой ленте.

Базовый ответ берётся с ПЕРЕСОБРАННОЙ полной сцены, а не с живого каталога: иначе
разница окна и базы несла бы в себе ещё и разницу «живое `data/` против сцены».

## Что считается «ответом»

Ответ — два публичных входа читающей модели, слитые в один словарь, и разложенные
в ЛИСТЬЯ (`путь → значение`). Элементы списков адресуются **по личности**
(`candidate_id`), а не по месту: при адресации по индексу исчезновение одного
кандидата сдвигает все следующие, и прибор докладывал бы 71 % зависимости там, где
её 33 % (замер 23.10, первый прогон прототипа — ровно эта ошибка). Два листа
меняются у любого усечения ПО ПОСТРОЕНИЮ (`ledger_head_hash` обоих входов): цепь
другая, и это не зависимость ответа от старых записей, а её механическое следствие.
Они названы поимённо (:data:`CHAIN_IDENTITY_LEAVES`), считаются отдельно и в долю
зависимости НЕ входят — а сам список ПРОВЕРЯЕТСЯ на существование в ответе, иначе
вычет был бы вычетом ничего.

## Чего прибор НЕ делает

Ничего не чинит, ничего не усекает и в живую ленту не пишет НИ БАЙТА: живой
каталог только читается, все сцены живут в одноразовом каталоге и снимаются сразу
после замера. Ни один гейт этот прибор не читает — он ADVISORY, его число читает
решение о сроке хранения ленты.

# LLM_FORBIDDEN
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re

import shutil
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from spa_core.utils.atomic import atomic_save

_ROOT = Path(__file__).resolve().parents[2]

VERSION = "ledger-window-dependency/1"
ARTIFACT = "ledger_window_dependency.json"
SELF_REL = "spa_core/monitoring/ledger_window_dependency_census.py"

#: Лестница окон в сутках. Прибор отвечает не «можно ли усечь до суток», а «есть ли
#: вообще N, при котором ответ не меняется» — поэтому лестница, а не одно окно.
WINDOWS: Tuple[int, ...] = (1, 2, 3, 5, 7, 10, 14)

#: Такт недельный, и срок решает ФАЙЛ, а не расписание бегуна: прогон поднимает
#: настоящую читающую модель на каждом окне и стои́т минуты.
MEASUREMENT_TACT_DAYS = 7

STATUS_CLEAN = "CLEAN"
STATUS_FINDINGS = "FINDINGS"
STATUS_UNMEASURED = "UNMEASURED"

FINDING_NO_SAFE_WINDOW = "no_safe_truncation_window"

#: Листья, которые меняются у ЛЮБОГО усечения по построению (другая цепь — другая
#: вершина). Это следствие усечения, а не зависимость ответа от старых записей.
#:
#: Список ПРОВЕРЯЕТСЯ: каждый путь обязан существовать в базовом ответе, иначе
#: вердикт — НЕ ИЗМЕРЕНО. Исключение, вычитающее несуществующий лист, не защищает
#: ни от чего и при этом выглядит защитой — ровно тот класс «пустого сторожа»,
#: который ловит `vacuous_guard_census`. Поймано на себе: первая редакция вычитала
#: ещё и `latest.integrity.entries`, которого в ответе НЕТ (есть `latest.integrity`
#: со значением `'OK'`, и оно от усечения не движется).
CHAIN_IDENTITY_LEAVES = (
    "latest.ledger_head_hash",
    "cio_view.ledger_head_hash",
)

#: Поля, по которым элемент списка опознаётся как ОДИН И ТОТ ЖЕ в двух ответах.
ID_KEYS = ("candidate_id", "id", "key", "cid", "name", "exposure_key", "seq")

#: Списки ответа, элементы которых НЕ НЕСУТ ни одного поля из :data:`ID_KEYS`.
#:
#: Первая редакция прибора (ADR-793) перевела на ЛИЧНОСТЬ те списки, у которых
#: личность есть, и МОЛЧА оставила остальным адресацию по месту — то есть ровно
#: тот дефект, против которого была написана, только в списках поменьше. Замер
#: 2026-10-23 назвал население точно: из 7 674 элементов ответа по месту
#: адресуются **14** в ДВУХ списках, и природа у них РАЗНАЯ, поэтому одного
#: лекарства на оба нет.
#:
#: ``latest.stale_feeds`` — ``{source_root, age_h}`` без личности вовсе
#: (``defillama:yields`` повторяется девять раз), а порядок берётся из порядка
#: обхода кандидатов. Усечение ленты меняет порядок первого появления, и прибор
#: докладывал **9 изменившихся листьев там, где множество пар совпадает
#: ПОЛНОСТЬЮ** (замер на сцене с пересъёмкой: ``множества равны: True ·
#: порядок равен: False``). Такой список адресуется как МУЛЬТИМНОЖЕСТВО — это
#: УМОЛЧАНИЕ прибора, и объявление здесь существует не ради поведения, а ради
#: того, чтобы природа списка была ЗАМЕРЕНА и названа, а не досталась молча.
ORDER_FREE_LISTS = frozenset({
    "latest.stale_feeds",
})

#: ``latest.sherlock.top_blockers`` — ``sorted(..., key=(-count, gate))[:5]``:
#: место в списке ЕСТЬ ранг, то есть часть ответа. Здесь адресация по месту
#: ВЕРНА, и перевод на мультимножество спрятал бы настоящую смену рангов.
#: Объявление существует ради того, чтобы это был ЗАМЕР, а не умолчание.
RANKED_LISTS = frozenset({
    "latest.sherlock.top_blockers",
})


def generic_path(path: str) -> str:
    """Путь с обезличенными индексами: ``a[id=7].b`` → ``a[*].b``."""
    return re.sub(r"\[[^\]]*\]", "[*]", path)

_CANDIDATE_PREFIX = "latest.candidates[candidate_id="


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_at(raw) -> Optional[dt.datetime]:
    """Отметка записи → момент. Не разобрали ⇒ ``None``, а не «эпоха»."""
    if not isinstance(raw, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


# ── сцена ────────────────────────────────────────────────────────────────────────


def load_entries(ledger_path: Path) -> List[dict]:
    """Строки живой ленты как они есть. Пустые строки пропускаются, битая — ошибка."""
    out: List[dict] = []
    with open(ledger_path, "r", encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"строка {n} ленты не разобрана: {exc}") from exc
    return out


def rechain(entries: Sequence[dict], data_dir: Path) -> str:
    """Собрать в ``data_dir`` НАСТОЯЩУЮ ленту из ``entries`` и вернуть её вершину.

    Перехеширование идёт кодом самой ленты (``HashLedger._entry_hash`` и
    ``_canonical``), поэтому полный набор воспроизводит живую вершину байт в байт —
    это и есть положительный контроль построения сцены.
    """
    from spa_core.research_factory import contract  # noqa: PLC0415
    from spa_core.utils.hash_ledger import GENESIS, HashLedger, _canonical  # noqa: PLC0415

    led_dir = Path(data_dir) / contract.DATA_SUBDIR
    anc_dir = Path(data_dir) / contract.ANCHORS_SUBDIR
    led_dir.mkdir(parents=True, exist_ok=True)
    anc_dir.mkdir(parents=True, exist_ok=True)
    ledger = HashLedger(Path(data_dir), contract.DATA_SUBDIR, contract.ANCHORS_SUBDIR,
                        contract.LEDGER)
    prev = GENESIS
    lines: List[str] = []
    anchors: List[str] = []
    for seq, entry in enumerate(entries, start=1):
        entry_hash = ledger._entry_hash(prev, seq, entry["kind"], entry["key"],
                                        entry["payload"], entry["at"])
        lines.append(_canonical({"seq": seq, "prev_hash": prev, "entry_hash": entry_hash,
                                 "kind": entry["kind"], "key": entry["key"],
                                 "payload": entry["payload"], "at": entry["at"]}))
        anchors.append(_canonical({"seq": seq, "kind": entry["kind"],
                                   "entry_hash": entry_hash}))
        prev = entry_hash
    tail = "\n" if lines else ""
    (led_dir / contract.LEDGER).write_text("\n".join(lines) + tail, encoding="utf-8")
    (anc_dir / "ledger.anchors.jsonl").write_text("\n".join(anchors) + tail,
                                                  encoding="utf-8")
    return prev


# ── ответ читающей модели ────────────────────────────────────────────────────────


def _identity_of(value) -> Optional[str]:
    """Личность элемента списка или ``None``, если её НЕТ (а не «есть пустая»).

    Строка личностью НЕ является. Так было до цикла #916, и именно этим
    «ответ НЕ ТРОНУТ» оказался неправдой: одинаковые строки списка получали
    ОДИН путь и схлопывались в один лист, поэтому список, выросший с одной
    копии причины до девяти, выглядел неизменившимся (замер 23.10 на живой
    ленте: 4 554 расхождения, которых прибор не видел вовсе).
    """
    if isinstance(value, dict):
        for key in ID_KEYS:
            if isinstance(value.get(key), (str, int)) and not isinstance(value.get(key), bool):
                return f"{key}={value[key]}"
    return None


def _item_key(value, index: int) -> str:
    identity = _identity_of(value)
    return identity if identity is not None else f"#{index}"


def _content_token(value) -> str:
    """Канонический слепок значения — личность элемента в МУЛЬТИМНОЖЕСТВЕ."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def leaves(obj, prefix: str = "", out: Optional[Dict[str, str]] = None,
           undeclared: Optional[Set[str]] = None) -> Dict[str, str]:
    """Словарь → ``путь → значение``. Элементы списков адресуются по ЛИЧНОСТИ.

    Личности нет ⇒ элемент адресуется МУЛЬТИМНОЖЕСТВЕННО: канонический слепок
    содержимого плюс НОМЕР ПОВТОРА. Перестановка при этом невидима (её в ответе
    и нет — порядок обхода кандидатов не есть утверждение), а появление второй
    копии видно, потому что вторая копия получает свой номер.

    Исключение одно и ОБЪЯВЛЕНО: :data:`RANKED_LISTS` — там место ЕСТЬ ранг.
    Список словарей БЕЗ личности, не объявленный ни в :data:`ORDER_FREE_LISTS`,
    ни в :data:`RANKED_LISTS`, кладётся в ``undeclared``, и вызывающий обязан
    ответить НЕ ИЗМЕРЕНО: выбор природы — замер, а не умолчание.
    """
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for key in obj:
            leaves(obj[key], f"{prefix}.{key!s}" if prefix else str(key), out,
                   undeclared)
    elif isinstance(obj, list):
        where = generic_path(prefix)
        ranked = where in RANKED_LISTS
        if (undeclared is not None and not ranked and where not in ORDER_FREE_LISTS
                and any(isinstance(value, dict) and _identity_of(value) is None
                        for value in obj)):
            undeclared.add(where)
        seen: Dict[str, int] = {}
        for index, value in enumerate(obj):
            identity = _identity_of(value)
            if identity is not None:
                item = identity
            elif ranked:
                item = f"#{index}"
            else:
                token = _content_token(value)
                repeat = seen.get(token, 0)
                seen[token] = repeat + 1
                item = f"={token}#{repeat}"
            leaves(value, f"{prefix}[{item}]", out, undeclared)
    else:
        out[prefix] = repr(obj)
    return out


def answer_leaves(data_dir: Path, now: dt.datetime,
                  undeclared: Optional[Set[str]] = None) -> Dict[str, str]:
    """Оба публичных входа читающей модели, разложенные в листья."""
    from spa_core.research_factory import read as rf_read  # noqa: PLC0415

    return leaves({"latest": rf_read.latest(Path(data_dir)),
                   "cio_view": rf_read.cio_view(Path(data_dir), now)},
                  undeclared=undeclared)


def candidate_ids(answer: Dict[str, str]) -> Set[str]:
    return {path.split(_CANDIDATE_PREFIX, 1)[1].split("]", 1)[0]
            for path in answer if path.startswith(_CANDIDATE_PREFIX)}


# ── структурный маршрут ──────────────────────────────────────────────────────────


def newest_snapshot_at(entries: Iterable[dict]) -> Dict[str, dt.datetime]:
    """Кандидат → момент его САМОГО СВЕЖЕГО ``candidate_snapshot``.

    Ключ строки — ``[kind, candidate_id, …]``; кандидат без разобранной отметки в
    словарь не попадает (его нечем сравнить с окном), и это видно по числу.
    """
    newest: Dict[str, dt.datetime] = {}
    for entry in entries:
        if entry.get("kind") != "candidate_snapshot":
            continue
        key = entry.get("key") or []
        if len(key) < 2 or not isinstance(key[1], str):
            continue
        moment = _parse_at(entry.get("at"))
        if moment is None:
            continue
        known = newest.get(key[1])
        if known is None or moment > known:
            newest[key[1]] = moment
    return newest


def structural_lost(newest: Dict[str, dt.datetime], horizon: dt.datetime,
                    window_days: int) -> Set[str]:
    """Кандидаты, у которых свежайший снимок старше окна — то есть усечение их съест."""
    edge = horizon - dt.timedelta(days=window_days)
    return {cid for cid, moment in newest.items() if moment < edge}


# ── замер ────────────────────────────────────────────────────────────────────────


def _unmeasured(reason: str, *, now: Optional[dt.datetime] = None, **extra) -> dict:
    doc = {"schema": VERSION, "generated_at": (now or _utcnow()).isoformat(),
           "measured": False, "status": STATUS_UNMEASURED, "reason": reason,
           "rows": [], "findings": []}
    doc.update(extra)
    return doc


def measure(data_dir: Path, *, now: Optional[dt.datetime] = None,
            windows: Sequence[int] = WINDOWS,
            work_dir: Optional[Path] = None) -> dict:
    """Замер по живой ленте ``data_dir``. Живой каталог только ЧИТАЕТСЯ."""
    from spa_core.research_factory import contract  # noqa: PLC0415

    moment = now or _utcnow()
    source = Path(data_dir)
    ledger_path = source / contract.DATA_SUBDIR / contract.LEDGER
    if not ledger_path.is_file():
        return _unmeasured(f"ленты нет на диске: {ledger_path}", now=moment)
    try:
        entries = load_entries(ledger_path)
    except (OSError, ValueError) as exc:
        return _unmeasured(f"лента не прочитана ({type(exc).__name__}): {exc}", now=moment)
    if len(entries) < 2:
        return _unmeasured(f"в ленте {len(entries)} запис(ей) — усекать нечего",
                           now=moment)
    #: Отметки разбираются ОДИН раз и ВСЕ: запись, чью отметку не разобрали, нельзя
    #: ни оставить, ни выбросить — подстановка соседней датой сделала бы «не
    #: наблюдали» неотличимым от «наблюдали и вот значение» (инв. #17).
    stamps = [_parse_at(e.get("at")) for e in entries]
    unparsed = [n for n, moment_ in enumerate(stamps, start=1) if moment_ is None]
    if unparsed:
        return _unmeasured(
            f"отметки не разобраны у {len(unparsed)} запис(ей) из {len(entries)} "
            f"(первая — №{unparsed[0]}): какие из них попадают в окно, НЕ ИЗВЕСТНО",
            now=moment)
    #: После отказа выше `None` в списке не осталось ни одного — отсев здесь
    #: ничего не отсеивает и существует ради типа, а не ради поведения.
    moments: List[dt.datetime] = [s for s in stamps if s is not None]
    first_at, last_at = moments[0], moments[-1]
    span_days = (last_at - first_at).total_seconds() / 86400.0
    #: Горизонт — САМАЯ СВЕЖАЯ ЗАПИСЬ ленты, а не стенные часы: окно обязано
    #: мериться от того же момента, от которого читающая модель считает «сегодня»
    #: (`_derive_latest`), иначе замер двигался бы от простоя писателя.
    horizon = last_at
    ladder = sorted({int(w) for w in windows if 0 < int(w) < span_days})
    if not ladder:
        return _unmeasured(
            f"охват ленты {span_days:.2f} сут короче наименьшего окна лестницы "
            f"{sorted(int(w) for w in windows)[:1]} — усечение по возрасту сегодня "
            "не снимает ни одной записи", now=moment, span_days=round(span_days, 2))

    owned_tmp = work_dir is None
    root = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(
        prefix="spa_ledger_window_"))
    try:
        base_dir = root / "full" / "data"
        head = rechain(entries, base_dir)
        live_head = entries[-1].get("entry_hash")
        if head != live_head:
            return _unmeasured(
                "пересборка полной цепи НЕ воспроизводит вершину живой ленты "
                f"({head} против {live_head}) — сцена есть другая лента, и ни одно "
                "число прибора не относится к измеряемой", now=moment)
        undeclared: Set[str] = set()
        try:
            base_answer = answer_leaves(base_dir, moment, undeclared=undeclared)
        except Exception as exc:  # noqa: BLE001 — любой отказ модели = НЕ ИЗМЕРЕНО
            return _unmeasured(f"читающая модель не ответила на ПОЛНОЙ ленте "
                               f"({type(exc).__name__}): {exc}", now=moment)
        if undeclared:
            #: Список без личности и без объявленной природы адресуется ПО МЕСТУ,
            #: а место в ответе читающей модели двигает САМО усечение — прибор
            #: мерил бы собственную адресацию (замер: 9 «изменившихся» листьев
            #: при полностью совпадающем множестве пар).
            return _unmeasured(
                "в ответе есть списки без личности, природа которых НЕ ОБЪЯВЛЕНА: "
                + ", ".join(sorted(undeclared))
                + " — объявить их в ORDER_FREE_LISTS (порядок не часть ответа) "
                  "или в RANKED_LISTS (место есть ранг); до этого прибор мерил бы "
                  "собственную адресацию", now=moment)
        absent = [leaf for leaf in CHAIN_IDENTITY_LEAVES if leaf not in base_answer]
        if absent:
            return _unmeasured(
                "объявленные листья цепи отсутствуют в ответе читающей модели: "
                + ", ".join(absent)
                + " — список исключений описывает ДРУГОЙ ответ, и доля зависимости "
                  "считалась бы с вычетом, который ничего не вычитает", now=moment)
        base_cids = candidate_ids(base_answer)
        newest = newest_snapshot_at(entries)

        rows: List[dict] = []
        for window in ladder:
            edge = horizon - dt.timedelta(days=window)
            kept = [e for e, at in zip(entries, moments) if at >= edge]
            scene = root / f"w{window}" / "data"
            rechain(kept, scene)
            try:
                window_answer = answer_leaves(scene, moment)
            except Exception as exc:  # noqa: BLE001
                rows.append({"window_days": window, "measured": False,
                             "kept_entries": len(kept),
                             "reason": f"читающая модель не ответила на окне "
                                       f"{window} сут ({type(exc).__name__}): {exc}"})
                shutil.rmtree(scene.parent, ignore_errors=True)
                continue
            shutil.rmtree(scene.parent, ignore_errors=True)
            union = set(base_answer) | set(window_answer)
            changed = {p for p in union if base_answer.get(p) != window_answer.get(p)}
            chain_only = sorted(changed & set(CHAIN_IDENTITY_LEAVES))
            dependent = changed - set(CHAIN_IDENTITY_LEAVES)
            lost_diff = base_cids - candidate_ids(window_answer)
            lost_struct = structural_lost(newest, horizon, window)
            rows.append({
                "window_days": window, "measured": True,
                "kept_entries": len(kept), "dropped_entries": len(entries) - len(kept),
                "answer_leaves": len(window_answer),
                "changed_leaves": len(dependent),
                "dependent_share_pct": round(100.0 * len(dependent) / len(union), 2),
                "chain_identity_leaves_changed": chain_only,
                "candidates_lost_differential": len(lost_diff),
                "candidates_lost_structural": len(lost_struct),
                "routes_agree": lost_diff == lost_struct,
            })

        disagreed = [r for r in rows if r.get("measured") and not r["routes_agree"]]
        if disagreed:
            names = ", ".join(f"{r['window_days']} сут "
                              f"(дифф. {r['candidates_lost_differential']} против "
                              f"структурно {r['candidates_lost_structural']})"
                              for r in disagreed)
            return _unmeasured(
                "два независимых маршрута НЕ СОШЛИСЬ на окнах: " + names
                + " — прибор не знает ответа, и среднее из двух было бы выдумкой",
                now=moment, rows=rows)

        measured_rows = [r for r in rows if r.get("measured")]
        if not measured_rows:
            return _unmeasured("ни одно окно лестницы не измерено: "
                               + " · ".join(str(r.get("reason")) for r in rows),
                               now=moment, rows=rows)

        safe = [r["window_days"] for r in measured_rows if r["changed_leaves"] == 0]
        one_day = next((r["dependent_share_pct"] for r in measured_rows
                        if r["window_days"] == 1), None)
        findings: List[dict] = []
        if not safe:
            widest = max(measured_rows, key=lambda r: r["window_days"])
            findings.append({
                "kind": FINDING_NO_SAFE_WINDOW,
                "text": (f"ни одно окно лестницы не сохраняет ответ: даже "
                         f"{widest['window_days']} сут из {span_days:.2f} сут ленты "
                         f"меняют {widest['dependent_share_pct']} % листьев и теряют "
                         f"{widest['candidates_lost_differential']} кандидат(ов) — "
                         "усечение по ВОЗРАСТУ не доступно как лекарство росту"),
            })
        doc = {
            "schema": VERSION,
            "generated_at": moment.isoformat(),
            "measured": True,
            "reason": None,
            "ledger": {
                "path": str(ledger_path),
                "entries": len(entries),
                "bytes": ledger_path.stat().st_size,
                "span_days": round(span_days, 2),
                "head_hash": head,
                "horizon": horizon.isoformat(),
            },
            "baseline": {"answer_leaves": len(base_answer), "candidates": len(base_cids)},
            "rows": rows,
            #: ТО САМОЕ число заказа G787 п. 1: доля ответа, зависящая от записей
            #: старше суток. ``None`` = окна в сутки в лестнице не было.
            "one_day_dependent_share_pct": one_day,
            #: Наименьшее окно, при котором ответ не меняется. ``None`` — не «ноль»,
            #: а «безопасного N в лестнице НЕТ» (инв. #17).
            "safe_window_days": min(safe) if safe else None,
            "findings": findings,
            "advisory": True,
        }
        doc["status"] = STATUS_FINDINGS if findings else STATUS_CLEAN
        return doc
    finally:
        if owned_tmp:
            shutil.rmtree(root, ignore_errors=True)


# ── такт и шаг ───────────────────────────────────────────────────────────────────


def measurement_due(out: Path, *, now: Optional[dt.datetime] = None,
                    tact_days: int = MEASUREMENT_TACT_DAYS) -> Tuple[bool, str]:
    """Пора ли переизмерять — решает ФАЙЛ, а не расписание запуска.

    Три исхода различимы (инв. #17): артефакта нет ⇒ пора; отметка не разобрана ⇒
    тоже пора, потому что «не смогли прочитать, когда мерили» не имеет права
    означать «мерили недавно»; отметка свежее такта ⇒ не пора, и это ЗАМЕР.
    """
    moment = now if now is not None else _utcnow()
    target = Path(out)
    if not target.is_file():
        return True, "артефакта нет — первый замер"
    try:
        raw = json.loads(target.read_text(encoding="utf-8")).get("generated_at")
        last = dt.datetime.fromisoformat(str(raw))
    except (OSError, ValueError, TypeError) as exc:
        return True, f"отметка прошлого замера не прочитана ({type(exc).__name__}) — мерим"
    if last.tzinfo is None:
        return True, "отметка прошлого замера без пояса — мерим"
    age_days = (moment - last).total_seconds() / 86400.0
    if age_days >= tact_days:
        return True, (f"со дня замера {last.isoformat()} прошло {age_days:.1f} дн "
                      f"(такт {tact_days})")
    return False, (f"со дня замера {last.isoformat()} прошло {age_days:.1f} дн "
                   f"из {tact_days}")


def run(root: Optional[str] = None, *, data_dir: Optional[str] = None,
        dest: Optional[str] = None, write: bool = True, if_due: bool = False,
        now: Optional[dt.datetime] = None,
        tact_days: int = MEASUREMENT_TACT_DAYS,
        windows: Sequence[int] = WINDOWS) -> dict:
    """Шаг моста: внутри такта НЕ мерить и НЕ выдумывать вердикт."""
    tree = Path(root) if root else _ROOT
    source = Path(data_dir) if data_dir is not None else tree / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    if if_due:
        due, why = measurement_due(target, now=now, tact_days=tact_days)
        if not due:
            return {"measured": False, "reason": why, "artifact": str(target)}
    doc = measure(source, now=now, windows=windows)
    if write:
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def format_report(doc: dict) -> List[str]:
    out = [f"ЦЕНА усечения ленты research_factory по возрасту ({VERSION})"]
    if not doc.get("measured"):
        out.append(f"  НЕ ИЗМЕРЕНО: {doc.get('reason')}")
        return out
    led = doc.get("ledger") or {}
    base = doc.get("baseline") or {}
    out.append(f"  лента: записей {led.get('entries')} · {led.get('bytes')} Б · "
               f"охват {led.get('span_days')} сут · вершина сцены сошлась с живой")
    out.append(f"  полный ответ: листьев {base.get('answer_leaves')} · "
               f"кандидатов {base.get('candidates')}")
    for row in doc.get("rows") or []:
        if not row.get("measured"):
            out.append(f"  {row.get('window_days')} сут: НЕ ИЗМЕРЕНО — {row.get('reason')}")
            continue
        out.append(f"  {row['window_days']:>3} сут: остаётся {row['kept_entries']} зап. · "
                   f"зависит {row['dependent_share_pct']} % ответа · "
                   f"кандидатов теряется {row['candidates_lost_differential']} "
                   f"(оба маршрута сошлись)")
    share = doc.get("one_day_dependent_share_pct")
    out.append("  ДОЛЯ ОТВЕТА, зависящая от записей старше СУТОК: "
               + ("НЕ ИЗМЕРЕНА (окна в сутки в лестнице не было)"
                  if share is None else f"{share} %"))
    safe = doc.get("safe_window_days")
    out.append("  наименьшее безопасное окно: "
               + ("НЕТ НИ ОДНОГО в лестнице" if safe is None else f"{safe} сут"))
    for finding in doc.get("findings") or []:
        out.append(f"  🔴 [{finding['kind']}] {finding['text']}")
    out.append("  ADVISORY: прибор только ЧИТАЕТ; живая лента не тронута")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись цены усечения ленты research_factory по возрасту "
                    "(заказ G787 п. 1)")
    ap.add_argument("--data-dir", default=None,
                    help="каталог data/ с живой лентой (ТОЛЬКО читается)")
    ap.add_argument("--tree-root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--if-due", action="store_true",
                    help=f"мерить только если со дня прошлого замера прошло "
                         f"{MEASUREMENT_TACT_DAYS} дн (прогон стои́т минуты)")
    ap.add_argument("--windows", default=None,
                    help="лестница окон в сутках через запятую "
                         f"(по умолчанию {','.join(str(w) for w in WINDOWS)})")
    args = ap.parse_args(argv)
    windows: Sequence[int] = WINDOWS
    if args.windows:
        try:
            windows = tuple(int(part) for part in args.windows.split(",") if part.strip())
        except ValueError:
            print("НЕ ИЗМЕРЕНО: лестница окон не разобрана — ожидались целые сутки "
                  "через запятую")
            return 2
    res = run(root=args.tree_root, data_dir=args.data_dir, dest=args.out,
              write=not args.no_write, if_due=args.if_due, windows=windows)
    if not res.get("measured"):
        print(f"перепись не проводилась: {res.get('reason')}")
        return 0
    doc = res["doc"]
    print("\n".join(format_report(doc)))
    if not doc.get("measured"):
        return 2
    return 1 if doc.get("findings") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
