#!/usr/bin/env python3
"""Director OS · Исследование САМОЙ СИСТЕМЫ — производный задел, а не выдуманный список.

Что здесь меряется
==================
Замер показал: инвестиционные исследования живут (лаборатории и бумага — часы), а
исследований самой системы **нет**. Живы только курьер находок и ремонтный оркестратор.

Задел исследований здесь не придумывается. Он ВЫВОДИТСЯ из улик, которые система уже
про себя собрала, по шести наблюдаемым поводам:

1. **повторяющийся отказ** — одна и та же находка надёжности живёт долго или
   воспроизводится;
2. **массовое «не измерено»** — целая стадия или поле не измерено у всего населения;
   это вопрос не к экземпляру, а к архитектуре;
3. **мёртвое объявление** — схема объявляет носитель, писателя нет;
4. **ручная работа владельца** — элемент очереди, который система должна разбирать сама;
5. **расхождение источников** — две копии одного числа расходятся;
6. **остановка автономии** — стадия конвейера, дальше которой работа не идёт.

Чего он НЕ делает
=================
Ничего не меняет в проде. Не заводит карточек. Не назначает исполнителей. Не оценивает
часы. Это ЗАДЕЛ ВОПРОСОВ, и каждый вопрос обязан назвать улику, из которой он вырос, —
иначе это не исследование, а мнение.

Только stdlib. LLM запрещён.
"""
from __future__ import annotations

from datetime import datetime, timezone

SCHEMA = 'system_rnd/1'

#: Поводы завести исследовательский вопрос. Каждый — наблюдаемое условие, не настроение.
TRIGGERS = ('RECURRING_FAILURE', 'MASS_NOT_MEASURED', 'DEAD_DECLARATION',
            'MANUAL_OWNER_WORK', 'SOURCE_DIVERGENCE', 'AUTONOMY_STOP')

#: Стадии исследовательской петли. Производство она НЕ меняет: последняя стадия —
#: предложение, и дальше идёт человек либо разбор архитектуры.
LOOP = ('OBSERVATION', 'QUESTION', 'EVIDENCE', 'HYPOTHESIS', 'EXPERIMENT',
        'RESULT', 'PROPOSAL')

#: На какой стадии петля стоит сегодня. Ни один вопрос не рождается дальше улики:
#: гипотеза без поставленного опыта — это ещё не результат.
STAGE_OBSERVED = 'EVIDENCE'


def _now():
    return datetime.now(timezone.utc)


def _q(trigger, question, *, evidence, population=None, hypothesis=None,
       experiment=None, cost_of_ignoring=None):
    if trigger not in TRIGGERS:
        raise ValueError(f'повод {trigger!r} вне словаря {TRIGGERS}')
    if not evidence:
        raise ValueError(f'вопрос без улики не является исследовательским: {question!r}')
    return {
        'trigger': trigger,
        'question': question,
        'evidence': evidence,
        'population': population,
        'hypothesis': hypothesis,
        'experiment': experiment,
        'cost_of_ignoring': cost_of_ignoring,
        'loop_stage': STAGE_OBSERVED,
        'changes_production': False,
    }


def from_reliability(rel, *, min_age_days=14.0):
    """Повторяющиеся отказы: находка, которая живёт долго, есть вопрос к архитектуре."""
    out = []
    if not rel:
        return out
    findings = rel.get('findings') or ()
    confirmed = [f for f in findings
                 if str(f.get('status') or '') == 'ACTIVE_CONFIRMED']
    by_kind = {}
    for f in confirmed:
        key = str(f.get('category') or f.get('kind') or f.get('rule') or 'UNKNOWN')
        by_kind.setdefault(key, []).append(f)
    for kind, group in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        if len(group) < 3:
            continue          # один случай — инцидент; три — уже класс
        out.append(_q('RECURRING_FAILURE',
                      f'почему отказ рода «{kind}» воспроизводится, а не устраняется',
                      evidence=f'reliability_snapshot: подтверждённых находок этого рода '
                               f'{len(group)}',
                      population=len(group),
                      hypothesis='устраняется экземпляр, а не причина рода',
                      experiment='проверить, есть ли у рода один общий источник; если да — '
                                 'закрыть его и измерить убыль населения рода',
                      cost_of_ignoring='население рода не убывает, работа повторяется'))
    return out


def from_service_health(health):
    """Массовое «не измерено» — вопрос к архитектуре, а не к экземпляру."""
    out = []
    if not health:
        return out
    counts = health.get('counts') or {}
    total = counts.get('total') or 0
    if total and counts.get('health_not_measured') == total:
        out.append(_q('MASS_NOT_MEASURED',
                      'что должно считаться здоровьем компонента, если контракта не '
                      'объявлено ни для одного',
                      evidence=f'здоровье не измерено у {total} из {total} сущностей; '
                               f'{health.get("health_contract_note")}',
                      population=total,
                      hypothesis='здоровье невыводимо из свежести файла: свежий файл '
                                 'доказывает, что писатель дошёл до записи',
                      experiment='объявить контракт у трёх самых важных сущностей и '
                                 'измерить, отличается ли вердикт от вердикта по свежести',
                      cost_of_ignoring='флот выглядит живым, и никто не знает, работает '
                                       'ли он по назначению'))
    unmeasured = counts.get('producing_not_measured') or 0
    if unmeasured and total and unmeasured / total > 0.3:
        out.append(_q('MASS_NOT_MEASURED',
                      'почему у трети флота не объявлен ни артефакт, ни срок его годности',
                      evidence=f'«производит ли выход» не измерено у {unmeasured} из {total}',
                      population=unmeasured,
                      hypothesis='объявление выхода не является обязательным при рождении '
                                 'компонента',
                      experiment='сделать объявление обязательным для НОВЫХ компонентов и '
                                 'измерить, убывает ли доля неизмеренных',
                      cost_of_ignoring='«не измерено» читается как «в порядке»'))
    kinds = health.get('by_kind') or {}
    if kinds.get('UNKNOWN'):
        out.append(_q('DEAD_DECLARATION',
                      'почему род сущности не объявляет ни один источник',
                      evidence=f'род не выводится у {kinds["UNKNOWN"]} сущностей; поля '
                               f'kind/type нет нигде. {health.get("kind_note")}',
                      population=kinds['UNKNOWN'],
                      hypothesis='род никогда не был нужен потребителю, поэтому его не '
                                 'объявляли',
                      experiment='объявить род у десяти сущностей и посмотреть, меняет ли '
                                 'это хоть один вывод кокпита',
                      cost_of_ignoring='классификация по имени ошибается в обе стороны'))
    return out


def from_bridge(bridge):
    """Мёртвые объявления: схема объявляет носитель, писателя нет."""
    out = []
    if not bridge or bridge.get('state') != 'READ':
        return out
    gaps = bridge.get('contract_gaps') or ()
    schema_gaps = [g for g in gaps if g.get('classification') == 'SCHEMA GAP']
    writer_gaps = [g for g in gaps if g.get('classification') == 'WRITER GAP']
    if schema_gaps:
        out.append(_q('DEAD_DECLARATION',
                      'почему колонки объявляются и не заполняются — и сколько ещё таких '
                      'в других хранилищах',
                      evidence='разрывов контракта улик моста: '
                               + '; '.join(g.get('anomaly', '') for g in schema_gaps),
                      population=len(schema_gaps),
                      hypothesis='объявление схемы и написание писателя — разные работы, '
                                 'и вторая необязательна',
                      experiment='пересчитать по всем базам проекта колонки, у которых нет '
                                 'ни одного писателя',
                      cost_of_ignoring='значение по умолчанию выдаётся за измерение'))
    if writer_gaps:
        out.append(_q('SOURCE_DIVERGENCE',
                      'почему боевая сборка идёт мимо собственного писателя',
                      evidence='; '.join(g.get('evidence_note') or g.get('anomaly', '')
                                         for g in writer_gaps),
                      population=len(writer_gaps),
                      hypothesis='писатель написан для одного пути исполнения, а работает '
                                 'другой',
                      experiment='сверить состав вызовов писателя с составом путей сборки',
                      cost_of_ignoring='улики есть на диске и отсутствуют там, где их ищут'))
    nf = bridge.get('commits_not_found') or ()
    if nf:
        out.append(_q('SOURCE_DIVERGENCE',
                      'почему доставка попадает в рабочий клон, а не в канон',
                      evidence=f'заявленных коммитов не найдено в канонических '
                               f'репозиториях: {len(nf)}',
                      population=len(nf),
                      hypothesis='целевой репозиторий доставки не объявлен и выбирается '
                                 'тем, где оказался рабочий каталог',
                      experiment='объявить целевой репозиторий задачей и сверять '
                                 'достижимость коммита из канонической ссылки',
                      cost_of_ignoring='«доставлено» означает «закоммичено куда-то»'))
    return out


def from_owner_queue(decisions):
    """Ручная работа владельца, которую система обязана разбирать сама."""
    out = []
    if not decisions or decisions.get('state') != 'READ':
        return out
    system_items = [i for i in decisions.get('items') or ()
                    if i.get('item_class') == 'SYSTEM_SHOULD_RESOLVE']
    if system_items:
        out.append(_q('MANUAL_OWNER_WORK',
                      'какая доля очереди владельца — вообще не его работа',
                      evidence=f'элементов, не принадлежащих ни одному из трёх предметов '
                               f'границы: {len(system_items)} из '
                               f'{decisions.get("waiting_total")}',
                      population=len(system_items),
                      hypothesis='предмет не проверяется при ПОСТАНОВКЕ вопроса, только '
                                 'при разборе',
                      experiment='проверять предмет в момент создания и измерить, убывает '
                                 'ли доля дефектов очереди',
                      cost_of_ignoring='очередь выглядит занятостью владельца'))
    no_age = decisions.get('items_without_declared_age') or 0
    if no_age:
        out.append(_q('MASS_NOT_MEASURED',
                      'почему носители очереди не объявляют возраст вопроса',
                      evidence=f'элементов без объявленного возраста: {no_age}',
                      population=no_age,
                      hypothesis='возраст не объявляют потому, что его никто не читал',
                      experiment='добавить дату в один носитель и посмотреть, меняет ли '
                                 'это порядок в очереди',
                      cost_of_ignoring='нельзя сказать, что ждёт дольше всех'))
    return out


def from_pipeline(pipeline):
    """Остановка автономии — самый дорогой исследовательский вопрос системы."""
    out = []
    brk = (pipeline or {}).get('autonomy_breaks_at')
    if not brk:
        return out
    # Название следующей стадии берётся ИЗ САМОГО конвейера, а не печатается ключом:
    # «CLASSIFICATION» — имя для машины, «Разбор по предмету» — для владельца.
    titles = {s.get('stage'): s.get('title') for s in (pipeline or {}).get('stages') or ()}
    nxt = titles.get(brk.get('hand_off_to')) or brk.get('hand_off_to')
    out.append(_q('AUTONOMY_STOP',
                  f'что именно мешает переходу «{brk.get("title")}» → «{nxt}»',
                  evidence=f'{brk.get("reason")} (носитель: {brk.get("evidence_carrier")})',
                  hypothesis='стадия требует суждения, которое пока делает человек',
                  experiment='закрыть стадию детерминированными правилами там, где их '
                             'достаточно, и измерить остаток, требующий суждения',
                  cost_of_ignoring='дальше этой точки работа не идёт сама'))
    return out


def build_system_rnd(*, reliability=None, service_health=None, bridge=None,
                     owner_decisions=None, pipeline=None, now=None):
    """Производный задел исследований системы."""
    now = now or _now()
    questions = []
    questions += from_pipeline(pipeline)
    questions += from_service_health(service_health)
    questions += from_bridge(bridge)
    questions += from_owner_queue(owner_decisions)
    questions += from_reliability(reliability)
    by_trigger = {}
    for q in questions:
        by_trigger[q['trigger']] = by_trigger.get(q['trigger'], 0) + 1
    return {
        'schema': SCHEMA,
        'state': 'READ' if questions else 'NOT_MEASURED',
        'measured_at': now.isoformat(),
        'questions': questions,
        'question_count': len(questions),
        'by_trigger': by_trigger,
        'loop': list(LOOP),
        'loop_stage_reached': STAGE_OBSERVED if questions else None,
        'derivation_note': ('каждый вопрос выведен из улики, которую система уже про себя '
                            'собрала; вопрос без улики здесь собрать нельзя'),
        'production_note': ('исследование производство НЕ меняет: последняя стадия петли — '
                            'предложение, дальше идёт разбор архитектуры или владелец'),
        'running_note': ('это ЗАДЕЛ, а не работающая петля: ни один опыт из списка ещё не '
                         'поставлен, и стадия петли честно стоит на улике'),
    }
