"""Перепись ЦЕНЫ ПЕРЕСЪЁМКИ описания как лекарства росту ленты (заказ G793 п. 1).

Сосед `ledger_window_dependency_census` (ADR-793) закрыл одно лекарство и назвал
другое. Его замер: усечение ленты `research_factory/ledger.jsonl` по ВОЗРАСТУ
недоступно ни при каком N — даже окно 14 суток из 18.74 меняет 25.29 % ответа
читающей модели и теряет 30 кандидатов из 100. Механизм назван: кандидат живёт в
ответе, пока в ленте есть его `candidate_snapshot`, а переснимаются не все.

Отсюда следовало направление, и ADR-793 записал его дословно:

    не резать хвост, а **переснимать описание** — тогда у усечения появится
    безопасное N, и прибор это увидит СВОИМ ЖЕ числом.

Эта перепись и есть то число. Она отвечает на два вопроса заказа сразу:

    сколько БАЙТ В СУТКИ добавит периодическая пересъёмка описания — и
    какое БЕЗОПАСНОЕ ОКНО она откроет?

## Почему ответ меряется, а не выводится

Арифметика «100 кандидатов × 12 405 Б = 1.24 МБ/сут» отвечает только на первую
половину и ровно ничего не говорит о второй. Замер 2026-10-23 это и показал:
пересъёмка ОДНИХ кандидатов стоит +1.218 МБ/сут и **не открывает окна** — доля
зависимости падает с 33.29 % лишь до 18.98 %, потому что ответ держится ещё и на
`evidence_bundle`, `admission_decision` и на ПОЛНОЙ истории `transition`
кандидата (`latest.rejections` — это перечень причин за всю его жизнь).
Какие именно виды записей надо переснимать, чтобы окно открылось, из
рассуждения не выводится: это свойство читающей модели, и спросить его можно
только у неё.

## Как устроен замер

Рецепт — объявленный набор: какие виды записей переснимать (свежайшую на
кандидата либо ВСЕ его строки) и с каким тактом. По рецепту строится СЦЕНА:
настоящая лента плюс периодические повторы этих записей на сетке
``горизонт − k·такт``, так что возраст свежайшего описания у любого живого
кандидата никогда не превышает такта. Сцена перехеширована кодом самой ленты,
поэтому это настоящая лента, а не её модель.

Дальше работает СОСЕДНИЙ прибор, целиком и без правок: ``lwd.measure`` на
сцене даёт ту же лестницу окон, те же два независимых маршрута и то же
``safe_window_days``. Заказ прямо этого и просил — «прибор ответит СВОИМ ЖЕ
числом».

## Три положительных контроля, и каждый отвечает на свой вопрос

**1. Сцена есть та же лента.** Полная пересборка без пересъёмки обязана
воспроизвести вершину живой ленты байт в байт. Это контроль соседа, и он
исполняется его же кодом.

**2. Пересъёмка НЕЙТРАЛЬНА к ответу.** Лекарство, меняющее ответ на ПОЛНОЙ
ленте, лечит не ту болезнь: оно бы «открыло окно», подменив сам предмет. Поэтому
ответ полной сцены с пересъёмкой сверяется полистно с ответом живой ленты, и
расхождение — находка :data:`FINDING_NOT_NEUTRAL`, а не примечание. Замер
23.10.2026: 0 расхождений из 14 919 листьев.

**3. Без лекарства окна НЕТ.** Нулевой рецепт (``none``) гоняется той же
дорогой, что и остальные, и обязан воспроизвести вердикт ADR-793. Воспроизвёл
не он — значит сдвинулось что-то ещё, и числа рецептов не с чем сравнивать.

## Чего прибор НЕ делает

Ничего не чинит, ничего не переснимает и в живую ленту не пишет НИ БАЙТА:
живой каталог только читается, сцены живут в одноразовом каталоге и снимаются
сразу после замера. Ни один гейт этот прибор не читает — он ADVISORY. Выбор
лекарства и его такта остаётся РЕШЕНИЕМ; прибор называет цену каждого варианта.

# LLM_FORBIDDEN
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.monitoring import ledger_window_dependency_census as lwd
from spa_core.utils.atomic import atomic_save

_ROOT = Path(__file__).resolve().parents[2]

VERSION = "ledger-resnapshot-price/1"
ARTIFACT = "ledger_resnapshot_price.json"

STATUS_CLEAN = lwd.STATUS_CLEAN
STATUS_FINDINGS = lwd.STATUS_FINDINGS
STATUS_UNMEASURED = lwd.STATUS_UNMEASURED

#: Лист ответа, который есть ИМЯ САМОГО ЛЕКАРСТВА, а не утверждение о кандидате.
#: ``latest.history_compaction`` докладывает, какие ОБСЛУЖИВАЮЩИЕ строки сегодня в
#: ленте (ADR-795: OK · ABSENT · BROKEN — три значения, инв. #17). Сравнивать его в
#: контроле нейтральности нельзя по ПОСТРОЕНИЮ: он меняется ровно оттого, что
#: лекарство применено, и контроль отвечал бы на вопрос «применили ли лекарство»
#: вместо «сдвинуло ли оно ответ». Вычет ОГРАНИЧЕН префиксом одного названного
#: блока, его НАЛИЧИЕ в живом ответе проверяется (иначе это был бы вычет ничего), и
#: ни одного утверждения о кандидате внутри него нет. Положительный контроль, что
#: вычет не глушит настоящую находку, — ``test_candidate_history_compaction.py``
#: (уплотнение, РАЗМНОЖАЮЩЕЕ причины, по-прежнему ловится как не-нейтральное).
MEDICINE_PRESENCE_PREFIX = "latest.history_compaction."

#: Вид записи УПЛОТНЕНИЯ. Литерал, а не импорт, чтобы модуль прибора не тянул
#: `research_factory` на импорте; что литерал не разошёлся с каноном
#: (`history.KIND`), держит отдельное утверждение батареи.
COMPACTION_KIND = "candidate_history"

FINDING_NO_RECIPE = "no_resnapshot_recipe_opens_a_window"
FINDING_NOT_NEUTRAL = "resnapshot_changes_the_answer"
FINDING_BASELINE_DRIFTED = "zero_recipe_already_has_a_window"

#: Такт недельный — прогон поднимает настоящую читающую модель на каждом окне
#: КАЖДОГО рецепта и стои́т минуты. Срок решает ФАЙЛ, а не расписание бегуна.
MEASUREMENT_TACT_DAYS = 7

#: Лестница окон. Короче соседской намеренно: сосед искал, ЕСТЬ ЛИ окно вообще
#: (и ответил «нет ни одного»), а эта перепись ищет НАИМЕНЬШЕЕ открывшееся —
#: широкие окна тут ничего не решают, а стоят полного прогона модели.
WINDOWS: Tuple[int, ...] = (1, 2, 3, 7)

#: Окно, в котором меряется НАБЛЮДЁННЫЙ темп роста живой ленты. Делить весь
#: размер на весь охват было бы неверно: лента начата посевом 04.10, и посев
#: размазался бы по всем суткам как «рост».
GROWTH_WINDOW_DAYS = 7


class Recipe:
    """Объявленный способ переснимать описание.

    :param newest_kinds: виды, у которых переснимается СВЕЖАЙШАЯ запись кандидата
        (описание — оно одно, и старые редакции лекарству не нужны);
    :param all_kinds: виды, у которых переснимаются ВСЕ строки кандидата. Так
        ведёт себя `transition`: ответ держится на полной истории переходов
        (`latest.rejections` перечисляет причины за всю жизнь кандидата), и
        свежайшая строка её не заменяет. Это ВЕРХНЯЯ ОЦЕНКА цены уплотнения:
        строка, сводящая историю в одну запись, стоила бы не дороже.
    """

    def __init__(self, recipe_id: str, *, cadence_days: int,
                 newest_kinds: Sequence[str] = (), all_kinds: Sequence[str] = (),
                 synthesised_kinds: Sequence[str] = (),
                 substitutes: Optional[str] = None, note: str = "") -> None:
        self.id = recipe_id
        self.cadence_days = int(cadence_days)
        self.newest_kinds = tuple(newest_kinds)
        self.all_kinds = tuple(all_kinds)
        #: Виды, которых в живой ленте ЕЩЁ НЕТ: писатель их только получает, и прибор
        #: СОБИРАЕТ их содержимое сам, на каждом моменте сетки (ADR-795). Объявлены
        #: отдельным полем, а не спрятаны в флаг: сторож населения рецептов обязан
        #: видеть ВСЕ виды, которые рецепт приносит, иначе «разность соседей = цена
        #: вида» перестаёт быть правдой молча.
        self.synthesised_kinds = tuple(synthesised_kinds)
        #: Рецепт-ЗАМЕНА: он не прибавляет вид к соседу, а СТАВИТ СВОЙ ВМЕСТО его вида.
        #: Лестница у таких рецептов не аддитивна по построению, и приписывать им
        #: «разность с предыдущим» было бы ложью о том, что эта разность означает.
        self.substitutes = substitutes
        self.note = note

    @property
    def compaction(self) -> bool:
        """Несёт ли рецепт строку УПЛОТНЕНИЯ (ADR-795).

        Повтор `transition` накапливает причины (замер ADR-794: 4 554 листа), поэтому
        цену истории нельзя мерить её повтором. Строка уплотнения несёт историю В СЕБЕ,
        и читается только СВЕЖАЙШАЯ — поэтому её повтор не накапливает ничего.
        """
        return COMPACTION_KIND in self.synthesised_kinds

    @property
    def is_zero(self) -> bool:
        return not self.newest_kinds and not self.all_kinds and not self.synthesised_kinds


#: Население рецептов ОБЪЯВЛЕНО, а не перебирается: каждый следующий добавляет
#: ровно один вид к предыдущему, поэтому разница между соседними строками отчёта
#: и есть цена ЭТОГО вида. Нулевой рецепт — положительный контроль №3.
RECIPES: Tuple[Recipe, ...] = (
    Recipe("none", cadence_days=1,
           note="без лекарства — обязан воспроизвести вердикт ADR-793"),
    Recipe("snapshot", cadence_days=1, newest_kinds=("candidate_snapshot",),
           note="только описание кандидата — лекарство, названное ADR-793"),
    Recipe("snapshot+evidence", cadence_days=1,
           newest_kinds=("candidate_snapshot", "evidence_bundle",
                         "admission_decision"),
           note="плюс свежайший свод доказательств и решение о допуске"),
    Recipe("snapshot+evidence+history", cadence_days=1,
           newest_kinds=("candidate_snapshot", "evidence_bundle",
                         "admission_decision"),
           all_kinds=("transition",),
           note="плюс ПОЛНАЯ история переходов — верхняя оценка цены уплотнения"),
    Recipe("snapshot+evidence+history@3", cadence_days=3,
           newest_kinds=("candidate_snapshot", "evidence_bundle",
                         "admission_decision"),
           all_kinds=("transition",),
           note="тот же состав реже: цена падает, окно расширяется"),
    Recipe("snapshot+evidence+compaction", cadence_days=1,
           newest_kinds=("candidate_snapshot", "evidence_bundle",
                         "admission_decision"),
           synthesised_kinds=(COMPACTION_KIND,),
           substitutes="snapshot+evidence+history",
           note="тот же состав, но история СВЁРНУТА в строку уплотнения (ADR-795) "
                "ВМЕСТО повтора всех transition — лекарство ФОРМЕ, не цене"),
)


# ── сцена ────────────────────────────────────────────────────────────────────────


def live_candidate_ids(answer: Dict[str, str]) -> set:
    """Кандидаты, которых ОТВЕТ сегодня знает. Переснимать мёртвых незачем."""
    return lwd.candidate_ids(answer)


def _candidate_of(entry: dict) -> Optional[str]:
    key = entry.get("key") or []
    if len(key) < 2 or not isinstance(key[1], str):
        return None
    return key[1]


def resnapshot_rows(entries: Sequence[dict], stamps: Sequence[dt.datetime],
                    recipe: Recipe, live: set) -> List[dict]:
    """Записи ОДНОГО оборота пересъёмки — то, что писатель повторял бы каждый такт."""
    newest: Dict[Tuple[str, str], Tuple[dt.datetime, dict]] = {}
    every: List[dict] = []
    for entry, at in zip(entries, stamps):
        cid = _candidate_of(entry)
        if cid is None or cid not in live:
            continue
        kind = entry.get("kind")
        if kind in recipe.all_kinds:
            every.append(entry)
        elif kind in recipe.newest_kinds:
            slot = (kind, cid)
            known = newest.get(slot)
            if known is None or at > known[0]:
                newest[slot] = (at, entry)
    return [e for _, e in newest.values()] + every


def compaction_rows_at(entries: Sequence[dict], stamps: Sequence[dt.datetime],
                       moment: dt.datetime, live: set) -> List[dict]:
    """Строки УПЛОТНЕНИЯ, какие писатель мог бы записать В МОМЕНТ ``moment``.

    Содержимое считается ПО МОМЕНТУ, а не один раз на весь прогон, и это не
    аккуратность, а отказ от fail-OPEN: уплотнение, собранное на горизонте и
    вставленное на такт раньше, несло бы переходы, которых писатель в тот
    момент ВИДЕТЬ НЕ МОГ, и прибор объявил бы окно, которого нет. Нужды в этом
    нет и по сути: переходы моложе момента остаются в ленте сами — усечение их
    не трогает.
    """
    from spa_core.research_factory import history  # noqa: PLC0415

    seen: Dict[str, List[dict]] = {}
    for entry, at in zip(entries, stamps):
        if entry.get("kind") != "transition" or at > moment:
            continue
        cid = (entry.get("payload") or {}).get("candidate_id")
        if cid is None or cid not in live:
            continue
        seen.setdefault(cid, []).append(
            {"kind": "transition", "at": entry.get("at"),
             "payload": entry.get("payload") or {}})
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    out: List[dict] = []
    for cid in sorted(seen):
        out.append({"kind": history.KIND, "key": [history.KIND, cid, stamp],
                    "payload": history.build_payload(cid, seen[cid],
                                                     recorded_at=stamp),
                    "at": stamp})
    return out


def build_scene_entries(entries: Sequence[dict], stamps: Sequence[dt.datetime],
                        rows: Sequence[dict], cadence_days: int,
                        horizon: dt.datetime,
                        first: dt.datetime,
                        rows_for_moment=None) -> Tuple[List[dict], int]:
    """Лента + периодические повторы ``rows`` на сетке ``горизонт − k·такт``.

    Сетка идёт НАЗАД от горизонта и начинается с ``k = 1``: свежайшая пересъёмка
    оказывается ровно на такт старше горизонта. Это ХУДШИЙ случай писателя с
    таким тактом — сетка, привязанная к началу ленты, дала бы описание моложе
    такта и завысила бы лекарство.

    ``rows_for_moment`` — рецепт, у которого содержимое записи ЗАВИСИТ ОТ
    МОМЕНТА (уплотнение истории, ADR-795). Фиксированный набор ``rows`` для него
    был бы fail-OPEN: вставка несла бы переходы из будущего своего момента.
    """
    if not rows and rows_for_moment is None:
        return list(entries), 0
    injected: List[dict] = []
    step = 1
    while True:
        moment = horizon - dt.timedelta(days=cadence_days * step)
        if moment <= first:
            break
        stamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        for entry in rows:
            injected.append({"kind": entry["kind"], "key": entry["key"],
                             "payload": entry["payload"], "at": stamp})
        if rows_for_moment is not None:
            injected.extend(rows_for_moment(moment))
        step += 1
    #: Порядок — ХРОНОЛОГИЧЕСКИЙ, и при равной отметке вставка идёт ПОСЛЕ
    #: настоящей записи: читающая модель берёт последнюю строку кандидата, и
    #: вставка, севшая перед живой записью того же мгновения, подменила бы ответ.
    ordered = sorted(
        [(at, index, entry) for index, (at, entry) in enumerate(zip(stamps, entries))]
        + [(lwd._parse_at(entry["at"]), 10 ** 9 + index, entry)
           for index, entry in enumerate(injected)],
        key=lambda row: (row[0], row[1]))
    return [entry for _, _, entry in ordered], len(injected)


def observed_growth_mb_per_day(entries: Sequence[dict], stamps: Sequence[dt.datetime],
                               horizon: dt.datetime,
                               window_days: int = GROWTH_WINDOW_DAYS) -> Optional[float]:
    """Темп роста по ПОСЛЕДНИМ суткам ленты. Окна не хватило ⇒ ``None``, не ноль."""
    edge = horizon - dt.timedelta(days=window_days)
    if stamps and stamps[0] > edge:
        return None
    tail = [entry for entry, at in zip(entries, stamps) if at >= edge]
    if not tail:
        return None
    size = sum(len(json.dumps(entry, ensure_ascii=False, separators=(",", ":"))) + 1
               for entry in tail)
    return round(size / window_days / 1e6, 3)


# ── замер ────────────────────────────────────────────────────────────────────────


def _unmeasured(reason: str, *, now: Optional[dt.datetime] = None, **extra) -> dict:
    doc = {"schema": VERSION, "generated_at": (now or lwd._utcnow()).isoformat(),
           "measured": False, "status": STATUS_UNMEASURED, "reason": reason,
           "rows": [], "findings": []}
    doc.update(extra)
    return doc


def _row_unmeasured(recipe: Recipe, reason: str, **extra) -> dict:
    row = {"recipe": recipe.id, "cadence_days": recipe.cadence_days,
           "measured": False, "reason": reason}
    row.update(extra)
    return row


def measure(data_dir: Path, *, now: Optional[dt.datetime] = None,
            recipes: Sequence[Recipe] = RECIPES,
            windows: Sequence[int] = WINDOWS,
            work_dir: Optional[Path] = None) -> dict:
    """Замер по живой ленте ``data_dir``. Живой каталог только ЧИТАЕТСЯ."""
    from spa_core.research_factory import contract  # noqa: PLC0415

    moment = now or lwd._utcnow()
    source = Path(data_dir)
    ledger_path = source / contract.DATA_SUBDIR / contract.LEDGER
    if not ledger_path.is_file():
        return _unmeasured(f"ленты нет на диске: {ledger_path}", now=moment)
    try:
        entries = lwd.load_entries(ledger_path)
    except (OSError, ValueError) as exc:
        return _unmeasured(f"лента не прочитана ({type(exc).__name__}): {exc}",
                           now=moment)
    if len(entries) < 2:
        return _unmeasured(f"в ленте {len(entries)} запис(ей) — переснимать нечего",
                           now=moment)
    stamps = [lwd._parse_at(entry.get("at")) for entry in entries]
    unparsed = [n for n, at in enumerate(stamps, start=1) if at is None]
    if unparsed:
        return _unmeasured(
            f"отметки не разобраны у {len(unparsed)} запис(ей) из {len(entries)} "
            f"(первая — №{unparsed[0]}): на какую сетку садится пересъёмка, "
            "НЕ ИЗВЕСТНО", now=moment)
    moments: List[dt.datetime] = [at for at in stamps if at is not None]
    first, horizon = moments[0], moments[-1]
    span_days = (horizon - first).total_seconds() / 86400.0
    ladder = sorted({int(w) for w in windows if 0 < int(w) < span_days})
    if not ladder:
        return _unmeasured(
            f"охват ленты {span_days:.2f} сут короче наименьшего окна лестницы "
            f"{sorted(int(w) for w in windows)[:1]} — усекать нечего, и цена "
            "лекарства ни с чем не сравнивается", now=moment,
            span_days=round(span_days, 2))

    owned_tmp = work_dir is None
    root = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(
        prefix="spa_resnapshot_price_"))
    try:
        live_dir = root / "live" / "data"
        head = lwd.rechain(entries, live_dir)
        if head != entries[-1].get("entry_hash"):
            return _unmeasured(
                "пересборка живой ленты НЕ воспроизводит её вершину "
                f"({head} против {entries[-1].get('entry_hash')}) — сцена есть "
                "другая лента, и ни одно число прибора к измеряемой не относится",
                now=moment)
        undeclared: set = set()
        try:
            live_answer = lwd.answer_leaves(live_dir, moment, undeclared=undeclared)
        except Exception as exc:  # noqa: BLE001 — любой отказ модели = НЕ ИЗМЕРЕНО
            return _unmeasured("читающая модель не ответила на живой ленте "
                               f"({type(exc).__name__}): {exc}", now=moment)
        if undeclared:
            return _unmeasured(
                "в ответе есть списки без объявленной природы: "
                + ", ".join(sorted(undeclared))
                + " — прибор адресовал бы их элементы ПО МЕСТУ и мерил бы "
                  "собственную адресацию", now=moment)
        live = live_candidate_ids(live_answer)
        live_bytes = ledger_path.stat().st_size
        growth = observed_growth_mb_per_day(entries, stamps, horizon)

        rows: List[dict] = []
        findings: List[dict] = []
        for recipe in recipes:
            batch = resnapshot_rows(entries, stamps, recipe, live)
            per_moment = None
            if recipe.compaction:
                def per_moment(moment, _e=entries, _s=stamps, _l=live):  # noqa: E731
                    return compaction_rows_at(_e, _s, moment, _l)
            scene_entries, injected = build_scene_entries(
                entries, stamps, batch, recipe.cadence_days, horizon, first,
                rows_for_moment=per_moment)
            scene = root / f"r_{recipe.id}" / "data"
            lwd.rechain(scene_entries, scene)
            scene_path = scene / contract.DATA_SUBDIR / contract.LEDGER
            scene_bytes = scene_path.stat().st_size
            added_per_day = round((scene_bytes - live_bytes) / span_days / 1e6, 3)

            #: Контроль №2: лекарство, сдвинувшее ответ на ПОЛНОЙ ленте, лечит
            #: не ту болезнь. Проверяется ДО лестницы — иначе безопасное окно
            #: рапортовалось бы для чужого ответа.
            neutral: Optional[bool] = None
            drifted: List[str] = []
            if not recipe.is_zero:
                scene_undeclared: set = set()
                try:
                    scene_answer = lwd.answer_leaves(scene, moment,
                                                     undeclared=scene_undeclared)
                except Exception as exc:  # noqa: BLE001
                    rows.append(_row_unmeasured(
                        recipe, f"читающая модель не ответила на сцене рецепта "
                                f"({type(exc).__name__}): {exc}",
                        injected_entries=injected))
                    shutil.rmtree(scene.parent, ignore_errors=True)
                    continue
                union = set(live_answer) | set(scene_answer)
                if not any(path.startswith(MEDICINE_PRESENCE_PREFIX)
                           for path in live_answer):
                    return _unmeasured(
                        "в живом ответе нет ни одного листа с префиксом "
                        f"{MEDICINE_PRESENCE_PREFIX!r} — вычет имени лекарства "
                        "был бы вычетом ничего, а читающая модель отвечает не то, "
                        "что прибор о ней объявил", now=moment)
                drifted = sorted(
                    path for path in union
                    if path not in lwd.CHAIN_IDENTITY_LEAVES
                    and not path.startswith(MEDICINE_PRESENCE_PREFIX)
                    and live_answer.get(path) != scene_answer.get(path))
                neutral = not drifted

            window_doc = lwd.measure(scene, now=moment, windows=ladder,
                                     work_dir=root / f"w_{recipe.id}")
            shutil.rmtree(root / f"w_{recipe.id}", ignore_errors=True)
            if not window_doc.get("measured"):
                rows.append(_row_unmeasured(
                    recipe, f"лестница окон не измерена: {window_doc.get('reason')}",
                    injected_entries=injected, added_mb_per_day=added_per_day,
                    answer_neutral=neutral))
                shutil.rmtree(scene.parent, ignore_errors=True)
                continue
            safe = window_doc.get("safe_window_days")
            steady_bytes = None
            if safe is not None:
                edge = horizon - dt.timedelta(days=int(safe))
                kept = [entry for entry in scene_entries
                        if (lwd._parse_at(entry["at"]) or first) >= edge]
                steady = root / f"s_{recipe.id}" / "data"
                lwd.rechain(kept, steady)
                steady_bytes = (steady / contract.DATA_SUBDIR
                                / contract.LEDGER).stat().st_size
                shutil.rmtree(root / f"s_{recipe.id}", ignore_errors=True)
            shutil.rmtree(scene.parent, ignore_errors=True)
            rows.append({
                "recipe": recipe.id,
                "note": recipe.note,
                "cadence_days": recipe.cadence_days,
                "newest_kinds": list(recipe.newest_kinds),
                "all_kinds": list(recipe.all_kinds),
                "synthesised_kinds": list(recipe.synthesised_kinds),
                "substitutes": recipe.substitutes,
                "compaction": recipe.compaction,
                "measured": True,
                "rows_per_round": len(batch),
                "injected_entries": injected,
                "scene_bytes": scene_bytes,
                "added_mb_per_day": added_per_day,
                "answer_neutral": neutral,
                "answer_drifted_leaves": len(drifted),
                "one_day_dependent_share_pct":
                    window_doc.get("one_day_dependent_share_pct"),
                "safe_window_days": safe,
                "steady_state_bytes": steady_bytes,
                "steady_state_mb": (None if steady_bytes is None
                                    else round(steady_bytes / 1e6, 2)),
            })
            if neutral is False:
                findings.append({
                    "kind": FINDING_NOT_NEUTRAL, "recipe": recipe.id,
                    "text": (f"рецепт «{recipe.id}» меняет ответ на ПОЛНОЙ ленте "
                             f"({len(drifted)} лист(ьев), напр. {drifted[0]}) — "
                             "окно, которое он «открывает», относится к ДРУГОМУ "
                             "ответу"),
                })

        measured_rows = [row for row in rows if row.get("measured")]
        if not measured_rows:
            return _unmeasured("ни один рецепт не измерен: "
                               + " · ".join(str(row.get("reason")) for row in rows),
                               now=moment, rows=rows)

        zero = next((row for row in measured_rows if row["recipe"] == "none"), None)
        if zero is not None and zero.get("safe_window_days") is not None:
            #: Контроль №3: без лекарства окна быть не должно. Появилось —
            #: сдвинулась сама лента, и цена рецептов не с чем сравнивать.
            findings.append({
                "kind": FINDING_BASELINE_DRIFTED, "recipe": "none",
                "text": (f"нулевой рецепт уже имеет безопасное окно "
                         f"{zero['safe_window_days']} сут — вердикт ADR-793 на "
                         "сегодняшней ленте НЕ воспроизводится, и разница "
                         "рецептов меряет не лекарство"),
            })

        openers = [row for row in measured_rows
                   if row["recipe"] != "none"
                   and row.get("safe_window_days") is not None
                   and row.get("answer_neutral") is not False]
        cheapest = min(openers, key=lambda row: (row["added_mb_per_day"],
                                                 row["safe_window_days"])) if openers else None
        if not openers:
            findings.append({
                "kind": FINDING_NO_RECIPE,
                "text": ("ни один объявленный рецепт пересъёмки не открывает "
                         "безопасного окна — усечение по возрасту остаётся "
                         "недоступным, и лекарство роста ленты по-прежнему НЕ "
                         "НАЙДЕНО"),
            })

        doc = {
            "schema": VERSION,
            "generated_at": moment.isoformat(),
            "measured": True,
            "reason": None,
            "ledger": {
                "path": str(ledger_path),
                "entries": len(entries),
                "bytes": live_bytes,
                "span_days": round(span_days, 2),
                "head_hash": head,
                "horizon": horizon.isoformat(),
                "observed_growth_mb_per_day": growth,
                "growth_window_days": GROWTH_WINDOW_DAYS,
            },
            "baseline": {"answer_leaves": len(live_answer),
                         "candidates": len(live)},
            "windows": ladder,
            "rows": rows,
            #: Самый ДЕШЁВЫЙ рецепт, открывающий окно. ``None`` — не «ноль» и не
            #: «любой подойдёт», а «не открыл НИ ОДИН» (инв. #17).
            "cheapest_opener": None if cheapest is None else cheapest["recipe"],
            "cheapest_added_mb_per_day": (None if cheapest is None
                                          else cheapest["added_mb_per_day"]),
            "cheapest_safe_window_days": (None if cheapest is None
                                          else cheapest["safe_window_days"]),
            "cheapest_steady_state_mb": (None if cheapest is None
                                         else cheapest["steady_state_mb"]),
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
    """Пора ли переизмерять — решает ФАЙЛ (три исхода, как у соседа)."""
    return lwd.measurement_due(out, now=now, tact_days=tact_days)


def run(root: Optional[str] = None, *, data_dir: Optional[str] = None,
        dest: Optional[str] = None, write: bool = True, if_due: bool = False,
        now: Optional[dt.datetime] = None,
        tact_days: int = MEASUREMENT_TACT_DAYS,
        recipes: Sequence[Recipe] = RECIPES,
        windows: Sequence[int] = WINDOWS) -> dict:
    """Шаг моста: внутри такта НЕ мерить и НЕ выдумывать вердикт."""
    tree = Path(root) if root else _ROOT
    source = Path(data_dir) if data_dir is not None else tree / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    if if_due:
        due, why = measurement_due(target, now=now, tact_days=tact_days)
        if not due:
            return {"measured": False, "reason": why, "artifact": str(target)}
    doc = measure(source, now=now, recipes=recipes, windows=windows)
    if write:
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def format_report(doc: dict) -> List[str]:
    out = [f"ЦЕНА пересъёмки описания как лекарства росту ленты ({VERSION})"]
    if not doc.get("measured"):
        out.append(f"  НЕ ИЗМЕРЕНО: {doc.get('reason')}")
        return out
    led = doc.get("ledger") or {}
    base = doc.get("baseline") or {}
    growth = led.get("observed_growth_mb_per_day")
    out.append(f"  лента: записей {led.get('entries')} · {led.get('bytes')} Б · "
               f"охват {led.get('span_days')} сут · наблюдённый рост "
               + ("НЕ ИЗМЕРЕН (окна не хватило)" if growth is None
                  else f"{growth} МБ/сут за последние {led.get('growth_window_days')} сут"))
    out.append(f"  полный ответ: листьев {base.get('answer_leaves')} · "
               f"кандидатов {base.get('candidates')}")
    for row in doc.get("rows") or []:
        if not row.get("measured"):
            out.append(f"  {row.get('recipe')}: НЕ ИЗМЕРЕНО — {row.get('reason')}")
            continue
        safe = row.get("safe_window_days")
        neutral = row.get("answer_neutral")
        out.append(
            f"  {row['recipe']:<30s} такт {row['cadence_days']} сут · "
            f"+{row['added_mb_per_day']} МБ/сут · "
            f"от записей старше суток зависит {row.get('one_day_dependent_share_pct')} % · "
            "окно " + ("НЕТ" if safe is None else f"{safe} сут")
            + ("" if row.get("steady_state_mb") is None
               else f" · лента устаканится на {row['steady_state_mb']} МБ")
            + ("" if neutral is None
               else (" · ответ НЕ ТРОНУТ" if neutral
                     else f" · ⚠ ответ СДВИНУТ ({row.get('answer_drifted_leaves')} лист.)")))
    cheapest = doc.get("cheapest_opener")
    if cheapest is None:
        out.append("  САМЫЙ ДЕШЁВЫЙ рецепт, открывающий окно: НИ ОДИН не открыл")
    else:
        out.append(f"  САМЫЙ ДЕШЁВЫЙ рецепт, открывающий окно: «{cheapest}» — "
                   f"+{doc.get('cheapest_added_mb_per_day')} МБ/сут за окно "
                   f"{doc.get('cheapest_safe_window_days')} сут "
                   f"(лента устаканится на {doc.get('cheapest_steady_state_mb')} МБ "
                   "вместо безграничного роста)")
    for finding in doc.get("findings") or []:
        out.append(f"  🔴 [{finding['kind']}] {finding['text']}")
    out.append("  ADVISORY: прибор только ЧИТАЕТ; живая лента не тронута")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись цены пересъёмки описания как лекарства росту ленты "
                    "research_factory (заказ G793 п. 1)")
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
    ap.add_argument("--recipes", default=None,
                    help="подмножество объявленных рецептов через запятую "
                         f"(по умолчанию все: {','.join(r.id for r in RECIPES)})")
    args = ap.parse_args(argv)

    windows: Sequence[int] = WINDOWS
    if args.windows:
        try:
            windows = tuple(int(part) for part in args.windows.split(",") if part.strip())
        except ValueError:
            print("НЕ ИЗМЕРЕНО: лестница окон не разобрана — ожидались целые сутки "
                  "через запятую")
            return 2
    recipes: Sequence[Recipe] = RECIPES
    if args.recipes:
        wanted = [part.strip() for part in args.recipes.split(",") if part.strip()]
        known = {recipe.id: recipe for recipe in RECIPES}
        missing = [name for name in wanted if name not in known]
        if missing:
            print("НЕ ИЗМЕРЕНО: рецепты не объявлены: " + ", ".join(missing)
                  + " (объявлены: " + ", ".join(known) + ")")
            return 2
        recipes = tuple(known[name] for name in wanted)

    res = run(root=args.tree_root, data_dir=args.data_dir, dest=args.out,
              write=not args.no_write, if_due=args.if_due, recipes=recipes,
              windows=windows)
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
