#!/usr/bin/env python3
"""Source-of-truth map: which source answers which KIND of fact (Phase 0C).

Offline and derived: built from a stored snapshot, it adds no source and rewrites none.

The point is the boundary, not a ranking. There is deliberately NO globally authoritative
source, because the sources answer different questions:

  * the manifest states what SHOULD run — it cannot state what does;
  * launchd states what is registered NOW — it cannot state what was intended;
  * a git commit states what the repository CONTAINS — not what executes on this Mac;
  * ``IN_SYNC`` from code_sync states that its own last run converged its own scope — it
    does not claim that no production-only file exists.

Where two sources disagree, BOTH statements are kept and neither is corrected. No
resolution policy exists in the repository, so the policy field stays POLICY_UNDEFINED
rather than being invented here.
"""
SOT_SCHEMA = 'cartographer.source_of_truth/0.2'

#: How two statements can differ. Only the FIRST is a contradiction, and it demands
#: incompatible claims about ONE fact under comparable conditions. Calling anything else
#: a proven contradiction overstates the evidence: two sources answering different
#: questions, or the same question about different scopes or moments, can both be right.
DIVERGENCE_KINDS = {
    'contradiction': 'несовместимые утверждения об ОДНОМ факте при сопоставимых условиях',
    'declaration_vs_observation': 'намерение против наблюдения: разные вопросы, оба ответа '
                                  'могут быть верны одновременно',
    'declaration_difference': 'две декларации расходятся, но требование их равенства нигде '
                              'не установлено',
    'scope_difference': 'оба утверждения верны, но относятся к разным областям или моментам',
    'different_subject': 'утверждения не об одном предмете (настройка против регистрации)',
}

#: Small, checkable interpretation rules. They are data, not a second registry: no agent
#: is listed here — the manifest remains the only place that enumerates agents.
FACT_TYPES = (
    {
        'fact_type': 'intended_configuration',
        'question': 'Что система НАМЕРЕНА запускать и с какими свойствами?',
        'source': 'architecture/manifest.json (+ documents named in governed_by)',
        'observation_method': 'file read in the production tree',
        'proves': 'что объявлено: label, intent, layer, role, schedule, produces, '
                  'consumes, governed_by',
        'does_not_prove': 'что объявленное установлено, загружено, работает или вообще '
                          'существует на диске',
        'observation_scope': 'один файл в наблюдаемом рабочем дереве',
        'freshness_rule': 'POLICY_UNDEFINED — срок годности декларации нигде не объявлен',
        'limits': ['декларация меняется коммитом, а не наблюдением',
                   'consumes объявлен лишь частью агентов; отсутствие поля не означает, '
                   'что агент ничего не читает'],
        'unavailable_marker': 'finding SOURCE_UNREADABLE:manifest; стадия DECLARED = null',
        'coverage_key': 'manifest_readable',
        'documents': ['CLAUDE.md', 'docs/SYSTEM_MAP.md'],
    },
    {
        'fact_type': 'registry_membership',
        'question': 'Кто числится в существующем реестре агентов?',
        'source': 'data/agent_registry.json',
        'observation_method': 'file read in the production tree',
        'proves': 'членство в реестре на момент записи файла',
        'does_not_prove': 'установку, загрузку, исполнение и соответствие манифесту',
        'observation_scope': 'один файл в наблюдаемом рабочем дереве',
        'freshness_rule': '26 ч — порог, уже закодированный в правиле REGISTRY_STALE; '
                          'просрочка означает устаревшую УЛИКУ, а не мёртвого агента',
        'limits': ['состав реестра и состав манифеста не обязаны совпадать'],
        'unavailable_marker': 'finding SOURCE_UNREADABLE:registry; стадия REGISTERED = null',
        'coverage_key': 'registry_readable',
        'documents': ['data/agent_registry.json'],
    },
    {
        'fact_type': 'installed_configuration',
        'question': 'Что реально установлено как plist на этой машине?',
        'source': 'plist-файлы в ~/Library/LaunchAgents, /Library/LaunchAgents, '
                  '/Library/LaunchDaemons',
        'observation_method': 'glob + plistlib разбор; значения environment не читаются',
        'proves': 'наличие и содержимое файла конфигурации: entrypoint, WorkingDirectory, '
                  'KeepAlive, расписание, ИМЕНА переменных окружения',
        'does_not_prove': 'что launchd этот plist загрузил, и что entrypoint исполним или '
                          'делает объявленное',
        'observation_scope': 'три каталога plist; другие домены не перечисляются',
        'freshness_rule': 'POLICY_UNDEFINED',
        'limits': ['обёртка НИКОГДА не запускается для анализа, поэтому динамическая цель '
                   'остаётся UNRESOLVED',
                   'значения аргументов и переменных окружения не сохраняются намеренно'],
        'unavailable_marker': 'findings PLIST_UNREADABLE / PLIST_DIR_UNREADABLE; '
                              'стадия INSTALLED = null',
        'coverage_key': 'installed_scan_complete',
        'documents': ['.claude/rules/deployment.md'],
    },
    {
        'fact_type': 'loaded_service',
        'question': 'Зарегистрирован ли сервис в конкретном домене launchd прямо сейчас?',
        'source': 'launchctl print <domain>/<label> — адресная проба, домен назван',
        'observation_method': 'targeted probe на домен; блоки services и disabled services '
                              'разделены при разборе домена',
        'proves': 'что в НАЗВАННОМ домене сервис зарегистрирован на момент пробы',
        'does_not_prove': 'что процесс работает, что он здоров, и что в другом домене его '
                          'нет; enable/disable override — настройка, а не сервис',
        'observation_scope': 'перечисленные домены (gui/<uid> и system)',
        'freshness_rule': 'момент пробы; наблюдение не атомарно относительно соседних проб',
        'limits': ['нечитаемый домен делает LOADED = null для всех меток, а не False'],
        'unavailable_marker': 'finding DOMAIN_UNREADABLE; стадия LOADED = null',
        'coverage_key': 'domains_complete',
        'documents': [],
    },
    {
        'fact_type': 'running_process',
        'question': 'Есть ли сейчас процесс у этой метки?',
        'source': 'PID из launchctl list, соединённый с таблицей ps',
        'observation_method': 'два последовательных чтения (не атомарно)',
        'proves': 'что в момент чтения существовал процесс с этим PID',
        'does_not_prove': 'что он здоров, что он делает объявленную работу и что смена PID '
                          'означает сбой: у расписанного агента новый PID каждый запуск',
        'observation_scope': 'таблица процессов машины целиком',
        'freshness_rule': 'момент чтения; между двумя пробами PID может исчезнуть',
        'limits': ['last_exit — ИСТОРИЧЕСКИЙ: launchctl хранит предыдущий код выхода',
                   'значение кода выхода по меткам объявлено в проде и здесь НЕ применяется'],
        'unavailable_marker': 'findings LAUNCHCTL_LIST_FAILED / PS_FAILED; '
                              'стадия RUNNING = null',
        'coverage_key': 'launchctl_list_ok',
        'documents': [],
    },
    {
        'fact_type': 'repository_content',
        'question': 'Что содержит конкретный коммит репозитория?',
        'source': 'один закреплённый git-коммит (reference_sha), полученный из '
                  'remote-tracking ref ОДИН раз',
        'observation_method': 'ls-tree/diff по SHA; ни fetch, ни запись не выполняются',
        'proves': 'состав и содержимое путей в этом коммите',
        'does_not_prove': 'что этот код исполняется в проде и что он есть на диске',
        'observation_scope': 'CODE_PATHS — та же область, что у существующего code_sync',
        'freshness_rule': 'коммит неизменен; устаревать может только сама ссылка на него',
        'limits': ['кэшированная remote-tracking ссылка может отставать от живого origin',
                   'сравнения против РАЗНЫХ коммитов несопоставимы'],
        'unavailable_marker': 'findings BASELINE_UNRESOLVED / DRIFT_UNMEASURABLE',
        'coverage_key': 'drift_measurable',
        'documents': ['.claude/rules/deployment.md'],
    },
    {
        'fact_type': 'production_content',
        'question': 'Что лежит в рабочем дереве прода прямо сейчас?',
        'source': 'фактически прочитанное рабочее дерево',
        'observation_method': 'git diff/ls-files против закреплённого коммита; индекс не '
                              'изменяется',
        'proves': 'расхождение диска с НАЗВАННЫМ коммитом по трём разным категориям',
        'does_not_prove': 'что production-only файл не нужен, устарел или выведен из '
                          'эксплуатации; untracked никогда не означает retired',
        'observation_scope': 'CODE_PATHS в наблюдаемых деревьях',
        'freshness_rule': 'момент чтения; дерево не атомарно и может меняться под наблюдением',
        'limits': ['три категории имеют разный смысл и не складываются в одно число',
                   'ничего не исправляется и не удаляется'],
        'unavailable_marker': 'finding DRIFT_UNMEASURABLE; drift = null',
        'coverage_key': 'drift_measurable',
        'documents': ['.claude/rules/deployment.md'],
    },
    {
        'fact_type': 'code_sync_result',
        'question': 'Чем закончился последний запуск синхронизации кода?',
        'source': 'data/code_sync_status.json — отчёт с СОБСТВЕННЫМ временем',
        'observation_method': 'file read; сам синхронизатор НИКОГДА не запускается',
        'proves': 'исход последнего запуска в его собственной области и в его момент',
        'does_not_prove': 'что прод совпадает с origin СЕЙЧАС; IN_SYNC не отменяет наличие '
                          'production-only файлов вне области синхронизации',
        'observation_scope': 'область самого скрипта синхронизации',
        'freshness_rule': '1 ч — уже закодированный советательный порог SYNC_STATUS_STALE; '
                          'просрочка = устаревшая улика, а не доказанное расхождение',
        'limits': ['время отчёта и время наблюдения — разные моменты и не смешиваются'],
        'unavailable_marker': 'finding SYNC_STATUS_UNREADABLE',
        'coverage_key': 'sync_status_readable',
        'documents': ['scripts/code_sync_from_origin.sh', '.claude/rules/deployment.md'],
    },
    {
        'fact_type': 'artifact_existence_freshness',
        'question': 'Существует ли объявленный артефакт и уложился ли он в свой SLO?',
        'source': 'метаданные файловой системы + slo_hours из манифеста',
        'observation_method': 'lstat (симлинк называется, а не разыменовывается молча)',
        'proves': 'существование, возраст и пересечение ОБЪЯВЛЕННОГО порога',
        'does_not_prove': 'КТО записал файл: свежесть не есть атрибуция производителя',
        'observation_scope': 'объявленные produces внутри наблюдаемого дерева',
        'freshness_rule': 'slo_hours, объявленный в манифесте для каждого артефакта; где '
                          'SLO не объявлен — свежесть не судится вовсе (null, не «stale»)',
        'limits': ['артефакт вне репозитория по симлинку исключается и называется',
                   'простое старение не есть пересечение SLO'],
        'unavailable_marker': 'fresh = null; producer_attribution = UNKNOWN',
        'coverage_key': 'manifest_readable',
        'documents': ['architecture/manifest.json'],
    },
    {
        'fact_type': 'health_and_producer_attribution',
        'question': 'Здоров ли компонент и кто произвёл артефакт?',
        'source': 'UNKNOWN — отдельного проверенного источника не существует',
        'observation_method': 'не наблюдается',
        'proves': 'ничего',
        'does_not_prove': 'ни здоровья, ни авторства записи; PID и свежий файл на эти '
                          'вопросы не отвечают',
        'observation_scope': 'нет',
        'freshness_rule': 'POLICY_UNDEFINED',
        'limits': ['стадии HEALTHY и PRODUCING_OUTPUT всегда null по построению',
                   'пока нет отдельной семантической пробы, любое «здоров» было бы выдумкой'],
        'unavailable_marker': 'HEALTHY = null, PRODUCING_OUTPUT = null, '
                              'producer_attribution = UNKNOWN',
        'coverage_key': None,
        'documents': [],
    },
)

NO_GLOBAL_AUTHORITY = (
    'Ни один источник не назначен главным вообще. Манифест и launchd отвечают на разные '
    'вопросы; origin не доказывает, что код исполняется в проде; IN_SYNC не отменяет '
    'наличия production-only файлов. Карта фиксирует границу утверждений, а не иерархию.'
)


def _coverage(snapshot):
    """Reuse the diff module's coverage view so both artifacts speak of one thing."""
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    spec = spec_from_file_location('cartographer_diff', Path(__file__).with_name('diff.py'))
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.coverage_view(snapshot)


def _availability(fact, cov):
    key = fact['coverage_key']
    if key is None:
        return {'coverage_key': None, 'available': None,
                'note': 'нет источника — недоступность здесь не дефект прогона, а '
                        'свойство самого факта'}
    value = cov.get(key)
    if isinstance(value, dict):  # per-repository map, e.g. drift_measurable
        value = all(v is True for v in value.values()) if value else None
    return {'coverage_key': key, 'available': value,
            'note': 'взято из coverage снимка' if cov.get('basis') == 'recorded'
                    else 'выведено из словаря находок снимка схемы 0.2'}


def divergences(snapshot):
    """Where statements differ — CLASSIFIED, not all called contradictions.

    Both facts are always kept and nothing is resolved. A `contradiction` requires
    incompatible claims about one fact under comparable conditions; everything else is a
    difference of question, scope or moment, and saying otherwise would invent evidence.
    """
    out = []

    def add(cid, kind, fact_types, statements, note):
        assert kind in DIVERGENCE_KINDS, kind
        out.append({'id': cid, 'kind': kind, 'kind_meaning': DIVERGENCE_KINDS[kind],
                    'fact_types': list(fact_types), 'statements': statements,
                    'resolution_policy': 'POLICY_UNDEFINED',
                    'resolution_note': 'политика разрешения расхождений в репозитории не '
                                       'объявлена; карта ничего не переписывает',
                    'note': note})

    declared_not_loaded, loaded_not_declared, registry_only, manifest_only = [], [], [], []
    probe_vs_listing = []
    domains = snapshot.get('launchd_domains') or {}
    for e in snapshot.get('entities') or []:
        st = e.get('stages') or {}
        if e.get('intent') == 'active' and st.get('INSTALLED') is True and st.get('LOADED') is False:
            declared_not_loaded.append(e['id'])
        if st.get('LOADED') is True and st.get('DECLARED') is False:
            loaded_not_declared.append(e['id'])
        if st.get('REGISTERED') is True and st.get('DECLARED') is False:
            registry_only.append(e['id'])
        if st.get('DECLARED') is True and st.get('REGISTERED') is False:
            manifest_only.append(e['id'])
        # A real contradiction, if it ever happens: the domain's REGISTERED SERVICES block
        # lists the label while the targeted probe for that same domain says it is absent.
        # One fact (`loaded_service`), one domain, one run — the two cannot both be true.
        for name, verdict in (e.get('domains') or {}).items():
            rec = domains.get(name) or {}
            if rec.get('readable') is True and verdict is False \
                    and e['id'] in (rec.get('services') or ()):
                probe_vs_listing.append(f"{e['id']}@{name}")

    if probe_vs_listing:
        add('divergence:services_listing_vs_targeted_probe', 'contradiction',
            ('loaded_service',),
            [{'source': 'блок services домена', 'says': 'метка зарегистрирована'},
             {'source': 'launchctl print <domain>/<label>', 'says': 'сервиса нет'}],
            'один факт, один домен, один прогон — оба утверждения верными быть не могут')
        out[-1]['subjects'] = sorted(probe_vs_listing)
    if declared_not_loaded:
        add('divergence:intended_active_vs_not_loaded', 'declaration_vs_observation',
            ('intended_configuration', 'loaded_service'),
            [{'source': 'architecture/manifest.json', 'says': 'intent=active и plist установлен'},
             {'source': 'launchctl print <domain>/<label>', 'says': 'сервис не зарегистрирован'}],
            f'{len(declared_not_loaded)} меток. Манифест говорит о НАМЕРЕНИИ, launchd — о '
            'регистрации; это разные вопросы, и оба ответа наблюдены')
        out[-1]['subjects'] = sorted(declared_not_loaded)
    if loaded_not_declared:
        add('divergence:loaded_but_not_in_manifest', 'declaration_vs_observation',
            ('loaded_service', 'intended_configuration'),
            [{'source': 'launchd domain', 'says': 'сервис зарегистрирован'},
             {'source': 'architecture/manifest.json', 'says': 'метки нет'}],
            'загружено то, чего манифест не объявляет; требование полноты манифеста нигде '
            'не установлено, поэтому это различие, а не доказанное противоречие')
        out[-1]['subjects'] = sorted(loaded_not_declared)
    if registry_only or manifest_only:
        add('divergence:registry_vs_manifest', 'declaration_difference',
            ('registry_membership', 'intended_configuration'),
            [{'source': 'data/agent_registry.json',
              'says': f'{len(registry_only)} меток есть только в реестре'},
             {'source': 'architecture/manifest.json',
              'says': f'{len(manifest_only)} меток есть только в манифесте'}],
            'равенство составов двух деклараций НИГДЕ не требуется, поэтому расхождение '
            'состава не является противоречием; оба состава сохранены как есть')
        out[-1]['subjects'] = sorted(registry_only + manifest_only)

    sync = snapshot.get('code_sync') or {}
    for repo in snapshot.get('repositories') or []:
        d = repo.get('drift') or {}
        only = list(d.get('production_only_tracked') or ()) + list(
            d.get('production_only_untracked') or ())
        if only and str(sync.get('result', '')).upper() in ('IN_SYNC', 'OK', 'SYNCED'):
            add(f"divergence:sync_scope_vs_production_only:{repo.get('path')}",
                'scope_difference', ('code_sync_result', 'production_content'),
                [{'source': 'data/code_sync_status.json',
                  'says': f"result={sync.get('result')} на момент {sync.get('timestamp')}"},
                 {'source': f"рабочее дерево против {str(d.get('reference_sha'))[:12]}",
                  'says': f'{len(only)} файлов есть на диске и отсутствуют в коммите'}],
                'НЕ противоречие: IN_SYNC относится к области самого синхронизатора и к его '
                'моменту, а production-only — к сравниваемому коммиту. Области утверждений '
                'разные, оба факта сохранены, вывод не делается')
            out[-1]['subjects'] = sorted(only)[:20]
        if repo.get('cached_origin_main') and repo.get('remote_origin_main') and \
                repo['cached_origin_main'] != repo['remote_origin_main']:
            add(f"divergence:cached_vs_live_remote:{repo.get('path')}", 'scope_difference',
                ('repository_content',),
                [{'source': 'кэшированный remote-tracking ref',
                  'says': repo['cached_origin_main']},
                 {'source': 'живой ls-remote', 'says': repo['remote_origin_main']}],
                'разные МОМЕНТЫ одного факта: сравнение велось против кэша, fetch не '
                'выполнялся')

    for label in snapshot.get('labels_with_override_but_no_service') or []:
        add(f'divergence:enable_override_without_service:{label}', 'different_subject',
            ('loaded_service', 'installed_configuration'),
            [{'source': 'блок disabled services домена', 'says': 'есть override для метки'},
             {'source': 'launchctl print <domain>/<label>', 'says': 'сервиса нет'}],
            'НЕ противоречие: override — это НАСТРОЙКА enable/disable, а сервис — '
            'регистрация. Настройка существует независимо от того, зарегистрирован ли '
            'сервис, поэтому оба утверждения верны и относятся к разным предметам')
        out[-1]['subjects'] = [label]
    return out


def build(snapshot, source_dir=None):
    cov = _coverage(snapshot)
    refs = snapshot.get('reference_documents')
    ref_index = {r['path']: r for r in refs} if isinstance(refs, list) else None

    facts = []
    for fact in FACT_TYPES:
        documents = []
        for path in fact['documents']:
            if ref_index is None:
                documents.append({'path': path, 'resolution': 'NOT_RECORDED_IN_THIS_SCHEMA',
                                  'note': 'снимок схемы 0.2 не содержит проверки ссылок'})
            elif path in ref_index:
                r = ref_index[path]
                documents.append({'path': path, 'resolution': 'CHECKED',
                                  'in_pinned_commit_docs_index': r.get('in_pinned_docs_index'),
                                  'in_production_tree': r.get('in_production_tree')})
            else:
                documents.append({'path': path, 'resolution': 'NOT_CHECKED',
                                  'note': 'путь не входит в проверяемый набор ссылок'})
        facts.append({**{k: v for k, v in fact.items() if k != 'documents'},
                      'observation_window': {
                          'started_at': snapshot.get('started_at'),
                          'finished_at': snapshot.get('finished_at'),
                          'atomic': False,
                          'note': 'пробы прогона последовательны; окно наблюдения — это '
                                  'интервал, а не момент'},
                      'availability': _availability(fact, cov),
                      'documents': documents})

    # code_sync carries its own time, which is NOT the observation window.
    sync = snapshot.get('code_sync') or {}
    for f in facts:
        if f['fact_type'] == 'code_sync_result':
            f['source_own_timestamp'] = sync.get('timestamp')
            f['source_own_result'] = sync.get('result')

    return {
        'schema_version': SOT_SCHEMA,
        'derived_state': True,
        'derived_from': {'snapshot_schema': snapshot.get('schema_version'),
                         'snapshot_finished_at': snapshot.get('finished_at'),
                         'snapshot_dir': source_dir},
        'no_global_authority': NO_GLOBAL_AUTHORITY,
        'fact_types': facts,
        'divergence_kinds': dict(DIVERGENCE_KINDS),
        'divergences': divergences(snapshot),
        'contradiction_count': sum(1 for x in divergences(snapshot)
                                   if x['kind'] == 'contradiction'),
        'coverage_basis': cov.get('basis'),
        'limits': [
            'Карта не переписывает источники, не разрешает противоречия и не назначает '
            'владельцев, SLA или приоритеты.',
            'Свежесть объявляется ТОЛЬКО там, где порог уже существует в репозитории; '
            'иначе POLICY_UNDEFINED.',
            'Карта не перечисляет агентов: их состав остаётся в манифесте, второго реестра '
            'не заводится.',
        ],
    }


def validate(sot):
    """Referential integrity, and the classification must not overstate the evidence."""
    declared = {f['fact_type'] for f in sot['fact_types']}
    if len(declared) != len(sot['fact_types']):
        raise ValueError('duplicate fact_type')
    required = ('question', 'source', 'proves', 'does_not_prove', 'observation_scope',
                'freshness_rule', 'limits', 'unavailable_marker', 'availability',
                'observation_window', 'documents')
    for f in sot['fact_types']:
        for key in required:
            if key == 'documents':
                continue
            if f.get(key) in (None, '', []):
                raise ValueError(f"fact type {f['fact_type']} lacks {key}")
    ids = [c['id'] for c in sot['divergences']]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate divergence ids')
    for c in sot['divergences']:
        if c['kind'] not in DIVERGENCE_KINDS:
            raise ValueError(f"divergence {c['id']} has unknown kind {c['kind']}")
        for ft in c['fact_types']:
            if ft not in declared:
                raise ValueError(f'divergence {c["id"]} cites unknown fact type {ft}')
        if c['resolution_policy'] != 'POLICY_UNDEFINED':
            raise ValueError('the map must not carry a resolution policy')
        if len(c['statements']) < 2:
            raise ValueError(f'divergence {c["id"]} keeps fewer than two statements')
        # A contradiction must be about ONE fact type: two different questions cannot be
        # incompatible, and calling them so would be the overstatement this guards.
        if c['kind'] == 'contradiction' and len(set(c['fact_types'])) != 1:
            raise ValueError(f'{c["id"]}: a contradiction must concern exactly one fact type')
    return True


def markdown(sot):
    lines = ['# Карта источников правды (Cartographer, Phase 0C)', '',
             sot['no_global_authority'], '',
             f"Построена из снимка `{sot['derived_from']['snapshot_dir']}` "
             f"(схема `{sot['derived_from']['snapshot_schema']}`, "
             f"снят {sot['derived_from']['snapshot_finished_at']}).",
             f"Основание coverage: `{sot['coverage_basis']}`.", '',
             '## Типы фактов', '']
    for f in sot['fact_types']:
        avail = f['availability']
        state = {True: 'доступен', False: 'НЕДОСТУПЕН', None: 'UNKNOWN'}[avail['available']]
        lines += [f"### {f['fact_type']}", '',
                  f"**Вопрос:** {f['question']}", '',
                  f"- **источник:** {f['source']}",
                  f"- **способ наблюдения:** {f['observation_method']}",
                  f"- **доказывает:** {f['proves']}",
                  f"- **НЕ доказывает:** {f['does_not_prove']}",
                  f"- **область:** {f['observation_scope']}",
                  f"- **окно наблюдения:** {f['observation_window']['started_at']} → "
                  f"{f['observation_window']['finished_at']} (не атомарно)",
                  f"- **свежесть:** {f['freshness_rule']}",
                  f"- **как обозначается недоступность:** {f['unavailable_marker']}",
                  f"- **в этом прогоне:** {state}"
                  + (f" (`{avail['coverage_key']}`)" if avail['coverage_key'] else '')]
        if f.get('source_own_timestamp') is not None or f.get('source_own_result') is not None:
            lines.append(f"- **собственное время источника:** {f.get('source_own_timestamp')} "
                         f"· результат: {f.get('source_own_result')}")
        for limit in f['limits']:
            lines.append(f"- ограничение: {limit}")
        for d in f['documents']:
            if d['resolution'] == 'CHECKED':
                lines.append(f"- документ `{d['path']}`: в прод-дереве "
                             f"{d['in_production_tree']}, в индексе docs/** "
                             f"закреплённого коммита {d['in_pinned_commit_docs_index']}")
            else:
                lines.append(f"- документ `{d['path']}`: {d['resolution']}")
        lines.append('')
    lines += ['## Где утверждения источников расходятся', '',
              'Расхождение — не всегда противоречие. Противоречием называется только '
              'несовместимость утверждений об ОДНОМ факте при сопоставимых условиях; '
              'всё прочее — разные вопросы, области или моменты, и обе стороны могут быть '
              'верны одновременно. Ни одно расхождение здесь не разрешается.', '',
              f"Противоречий в этом снимке: **{sot['contradiction_count']}** из "
              f"{len(sot['divergences'])} расхождений.", '']
    if not sot['divergences']:
        lines.append('Расхождений между источниками в этом снимке не наблюдается.')
    for c in sot['divergences']:
        lines.append(f"### {c['id']}")
        lines.append('')
        lines.append(f"- вид: **{c['kind']}** — {c['kind_meaning']}")
        for s in c['statements']:
            lines.append(f"- `{s['source']}` утверждает: {s['says']}")
        if c.get('subjects'):
            shown = ', '.join(f'`{x}`' for x in c['subjects'][:6])
            more = f" … ещё {len(c['subjects']) - 6}" if len(c['subjects']) > 6 else ''
            lines.append(f"- предметы: {shown}{more}")
        lines += [f"- {c['note']}",
                  f"- разрешение: **{c['resolution_policy']}** — {c['resolution_note']}", '']
    lines += ['## Границы карты', '']
    lines += [f'- {x}' for x in sot['limits']]
    lines.append('')
    return '\n'.join(lines) + '\n'
