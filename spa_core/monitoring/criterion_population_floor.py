"""Доля населения критерия, посчитанная по ПОЛУ знаменателя, а не по потолку (заказ #599/G13).

Заказ, оставленный в хвосте [ADR-380] по стоячему приказу владельца «Portfolio CIO»
(`nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md`):

> G12 закрыл цену `pendle` в днях и обнаружил, что **ПОЛ рычага писателя — 19 дн., а не 22**.
> Заказ G13: **пересчитать долю населения критерия по ПОЛУ, а не по потолку — и назвать, что
> именно этим сдвигом меняется в очереди починок.** [ADR-371] предъявил владельцу «проходящий
> ``hit_rate`` = 1.0 посчитан на 16 из 24 достижимых дней = 66.67 % населения», и число 24
> есть ПОТОЛОК при любом рычаге. Но потолок включает дни, стоящие на ногах без единой точки
> в ряду (`pendle` — 3 дн.) и на ноге владельца (`spark_susds` — 1 дн.). Значит у доли
> населения есть своя нижняя граница, подтверждённая материалом, и она не измерена: сколько
> дней достижимо СЕГОДНЯШНИМ состоянием фидов, а не гипотезой об идеальном. Прибор для этого
> уже стои́т: ``silent_leg_day_price.writer_lever_floor_without_leg`` даёт пол,
> ``hit_rate_denominator_recovery`` — потолок; свести их обязан ТРЕТИЙ, потому что ни один
> из двух не вправе пересчитывать чужое число.

## Предмет ровно один

**Какова доля населения проходящего критерия, если знаменатель брать по материалу, а не по
гипотезе об идеальном состоянии фидов.** Не значение критерия (оно не считается вовсе и это
закреплено тестом), не доллары оборота, не число молчащих ног.

## Почему ТРЕТИЙ, а не правка одного из двух

Ни потолочный прибор, ни прибор пола не вправе пересчитывать чужое число: у каждого свой
предмет, и правка «заодно» сделала бы ответ соседа функцией нашего вопроса. Поэтому здесь нет
НИ ОДНОГО собственного вычисления знаменателя — все числа ПРИХОДЯТ от соседей, а прибор
делает ровно две вещи: проверяет, что соседи говорят об ОДНОМ населении, и делит.

## Лестница из трёх знаменателей, и они не сливаются (инв. #17)

| знаменатель | что включает | чей рычаг |
|---|---|---|
| **потолок** ``ceiling_all_blocking`` | все блокирующие дни при ЛЮБОМ рычаге | гипотеза об идеальном материале |
| **пол по материалу** | потолок минус дни, у ног которых нет НИ ОДНОЙ точки ряда | наш код + владелец |
| **пол нашего кода** | то же минус дни, чей рычаг лежит у владельца | только наш код |

Слить их значило бы отправить читателя чинить не то место. Разница потолка и пола по
материалу — это дни, которые очередь считает работой, а материала под ними нет ни у кого.

## Направление границы названо, потому что читатель перенесёт его в решение

Материал — условие **НЕОБХОДИМОЕ и НЕ достаточное** ([ADR-302], [ADR-378]): точка ряда
доказывает, что производителю было что записать, но не доказывает, что день поднялся бы.
Значит пол есть **ВЕРХНЯЯ** граница достижимого знаменателя, а доля ``D / пол`` —
**НИЖНЯЯ** граница доли населения. Опубликованные 66.67 % тоже нижняя граница, но слабее:
она стои́т на знаменателе, куда входят дни, про которые материал говорит «нет» напрямую.

**И отдельно: убранные дни не «ждут починки», они не возвращаются НИКЕМ.** Материала для тех
дат не существует, а задним числом ряд не наполняется. Починка фида молчащей ноги ценна
вперёд и стои́т в очереди по-прежнему — но исторических дней знаменателя она не возвращает
ни одного, и читатель, поставивший её в очередь ради них, работу переоценит.

## Контроль маршрута — тот, без которого сведение есть арифметика по кругу

Пол рычага писателя прибор считает СВОИМ маршрутом (сценарий потолочного прибора минус
названные дни без материала) и сверяет с числом соседа, полученным ДРУГОЙ машинерией —
возмущением судьи с изъятой ногой. Разошлись ⇒ **не измерено**, а не «взять любое».

**ADVISORY.** Прибор ЧИТАЕТ. ``hit_rate``, ``MIN_HIT_RATE``, ``TriggerParams``, писатель
журнала, ``POLLED_ADAPTERS``, пины, адаптеры, пороги RiskPolicy v1.0, стоп-кран, живой трек
и ``landing/`` не трогаются; капитал не двигается.

[ADR-302]: docs/decisions/ADR-302-live-rate-provenance.md
[ADR-371]: docs/decisions/ADR-371-hit-rate-denominator-recovery.md
[ADR-378]: docs/decisions/ADR-378-writer-universe-lever-floor.md
[ADR-380]: docs/decisions/ADR-380-silent-leg-day-price.md
"""
# LLM_FORBIDDEN
from __future__ import annotations
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
# Соседи зовутся ПО ССЫЛКЕ НА МОДУЛЬ, а не связанными при импорте именами: связанное имя
# есть СНИМОК функции на момент импорта, и подмена канонического правила прошла бы мимо нас
# молча. Так же поступают все соседи по этому заказу (ADR-366/368/369/371/378/379/380).
from spa_core.monitoring import hit_rate_denominator_recovery as _rec
from spa_core.monitoring import silent_leg_day_price as _sldp
from spa_core.monitoring import writer_universe_lever_floor as _mat
from spa_core.utils.observation import observed
log = logging.getLogger('spa.monitoring.criterion_population_floor')
OUTPUT_FILENAME = 'criterion_population_floor.json'
VERSION = 'criterion-population-floor-v1'
STATUS_OK = 'OK'
STATUS_WARNING = 'WARNING'
STATUS_CRITICAL = 'CRITICAL'
STATUS_UNMEASURED = 'UNMEASURED'
#: Имена ступеней лестницы. Три, и они не сливаются.
RUNG_CEILING = 'ceiling'
RUNG_MATERIAL = 'material_floor'
RUNG_OUR_CODE = 'our_code_floor'
#: Сценарий потолка у соседа. Литерал назван ОДИН раз: второй копии в файле нет, иначе они
#: разошлись бы молча при переименовании у соседа.
SC_CEILING = 'ceiling_all_blocking'
SC_WRITER = 'writer_universe'
SC_OUR_CODE = 'our_code'
_ADVISORY = 'ADVISORY: `hit_rate`, `MIN_HIT_RATE`, `TriggerParams`, писатель журнала, `POLLED_ADAPTERS`, пины, адаптеры, пороги RiskPolicy v1.0, стоп-кран и живой трек НЕ трогаются — прибор только делит уже измеренный знаменатель на ступени по материалу'
#: Границы утверждения едут В АРТЕФАКТЕ, а не только в шапке модуля: читатель отчёта шапку
#: не открывает, а именно он переносит долю в решение об очереди починок.
WHAT_IT_DOES_NOT_PROVE = ['не печатает значение критерия и не печатает исход НИ ОДНОГО дня: под сентинелом это артефакт сентинела, а не наблюдение (конвенция ADR-300). Утверждение прибора — о ДОЛЕ населения',
    
    
    
    
    
    'не обещает, что день С материалом поднялся бы: материал — условие НЕОБХОДИМОЕ и не достаточное (ADR-302/ADR-378), '
        'поэтому пол есть ВЕРХНЯЯ граница достижимого знаменателя, а доля по полу — НИЖНЯЯ граница доли населения',
        
        
        
        
        
    'не утверждает, что вердикты убранных дней были бы верны или что HOLD был неправ',
    'не пересчитывает чужие числа: потолок, сценарии рычагов и цена молчащей ноги взяты у их производителей как есть, и собственного знаменателя у прибора нет ни одного',
        
        
        
        
        
    'не обещает, что починка фида молчащей ноги вернёт хоть один ИСТОРИЧЕСКИЙ день: материала для тех дат не существует, задним числом ряд не наполняется, и ценность такой починки лежит ВПЕРЁД',
        
        
        
        
        
    'не принимает ни строки у писателя, ни проводки ноги к фиду: и то и другое money-path и решение владельца']
NO_REC = 'потолочный прибор (`hit_rate_denominator_recovery`) не дал измерения — потолка нет, и делить не на что'
NO_SLDP = 'прибор цены молчащей ноги (`silent_leg_day_price`) не дал измерения — набор дней без материала неизвестен'

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _share(numerator: int, denominator: int) -> Optional[float]:
    """Доля в процентах либо ``None``. Ноль знаменателя — НЕ ноль доли (инв. #17)."""
    if denominator <= 0:
        return None
    return round(100.0 * numerator / denominator, 2)

def measure(data_dir: Path,
    *,
    now: Optional[datetime]=None,
    rec_doc: Optional[dict]=None,
    sldp_doc: Optional[dict]=None,
    mat_doc: Optional[dict]=None) -> dict:
    """Свести пол и потолок и пересчитать долю населения критерия.

    ``rec_doc`` / ``sldp_doc`` / ``mat_doc`` — точки инъекции для тестов: стенд подаёт
    выдачи соседей напрямую, не поднимая живой журнал. Умолчание — позвать соседей.
    """
    data_dir = Path(data_dir)
    doc: dict = {'version': VERSION,
        'generated_at': (now or _utcnow()).isoformat(),
        'subject': 'доля населения проходящего критерия, посчитанная по ПОЛУ знаменателя (что подпирает материал сегодня), а не по потолку (заказ #599/G13 приказа «Portfolio CIO»)',
            
            
            
            
            
        'unit': 'дни знаменателя hit_rate и доля населения в процентах (не доллары)',
        'advisory': _ADVISORY,
        'what_it_does_not_prove': list(WHAT_IT_DOES_NOT_PROVE)}
    f: List[str] = []
    doc['findings'] = f

    def refuse(reason: str) -> dict:
        doc['status'] = STATUS_UNMEASURED
        doc['unmeasured_reason'] = reason
        f.append(f'[НЕ ИЗМЕРЕНО] {reason}')
        return doc
    if rec_doc is None:
        try:
            rec_doc = _rec.measure(data_dir, now=now)
        except Exception as e:
            return refuse(f'{NO_REC}: {type(e).__name__}: {e}')
    if sldp_doc is None:
        try:
            sldp_doc = _sldp.measure(data_dir, now=now)
        except Exception as e:
            return refuse(f'{NO_SLDP}: {type(e).__name__}: {e}')
    if mat_doc is None:
        try:
            mat_doc = _mat.measure(data_dir, now=now)
        except Exception as e:
            mat_doc = None
    if (rec_doc or {}).get('status') == STATUS_UNMEASURED:
        return refuse(f"{NO_REC}: {rec_doc.get('unmeasured_reason')}")
    if (sldp_doc or {}).get('status') == STATUS_UNMEASURED:
        return refuse(f"{NO_SLDP}: {sldp_doc.get('unmeasured_reason')}")
    rec_pop = (rec_doc or {}).get('population') or {}
    sldp_pop = (sldp_doc or {}).get('population') or {}
    scenarios = (rec_doc or {}).get('scenarios') or {}
    # Тождество населений проверяется ПОИМЁННО. Оба соседа отвечают «8», и это НЕ
    # доказательство, что восьмёрки одинаковые: две разные дали бы долю, у которой
    # числитель и знаменатель про разное, и она выглядела бы измеренной.
    rec_days = rec_pop.get('recoverable_days')
    sldp_days = sldp_pop.get('recoverable_days')
    if rec_days is None or sldp_days is None:
        return refuse('сосед не назвал восстановимые дни поимённо — тождество населений проверить нечем, а по мощности оно не проверяется')
    rec_set, sldp_set = (set(rec_days), set(sldp_days))
    if rec_set != sldp_set:
        only_rec = sorted(rec_set - sldp_set)
        only_sldp = sorted(sldp_set - rec_set)
        return refuse(f"соседи говорят о РАЗНЫХ населениях: только у потолочного {only_rec or '—'}, только у прибора пола {only_sldp or '—'}; сведение дало бы долю, у которой числитель и знаменатель про разное")
    d_rec = rec_pop.get('denominator_today')
    d_sldp = sldp_pop.get('denominator_today')
    if d_rec is None or d_sldp is None or d_rec != d_sldp:
        return refuse(f'соседи расходятся в сегодняшнем знаменателе: {d_rec} против {d_sldp} — общего числителя у доли нет')
    denominator_today = int(d_rec)
    # Мало согласия соседей между собой: оба населения обязаны быть отобраны ОДНИМ
    # каноническим знаменателем, иначе они согласованно отвечают не на наш вопрос.
    for name, d in (('hit_rate_denominator_recovery', rec_doc),
        ('silent_leg_day_price', sldp_doc)):
        par = (d or {}).get('canonical_parity') or {}
        if not par.get('canonical_measured') or not par.get('passed'):
            return refuse(f'у соседа `{name}` не сошлась сверка с КАНОНИЧЕСКИМ знаменателем — его население отобрано вторым определением, и доля стояла бы не на том наборе')
    ceiling_sc = scenarios.get(SC_CEILING) or {}
    ceiling = ceiling_sc.get('denominator')
    if ceiling is None:
        return refuse(f'{NO_REC}: сценарий `{SC_CEILING}` не назван')
    ceiling = int(ceiling)
    # Потолок обязан раскладываться на «сегодня» плюс «восстановимые». Не сошлось ⇒
    # сосед говорит о другом населении, и вычитание из него было бы арифметикой по кругу.
    if ceiling != denominator_today + len(rec_set):
        return refuse(f'потолок соседа ({ceiling}) не равен знаменателю сегодня ({denominator_today}) плюс восстановимых ({len(rec_set)}) — числа соседа между собой не сходятся, сводить нечего')
    silent_legs = sorted((sldp_doc.get('answer') or {}).get('silent_legs') or [])
    material_empty: Set[str] = set()
    per_leg_days: Dict[str, List[str]] = {}
    for row in sldp_doc.get('per_leg') or []:
        days = sorted(row.get('blocking_day_list') or [])
        per_leg_days[row.get('leg')] = days
        material_empty.update(days)
    outside = sorted(material_empty - rec_set)
    if outside:
        return refuse(f"прибор пола назвал дни вне населения потолка ({', '.join(outside)}) — наборы разошлись, и вычитание было бы вычитанием из не того")
    our_sc = scenarios.get(SC_OUR_CODE) or {}
    owner_days = set(our_sc.get('recoverable_not_lifted') or [])
    outside_owner = sorted(owner_days - rec_set)
    if outside_owner:
        return refuse(f"потолочный прибор назвал дни владельца вне собственного населения ({', '.join(outside_owner)})")
    # Ступени вычитаются ПОСЛЕДОВАТЕЛЬНО, и день, который И без материала, И на рычаге
    # владельца, снимается РОВНО ОДИН раз: `owner_only` берётся уже за вычетом безматериальных.
    material_floor = ceiling - len(material_empty)
    owner_only = owner_days - material_empty
    our_code_floor = material_floor - len(owner_only)
    ladder = [{'rung': RUNG_CEILING, 'denominator': ceiling, 'share_pct': _share(denominator_today, ceiling), 'reading': 'ПОТОЛОК: все блокирующие дни при любом рычаге, гипотеза об идеальном материале — число, опубликованное ADR-371'},
        
        
        
        
        
        {'rung': RUNG_MATERIAL, 'denominator': material_floor, 'share_pct': _share(denominator_today, material_floor), 'reading': 'ПОЛ ПО МАТЕРИАЛУ: потолок минус дни, у ног которых нет ни одной точки ряда — их не возвращает ничей рычаг'},
            
            
            
            
            
        {'rung': RUNG_OUR_CODE,
            'denominator': our_code_floor,
            'share_pct': _share(denominator_today, our_code_floor),
            'reading': 'ПОЛ НАШЕГО КОДА: то же минус дни, чей рычаг лежит у владельца (`POLLED_ADAPTERS`, money-path, предмет №1 границы ADR-285)'}]
    doc['population'] = {'journal_days': (rec_doc.get('journal') or {}).get('days'),
        'denominator_today': denominator_today,
        'recoverable_in_principle': len(rec_set),
        'recoverable_days': sorted(rec_set),
        'days_without_material': sorted(material_empty),
        'days_owner_lever': sorted(owner_days),
        'days_recoverable_by_our_code_with_material': sorted(rec_set - material_empty - owner_days),
            
            
            
            
            
        'silent_legs': silent_legs,
        'blocking_days_per_silent_leg': per_leg_days,
        'parity_with_neighbours': {'same_recoverable_set': True,
            'same_denominator_today': True,
            'what_it_proves': 'оба соседа говорят об ОДНОМ населении поимённо, а не о двух наборах равной мощности; без этого доля собиралась бы из числителя и знаменателя про разное'}}
    doc['ladder'] = ladder
    writer_sc = scenarios.get(SC_WRITER) or {}
    writer_added = set(writer_sc.get('days_added') or [])
    writer_den = writer_sc.get('denominator')
    # Контроль маршрута: пол рычага писателя получается ДВУМЯ разными машинериями —
    # нашим вычитанием из сценария соседа и возмущением судьи с изъятой ногой. Совпадение
    # не обязано случиться по построению, потому оно и контроль; разошлись ⇒ НЕ ИЗМЕРЕНО,
    # и победитель не выбирается: какое из двух неверно, прибор не знает.
    route = {'measured': False, 'reason': None}
    if writer_den is None:
        route['reason'] = f'сценарий `{SC_WRITER}` у соседа не назван'
    else:
        ours = int(writer_den) - len(writer_added & material_empty)
        theirs = [r.get('writer_lever_floor_without_leg') for r in sldp_doc.get('per_leg') or [] if r.get('writer_lever_floor_without_leg') is not None]
        if len(theirs) != 1:
            route['reason'] = f'у соседа {len(theirs)} значений пола рычага писателя — сверять маршрут не с чем однозначно'
        else:
            route = {'measured': True,
                'reason': None,
                'our_route': ours,
                'neighbour_route': int(theirs[0]),
                'passed': ours == int(theirs[0]),
                'what_it_proves': 'пол рычага писателя получен ДВУМЯ машинериями — вычитанием названных дней из сценария и возмущением судьи с изъятой ногой — и они дают одно число'}
    doc['route_parity'] = route
    if route.get('measured') and (not route.get('passed')):
        return refuse(f"маршруты разошлись: пол рычага писателя нашим вычитанием {route['our_route']} дн., возмущением судьи у соседа {route['neighbour_route']} дн. — одно из двух неверно, и какое именно, прибор не знает")
    # Подтверждение ВТОРОГО производителя материала объявлено НЕ несущим: у него своё
    # население (доллары класса `writer_universe`), и отменять наш ответ чужая ось не вправе.
    # Поэтому его отсутствие — строка «[НЕ ИЗМЕРЕНО]», а не отказ прибора.
    if mat_doc is None:
        corr = {'measured': False,
            'reason': 'прибор материала не дал документа — звать было нечем'}
    elif mat_doc.get('status') == STATUS_UNMEASURED:
        corr = {'measured': False,
            'reason': f"прибор материала позван и сам НЕ ИЗМЕРИЛ: {mat_doc.get('unmeasured_reason')}"}
    else:
        verdicts = {r.get('cycle_date'): r.get('verdict') for r in mat_doc.get('per_day') or []}
        shared = sorted(set(verdicts) & rec_set)
        disagree = sorted((d for d in shared if (verdicts[d] == 'material') == (d in material_empty)))
        corr = {'measured': True,
            'reason': None,
            'days_compared': len(shared),
            'disagreements': disagree,
            'agreed': not disagree,
            'what_it_proves': 'второй производитель, судящий о материале на СВОЁМ населении (доллары класса `writer_universe`), на общих днях говорит то же самое'}
    doc['material_corroboration'] = corr
    queue: List[dict] = []
    for key, label in ((SC_WRITER, 'строка отсечения по universe у писателя журнала'),
        ('key_mismatch', 'свести два имени одних денег (близнец)'),
        (SC_OUR_CODE, 'оба рычага нашего кода вместе')):
        sc = scenarios.get(key) or {}
        added = set(sc.get('days_added') or [])
        with_material = sorted(added - material_empty)
        queue.append({'lever': key,
            'reading': label,
            'days_published': len(added),
            'days_with_material': len(with_material),
            'day_list_with_material': with_material,
            'days_resting_on_absent_material': sorted(added & material_empty),
            'whose': 'наш код'})
    queue.append({'lever': 'owner_polled_adapters',
        'reading': 'провести ногу в опрашиваемый набор (`POLLED_ADAPTERS`)',
        'days_published': len(owner_days),
        'days_with_material': len(owner_only),
        'day_list_with_material': sorted(owner_only),
        'days_resting_on_absent_material': sorted(owner_days & material_empty),
        'whose': 'владелец (money-path, предмет №1 границы ADR-285)'})
    queue.append({'lever': 'silent_leg_feed',
        'reading': 'провести молчащую ногу к живому фиду ' + (', '.join((f'`{x}`' for x in silent_legs)) if silent_legs else '—'),
            
            
            
            
            
        'days_published': len(material_empty),
        'days_with_material': 0,
        'day_list_with_material': [],
        'days_resting_on_absent_material': sorted(material_empty),
        'whose': 'наш код (проводка фида), но цена ВПЕРЁД, а не в исторических днях'})
    doc['repair_queue'] = queue
    doc['answer'] = {'denominator_today': denominator_today,
        'ceiling': ceiling,
        'material_floor': material_floor,
        'our_code_floor': our_code_floor,
        'share_by_ceiling_pct': _share(denominator_today, ceiling),
        'share_by_material_floor_pct': _share(denominator_today, material_floor),
        'share_by_our_code_floor_pct': _share(denominator_today, our_code_floor),
        'days_queue_counts_but_material_denies': len(material_empty),
        'criterion_value': None,
        'criterion_value_note': 'НЕ СЧИТАЕТСЯ НАМЕРЕННО: вердикт поднятого дня получен под сентинелом и есть артефакт сентинела (ADR-300). Ответ заказа — о ДОЛЕ НАСЕЛЕНИЯ',
            
            
            
            
            
        'bound_direction': 'доля по полу есть НИЖНЯЯ граница доли населения: материал — условие необходимое и не достаточное, поэтому пол есть ВЕРХНЯЯ граница достижимого знаменателя'}
    sh_c = doc['answer']['share_by_ceiling_pct']
    sh_m = doc['answer']['share_by_material_floor_pct']
    sh_o = doc['answer']['share_by_our_code_floor_pct']
    f.append(f'[ОТВЕТ] доля населения критерия: по ПОТОЛКУ {denominator_today} из {ceiling} = {sh_c} % (опубликовано ADR-371); по ПОЛУ МАТЕРИАЛА {denominator_today} из {material_floor} = {sh_m} %; по полу НАШЕГО КОДА {denominator_today} из {our_code_floor} = {sh_o} %. Значение критерия не печатается (ADR-300)')
    if material_empty:
        f.append(f"[CRITICAL] {len(material_empty)} дн. потолка материал НЕ подпирает ({', '.join(sorted(material_empty))}): их ноги ({', '.join((f'`{x}`' for x in silent_legs))}) не имеют в ряду ни одной точки (ADR-379). Эти дни очередь считает работой, а вернуть их не может НИЧЕЙ рычаг: материала для тех дат не существует, а задним числом ряд не наполняется. Разница {sh_c} % → {sh_m} % есть в точности эта часть")
    if owner_only:
        f.append(f"[ЦЕНА] ещё {len(owner_only)} дн. ({', '.join(sorted(owner_only))}) материал подпирает, но рычаг там у ВЛАДЕЛЬЦА (`POLLED_ADAPTERS`, money-path, предмет №1 границы ADR-285): нашим кодом они не возвращаются ни при каком его состоянии")
    writer_row = next((q for q in queue if q['lever'] == SC_WRITER), None)
    if writer_row and writer_row['days_resting_on_absent_material']:
        f.append(f"[ОЧЕРЕДЬ] порядок починок МЕНЯЕТСЯ: строка писателя, опубликованная в {writer_row['days_published']} дн. из {len(rec_set)} восстановимых, материалом подтверждена на {writer_row['days_with_material']} дн. ({', '.join(writer_row['day_list_with_material']) or '—'}); остальные {len(writer_row['days_resting_on_absent_material'])} дн. её рычагом не поднимаются вовсе. Читатель, взявший {writer_row['days_published']} дн. как план, ПЕРЕОЦЕНИТ отдачу самой дешёвой строки вдвое")
    f.append(f'[ОСТАТОК] работой, подтверждённой материалом, остаются {our_code_floor - denominator_today} дн. нашего кода и {len(owner_only)} дн. владельца — {material_floor - denominator_today} дн. из {len(rec_set)} восстановимых по потолку, а не {len(rec_set)}')
    if corr.get('measured') and corr.get('disagreements'):
        f.append(f"[РАСХОЖДЕНИЕ] второй производитель материала (ADR-378) спорит о {len(corr['disagreements'])} дн. ({', '.join(corr['disagreements'])}): у него своё население (доллары класса), и отменить наш ответ он не вправе — но расхождение названо, а не проглочено")
    elif not corr.get('measured'):
        f.append(f"[НЕ ИЗМЕРЕНО] подтверждение вторым производителем материала не снято: {corr.get('reason')}. Ответ прибора на нём не держится")
    # CRITICAL ровно тогда, когда очередь считает работой дни, которых не вернёт НИЧЕЙ
    # рычаг; WARNING — когда рычаг есть, но он у владельца (предмет №1 границы ADR-285).
    if material_empty:
        doc['status'] = STATUS_CRITICAL
    elif owner_only:
        doc['status'] = STATUS_WARNING
    else:
        doc['status'] = STATUS_OK
    return doc

def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: население → лестница → очередь → контроли."""
    out: List[str] = []
    pop = doc.get('population') or {}
    out.append(f"   доля населения критерия по ПОЛУ, а не по потолку (заказ #599/G13): {doc.get('status')} · знаменатель сегодня {pop.get('denominator_today')} · восстановимых по потолку {pop.get('recoverable_in_principle')} · без материала {len(pop.get('days_without_material') or [])}")
    if doc.get('unmeasured_reason'):
        out.append(f"   [НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}")
    for rung in doc.get('ladder') or []:
        share = rung.get('share_pct')
        out.append(f"   {rung['rung']}: знаменатель {rung['denominator']} · доля " + (f'{share} %' if share is not None else 'НЕ ИЗМЕРЕНО'))
    for q in doc.get('repair_queue') or []:
        out.append(f"   очередь · {q['lever']}: опубликовано {q['days_published']} дн. → материалом подтверждено {q['days_with_material']} дн. ({q['whose']})")
    par = observed(doc, 'route_parity', kind=dict)
    out.append('   контроль маршрута (пол рычага писателя двумя машинериями): ' + ('секции нет — прибор до неё не дошёл' if par is None else 'сошёлся' if par.get('passed') else 'РАЗОШЁЛСЯ' if par.get('measured') else 'НЕ ИЗМЕРЕН'))
    corr = observed(doc, 'material_corroboration', kind=dict)
    out.append('   подтверждение вторым производителем материала: ' + ('секции нет — прибор до неё не дошёл' if corr is None else 'сошлось' if corr.get('agreed') else 'РАЗОШЛОСЬ' if corr.get('measured') else 'НЕ ИЗМЕРЕНО'))
    for line in doc.get('findings') or []:
        out.append(f'   {line}')
    note = (doc.get('answer') or {}).get('criterion_value_note')
    if note:
        out.append(f'   НЕ ДОКЛАДЫВАЕТ: {note}')
    bound = (doc.get('answer') or {}).get('bound_direction')
    if bound:
        out.append(f'   НАПРАВЛЕНИЕ ГРАНИЦЫ: {bound}')
    if doc.get('advisory'):
        out.append(f"   {doc['advisory']}")
    return out

def run(root: Optional[str]=None,
    *,
    now: Optional[datetime]=None,
    write: bool=True,
    **kwargs) -> dict:
    """Форма, которую ждут ступень переписей `findings_bridge` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save
    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / 'data'
    doc = measure(data_dir, now=now, **kwargs)
    findings = list(doc.get('findings') or [])
    doc['overall'] = doc['status']
    doc['counts'] = {'critical': sum((1 for x in findings if x.startswith('[CRITICAL]'))),
        'warn': sum((1 for x in findings if x.startswith('[ЦЕНА]') or x.startswith('[ОЧЕРЕДЬ]') or x.startswith('[РАСХОЖДЕНИЕ]'))),
            
            
            
            
            
        'info': sum((1 for x in findings if x.startswith('[ОТВЕТ]') or x.startswith('[ОСТАТОК]'))),
            
            
            
            
            
        'unchecked': (1 if doc['status'] == STATUS_UNMEASURED else 0) + sum((1 for x in findings if x.startswith('[НЕ ИЗМЕРЕНО]')))}
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc

def main(argv: Optional[List[str]]=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description='доля населения критерия по ПОЛУ знаменателя, а не по потолку (заказ #599/G13)')
    ap.add_argument('--data-dir', default=None)
    ap.add_argument('--no-write', action='store_true')
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else Path(os.environ.get('SPA_DATA_DIR') or Path(__file__).resolve().parents[2] / 'data')
    doc = measure(data_dir)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(data_dir) / OUTPUT_FILENAME))
    for line in format_report(doc):
        print(line)
    return 0 if doc['status'] in (STATUS_OK, STATUS_WARNING, STATUS_CRITICAL) else 1
if __name__ == '__main__':
    raise SystemExit(main())