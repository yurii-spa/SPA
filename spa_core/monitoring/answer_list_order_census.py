"""Перепись СПИСКОВ ответа читающей модели: чем задан их ПОРЯДОК (заказ G799 п. 2).

ADR-799 нашёл класс: список в ответе `research_factory.read`, чей ПОРЯДОК есть
функция МЕСТА записи в ленте, а не функция МНОЖЕСТВА. Носителей тогда нашлось два
(`registry.all_candidate_ids` и `read._sherlock_block`), и второй был назван ЗАМЕРОМ,
а не чтением кода. Границы ADR-799 назвали остаток честно:

    «третьего носителя класса никто не искал исчерпывающе. Сегодняшнее согласие
    строгой и порядко-слепой мер — ЗАМЕР на одной сцене, а не доказательство, что
    списков, адресуемых по месту, в ответе больше нет.»

Эта перепись и есть то население. Она отвечает ровно на один вопрос:

    у КАЖДОГО списка ответа — его порядок задан множеством, рангом или ничем,
    и СОГЛАСЕН ли этот ответ с тем, что о списке объявлено?

## Почему прежние приборы на этот вопрос не отвечают

Рядом работает `ledger_window_dependency_census`, и он к этому классу слеп ПО
ПОСТРОЕНИЮ — не по недосмотру. Он раскладывает ответ в ЛИСТЬЯ, адресуя элементы
списков по ЛИЧНОСТИ (`candidate_id`), а при её отсутствии — МУЛЬТИМНОЖЕСТВЕННО
(слепок содержимого + номер повтора). Обе адресации порядок СТИРАЮТ, и это для его
вопроса верно: «изменится ли ответ от усечения» не должно зависеть от перестановки.
Но ровно поэтому список, чей порядок уехал к читателю артефактом места в ленте,
в его числах не виден. Замер: `latest.sherlock.decisions_today` — список словарей
С личностью, то есть у соседа он адресуется по личности и порядок его невидим; при
этом ADR-799 нашёл его ВТОРЫМ носителем класса. Сосед был зелёным и прав.

Отсюда и разделение предметов: сосед мерит ЦЕНУ УСЕЧЕНИЯ, эта перепись — ПРИРОДУ
ПОРЯДКА. Объявления `ORDER_FREE_LISTS`/`RANKED_LISTS` у соседа существуют ради его
собственной адресации (два списка, у которых личности нет вовсе) и населением этого
класса не являются: списков в ответе 37.

## Чем меряется природа порядка — ПЕРЕСТАНОВКА, а не усечение

Усечение меняет и содержимое, и порядок разом, поэтому «порядок сдвинулся» в нём
неотделимо от «запись исчезла». Нужна проба, которая меняет МЕСТО записи, не меняя
того, что записано.

Такая проба — **перестановка предметов**. Предмет записи это кандидат, которого она
касается; лента переставляется так, что ПОРЯДОК ПРЕДМЕТОВ меняется, а внутри каждого
предмета относительный порядок его записей СОХРАНЯЕТСЯ. Тогда «свежайшая запись
предмета» — та же самая, содержимое ответа обязано совпасть, и любой список, чья
ПОСЛЕДОВАТЕЛЬНОСТЬ при этом сдвинулась, есть носитель класса.

**Предмет разрешается ПО ЛЕНТЕ, и на этом можно ошибиться дважды — ошибся.**
`paper_mark` живёт под номером ПОЗИЦИИ, а не кандидата (`key[1]`), а номер позиции
лежит в ПОЛЕЗНОЙ НАГРУЗКЕ записи открытия, а не в её ключе (в ключе там номер
допуска). Первые две редакции пробы группировали по `key[1]` и по `key[2]`
открытия — и обе разорвали марки от их открытия: `nav()` берёт строку с
НАИБОЛЬШИМ `seq`, поэтому все 16 позиций кандидата `3e20c5e9…` уехали в
`NEVER_MARKED`, а 10 012,53 $ NAV — в 10 000,00 $. Проба при этом не соврала:
множество листьев разошлось, и вердикт был **НЕ ИЗМЕРЕНО с названной причиной**, а
не «носитель». Разрешение предмета через `payload.position_id` закрыло обе ошибки
(:func:`subject_map`).

Сохранность содержимого не предполагается, а ПРОВЕРЯЕТСЯ на каждом списке отдельно:
совпало множество ⇒ о порядке судить можно; не совпало ⇒ **НЕ ИЗМЕРЕНО** по этому
списку (инв. #17), и перестановка объявляется негодной для него, а не он — носителем.

Перестановок ДВЕ (обращение порядка предметов и порядок по слепку имени предмета):
список, чей порядок есть функция места, мог бы случайно уцелеть под одной
перестановкой, и «уцелел под одной» не есть «порядок устойчив».

## Три природы, и объявление обязано быть ЗАМЕРОМ, а не трактовкой

* ``RANKED`` — место ЕСТЬ часть ответа (ранг). Читатель вправе на него опираться,
  поэтому сдвиг порядка здесь — НАХОДКА.
* ``SET_DERIVED`` — порядок есть функция множества либо свойство самой записи
  (сортировка по постоянному ключу, список из полезной нагрузки). Ранга не несёт,
  но воспроизводим; сдвиг — НАХОДКА, потому что опровергает объявление.
* ``MULTISET`` — порядок не несёт утверждения ВОВСЕ, и сдвиг для него ожидаем.

``MULTISET`` — единственная природа, которой сдвиг прощается, то есть единственная,
которой можно было бы погасить находку. Поэтому она держится замером, а не словом:
объявить её списку, элементы которого НЕСУТ личность, нельзя — такой список можно
и должно упорядочить по личности, и объявление `MULTISET` на нём есть находка
(``multiset_declared_for_identifiable_list``). Население `MULTISET` сегодня — один
список `latest.stale_feeds`, у чьих `{source_root, age_h}` личности нет вовсе.

## Чего перепись НЕ делает и НЕ закрывает

Ничего не чинит, в ленту не пишет НИ БАЙТА, ни один гейт её не читает — она
ADVISORY. Объявления природы сняты с ЗАМЕРА (прогон на живой ленте 24.10), и у
этого есть цена, названная вслух: прибор, у которого объявление взято из его же
вердикта, НЕ способен поймать список, который был носителем УЖЕ в день переписи.
Он ловит другое, и этого по заказу довольно: (а) НОВЫЙ список ответа без
объявленной природы — красный сразу; (б) СМЕНУ вердикта у объявленного списка —
то есть возврат ADR-799 или новый носитель; (в) `MULTISET`, объявленный списку с
личностью. День нулевой держится не объявлением, а положительными контролями на
НАСТОЯЩИХ носителях ADR-799 (`test_answer_list_order_census.py`).

**ПУСТОЕ объявление перепись назвать не умеет, и это сказано, а не закрыто нулём.**
Сосед `ledger_window_dependency_census` вправе краснеть на вычет несуществующего
листа: его список исключений мерится против ОДНОГО ответа — живого. Здесь не так:
объявление, которого ЭТА лента не задела, может быть и мёртвым, и просто не
проверенным этой лентой (рукав без решений сегодня пуст законно), а по одной ленте
эти два состояния неразличимы. Поэтому они не сливаются в находку: третий исход
`unexercised_declarations` называется и печатается. Замер 24.10 на живой ленте: не
задействованных объявлений **ноль**, то есть каждое из 37 проверено ответом.

# LLM_FORBIDDEN
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from spa_core.monitoring import ledger_window_dependency_census as lwd
from spa_core.utils.atomic import atomic_save

VERSION = "answer-list-order/1"
ARTIFACT = "answer_list_order.json"
SELF_REL = "spa_core/monitoring/answer_list_order_census.py"

#: Такт недельный: прогон поднимает настоящую читающую модель трижды на полной
#: ленте и стои́т десятки секунд. Срок решает ФАЙЛ артефакта, а не расписание
#: бегуна — иначе «раз в неделю» держалось бы на том, что никто не звал прибор.
MEASUREMENT_TACT_DAYS = 7

RANKED = "RANKED"
SET_DERIVED = "SET_DERIVED"
MULTISET = "MULTISET"
NATURES = (RANKED, SET_DERIVED, MULTISET)

STATUS_CLEAN = "CLEAN"
STATUS_FINDINGS = "FINDINGS"
STATUS_UNMEASURED = "UNMEASURED"

#: Исходы вопроса «пора ли мерить». Третий — отдельное значение, а не True.
DUE = "DUE"
NOT_DUE = "NOT_DUE"
DUE_UNMEASURED = "DUE_UNMEASURED"

VERDICT_STABLE = "ORDER_STABLE"
VERDICT_MOVED = "ORDER_MOVED"
VERDICT_UNMEASURED = "UNMEASURED"

FINDING_UNDECLARED = "undeclared_list_nature"
FINDING_MOVED = "declared_order_moved_under_permutation"
#: Объявление, которого ЭТА лента не задела, находкой НЕ является: «списка в ответе
#: нет» и «объявление не защищает ни от чего» — два разных утверждения, и по одной
#: ленте они неразличимы (рукав без решений сегодня пуст законно). Третий исход
#: (инв. #17) — поле ``unexercised_declarations``, названное и напечатанное.
UNEXERCISED = "declaration_not_exercised_by_this_ledger"
FINDING_MULTISET_WITH_IDENTITY = "multiset_declared_for_identifiable_list"

#: Природа порядка КАЖДОГО списка ответа. Ключ — обезличенный путь
#: (:func:`ledger_window_dependency_census.generic_path`); сегмент ``*`` в ключе
#: означает «любой ключ словаря на этом месте» и существует ради путей, чей
#: сегмент есть ДАННЫЕ, а не строение (имена групп корреляции приходят из самих
#: кандидатов, и новая группа не есть новый список).
#:
#: Население замерено 2026-10-24 на живой ленте (25 519 записей): 37 списков.
DECLARED: Dict[str, str] = {
    # ── cio_view ────────────────────────────────────────────────────────────────
    # Все три списка состояний набираются ``.append(cid)`` в обходе
    # ``registry.all_candidate_ids(ledger)``, который ADR-799 сделал функцией
    # МНОЖЕСТВА. До ADR-799 они были носителями класса — поэтому их вердикт и есть
    # то, что сторожит возврат той правки.
    "cio_view.observe_only": SET_DERIVED,
    "cio_view.paper_active": SET_DERIVED,
    "cio_view.cio_eligible": SET_DERIVED,
    # Группы строятся ``dedup.correlation_groups`` из того же обхода.
    "cio_view.correlation_groups.*": SET_DERIVED,
    # ── latest: списки кандидатов ───────────────────────────────────────────────
    "latest.candidates": SET_DERIVED,
    "latest.rejections": SET_DERIVED,
    "latest.sherlock.decisions_today": SET_DERIVED,
    # ── latest: место ЕСТЬ ранг ─────────────────────────────────────────────────
    # ``sorted(..., key=(-count, gate))[:5]`` — место в списке есть часть ответа.
    "latest.sherlock.top_blockers": RANKED,
    # ── latest: порядок не несёт утверждения вовсе ──────────────────────────────
    # ``{source_root, age_h}`` без личности (``defillama:yields`` повторяется
    # девять раз). Единственная природа, которой сдвиг прощается.
    "latest.stale_feeds": MULTISET,
    # ── latest: списки внутри кандидата ─────────────────────────────────────────
    # Приходят из полезной нагрузки свежайшей записи либо из ``sorted`` по оценкам;
    # порядок есть свойство ЗАПИСИ, а не места записи в ленте.
    "latest.candidates[*].reasons": SET_DERIVED,
    "latest.candidates[*].evidence.measured": SET_DERIVED,
    "latest.candidates[*].evidence.documented": SET_DERIVED,
    "latest.candidates[*].evidence.unknown": SET_DERIVED,
    "latest.candidates[*].evidence.blocking_gaps": SET_DERIVED,
    "latest.candidates[*].evidence.circularity_concerns": SET_DERIVED,
    "latest.candidates[*].evidence.issuer_asserted_roles": SET_DERIVED,
    "latest.candidates[*].evidence.latest_decision.failed_gates": SET_DERIVED,
    "latest.candidates[*].evidence.latest_decision.unknown_gates": SET_DERIVED,
    "latest.candidates[*].evidence.latest_decision.required_next_evidence": SET_DERIVED,
    "latest.candidates[*].evidence.latest_decision.rationale": SET_DERIVED,
    "latest.candidates[*].counterparty_summary.concerns": SET_DERIVED,
    "latest.candidates[*].counterparty_summary.roles_named": SET_DERIVED,
    "latest.candidates[*].counterparty_summary.roles_unknown": SET_DERIVED,
    "latest.candidates[*].counterparty_summary.required_roles_missing": SET_DERIVED,
    "latest.candidates[*].counterparty_summary.dimensions_observed": SET_DERIVED,
    "latest.candidates[*].counterparty_summary.dimensions_documented": SET_DERIVED,
    "latest.candidates[*].counterparty_summary.dimensions_unknown": SET_DERIVED,
    "latest.rejections[*].reasons": SET_DERIVED,
    "latest.sherlock.decisions_today[*].failed_gates": SET_DERIVED,
    "latest.sherlock.decisions_today[*].unknown_gates": SET_DERIVED,
    "latest.sherlock.decisions_today[*].required_next_evidence": SET_DERIVED,
    "latest.sherlock.decisions_today[*].rationale": SET_DERIVED,
    # ── latest: отчёт уплотнителя истории ───────────────────────────────────────
    "latest.history_compaction.broken": SET_DERIVED,
}


def declared_nature(path: str) -> Optional[str]:
    """Объявленная природа списка или ``None``, если её НЕТ (а не «есть пустая»).

    Сначала точное совпадение, затем образцы с сегментом ``*``. Образец
    применяется только к пути ТОЙ ЖЕ длины в сегментах: иначе
    ``cio_view.correlation_groups.*`` накрыл бы и вложенные списки внутри группы,
    то есть объявление молча расширилось бы на то, чего никто не мерил.
    """
    exact = DECLARED.get(path)
    if exact is not None:
        return exact
    parts = path.split(".")
    for pattern, nature in DECLARED.items():
        if "*" not in pattern:
            continue
        shape = pattern.split(".")
        if len(shape) != len(parts):
            continue
        if all(want in ("*", have) for want, have in zip(shape, parts)):
            return nature
    return None


def _pattern_matches_nothing(pattern: str, paths: Iterable[str]) -> bool:
    """Не накрыло ли объявление ``pattern`` НИ ОДНОГО списка этого ответа."""
    shape = pattern.split(".")
    for path in paths:
        if path == pattern:
            return False
        parts = path.split(".")
        if len(parts) == len(shape) and all(w in ("*", h) for w, h in zip(shape, parts)):
            return False
    return True


# ── предмет записи ───────────────────────────────────────────────────────────────


def subject_map(entries: Iterable[dict]) -> Dict[str, str]:
    """Номер позиции → кандидат, по записям ОТКРЫТИЯ бумажной позиции.

    Номер позиции лежит в полезной НАГРУЗКЕ `paper_open`; в его КЛЮЧЕ на том же
    месте стои́т номер допуска. Группировка по ключу рвёт `paper_mark` от его
    открытия — замер этой ошибки назван в шапке модуля.
    """
    out: Dict[str, str] = {}
    for entry in entries:
        if entry.get("kind") != "paper_open":
            continue
        key = entry.get("key") or []
        position_id = (entry.get("payload") or {}).get("position_id")
        if position_id and len(key) >= 2 and isinstance(key[1], str):
            out[position_id] = key[1]
    return out


def subject_of(entry: dict, positions: Dict[str, str]) -> Tuple[str, str]:
    """Предмет записи — тот, чьи записи обязаны сохранить взаимный порядок.

    Запись прогона и запись без опознаваемого второго поля ключа предметом
    кандидата не являются и группируются по своему роду: переставлять их между
    собой значило бы менять «последний прогон», то есть содержимое ответа.
    """
    key = entry.get("key") or []
    if entry.get("kind") == "run" or len(key) < 2 or not isinstance(key[1], str):
        return ("kind", str(entry.get("kind")))
    return ("subject", positions.get(key[1]) or key[1])


def _subject_order(entries: Sequence[dict], positions: Dict[str, str],
                   rank_of) -> List[dict]:
    first: Dict[Tuple[str, str], int] = {}
    for index, entry in enumerate(entries):
        first.setdefault(subject_of(entry, positions), index)
    order = rank_of(sorted(first, key=lambda s: first[s]))
    rank = {subject: n for n, subject in enumerate(order)}
    return [entries[i] for i in sorted(
        range(len(entries)),
        key=lambda i: (rank[subject_of(entries[i], positions)], i))]


def permutations(entries: Sequence[dict]) -> List[Tuple[str, List[dict]]]:
    """Перестановки ленты, сохраняющие порядок записей ВНУТРИ каждого предмета.

    Две, а не одна: список, чей порядок есть функция места, мог бы случайно
    уцелеть под одной перестановкой, и «уцелел под одной» не есть «устойчив».
    """
    positions = subject_map(entries)
    return [
        ("обращение", _subject_order(entries, positions, lambda s: list(reversed(s)))),
        ("по слепку имени", _subject_order(
            entries, positions,
            lambda s: sorted(s, key=lambda x: hashlib.sha256(
                "".join(x).encode()).hexdigest()))),
    ]


# ── последовательности списков ───────────────────────────────────────────────────


def list_sequences(obj, prefix: str = "",
                   out: Optional[Dict[str, List[List[str]]]] = None
                   ) -> Dict[str, List[List[str]]]:
    """Обезличенный путь списка → ПОСЛЕДОВАТЕЛЬНОСТИ слепков его элементов.

    У одного обезличенного пути вхождений может быть много (сто кандидатов — сто
    вхождений `latest.candidates[*].reasons`), и они складываются списком в
    порядке обхода, чтобы вхождение сравнивалось со СВОИМ, а не с соседним.
    """
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for key in obj:
            list_sequences(obj[key], f"{prefix}.{key!s}" if prefix else str(key), out)
    elif isinstance(obj, list):
        out.setdefault(lwd.generic_path(prefix), []).append(
            [lwd._content_token(value) for value in obj])
        for index, value in enumerate(obj):
            list_sequences(value, f"{prefix}[{index}]", out)
    return out


def any_element_has_identity(obj, path: str, prefix: str = "") -> bool:
    """Несёт ли ХОТЯ БЫ один элемент списка ``path`` личность.

    Нужен ровно для одной проверки: `MULTISET`, объявленный списку с личностью,
    есть находка. Пустой список личности не несёт и под неё не попадает — это
    отсутствие наблюдения, а не наблюдённый ноль.
    """
    found = False
    if isinstance(obj, dict):
        for key in obj:
            found = any_element_has_identity(
                obj[key], path, f"{prefix}.{key!s}" if prefix else str(key)) or found
    elif isinstance(obj, list):
        if lwd.generic_path(prefix) == path:
            if any(lwd._identity_of(value) is not None for value in obj):
                return True
        for index, value in enumerate(obj):
            found = any_element_has_identity(
                value, path, f"{prefix}[{index}]") or found
    return found


def answer_of(entries: Sequence[dict], now: dt.datetime) -> dict:
    """Ответ читающей модели на сцене, собранной из ``entries``.

    Сцена живёт в одноразовом каталоге и снимается сразу: живой каталог этот
    прибор только ЧИТАЕТ.
    """
    from spa_core.research_factory import read as rf_read  # noqa: PLC0415

    scene = Path(tempfile.mkdtemp(prefix="answer_list_order_"))
    try:
        lwd.rechain(entries, scene)
        return {"latest": rf_read.latest(scene),
                "cio_view": rf_read.cio_view(scene, now)}
    finally:
        shutil.rmtree(scene, ignore_errors=True)


# ── замер ────────────────────────────────────────────────────────────────────────


def _live_head(ledger_path: Path) -> Optional[str]:
    """Вершина живой ленты или ``None``, если её нечем прочитать."""
    try:
        lines = [ln for ln in ledger_path.read_text(encoding="utf-8").split("\n") if ln.strip()]
    except OSError:
        return None
    if not lines:
        return None
    try:
        return json.loads(lines[-1]).get("entry_hash")
    except json.JSONDecodeError:
        return None


def measure(ledger_path: Path, *, now: dt.datetime) -> dict:
    """Перепись: население списков, природа каждого, согласие замера с объявлением.

    Положительный контроль построения сцены — вершина полной пересборки обязана
    совпасть с вершиной ЖИВОЙ ленты. Не совпала ⇒ **НЕ ИЗМЕРЕНО**: все остальные
    числа в этом случае говорят о чужой ленте.
    """
    ledger_path = Path(ledger_path)
    report: dict = {"version": VERSION, "generated_at": lwd._utcnow().isoformat(),
                    "ledger": str(ledger_path), "status": STATUS_UNMEASURED,
                    "unmeasured_reason": None, "entries": None, "population": None,
                    "lists": {}, "findings": [], "permutations": [],
                    "unexercised_declarations": [], "carriers": [],
                    "unmeasured_lists": []}
    try:
        entries = lwd.load_entries(ledger_path)
    except (OSError, ValueError) as exc:
        report["unmeasured_reason"] = f"лента не прочитана: {exc}"
        return report
    report["entries"] = len(entries)
    if not entries:
        report["unmeasured_reason"] = "лента пуста — населения списков нет"
        return report

    base = answer_of(entries, now)
    live = _live_head(ledger_path)
    rebuilt = (base.get("latest") or {}).get("ledger_head_hash")
    if live is not None and rebuilt != live:
        report["unmeasured_reason"] = (
            f"пересобранная сцена не есть та же лента: вершина {rebuilt} против живой {live}")
        return report

    base_seq = list_sequences(base)
    report["population"] = len(base_seq)

    # вердикт по каждому списку: сведение по ВСЕМ перестановкам
    verdicts: Dict[str, dict] = {
        path: {"verdict": VERDICT_STABLE, "occurrences": len(seqs),
               "elements": sum(len(s) for s in seqs), "reason": None,
               "nature": declared_nature(path)}
        for path, seqs in base_seq.items()}

    for label, permuted in permutations(entries):
        other = list_sequences(answer_of(permuted, now))
        report["permutations"].append(label)
        for path, state in verdicts.items():
            # Старшинство вердиктов: MOVED > UNMEASURED > STABLE, и порядок перестановок
            # на итог не влияет. Сдвиг, ПОКАЗАННЫЙ одной годной перестановкой, есть
            # положительное наблюдение и негодностью ДРУГОЙ не отменяется; иначе вердикт
            # зависел бы от того, какая перестановка прошла первой, — то есть прибор
            # отвечал бы на вопрос «в каком порядке я мерил», а не на свой.
            if state["verdict"] == VERDICT_MOVED:
                continue
            mine, theirs = base_seq[path], other.get(path)
            if theirs is None or len(mine) != len(theirs):
                state["verdict"] = VERDICT_UNMEASURED
                state["reason"] = (f"перестановка «{label}»: число вхождений списка "
                                   f"изменилось ({len(mine)} против "
                                   f"{0 if theirs is None else len(theirs)})")
                continue
            if not all(sorted(a) == sorted(b) for a, b in zip(mine, theirs)):
                state["verdict"] = VERDICT_UNMEASURED
                state["reason"] = (f"перестановка «{label}» не сохранила СОДЕРЖИМОЕ этого "
                                   "списка — о порядке по ней судить нельзя")
                continue
            moved = sum(1 for a, b in zip(mine, theirs) if a != b)
            if moved:
                state["verdict"] = VERDICT_MOVED
                state["reason"] = (f"перестановка «{label}»: множество то же, ПОРЯДОК "
                                   f"сдвинулся у {moved} вхождени(я/й)")
            # сдвига не нашли — вердикт НЕ переписывается: если негодная перестановка
            # уже была, «устойчив» сказать нельзя (часть ответа пробой не покрыта),
            # а UNMEASURED здесь и остаётся

    findings: List[dict] = []
    for path, state in sorted(verdicts.items()):
        nature = state["nature"]
        if nature is None:
            findings.append({"finding": FINDING_UNDECLARED, "list": path,
                             "detail": "природа порядка не объявлена — «носителем не является» "
                                       "по этому списку есть НЕ ИЗМЕРЕНО, а не ноль"})
            continue
        if nature == MULTISET and any_element_has_identity(base, path):
            findings.append({"finding": FINDING_MULTISET_WITH_IDENTITY, "list": path,
                             "detail": "элементы НЕСУТ личность — такой список можно упорядочить "
                                       "по ней, и MULTISET на нём гасит находку, а не называет природу"})
        if state["verdict"] == VERDICT_MOVED and nature in (RANKED, SET_DERIVED):
            findings.append({"finding": FINDING_MOVED, "list": path, "nature": nature,
                             "detail": state["reason"]})

    unexercised: List[str] = []
    for pattern in sorted(DECLARED):
        if _pattern_matches_nothing(pattern, base_seq):
            unexercised.append(pattern)

    report["lists"] = {path: {k: v for k, v in state.items()} for path, state in verdicts.items()}
    report["findings"] = findings
    report["unexercised_declarations"] = unexercised
    report["carriers"] = sorted(p for p, s in verdicts.items()
                                if s["verdict"] == VERDICT_MOVED)
    report["unmeasured_lists"] = sorted(p for p, s in verdicts.items()
                                        if s["verdict"] == VERDICT_UNMEASURED)
    if report["unmeasured_lists"]:
        report["status"] = STATUS_UNMEASURED
        report["unmeasured_reason"] = (
            f"{len(report['unmeasured_lists'])} список(ов) без вердикта о порядке")
    elif findings:
        report["status"] = STATUS_FINDINGS
    else:
        report["status"] = STATUS_CLEAN
    return report


def measurement_due(artifact: Path, *, now: dt.datetime) -> str:
    """Прошёл ли такт. Срок решает ФАЙЛ, а не расписание звавшего.

    Исходов ТРИ, и третий назван отдельным значением (инв. #17): артефакта нет
    вовсе — замера не было НИ РАЗУ, и это наблюдение, а не его отсутствие; срок
    ПРОЧИТАТЬ не удалось (каталог не читается, файл не разбирается, отметки в нём
    нет) — это **НЕ ИЗМЕРЕНО**, и выдавать его за «пора мерить» нельзя: «пора»
    и «неизвестно» ведут к разным действиям, а слитые вместе они прячут сломанный
    артефакт за обычным прогоном.
    """
    path = Path(artifact)
    if not path.exists():
        return DUE
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"{DUE_UNMEASURED}: артефакт не прочитан ({exc})"
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"{DUE_UNMEASURED}: артефакт не разобран ({exc})"
    stamp = lwd._parse_at(doc.get("generated_at"))
    if stamp is None:
        return f"{DUE_UNMEASURED}: в артефакте нет разобранной отметки generated_at"
    return (DUE if (now - stamp).total_seconds() >= MEASUREMENT_TACT_DAYS * 86400
            else NOT_DUE)


def _print(report: dict) -> None:
    print(f"перепись порядка списков ответа ({report['version']}): {report['status']}")
    print(f"  записей ленты: {report['entries']}  списков в ответе: {report['population']}")
    print(f"  перестановок: {len(report['permutations'])} "
          f"({', '.join(report['permutations']) or 'ни одной'})")
    if report["status"] == STATUS_UNMEASURED and report["population"] is None:
        print(f"  ⚠️ НЕ ИЗМЕРЕНО: {report['unmeasured_reason']}")
        return
    lists = report["lists"]
    stable = sum(1 for s in lists.values() if s["verdict"] == VERDICT_STABLE)
    moved = sum(1 for s in lists.values() if s["verdict"] == VERDICT_MOVED)
    unm = sum(1 for s in lists.values() if s["verdict"] == VERDICT_UNMEASURED)
    print(f"  порядок устойчив {stable} · сдвинулся {moved} · НЕ ИЗМЕРЕНО {unm}")
    for nature in NATURES:
        n = sum(1 for s in lists.values() if s["nature"] == nature)
        print(f"    объявлено {nature}: {n}")
    for path in report["carriers"]:
        print(f"  [НОСИТЕЛЬ] {path} — {lists[path]['reason']}")
    for path in report["unmeasured_lists"]:
        print(f"  [НЕ ИЗМЕРЕНО] {path} — {lists[path]['reason']}")
    for finding in report["findings"]:
        print(f"  [{finding['finding']}] {finding['list']} — {finding['detail']}")
    for pattern in report["unexercised_declarations"]:
        print(f"  [НЕ ЗАДЕЙСТВОВАНО] {pattern} — этой лентой объявление не проверено; "
              "«нет в ответе» не есть «не защищает» (инв. #17)")
    if not report["findings"]:
        print("  ✅ у каждого списка ответа природа ОБЪЯВЛЕНА и замер с ней согласен")
    print("  ADVISORY: прибор только ЧИТАЕТ, в ленту не пишет ни байта")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--data-dir", default=str(lwd._ROOT / "data"),
                        help="каталог данных (лента берётся из него)")
    parser.add_argument("--out", default=None, help="куда положить артефакт")
    parser.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    parser.add_argument("--if-due", action="store_true",
                        help="мерить только если прошёл такт (решает файл артефакта)")
    args = parser.parse_args(argv)

    from spa_core.research_factory import contract  # noqa: PLC0415

    data_dir = Path(args.data_dir)
    out = Path(args.out) if args.out else data_dir / ARTIFACT
    now = lwd._utcnow()
    if args.if_due:
        verdict = measurement_due(out, now=now)
        if verdict == NOT_DUE:
            print(f"такт не прошёл: артефакт {out} свежее {MEASUREMENT_TACT_DAYS} сут — "
                  "перепись не звалась")
            return 0
        if verdict != DUE:
            print(f"⚠️ НЕ ИЗМЕРЕНО: срок переписи не прочитан — {verdict}")
            return 2

    report = measure(data_dir / contract.DATA_SUBDIR / contract.LEDGER, now=now)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print(report)
    try:
        atomic_save(report, str(out))
    except OSError as exc:
        print(f"⚠️ артефакт не записан: {exc}")
        return 2
    if report["status"] == STATUS_UNMEASURED:
        return 2
    return 1 if report["status"] == STATUS_FINDINGS else 0


if __name__ == "__main__":
    sys.exit(main())
