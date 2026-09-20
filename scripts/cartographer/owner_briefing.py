#!/usr/bin/env python3
"""Owner Briefing (Director OS, Phase 1): five answers for the owner, offline.

Built ONLY from stored Cartographer artifacts — a snapshot, an offline comparison and the
source-of-truth map. This layer OBSERVES NOTHING of its own: it adds no fact, queries no
source, and is not a new source of truth. If a fact is not in the artifacts, it stays
UNKNOWN here too.

Offline by construction: no ``subprocess``, no ``socket``, no ``urllib``.

Five questions:
  A. On what moment do we have a trustworthy picture, and how complete is it?
  B. What materially changed since the chosen earlier observation?
  C. What deserves attention, and on what concrete ground?
  D. What may need the owner's decision — and what cannot yet be justified at all?
  E. What does the system still not know?
  F. What does this briefing NOT prove?

Two rules govern every line below:
  * nothing here may be stronger than the evidence it points at;
  * a loss of observation is never rendered as an improvement.
"""
import datetime as dt
import hashlib
import json

BRIEFING_SCHEMA = 'cartographer.owner_briefing/0.1'

#: Rules whose findings are worth the owner's ATTENTION, each with the practical meaning
#: that justifies raising it. A rule that is not listed here never becomes an alarm — most
#: UNKNOWNs are known limits of the instrument, not problems with the machine.
ATTENTION_RULES = {
    'DRIFT_CHANGED_OR_MISSING_ON_DISK': (
        'Содержимое файла на диске отличается от сравниваемого коммита или его нет',
        'Доказано РАЗЛИЧИЕ СОДЕРЖИМОГО на диске — и только оно. Что именно исполняется, '
        'здесь не наблюдается вовсе: долгоживущий процесс держит код, набранный при '
        'старте, поэтому «на диске другое» не равно «работает другое».'),
    'DRIFT_PRODUCTION_ONLY_TRACKED': (
        'Файл отслеживается на диске и отсутствует в сравниваемом коммите',
        'Утверждение ровно одно: его нет В ЭТОМ коммите. Из этого не следует ни что он '
        'существует только на этой машине (он может быть в другой ветке, другом коммите '
        'или другом дереве), ни что он лишний или выведен из эксплуатации.'),
    'DRIFT_PRODUCTION_ONLY_UNTRACKED': (
        'Неотслеживаемый файл на диске, отсутствующий в сравниваемом коммите',
        'Он не отслеживается git и его нет в этом коммите — значит, история этого дерева '
        'его не хранит. Где он есть ещё, наблюдение не отвечает; untracked никогда не '
        'означает «ненужный».'),
    'STATUS_DEGRADED': (
        'Компонент в состоянии DEGRADED',
        'Либо последний код выхода ненулевой, либо plist установлен, но сервис не '
        'загружен. Значение кода выхода по меткам объявлено в проде и здесь НЕ '
        'применяется: «последний исход ненулевой» ≠ «сломан».'),
    'STATUS_STALE': (
        'Объявленный артефакт вышел за свой ОБЪЯВЛЕННЫЙ SLO',
        'Порог взят из манифеста, не выдуман. Кто именно должен был записать файл — '
        'неизвестно: свежесть не есть атрибуция производителя.'),
    'LOADED_WITHOUT_INSTALLED_PLIST': (
        'Сервис зарегистрирован в домене, а plist в проверенных каталогах нет',
        'Проверялись три каталога plist; другие пути и домены не перечислялись, поэтому '
        'поведение после перезагрузки отсюда НЕ следует — установлено лишь, что в '
        'проверенных местах файла конфигурации не найдено.'),
    'CACHED_VS_REMOTE_DIVERGED': (
        'Кэшированный origin/main расходится с живым',
        'Сравнение велось против кэша; fetch не выполнялся. Это про свежесть ЛИНЕЙКИ, а '
        'не про состояние прод-дерева.'),
    'SYNC_STATUS_STALE': (
        'Отчёт синхронизации кода старше часа',
        'Устаревшая УЛИКА, а не доказанное расхождение кода. Порог в 1 час — уже '
        'существующий советательный порог, не выдуманный здесь.'),
    'REGISTRY_STALE': (
        'Реестр агентов старше своего SLO в 26 часов',
        'Устаревшая улика о составе реестра. Про живость агентов не говорит ничего.'),
    'ENABLE_OVERRIDE_WITHOUT_SERVICE': (
        'Для метки есть override enable/disable, но сервиса нет',
        'Настройка-сирота: она ничего не запускает. Это не признак загрузки.'),
}

#: What still has to be found out, and the smallest safe next step, per owner-decision
#: condition. Deliberately conservative: where the honest answer is "investigate first",
#: that is what it says. Nothing here creates, closes or schedules anything.
OWNER_CANDIDATE_GUIDANCE = {
    'drift_present': (
        'Для каждого файла: это незадеплоенная правка, локальный эксперимент или остаток '
        'прошлой доставки? По самому наблюдению это неразличимо.',
        'Разбор списка ЧЕЛОВЕКОМ по одному файлу. Автоматического безопасного шага нет: '
        'любое устранение меняет прод-дерево, а это предмет владельца.'),
    'installed_but_not_loaded': (
        'Намеренно ли агент не загружен (вывод из эксплуатации) или это сбой bootstrap.',
        'Сначала расследование: сверить намерение в манифесте с историей решений. '
        'Загрузка сервиса — изменение launchd и требует разрешения владельца.'),
    'orphaned_service': (
        'Откуда запущен сервис и нужен ли он вообще.',
        'Сначала расследование. Выгрузка меняет launchd — только решением владельца.'),
    'cached_vs_remote_diverged': (
        'Отстаёт ли прод от origin по коду или расходится только кэш ссылки.',
        'Сведение выполняет существующий writer в проде; наблюдатель его не запускает.'),
}

#: What this briefing never proves, whatever it shows.
CLAIM_LIMITS = (
    'HEALTHY и PRODUCING_OUTPUT остаются НЕИЗВЕСТНЫМИ: семантической пробы здоровья не '
    'существует, и ни один PID её не заменяет.',
    'Наличие и свежесть файла не доказывают, КАКОЙ процесс его записал '
    '(producer_attribution: UNKNOWN).',
    'Отсутствие изменений между двумя снимками не доказывает непрерывной доступности '
    'между ними: наблюдались два момента, а не интервал.',
    'Наблюдение внутри одного прогона не атомарно: пробы идут последовательно, поэтому '
    'изменение может лежать между двумя окнами.',
    'Ни одно число здесь не является оценкой здоровья системы: сводного health score нет '
    'намеренно — принятого контракта для него не существует.',
)

#: Human wording for a change type. A type without an entry falls back to its own name —
#: better a raw code than an invented explanation.
CHANGE_HEADLINES = {
    'STAGE_CHANGED': 'Стадия {detail} изменилась',
    'STAGE_OBSERVATION_LOST': 'Стадия {detail}: наблюдение ПОТЕРЯНО (не остановка)',
    'STAGE_OBSERVATION_GAINED': 'Стадия {detail}: наблюдение появилось',
    'STATUS_CHANGED': 'Статус компонента изменился',
    'STATUS_CHANGED_BY_OBSERVATION_QUALITY': 'Ярлык статуса сдвинулся от качества наблюдения',
    'COMPONENT_APPEARED': 'Компонент появился в области наблюдения',
    'COMPONENT_DISAPPEARED': 'Компонент исчез (все источники были перечитаны)',
    'COMPONENT_ABSENT_UNVERIFIABLE': 'Компонент отсутствует, но источник был недоступен',
    'PID_CHANGED': 'Сменился PID (сам по себе не перезапуск и не сбой)',
    'LAST_EXIT_CHANGED': 'Изменился последний код выхода (значение не интерпретируется)',
    'ARTIFACT_SLO_CROSSED': 'Артефакт пересёк ОБЪЯВЛЕННЫЙ SLO',
    'ARTIFACT_STATE_CHANGED': 'Изменилось состояние артефакта',
    'ARTIFACT_FRESHNESS_UNKNOWN': 'Свежесть артефакта стала неопределимой',
    'BASELINE_CHANGED': 'Сменился коммит сравнения (линейка сдвинулась)',
    'REPOSITORY_HEAD_CHANGED': 'HEAD репозитория изменился',
    'REMOTE_REF_CHANGED': 'Живой origin/main сдвинулся',
    'DRIFT_PATH_ADDED': 'В расхождение добавился путь',
    'DRIFT_PATH_REMOVED': 'Путь ушёл из расхождения',
    'DRIFT_MEASURABILITY_CHANGED': 'Измеримость расхождения изменилась',
    'DECLARATION_CHANGED': 'Изменилась декларация (о работе системы не говорит)',
    'INSTALLED_CONFIG_CHANGED': 'Изменилась установленная конфигурация',
    'ENTRYPOINT_CHANGED': 'Изменилась точка входа',
    'INSTALLED_PLIST_ADDED': 'Установлен новый plist',
    'INSTALLED_PLIST_REMOVED': 'Plist снят',
    'COVERAGE_CHANGED': 'Изменилось покрытие наблюдения',
    'DOMAIN_VERDICT_OBSERVATION_LOST': 'Домен {detail} перестал отвечать по метке '
                                       '(знание потеряно)',
    'DOMAIN_VERDICT_OBSERVATION_GAINED': 'Домен {detail}: вердикт по метке появился',
    'DOMAIN_VERDICT_CHANGED': 'Вердикт домена {detail} по метке изменился',
    'SCHEMA_FIELD_ABSENT': 'Поле есть только с одной стороны (пробел схемы, не значение)',
    'FINDING_NEW': 'Новая находка',
    'FINDING_RESOLVED': 'Находка снята ДОКАЗАТЕЛЬСТВОМ',
    'FINDING_NOT_RECHECKED': 'Находка исчезла, но НЕ перепроверена',
    'FINDING_APPLICABILITY_CHANGED': 'Правило перестало применяться к своему объекту',
    'GRAPH_SIZE_CHANGED': 'Размер производного графа изменился',
    'OLLAMA_REACHABILITY_CHANGED': 'Изменилась доступность локального API Ollama',
}

#: Phase 0C semantics the briefing must never quietly drop.
SEMANTIC_GUARDS = (
    'UNKNOWN не означает false.',
    'NOT_RECHECKED не означает resolved.',
    'Смена baseline не означает, что production починили.',
    'Снятие SLO или декларации не означает восстановление артефакта.',
    'Обычный переход расписанного агента между «работает» и «ждёт» — не инцидент.',
)


class BriefingInputError(Exception):
    """Inconsistent or incomplete inputs. Never degraded into a normal briefing."""


def _evidence(artifact, pointer, note=None):
    rec = {'artifact': artifact, 'pointer': pointer}
    if note:
        rec['note'] = note
    return rec


def _age(seconds):
    if seconds is None:
        return 'UNKNOWN'
    if seconds < 90:
        return f'{int(seconds)} с'
    if seconds < 5400:
        return f'{seconds / 60:.0f} мин'
    if seconds < 172800:
        return f'{seconds / 3600:.1f} ч'
    return f'{seconds / 86400:.1f} сут'


def _parse(ts):
    try:
        return dt.datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _freshness(new_snapshot, diff, sot, generated_at):
    started, finished = new_snapshot.get('started_at'), new_snapshot.get('finished_at')
    t_finished, t_gen = _parse(finished), _parse(generated_at)
    age = (t_gen - t_finished).total_seconds() if (t_finished and t_gen) else None
    window = None
    t_started = _parse(started)
    if t_started and t_finished:
        window = round((t_finished - t_started).total_seconds(), 1)

    coverage = new_snapshot.get('coverage') or {}
    sources = []
    for key, label, meaning in (
        ('manifest_readable', 'architecture/manifest.json (намерение)',
         'без него стадия DECLARED = null для всех компонентов'),
        ('registry_readable', 'data/agent_registry.json (реестр)',
         'без него стадия REGISTERED = null'),
        ('installed_scan_complete', 'plist на диске (установленная конфигурация)',
         'без него стадия INSTALLED = null, а не false'),
        ('domains_complete', 'домены launchd (адресные пробы)',
         'нечитаемый домен делает LOADED = null для ВСЕХ меток'),
        ('launchctl_list_ok', 'launchctl list (PID и последний код выхода)',
         'без него RUNNING = null и last_exit неизвестен'),
        ('ps_ok', 'таблица процессов', 'без неё RUNNING = null'),
        ('document_index_available', 'индекс docs/** на закреплённом коммите',
         'без него «документа нет» неотличимо от «мы не смотрели»'),
        ('sync_status_readable', 'отчёт code_sync',
         'без него исход последней синхронизации неизвестен'),
    ):
        value = coverage.get(key)
        sources.append({
            'source': label, 'coverage_key': key,
            'available': value,
            'state': {True: 'доступен', False: 'НЕДОСТУПЕН', None: 'UNKNOWN'}.get(value, 'UNKNOWN'),
            'if_unavailable': meaning,
            'evidence': _evidence('snapshot.json', f'coverage.{key}'),
        })

    baselines = []
    for repo in new_snapshot.get('repositories') or []:
        drift = repo.get('drift') or {}
        moved = None
        if diff:
            moved = any(c['type'] == 'BASELINE_CHANGED' and c['subject'] == repo.get('path')
                        for c in diff.get('changes') or [])
        baselines.append({
            'repository': repo.get('path'),
            'reference_sha': drift.get('reference_sha') or repo.get('cached_origin_main'),
            'basis': drift.get('basis') or 'UNKNOWN',
            'live_remote': repo.get('remote_origin_main'),
            'baseline_changed_between_the_two_runs': moved,
            'evidence': _evidence('snapshot.json',
                                  f"repositories[path='{repo.get('path')}'].drift"),
        })

    return {
        'observed_at': finished,
        'capture_window': {'started_at': started, 'finished_at': finished,
                           'duration_seconds': window, 'atomic': False,
                           'note': 'пробы прогона последовательны — это интервал, не момент'},
        'age_at_generation_seconds': None if age is None else round(age, 1),
        'age_at_generation_human': _age(age),
        'freshness_policy': 'POLICY_UNDEFINED',
        'freshness_note': 'порог свежести НАБЛЮДЕНИЯ нигде в репозитории не объявлен, '
                          'поэтому показан возраст, а не вердикт «свежо»',
        'stale_summary_is_not_a_broken_system': (
            'Устаревшая сводка означает, что давно не наблюдали. Это НЕ означает, что '
            'система неисправна, и наоборот — свежая сводка не означает, что всё здорово.'),
        'sources': sources,
        'coverage_basis': coverage.get('note') and 'recorded' or 'recorded',
        'compared_sets': ({'old': (diff.get('inputs') or {}).get('old'),
                           'new': (diff.get('inputs') or {}).get('new')} if diff else None),
        'git_baselines': baselines,
        'not_measured': [
            'HEALTHY — у всех компонентов (семантической пробы нет)',
            'PRODUCING_OUTPUT — у всех компонентов',
            'Кто записал артефакт (producer_attribution: UNKNOWN)',
            'Смысл ненулевого last_exit по меткам (словарь объявлен в проде и не применяется)',
        ],
        'source_map': {'fact_types': len((sot or {}).get('fact_types') or ()),
                       'divergences': len((sot or {}).get('divergences') or ()),
                       'contradictions': (sot or {}).get('contradiction_count'),
                       'evidence': _evidence('source_of_truth.json', 'divergences')},
    }


def _changes(diff):
    buckets = {'confirmed': [], 'observation_quality': [], 'applicability': [],
               'informational': []}
    if not diff:
        return buckets
    route = {'material': 'confirmed', 'observation_quality': 'observation_quality',
             'not_comparable': 'applicability', 'informational': 'informational',
             'expected_schedule': 'informational'}
    for c in diff.get('changes') or []:
        target = route.get(c['materiality'])
        if target is None:
            continue
        template = CHANGE_HEADLINES.get(c['type'], c['type'])
        headline = template.format(detail=c.get('detail') or '') if '{detail}' in template \
            else template
        buckets[target].append({
            'id': c['id'], 'headline': headline.strip(), 'type': c['type'],
            'subject_kind': c['subject_kind'], 'subject': c['subject'],
            'detail': c.get('detail'), 'old': c.get('old'), 'new': c.get('new'),
            'class': c['class'], 'materiality': c['materiality'], 'note': c.get('note'),
            'evidence': _evidence('diff.json', f"changes[id={c['id']!r}]"),
        })
    return buckets


def _attention(new_snapshot, diff):
    """Only findings whose practical meaning is written down. No health score, ever."""
    live = {f.get('rule_code'): [] for f in new_snapshot.get('findings') or []}
    for f in new_snapshot.get('findings') or []:
        live.setdefault(f.get('rule_code'), []).append(f)
    # Both lists hold finding IDS (strings), not records — reading them as dicts crashed
    # the first one-shot run that actually produced a new finding.
    persisting = set((diff or {}).get('findings', {}).get('persisting') or ())
    fresh = set((diff or {}).get('findings', {}).get('new') or ())

    items = []
    for rule, (label, practical) in sorted(ATTENTION_RULES.items()):
        hits = live.get(rule) or []
        if not hits:
            continue
        ids = sorted(f['id'] for f in hits)
        since = None
        if diff:
            new_here = [i for i in ids if i in fresh]
            old_here = [i for i in ids if i in persisting]
            since = {'new_in_this_comparison': len(new_here),
                     'carried_over': len(old_here)}
        items.append({
            'id': f'attention:{rule}',
            'rule_code': rule,
            'headline': label,
            'count': len(hits),
            'practical_meaning': practical,
            # The LABEL is what a person needs to see. For a drift finding the subject
            # is the repository and the concrete file lives in `context`; showing the
            # subject five times would print the same path five times and say nothing.
            'examples': [{'label': f.get('context') or f.get('subject'),
                          'subject': f.get('subject'), 'context': f.get('context'),
                          'finding_id': f['id']} for f in hits[:5]],
            'all_finding_ids': ids,
            'since_last_observation': since,
            'severity': 'POLICY_UNDEFINED',
            'severity_note': 'политики приоритетов в репозитории нет; критичность здесь не '
                             'назначается',
            'evidence': _evidence('findings.json', f"[rule_code={rule!r}]"),
        })
    items.sort(key=lambda x: (-x['count'], x['rule_code']))
    return items


def _owner_candidates(diff, new_snapshot):
    out = []
    for item in (diff or {}).get('owner_decision_candidates') or []:
        find_out, next_step = OWNER_CANDIDATE_GUIDANCE.get(
            item['condition'],
            ('Что именно требуется выяснить — не установлено.',
             'Безопасный следующий шаг не определён; сначала расследование.'))
        out.append({
            'id': item['id'],
            'condition': item['condition'],
            'observed_fact': f"{item['count']} наблюдений этого вида в текущем снимке",
            'why_a_decision_may_be_needed': item['why_it_is_the_owner_s'],
            'existing_rule': item['existing_rule'],
            'what_must_still_be_found_out': find_out,
            'possible_next_safe_step': next_step,
            'severity': 'POLICY_UNDEFINED',
            'deadline': 'POLICY_UNDEFINED',
            'obligation': 'НЕ ОБЯЗАТЕЛЬНО: это производный кандидат, а не карточка решения',
            'action_taken': 'НИЧЕГО не создано, не закрыто и не исполнено',
            'examples': item['examples'],
            'evidence': _evidence('diff.json', f"owner_decision_candidates[id={item['id']!r}]"),
        })
    return out


def _unknowns(new_snapshot, diff):
    groups = {}
    for f in new_snapshot.get('findings') or []:
        if f.get('kind') != 'UNKNOWN':
            continue
        groups.setdefault(f.get('rule_code'), []).append(f)
    out = []
    for rule, hits in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append({
            'id': f'unknown:{rule}',
            'rule_code': rule,
            'count': len(hits),
            'headline': (hits[0].get('reason') or rule).split(';')[0][:160],
            'subjects': sorted({f.get('subject') for f in hits if f.get('subject')}),
            'finding_ids': sorted(f['id'] for f in hits),
            'is_by_design': rule in ('WRAPPER_TARGET_UNDECLARED', 'HEALTH_UNMEASURED',
                                     'EXIT_SEMANTICS_NOT_APPLIED'),
            'evidence': _evidence('findings.json', f"[rule_code={rule!r}]"),
        })
    if diff:
        for bucket, label in (('not_rechecked', 'исчезло, но НЕ перепроверено'),
                              ('applicability_changed',
                               'правило перестало применяться к своему объекту')):
            rows = (diff.get('findings') or {}).get(bucket) or []
            if rows:
                out.append({
                    'id': f'unknown:{bucket}',
                    'rule_code': bucket.upper(),
                    'count': len(rows),
                    'headline': label,
                    'subjects': sorted({r.get('rule_code') for r in rows}),
                    'finding_ids': sorted(r['id'] for r in rows),
                    'is_by_design': False,
                    'details': [{'id': r['id'], 'why': r.get('why')} for r in rows],
                    'evidence': _evidence('diff.json', f"findings.{bucket}"),
                })
    return out


def build(new_snapshot, source_of_truth, diff=None, provenance=None, generated_at=None):
    """Assemble the briefing. Pure function of its inputs plus one clock reading."""
    if not isinstance(new_snapshot, dict) or not isinstance(source_of_truth, dict):
        raise BriefingInputError('snapshot and source-of-truth map are required')
    generated_at = generated_at or dt.datetime.now(dt.timezone.utc).isoformat()
    mode = 'comparison' if diff else 'first_run'

    briefing = {
        'schema_version': BRIEFING_SCHEMA,
        'generated_at': generated_at,
        'volatile_fields': ['generated_at'],
        'derived_state': True,
        'observes_nothing_itself': True,
        'mode': mode,
        'mode_note': ('сравнение с явно выбранным прошлым наблюдением' if mode == 'comparison'
                      else 'ПЕРВЫЙ ЗАПУСК: прошлого наблюдения не выбрано, сравнение не '
                           'выдумывается — показано только текущее состояние'),
        'provenance': provenance or {},
        'freshness_and_coverage': _freshness(new_snapshot, diff, source_of_truth, generated_at),
        'material_changes': _changes(diff),
        'semantic_guards': list(SEMANTIC_GUARDS),
        'attention': _attention(new_snapshot, diff),
        'owner_decision_candidates': _owner_candidates(diff, new_snapshot),
        'unknowns': _unknowns(new_snapshot, diff),
        'claim_limits': list(CLAIM_LIMITS),
        'overall_health_score': None,
        'overall_health_note': 'сводной оценки здоровья нет намеренно: принятого контракта '
                              'для неё не существует, и любое единое число было бы сильнее '
                              'имеющихся evidence',
        'counts': {},
    }
    briefing['counts'] = {
        'confirmed_changes': len(briefing['material_changes']['confirmed']),
        'observation_quality_changes': len(briefing['material_changes']['observation_quality']),
        'applicability_changes': len(briefing['material_changes']['applicability']),
        'informational_changes': len(briefing['material_changes']['informational']),
        'attention_items': len(briefing['attention']),
        'owner_candidates': len(briefing['owner_decision_candidates']),
        'unknown_groups': len(briefing['unknowns']),
        'unknown_findings': sum(u['count'] for u in briefing['unknowns']),
    }
    briefing['semantic_digest'] = semantic_digest(briefing)
    return briefing


def semantic_view(briefing):
    return {k: v for k, v in briefing.items()
            if k not in ('generated_at', 'semantic_digest', 'volatile_fields')}


def semantic_digest(briefing):
    blob = json.dumps(semantic_view(briefing), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()
