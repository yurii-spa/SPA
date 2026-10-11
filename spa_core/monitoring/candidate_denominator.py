"""Население кандидата против его ПРИСУТСТВИЯ — одна копия правила разницы.

Заказ **G115 п. 3** приказа владельца «Portfolio CIO» (хвост
[ADR-541](../../docs/decisions/ADR-541-the-quadruple-rotted-before-it-was-adjudicated.md),
поставлен 02.10) дословно:

> «**Население четвёрки n ≤ 2 — проверить, не свойство ли это самой переписи.**
> Население имени считается по спискам, у которых поле ГОДНО, а не по спискам,
> где поле ЕСТЬ. Замерить разницу: возможно, низкое население четвёрки есть
> артефакт знаменателя, и тогда мерило ADR-503 рассудило четвёрку не тем
> числом.»

## Почему это отдельный модуль, а не ветка у переписи

Правило разницы коротко, но у него ДВА операнда разной природы, и ровно на этом
его легко напечатать неверно: «присутствие» есть наблюдение СОСТАВА списка, а
«население» есть наблюдение, уже отобранное признаком, о котором и спрашивают.
Вторая копия такого правила расходится с первой молча. Поэтому число ``counted``
здесь — **ВХОД, а не пересчёт**: берётся то самое ``candidate_fields_outside``,
которое перепись печатает читателю, иначе отчёт нёс бы два числа под одним
именем. Пересчёт рядом всё же идёт — но как КОНТРОЛЬ (``counted_disagrees``):
разойдись он со входом, это расхождение зонда со сводом, и молчать о нём нельзя.

## Четыре числа у имени, и складывать их нельзя

| число | что наблюдено | почему отдельно |
|---|---|---|
| ``counted`` | как перепись считает СЕГОДНЯ | это и есть мерило ADR-503 |
| ``eligible_anywhere`` | поле ГОДНО на любом словарном списке длиннее одного | тот же предикат на ШИРОКОМ знаменателе |
| ``present`` | поле ЕСТЬ хотя бы у одного элемента | состав, а не годность |
| ``eligible_singletons`` | годно на списке из ОДНОГО элемента | годность там тривиальна (ADR-409) |

**Разница ``eligible_anywhere − counted`` и разница ``present −
eligible_anywhere`` суть РАЗНЫЕ утверждения, и путать их нельзя:**

* первая — **артефакт знаменателя**: тот же предикат «поле годно» на более
  широком населении даёт БОЛЬШЕЕ число, и значит мерило судило по узкому;
* вторая — **собственная негодность поля**, и она свидетельствует ПРОТИВ имени,
  а не за него: присутствие без уникальности есть худшее свидетельство, не
  лучшее. Выдать её за поправку населения значило бы продвигать имя числом,
  которое его опровергает.

Поэтому вердикт (``verdict``) ВЫЧИСЛЯЕТСЯ из первой разницы и только из неё, а
вторая печатается своим числом (``gap_is_unfitness``).

## Три исхода, и третий не ноль (инв. #17)

* у словарного списка стои́т состав ⇒ он идёт в оба знаменателя;
* словарный список БЕЗ состава ⇒ ``lists_unmeasured`` с названной причиной:
  живой зонд такого не производит (``classify_list`` ставит ключ всем словарным
  спискам), но сложить такую строку «никуда» значило бы дать расхождению зонда
  со сводом исчезнуть молча;
* имя, которому перепись дала население, а состав — ни одной строки ⇒
  ``counted_disagrees``: это не «присутствие ноль».

## Чего это НЕ доказывает

* **Присутствие не есть годность.** Число ``present`` не говорит, что имя
  годится в личность; оно говорит, из какого состава считалась годность.
* **Усечённый обход даёт находки, но не досмотрен.** Читатель, упёршийся в
  потолок узлов, в населении участвует (так же, как у ``candidate_fields_outside``),
  поэтому и ``present``, и ``eligible_anywhere`` суть НИЖНИЕ границы. Число
  усечённых читателей печатается рядом.
* **Ни одно имя не дописывается в ``_IDENTITY_FIELDS``, и порога не назначено
  ни одного.** Запрет пинится составом публичных имён у потребителя
  (``list_identity_census._NO_GATE_NAMES``).
* Замер — наблюдение ОДНОГО ответа читателей, как население и длина: он
  меняется со скоростью кода. Четвёрка заказа за три дня истлела (ADR-541
  ОТВЕТ 1), и перечень имён ниже есть запись о том, ЧТО БЫЛО РАССУЖДЕНО, а не
  состав класса на сегодня.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.utils.observation import observed  # noqa: E402

#: Исходы зонда, у которых элементы — СЛОВАРИ, то есть вопрос «есть ли у списка
#: такое поле» вообще осмыслен. Шире, чем ``_DICT_OUTCOMES`` у переписи, ровно на
#: ``named``: там перечислены исходы, у которых осмыслен вопрос ЗАКАЗА G34
#: («годного имени из списка нет»), а здесь — исходы, у которых осмыслен вопрос
#: о СОСТАВЕ. Разница между двумя перечнями и есть предмет заказа G115 п. 3:
#: названный список из населения выпадает, хотя поле в нём есть и бывает годно.
DICT_OUTCOMES: Tuple[str, ...] = ("named", "unnamed_candidate_outside",
                                  "unnamed_no_candidate")

#: Исход зонда, при котором у списка УЖЕ есть личность из ``_IDENTITY_FIELDS``.
#: Имя строки пинится тестом: переименуй его мутант — и «годно, но список уже
#: назван» сложилось бы в ноль, то есть артефакт знаменателя исчез бы молча.
NAMED_OUTCOME = "named"

#: Пустая причина = поле годно. Та же условность, что у ``scalar_refusal``.
ELIGIBLE = ""

#: Ключ состава в строке зонда.
COMPOSITION_KEY = "outside_fields"

#: Имена, о которых решение УЖЕ ПРИНЯТО мерилом населения, — то есть ровно те, о
#: чьём рассуждении заказ и спрашивает: ``value`` отвергнут
#: [ADR-503](../../docs/decisions/ADR-503-identity-fields-extended-by-measurement.md)
#: словами «население — ОДИН список, длина одного списка населением не
#: является», четвёрка и её сильнейший кандидат — ADR-541 (решение 2 и 3).
#:
#: Кортеж есть ЗАПИСЬ О РЕШЕНИИ, а не замер: имя, которого в сегодняшнем
#: населении нет вовсе, остаётся в нём намеренно и получает третий исход
#: (``absent_today``), а не ноль. ADR-541 на этом и настаивает: ``best_net_usd``
#: из населения исчез за три дня, и выкинуть его из перечня значило бы сделать
#: «рассудили имя, которого больше нет» невидимым.
ADJUDICATED_NAMES: Tuple[str, ...] = ("value", "realised_usd_per_day",
                                      "best_net_usd", "message", "window_s",
                                      "trade_id")


def composition_of(row: dict) -> Optional[Dict[str, str]]:
    """Состав имён вне списка у ОДНОЙ строки зонда либо ``None`` — не измерено.

    ``None`` и пустой словарь — РАЗНЫЕ ответы: первый значит «зонд состава не
    поставил» (расхождение зонда со сводом), второй — «вне списка имён у этого
    списка нет ни одного поля». Слить их значило бы сделать отсутствие замера
    неотличимым от наблюдённого нуля (инв. #17).
    """
    composition = row.get(COMPOSITION_KEY)
    if not isinstance(composition, dict):
        return None
    return {str(k): str(v) for k, v in composition.items()}


def tally(rows: Iterable[dict], counted: Dict[str, int]) -> dict:
    """Разница «поле ЕСТЬ» против «поле ГОДНО» — по каждому имени.

    ``rows`` — строки списков зонда (``n``, ``outcome``, ``outside_fields``,
    ``module``, ``coord``). ``counted`` — население, которое перепись ПЕЧАТАЕТ
    (``candidate_fields_outside``); оно вход, а не пересчёт (см. докстринг
    модуля).
    """
    if not isinstance(counted, dict):
        return {"status": "UNMEASURED",
                "reason": ("населения переписи не дали вовсе — разницу мерить "
                           "не от чего; это не «разницы нет»")}
    present: Dict[str, int] = {}
    eligible: Dict[str, int] = {}
    eligible_named: Dict[str, int] = {}
    eligible_counted: Dict[str, int] = {}
    eligible_singleton: Dict[str, int] = {}
    present_singleton: Dict[str, int] = {}
    refused: Dict[str, Dict[str, int]] = {}
    contradictions: List[dict] = []
    lists_unmeasured: List[dict] = []
    lists_seen = 0
    dict_lists_multi = 0

    for row in rows:
        outcome = str(row.get("outcome"))
        if outcome not in DICT_OUTCOMES:
            continue
        lists_seen += 1
        composition = composition_of(row)
        if composition is None:
            lists_unmeasured.append({
                "module": row.get("module"), "coord": row.get("coord"),
                "outcome": outcome, "n": row.get("n"),
                "reason": "зонд не поставил состав имён вне списка"})
            continue
        # ДЛИНА — наблюдение, и её отсутствие не есть «ноль элементов»
        # (инв. #17). `int(row.get("n") or 0)` отправил бы строку без длины в
        # синглтоны, то есть МОЛЧА вынес бы её из обоих знаменателей: именно так
        # выглядит расхождение зонда со сводом, если оно однажды случится.
        n = observed(row, "n", kind=int)
        if n is None:
            lists_unmeasured.append({
                "module": row.get("module"), "coord": row.get("coord"),
                "outcome": outcome, "n": None,
                "reason": "у строки нет длины — в синглтоны её класть нельзя"})
            continue
        singleton = n <= 1
        if not singleton:
            dict_lists_multi += 1
        for name, cause in composition.items():
            if singleton:
                present_singleton[name] = present_singleton.get(name, 0) + 1
                if cause == ELIGIBLE:
                    eligible_singleton[name] = (
                        eligible_singleton.get(name, 0) + 1)
                continue
            present[name] = present.get(name, 0) + 1
            if cause != ELIGIBLE:
                bucket = refused.setdefault(name, {})
                bucket[cause] = bucket.get(cause, 0) + 1
                continue
            eligible[name] = eligible.get(name, 0) + 1
            if outcome == NAMED_OUTCOME:
                eligible_named[name] = eligible_named.get(name, 0) + 1
            elif outcome == "unnamed_candidate_outside":
                eligible_counted[name] = eligible_counted.get(name, 0) + 1
            else:
                # Исход `unnamed_no_candidate` значит «годного поля вне списка
                # НЕТ ВОВСЕ», и годное поле в его составе есть противоречие
                # зонда с самим собой. Ветвь оставлена не «для симметрии»: это
                # единственное место, где такое расхождение наблюдаемо, и
                # сложить его в население значило бы погасить улику числом.
                contradictions.append({
                    "field": name, "module": row.get("module"),
                    "coord": row.get("coord"), "n": n,
                    "reason": (f"исход {outcome} утверждает «годных полей вне "
                               f"списка нет», а состав называет годным "
                               f"«{name}»")})

    names = sorted(set(counted) | set(present) | set(eligible))
    # Имя, которое встретилось ТОЛЬКО в синглтонах, строки не получает: перепись
    # его тоже не считает (годность в списке из одного тривиальна, ADR-409), и
    # дать ему строку значило бы смешать тривиальную годность с наблюдённой. Но
    # счётчик синглтонов у такого имени уже посчитан, и промолчать о нём значило
    # бы дать наблюдению исчезнуть МОЛЧА — поэтому оно отдельное число, а не ноль.
    only_singletons = sorted(set(present_singleton) - set(names))
    rows_out: List[dict] = []
    understated: List[dict] = []
    unfitness: List[dict] = []
    invisible: List[str] = []
    disagrees: List[dict] = []
    for name in names:
        counted_n = counted.get(name)
        recomputed = eligible_counted.get(name, 0)
        if counted_n is None:
            # Имя, которого перепись НЕ ПЕЧАТАЕТ ни одной строкой: ГОДНОЕ только
            # на списках, у которых личность уже есть. Ровно то, что прячет
            # нынешний знаменатель, — и это не «население ноль».
            #
            # Условие годности здесь ОБЯЗАТЕЛЬНО, и поймал его положительный
            # контроль второй разницы: без него имя, которое всюду ЕСТЬ и нигде
            # не годно (`note` с `not_unique`), объявлялось бы «спрятанным от
            # переписи». Перепись его не печатает ВЕРНО — оно не кандидат ни на
            # одном списке, — и считать это артефактом знаменателя значило бы
            # изготовить находку из правильного молчания.
            if eligible.get(name, 0):
                invisible.append(name)
        elif int(counted_n) != recomputed:
            disagrees.append({"field": name, "census": int(counted_n),
                              "recomputed_from_composition": recomputed})
        eligible_n = eligible.get(name, 0)
        present_n = present.get(name, 0)
        row_out = {
            "field": name,
            "counted": counted_n,
            "counted_unmeasured": counted_n is None,
            "eligible_anywhere": eligible_n,
            "present": present_n,
            "eligible_on_named_lists": eligible_named.get(name, 0),
            "eligible_singletons": eligible_singleton.get(name, 0),
            "present_singletons": present_singleton.get(name, 0),
            "refused_causes": dict(sorted(refused.get(name, {}).items())),
        }
        rows_out.append(row_out)
        base = 0 if counted_n is None else int(counted_n)
        if eligible_n > base:
            understated.append({"field": name, "counted": counted_n,
                                "eligible_anywhere": eligible_n,
                                # Насколько занижено. Считается ТАМ, где уже
                                # посчитан `base`: вторая копия правила «чем
                                # считать отсутствующее население» ниже была
                                # `(r["counted"] or 0)` — и это и вторая копия,
                                # и ещё одна `or`-подстановка (инв. #17).
                                "gap": eligible_n - base,
                                "hidden_by_named_lists":
                                    eligible_named.get(name, 0)})
        if present_n > eligible_n:
            unfitness.append({"field": name, "present": present_n,
                              "eligible_anywhere": eligible_n,
                              "refused_causes":
                                  dict(sorted(refused.get(name, {}).items()))})

    adjudicated = _adjudicated(rows_out)
    reasons: List[str] = []
    if understated:
        worst = max(understated, key=lambda r: r["gap"])
        reasons.append(
            f"у {len(understated)} имён ТОТ ЖЕ предикат «поле годно» на широком "
            f"знаменателе даёт БОЛЬШЕЕ число (сильнейшее: {worst['field']} — "
            f"перепись печатает {worst['counted']}, годно на "
            f"{worst['eligible_anywhere']})")
    if invisible:
        reasons.append(
            f"{len(invisible)} имён перепись не печатает НИ ОДНОЙ строкой — они "
            f"годны только на списках, у которых личность уже есть, и нынешний "
            f"знаменатель их не видит вовсе")
    restated = [r for r in adjudicated if r.get("counted_understates")]
    if restated:
        reasons.append(
            f"среди РАССУЖДЕННЫХ имён таких {len(restated)}: "
            f"{', '.join(r['field'] for r in restated)} — мерило ADR-503 "
            f"рассудило их по узкому числу")
    return {
        "status": "MEASURED",
        "lists_seen": lists_seen,
        "dict_lists_multi": dict_lists_multi,
        "lists_unmeasured": lists_unmeasured,
        "names": len(names),
        # Отдельное число, а не слагаемое `names`: эти имена в знаменатель
        # разницы не входят ни одной стороной.
        "names_only_on_singletons": only_singletons,
        "rows": rows_out,
        # Главное число заказа: у кого ТОТ ЖЕ предикат на широком знаменателе
        # даёт больше. Только это и есть «артефакт знаменателя».
        "counted_understates": understated,
        # Имена, которых перепись не печатает вовсе. Отдельным числом: «население
        # занижено» и «имени нет в отчёте» — разные беды.
        "names_invisible_to_the_census": invisible,
        # ВТОРАЯ разница, и она свидетельствует ПРОТИВ имени. Отдельным числом
        # намеренно: сложить её с первой значило бы продвигать имя числом,
        # которое его опровергает.
        "gap_is_unfitness": unfitness,
        "probe_contradictions": contradictions,
        "counted_disagrees": disagrees,
        "adjudicated": adjudicated,
        "verdict": "DENOMINATOR_ARTIFACT" if reasons else "NOT_AN_ARTIFACT",
        "verdict_reasons": reasons,
        "what_it_does_not_prove": [
            "присутствие не есть годность: `present` говорит не о том, что имя "
            "годится, а о том, из какого состава считалась годность",
            "разница `present − eligible` свидетельствует ПРОТИВ имени, а не за "
            "него: присутствие без уникальности есть худшее свидетельство",
            "усечённый обход участвует в населении так же, как у "
            "candidate_fields_outside ⇒ оба числа суть НИЖНИЕ границы",
            "ни одно имя не дописано в _IDENTITY_FIELDS и ни один порог не "
            "назначен: разница — наблюдение, а не гейт",
        ],
    }


def _adjudicated(rows_out: List[dict]) -> List[dict]:
    """Строки по именам, о которых решение уже принято (ADR-503 / ADR-541).

    Имя, которого в сегодняшнем замере нет, получает ``absent_today`` — третий
    исход, а не нули по четырём числам: «рассудили имя, которого больше нет» и
    «имя есть, и у него всё по нулям» суть разные наблюдения, и ADR-541 ОТВЕТ 1
    написан ровно про первое.
    """
    by_name = {str(r.get("field")): r for r in rows_out}
    out: List[dict] = []
    for name in ADJUDICATED_NAMES:
        row = by_name.get(name)
        if row is None:
            out.append({"field": name, "absent_today": True,
                        "why": ("имени нет в сегодняшнем замере вовсе — ни "
                                "населения, ни присутствия; это не нули")})
            continue
        base = 0 if row["counted"] is None else int(row["counted"])
        out.append({
            "field": name,
            "absent_today": False,
            "counted": row["counted"],
            "eligible_anywhere": row["eligible_anywhere"],
            "present": row["present"],
            "eligible_on_named_lists": row["eligible_on_named_lists"],
            "refused_causes": row["refused_causes"],
            "counted_understates": row["eligible_anywhere"] > base,
        })
    return out


def report(axis: dict, *, max_rows: Optional[int] = None) -> List[str]:
    """Строки раздела. Знаменатель — рядом с числителем, как везде."""
    if str(axis.get("status")) != "MEASURED":
        return [f"НЕ ИЗМЕРЕНО: {axis.get('reason')}"]
    singles = axis.get("names_only_on_singletons")
    out = [f"знаменатель разницы: словарных списков длиннее одного "
           f"{axis.get('dict_lists_multi')} из {axis.get('lists_seen')} "
           f"словарных вообще; имён в замере {axis.get('names')}; имён только в "
           f"синглтонах (вне знаменателя обеими сторонами) "
           f"{len(singles) if singles is not None else 'НЕ ИЗМЕРЕНО'}"]
    understates = axis.get("counted_understates") or []
    invisible = axis.get("names_invisible_to_the_census") or []
    # «Из них» сказано дословно намеренно: имя, которого перепись не печатает
    # вовсе, занижено ТОЖЕ (её число для него отсутствует), то есть второе
    # множество ВЛОЖЕНО в первое. Напечатай их через точку как равноправные —
    # читатель сложил бы два числа и получил бы имён больше, чем их есть.
    out.append(f"ВЕРДИКТ {axis.get('verdict')}: население занижено у "
               f"{len(understates)} имён, из них не печатается переписью вовсе "
               f"{len(invisible)}")
    for line in (axis.get("verdict_reasons") or []):
        out.append(f"ПОЧЕМУ: {line}")
    if invisible:
        shown = invisible if max_rows is None else invisible[:max_rows]
        tail = ("" if len(shown) == len(invisible)
                else f"; … ещё {len(invisible) - len(shown)}")
        out.append(f"НЕ В ОТЧЁТЕ ПЕРЕПИСИ: {', '.join(shown)}{tail}")
    unfit = axis.get("gap_is_unfitness") or []
    out.append(f"ВТОРАЯ РАЗНИЦА (ПРОТИВ имени): у {len(unfit)} имён поле ЕСТЬ "
               f"там, где оно НЕ годно — это не поправка населения")
    for row in (axis.get("adjudicated") or []):
        if row.get("absent_today"):
            out.append(f"РАССУЖДЕНО {row.get('field')}: НЕ ИЗМЕРЕНО — "
                       f"{row.get('why')}")
            continue
        # «Строки нет» вместо `None`: перепись об этом имени не печатает НИЧЕГО,
        # и `None` в строке отчёта читался бы как напечатанное значение.
        counted = row.get("counted")
        verdict = ("мерило судило по УЗКОМУ числу"
                   if row.get("counted_understates")
                   else "низкое население НЕ артефакт знаменателя")
        out.append(f"РАССУЖДЕНО {row.get('field')}: перепись печатает "
                   f"{'СТРОКИ НЕТ' if counted is None else counted} "
                   f"· годно {row.get('eligible_anywhere')} "
                   f"(из них у названных списков "
                   f"{row.get('eligible_on_named_lists')}) · ЕСТЬ "
                   f"{row.get('present')} ⇒ {verdict}")
    for row in (axis.get("counted_disagrees") or []):
        out.append(f"НЕ ИЗМЕРЕНО: у {row.get('field')} перепись печатает "
                   f"{row.get('census')}, а состав даёт "
                   f"{row.get('recomputed_from_composition')} — зонд разошёлся "
                   f"со сводом")
    for row in (axis.get("probe_contradictions") or []):
        out.append(f"НЕ ИЗМЕРЕНО: {row.get('reason')} "
                   f"({row.get('module')} {row.get('coord')})")
    for row in (axis.get("lists_unmeasured") or []):
        out.append(f"НЕ ИЗМЕРЕНО: {row.get('reason')} "
                   f"({row.get('module')} {row.get('coord')})")
    return out
