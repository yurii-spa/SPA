#!/usr/bin/env python3
"""Offline comparison of two stored Cartographer snapshots (Phase 0C).

OFFLINE BY CONSTRUCTION. This module imports no ``subprocess``, no ``socket`` and no
``urllib``; it reads the two snapshot directories it is given and nothing else. What a
stored snapshot does not contain is UNKNOWN — it is never reconstructed from the machine
as it is today, because "how it is now" is not evidence about the run that wrote the
older file.

The hard part of a diff is not spotting differences, it is refusing to invent them:

  * ``true → null`` is a LOSS OF KNOWLEDGE, not a stop. The two are different answers.
  * an entity missing while its source failed is UNKNOWN, not a removal;
  * a finding absent from the new array is resolved ONLY if the probe that could see it
    ran again over a comparable scope — otherwise NOT_RECHECKED;
  * a new PID does not prove a restart, and a scheduled job that is running now and idle
    later is doing its job, not failing;
  * ageing is not an SLO crossing; array order and timestamps are not changes;
  * drift measured against a DIFFERENT baseline is not comparable, so a shorter drift
    list under a moved baseline is never reported as production having been fixed.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

DIFF_SCHEMA = 'cartographer.diff/0.1'
SUPPORTED_SNAPSHOT_SCHEMAS = ('cartographer.snapshot/0.2', 'cartographer.snapshot/0.3')
STAGES = ('DECLARED', 'REGISTERED', 'INSTALLED', 'LOADED', 'RUNNING',
          'PRODUCING_OUTPUT', 'HEALTHY')

#: What a change is ABOUT. A declaration changing and an observation changing are
#: different events even when they touch the same word.
CHANGE_CLASSES = ('observed_state', 'declaration', 'installed_configuration',
                  'observation_quality', 'comparison_basis', 'derived_graph')

#: How much it means. `not_comparable` exists so that a difference measured against two
#: different baselines is shown WITHOUT being called an improvement or a regression.
MATERIALITY = ('material', 'observation_quality', 'expected_schedule',
               'informational', 'not_comparable')

#: Deliberately never compared: they differ between any two runs and mean nothing.
#: Comparison is by WHITELIST (fields named below are read; everything else is ignored),
#: so a noisy field cannot leak in by being forgotten here.
IGNORED_BY_DESIGN = (
    'started_at / finished_at — every run has new ones',
    'age_seconds / mtime_epoch / size_bytes — ageing is not an SLO crossing',
    'list ORDER of entities, findings, installed_paths, declared_outputs, processes',
    'the process table itself — it turns over constantly; only its size is reported',
)

ENTITY_DECLARED_FIELDS = ('intent', 'layer', 'role', 'schedule', 'declared_program',
                          'declared_plist_source', 'declared_plist_in_repo',
                          'declared_consumes', 'declared_governed_by')
ENTITY_OBSERVED_FIELDS = ('status', 'domains', 'enable_overrides')
#: Per-domain verdict maps: a value turning null means the probe stopped answering, not
#: that the service changed. Compared key by key, never as one opaque value.
VERDICT_MAP_FIELDS = ('domains', 'enable_overrides')
PLIST_FIELDS = ('working_directory', 'keep_alive', 'start_interval',
                'has_calendar_schedule', 'environment_keys', 'stdout', 'stderr',
                'entrypoint_checkout', 'entrypoint_declared_target')
ENTRYPOINT_FIELDS = ('executable', 'target_kind', 'target', 'target_exists',
                     'argument_count', 'unknown_code')
OUTPUT_FIELDS = ('exists', 'fresh', 'slo_hours', 'is_symlink')
DRIFT_CATEGORIES = ('changed_or_missing_on_disk', 'production_only_tracked',
                    'production_only_untracked')

_MISSING = object()


class IncompatibleInput(Exception):
    """Unreadable, unsupported or malformed input. Never degraded into 'no changes'."""


# ── input contract: a truncated file must not look like a quiet machine ──────

STATUSES = ('LIVE', 'DEGRADED', 'STALE', 'LEGACY', 'DEAD', 'ORPHANED', 'UNKNOWN',
            'DUPLICATED')

#: Present in EVERY supported snapshot, with these types. Absence is a truncated file,
#: not an empty machine: `{"schema_version": "…/0.3", "entities": []}` used to be
#: accepted and then compared, producing a normal-looking report out of nothing.
REQUIRED_TOP_LEVEL = {
    'schema_version': str, 'started_at': str, 'finished_at': str, 'scope': str,
    'entities': list, 'findings': list, 'repositories': list, 'processes': list,
    'launchd_domains': dict, 'document_index': dict,
    'labels_with_override_but_no_service': list,
}

#: Recorded coverage of a 0.3 run. A MISSING block is refused rather than silently
#: replaced by the 0.2 inference — inheriting an assumption about which sources were
#: readable is exactly how a truncated file turned into "everything was observed".
REQUIRED_COVERAGE = {
    'manifest_readable': bool, 'registry_readable': bool,
    'installed_scan_complete': bool, 'declared_plist_scan_complete': bool,
    'launchctl_list_ok': bool, 'ps_ok': bool, 'domains_complete': bool,
    'document_index_available': bool, 'sync_status_readable': bool,
    'domains_readable': dict, 'drift_measurable': dict, 'baseline_sha': dict,
}


def _require(condition, message):
    if not condition:
        raise IncompatibleInput(message)


def _typed(container, key, expected, where, optional_none=False):
    value = container.get(key, _MISSING)
    _require(value is not _MISSING, f'{where}: required field `{key}` is missing')
    if optional_none and value is None:
        return None
    _require(isinstance(value, expected) and not (expected is not bool
                                                  and isinstance(value, bool)),
             f'{where}: field `{key}` must be {expected.__name__}, '
             f'got {type(value).__name__}')
    return value


def validate_snapshot(s, where):
    """Full structural check BEFORE any comparison. Raises IncompatibleInput.

    A legitimately empty result and a truncated file must not look alike: an empty
    `entities` list is accepted only when the rest of the contract — including an
    explicit coverage block for 0.3 — is present and well typed.
    """
    _require(isinstance(s, dict), f'{where}: snapshot is not an object')
    schema = s.get('schema_version')
    _require(schema in SUPPORTED_SNAPSHOT_SCHEMAS,
             f'{where}: unsupported snapshot schema {schema!r}; '
             f'supported: {", ".join(SUPPORTED_SNAPSHOT_SCHEMAS)}')
    for key, kind in REQUIRED_TOP_LEVEL.items():
        _typed(s, key, kind, where)
    _typed(s, 'launchctl_list_ok', bool, where, optional_none=True)

    if schema == 'cartographer.snapshot/0.3':
        coverage = _typed(s, 'coverage', dict, where)
        for key, kind in REQUIRED_COVERAGE.items():
            value = coverage.get(key, _MISSING)
            _require(value is not _MISSING,
                     f'{where}: coverage is missing `{key}`; a 0.3 snapshot must RECORD '
                     'its coverage — it is never inferred back')
            _require(value is None or isinstance(value, kind),
                     f'{where}: coverage.{key} must be {kind.__name__} or null')
        _typed(s, 'reference_documents', list, where)
    else:
        _require('coverage' not in s,
                 f'{where}: schema {schema} must not carry a coverage block')

    seen_entities = set()
    for i, e in enumerate(s['entities']):
        at = f'{where}: entities[{i}]'
        _require(isinstance(e, dict), f'{at} is not an object')
        label = _typed(e, 'id', str, at)
        _require(label.strip(), f'{at}: empty id')
        _require(label not in seen_entities, f'{at}: duplicate entity id {label!r}')
        seen_entities.add(label)
        status = _typed(e, 'status', str, at)
        _require(status in STATUSES, f'{at}: unknown status {status!r}')
        stages = _typed(e, 'stages', dict, at)
        for stage in STAGES:
            _require(stage in stages, f'{at}: stages lacks `{stage}`')
            _require(stages[stage] in (True, False, None),
                     f'{at}: stages.{stage} must be true, false or null')
        for key in ('installed_paths', 'declared_outputs', 'document_references'):
            _typed(e, key, list, at)
        _typed(e, 'domains', dict, at)

    seen_findings = set()
    for i, f in enumerate(s['findings']):
        at = f'{where}: findings[{i}]'
        _require(isinstance(f, dict), f'{at} is not an object')
        fid = _typed(f, 'id', str, at)
        _require(fid.strip(), f'{at}: empty finding id')
        _require(fid not in seen_findings, f'{at}: duplicate finding id {fid!r}')
        seen_findings.add(fid)
        _typed(f, 'kind', str, at)
        _typed(f, 'subject', str, at)
        rule = _typed(f, 'rule_code', str, at)
        _require(rule.strip(), f'{at}: empty rule_code')

    seen_repos = set()
    for i, r in enumerate(s['repositories']):
        at = f'{where}: repositories[{i}]'
        _require(isinstance(r, dict), f'{at} is not an object')
        path = _typed(r, 'path', str, at)
        _require(path not in seen_repos, f'{at}: duplicate repository path {path!r}')
        seen_repos.add(path)
        _require('drift' in r, f'{at}: required field `drift` is missing')
        drift = r['drift']
        _require(drift is None or isinstance(drift, dict),
                 f'{at}: drift must be an object or null')
        if isinstance(drift, dict):
            _typed(drift, 'reference_sha', str, at + '.drift')
            for cat in DRIFT_CATEGORIES:
                _typed(drift, cat, list, at + '.drift')
    return True


# ── coverage: what a run could OBSERVE, which is what makes absence readable ──

#: What the ABSENCE of a finding must be backed by before it may be called a fix.
#:
#: Global coverage flags are NECESSARY but never SUFFICIENT. Reproduced defect: making
#: one component's declared outputs unobservable (`exists: null`) removed STATUS_STALE
#: from the array, `manifest_readable` was still true, and the comparison announced the
#: finding RESOLVED — a claim about an artifact nobody managed to stat. A rule is now
#: re-checked only when (a) its coverage held, (b) its SUBJECT is still in comparable
#: scope, and (c) the specific inputs its own condition reads were OBSERVED for that
#: subject in the new run.
#:
#: `coverage` — global flags of the new run.
#: `subject`  — what the finding is about, and therefore what must still be observable.
#: `needs`    — rule-specific evidence, evaluated against that subject.
RECHECK_SPECS = {
    # ── sources and probes: the flag IS the observation ─────────────────────
    'SOURCE_UNREADABLE': {'subject': 'source', 'coverage': ('subject_source',)},
    'DOMAIN_UNREADABLE': {'subject': 'domain', 'needs': ('domain_readable',)},
    'LAUNCHCTL_LIST_FAILED': {'subject': 'global', 'coverage': ('launchctl_list_ok',)},
    'PS_FAILED': {'subject': 'global', 'coverage': ('ps_ok',)},
    'PLIST_UNREADABLE': {'subject': 'global', 'coverage': ('installed_scan_complete',)},
    'PLIST_DIR_UNREADABLE': {'subject': 'global', 'coverage': ('installed_scan_complete',)},
    'DECLARED_PLIST_DIR_UNREADABLE': {'subject': 'global',
                                      'coverage': ('declared_plist_scan_complete',)},
    'DOC_INDEX_UNAVAILABLE': {'subject': 'global', 'coverage': ('document_index_available',)},
    'SYNC_STATUS_UNREADABLE': {'subject': 'global', 'coverage': ('sync_status_readable',)},
    'SYNC_STATUS_STALE': {'subject': 'global', 'coverage': ('sync_status_readable',)},
    'REGISTRY_STALE': {'subject': 'global', 'coverage': ('registry_readable',)},
    #: Emitted unconditionally by this producer, so its absence is structural, and the
    #: input contract already guarantees a well-formed producer.
    'HEALTH_UNMEASURED': {'subject': 'global'},
    #: Fires on the presence of a production file the snapshot does not record. Its
    #: absence is therefore not observable from a stored snapshot at all.
    'EXIT_SEMANTICS_NOT_APPLIED': {'subject': 'global', 'needs': ('not_observable',)},

    # ── entity-scoped: the component AND the inputs of its condition ────────
    'STATUS_STALE': {'subject': 'entity', 'coverage': ('manifest_readable',),
                     'needs': ('stale_outputs_recovered',)},
    'STATUS_DEGRADED': {'subject': 'entity',
                        'coverage': ('launchctl_list_ok', 'installed_scan_complete'),
                        'needs': ('stages:INSTALLED,LOADED,RUNNING', 'domains_probed')},
    'STATUS_DUPLICATED': {'subject': 'entity', 'coverage': ('installed_scan_complete',),
                          'needs': ('stages:INSTALLED',)},
    'STATUS_UNCLASSIFIABLE': {'subject': 'entity',
                              'coverage': ('launchctl_list_ok', 'ps_ok',
                                           'installed_scan_complete'),
                              'needs': ('stages:INSTALLED,LOADED,RUNNING', 'domains_probed')},
    'LOADED_WITHOUT_INSTALLED_PLIST': {'subject': 'entity',
                                       'coverage': ('installed_scan_complete',),
                                       'needs': ('stages:INSTALLED,LOADED', 'domains_probed')},
    'LOADED_NOT_IN_MANIFEST': {'subject': 'entity', 'coverage': ('manifest_readable',),
                               'needs': ('stages:DECLARED,LOADED', 'domains_probed')},
    'PID_VANISHED_BETWEEN_PROBES': {'subject': 'entity',
                                    'coverage': ('launchctl_list_ok', 'ps_ok'),
                                    'needs': ('stages:RUNNING',)},
    'ENTRYPOINT_FORM_UNSUPPORTED': {'subject': 'entity',
                                    'coverage': ('installed_scan_complete',),
                                    'needs': ('plist_present',)},
    'ENTRYPOINT_SCRIPT_MISSING': {'subject': 'entity',
                                  'coverage': ('installed_scan_complete',),
                                  'needs': ('plist_present',)},
    'WRAPPER_TARGET_UNDECLARED': {'subject': 'entity',
                                  'coverage': ('installed_scan_complete',),
                                  'needs': ('plist_present',)},
    'DOC_REFERENCE_ABSENT': {'subject': 'entity',
                             'coverage': ('document_index_available', 'manifest_readable'),
                             'needs': ('declares_reference',)},
    'DOC_REFERENCE_UNVERIFIABLE': {'subject': 'entity',
                                   'coverage': ('document_index_available',
                                                'manifest_readable'),
                                   'needs': ('declares_reference',)},
    'DECLARED_OUTPUT_UNRESOLVABLE': {'subject': 'entity', 'coverage': ('manifest_readable',),
                                     'needs': ('declares_output',)},
    'DECLARED_OUTPUT_ESCAPES_REPO': {'subject': 'entity', 'coverage': ('manifest_readable',),
                                     'needs': ('declares_output',)},
    'ENABLE_OVERRIDE_WITHOUT_SERVICE': {'subject': 'label_in_domain',
                                        'needs': ('override_absent_in_domain',)},

    # ── repository-scoped: the SAME repository, probed again ───────────────
    'BASELINE_UNRESOLVED': {'subject': 'repository',
                            'needs': ('repo_present', 'baseline_resolved')},
    'DRIFT_UNMEASURABLE': {'subject': 'repository',
                           'needs': ('repo_present', 'drift_measured')},
    'DRIFT_CHANGED_OR_MISSING_ON_DISK': {'subject': 'repository',
                                         'needs': ('repo_present', 'drift_measured',
                                                   'same_baseline', 'drift_path_absent')},
    'DRIFT_PRODUCTION_ONLY_TRACKED': {'subject': 'repository',
                                      'needs': ('repo_present', 'drift_measured',
                                                'same_baseline', 'drift_path_absent')},
    'DRIFT_PRODUCTION_ONLY_UNTRACKED': {'subject': 'repository',
                                        'needs': ('repo_present', 'drift_measured',
                                                  'same_baseline', 'drift_path_absent')},
    #: `always` was wrong here: it proved nothing about THIS repository being probed
    #: again. A live remote probe must actually have succeeded in the new run.
    'REMOTE_UNAVAILABLE': {'subject': 'repository',
                           'needs': ('repo_present', 'remote_probed')},
    'CACHED_VS_REMOTE_DIVERGED': {'subject': 'repository',
                                  'needs': ('repo_present', 'remote_probed',
                                            'baseline_resolved')},
}

#: Verdicts for a finding that is absent from the new set.
RESOLVED, NOT_RECHECKED, APPLICABILITY_CHANGED = (
    'resolved', 'not_rechecked', 'applicability_changed')


def _coverage_met(token, cov, finding):
    if token == 'subject_source':
        key = {'manifest': 'manifest_readable',
               'registry': 'registry_readable'}.get(finding.get('subject'))
        if key is None:
            return None, 'subject is not a known source name'
        return cov.get(key) is True, f'coverage `{key}` is not True in the new run'
    value = cov.get(token)
    if value is True:
        return True, None
    if value is None:
        return None, f'coverage `{token}` is UNKNOWN in the new run'
    return False, f'coverage `{token}` is False in the new run'


def _need_met(need, ctx):
    """One piece of rule-specific evidence.

    Returns (verdict, reason) where verdict is True, False (not re-checked) or the
    string APPLICABILITY_CHANGED — the object the rule spoke about is gone, which is a
    different event from the condition having been fixed.
    """
    f, new_e, new_s = ctx['finding'], ctx['new_entity'], ctx['new_snapshot']
    context = f.get('context')

    if need == 'not_observable':
        return False, ('the condition of this rule is not recorded in a snapshot, so its '
                       'absence cannot be re-checked offline')
    if need.startswith('stages:'):
        missing = [st for st in need.split(':', 1)[1].split(',')
                   if (new_e.get('stages') or {}).get(st) is None]
        if missing:
            return False, ('stage(s) ' + ', '.join(missing) + ' were not established for '
                           'this component in the new run')
        return True, None
    if need == 'domains_probed':
        domains = new_e.get('domains') or {}
        if not domains:
            return False, 'no launchd domain verdict was recorded for this label'
        unknown = sorted(n for n, v in domains.items() if v is None)
        if unknown:
            return False, ('the targeted launchd probe for this label did not answer in '
                           'domain(s) ' + ', '.join(unknown) +
                           '; a readable domain is not a probed label')
        return True, None
    if need == 'stale_outputs_recovered':
        # The rule fired because SPECIFIC declared outputs were past their SLO. Recover
        # that set from the OLD snapshot and match each one by its stable relpath: asking
        # only "is metadata available now" let three different events pass as a fix — the
        # file vanishing, the output being withdrawn from the declaration, and its SLO
        # being removed. None of those is evidence that the overdue artifact recovered.
        old_e = ctx['old_entity']
        if not isinstance(old_e, dict):
            return False, ('the previously stale outputs cannot be reconstructed: the '
                           'component is not present in the stored old snapshot')
        was_stale = {o.get('relpath'): o for o in (old_e.get('declared_outputs') or [])
                     if o.get('fresh') is False and o.get('relpath')}
        if not was_stale:
            return False, ('the old snapshot does not record WHICH declared output was past '
                           'its SLO, so the original cause cannot be re-checked')
        now = {o.get('relpath'): o for o in (new_e.get('declared_outputs') or [])
               if o.get('relpath')}
        blocked, no_longer_applies = [], []
        for rel, before in sorted(was_stale.items()):
            after = now.get(rel)
            if after is None:
                no_longer_applies.append(f'`{rel}` is no longer declared as an output')
            elif after.get('slo_hours') != before.get('slo_hours'):
                no_longer_applies.append(
                    f'`{rel}` no longer carries the same SLO '
                    f'({before.get("slo_hours")} → {after.get("slo_hours")}), so freshness '
                    'is not comparable with the condition that fired')
            elif after.get('exists') is None:
                blocked.append(f'`{rel}`: artifact metadata was not obtained')
            elif after.get('exists') is False:
                blocked.append(f'`{rel}`: the artifact is now ABSENT — its freshness cannot '
                               'be established, and a file disappearing is not a recovery')
            elif after.get('fresh') is not True:
                blocked.append(f'`{rel}`: freshness is {after.get("fresh")!r}, which is not '
                               'positive evidence of recovery')
        still_stale = sorted(rel for rel, o in now.items() if o.get('fresh') is False)
        if still_stale:
            blocked.append('a stale condition persists on ' + ', '.join(still_stale))
        # The ABSENCE of a stale condition must be established, not assumed. An output
        # that declares an SLO but whose metadata was not obtained could be overdue and
        # nobody looked; treating that as "no longer stale" would be the same mistake one
        # neighbour to the left.
        undetermined = sorted(rel for rel, o in now.items()
                              if o.get('exists') is None
                              and isinstance(o.get('slo_hours'), (int, float)))
        if undetermined:
            blocked.append('staleness is undetermined for ' + ', '.join(undetermined) +
                           ' (an SLO is declared but the metadata was not obtained), so the '
                           'absence of a stale condition is not established')
        # Partial evidence never resolves the aggregate finding, and missing evidence
        # outranks lost applicability: not knowing is weaker than knowing the rule moved.
        if blocked:
            return False, ('not every previously stale output was shown to have recovered: '
                           + '; '.join(blocked))
        if no_longer_applies:
            return APPLICABILITY_CHANGED, ('the rule no longer applies to what it judged: '
                                           + '; '.join(no_longer_applies))
        return True, None
    if need == 'plist_present':
        names = {Path(p.get('plist', '')).name for p in new_e.get('installed_paths') or []}
        if context and context not in names:
            return APPLICABILITY_CHANGED, (f'the plist `{context}` this rule was about is '
                                           'no longer installed for this component')
        return True, None
    if need == 'declares_reference':
        if context and context not in (new_e.get('declared_governed_by') or []):
            return APPLICABILITY_CHANGED, (f'`{context}` is no longer declared in '
                                           'governed_by')
        return True, None
    if need == 'declares_output':
        rels = {o.get('relpath') for o in new_e.get('declared_outputs') or []}
        if context and context not in rels:
            return APPLICABILITY_CHANGED, f'`{context}` is no longer a declared output'
        return True, None
    if need == 'domain_readable':
        name = f.get('subject', '').split('launchd_domain:', 1)[-1]
        rec = (new_s.get('launchd_domains') or {}).get(name)
        if rec is None:
            return False, f'domain {name} was not observed at all in the new run'
        return (rec.get('readable') is True,
                f'domain {name} was still not readable in the new run')
    if need == 'override_absent_in_domain':
        rec = (new_s.get('launchd_domains') or {}).get(context)
        if rec is None or rec.get('readable') is not True:
            return False, (f'domain {context} was not readable in the new run, so the '
                           'absence of the override is not established')
        return (f.get('subject') not in (rec.get('enable_overrides') or {}),
                'the override is still recorded in that domain')

    repo = ctx['new_repo']
    if need == 'repo_present':
        return (repo is not None,
                'this repository is outside the observed scope of the new run')
    if repo is None:
        return False, 'this repository is outside the observed scope of the new run'
    if need == 'drift_measured':
        return repo.get('drift') is not None, 'drift was not measurable for this repository'
    if need == 'baseline_resolved':
        return (repo.get('cached_origin_main') is not None,
                'the comparison baseline was not resolved in the new run')
    if need == 'remote_probed':
        return (repo.get('remote_origin_main') is not None,
                'the live remote was not reached in the new run, so nothing was re-checked')
    if need == 'drift_path_absent':
        category = {'DRIFT_CHANGED_OR_MISSING_ON_DISK': 'changed_or_missing_on_disk',
                    'DRIFT_PRODUCTION_ONLY_TRACKED': 'production_only_tracked',
                    'DRIFT_PRODUCTION_ONLY_UNTRACKED': 'production_only_untracked'}[
            f['rule_code']]
        still = context in ((repo.get('drift') or {}).get(category) or ())
        return (not still,
                f'`{context}` is still listed in {category} of the new run, so the finding '
                'is absent without its condition having changed')
    if need == 'same_baseline':
        old_repo = ctx['old_repo'] or {}
        old_sha = ((old_repo.get('drift') or {}).get('reference_sha')
                   or old_repo.get('cached_origin_main'))
        new_sha = (repo.get('drift') or {}).get('reference_sha') or repo.get('cached_origin_main')
        if old_sha is None or new_sha is None:
            return None, 'one of the two baselines is unknown'
        if old_sha != new_sha:
            return False, ('compared against a DIFFERENT baseline; a shorter drift list is '
                           'not evidence that production changed')
        return True, None
    return None, f'unknown evidence requirement `{need}`'


def _recheck(finding, old_snapshot, new_snapshot, cov, index):
    """Decide what the absence of one finding means. Never optimistic by default."""
    rule = finding.get('rule_code')
    spec = RECHECK_SPECS.get(rule)
    if spec is None:
        return NOT_RECHECKED, (f'rule {rule} is not in the re-check table; an unknown rule '
                               'means an unknown probe'), []
    if old_snapshot.get('scope') != new_snapshot.get('scope'):
        return NOT_RECHECKED, ('the declared observation scope of the two runs differs, so '
                               'the subject was not re-examined under comparable conditions'), []

    subject = finding.get('subject')
    new_entity = index['entities_new'].get(subject)
    old_entity = index['entities_old'].get(subject)
    if spec['subject'] in ('entity', 'label_in_domain') and new_entity is None:
        if spec['subject'] == 'entity':
            carriers = _carriers(old_entity or {})
            blind = [c for c in carriers if _carrier_available(c, cov) is not True]
            if blind:
                return NOT_RECHECKED, ('the component is absent while a source that placed '
                                       'it was unavailable: ' + ', '.join(blind)), []
            return APPLICABILITY_CHANGED, ('the component left the observed scope; removing '
                                           'the object is not fixing its condition'), []
        new_entity = {}
    ctx = {'finding': finding, 'new_entity': new_entity or {}, 'old_entity': old_entity,
           'new_snapshot': new_snapshot, 'old_snapshot': old_snapshot,
           'new_repo': index['repos_new'].get(subject),
           'old_repo': index['repos_old'].get(subject)}

    met = []
    for token in spec.get('coverage', ()):
        ok, why = _coverage_met(token, cov, finding)
        if ok is not True:
            return NOT_RECHECKED, why or f'coverage `{token}` not established', met
        met.append(f'coverage:{token}')
    for need in spec.get('needs', ()):
        ok, why = _need_met(need, ctx)
        if ok is APPLICABILITY_CHANGED or ok == APPLICABILITY_CHANGED:
            return APPLICABILITY_CHANGED, why, met
        if ok is not True:
            return NOT_RECHECKED, why or f'evidence `{need}` not established', met
        met.append(need)
    return RESOLVED, None, met


#: Conditions that an EXISTING written rule places on the owner's desk. Nothing here is
#: invented: each entry quotes where the rule lives. Severity is never assigned — no
#: prioritisation policy exists, so it stays POLICY_UNDEFINED.
OWNER_DECISION_RULES = (
    {'condition': 'drift_present',
     'rule': '.claude/rules/deployment.md — «Прод-дерево — только с разрешения владельца» '
             '(Обязательное, п. 6); «data/ при синхронизации кода НЕ ТРОГАТЬ» (п. 4)',
     'why': 'любое устранение расхождения меняет рабочее дерево прода, а это действие '
            'владельца, не наблюдателя'},
    {'condition': 'installed_but_not_loaded',
     'rule': 'CLAUDE.md инв. 12 («Деплой агента только через gate») + '
             '.claude/rules/deployment.md п. 6',
     'why': 'привести INSTALLED-агента в LOADED можно только bootstrap-ом в launchd'},
    {'condition': 'orphaned_service',
     'rule': '.claude/rules/deployment.md — «Останавливать агентов „на минутку“ без '
             'возврата» запрещено; выгрузка сервиса меняет launchd',
     'why': 'сервис в домене без установленного plist снимается только изменением launchd'},
    {'condition': 'cached_vs_remote_diverged',
     'rule': '.claude/rules/deployment.md п. 6 + CLAUDE.md «канонический путь доставки»',
     'why': 'сведение кэша с origin выполняет существующий writer в проде, запускать его '
            'наблюдатель не вправе'},
)


def coverage_view(snapshot):
    """What the run could observe, as the snapshot itself records it.

    ``cartographer.snapshot/0.3`` records this directly. For an accepted ``0.2`` set the
    same facts are INFERRED from the finding vocabulary of the producer that wrote it —
    that producer emits ``SOURCE_UNREADABLE`` whenever the manifest is unreadable, so the
    absence of that finding is evidence, not silence. The basis is reported either way,
    and a finding resolved on an inferred coverage carries ``recheck_basis: inferred`` so
    a reader can discount it. A fact neither recorded nor inferable stays ``None``.
    """
    recorded = snapshot.get('coverage')
    if isinstance(recorded, dict):
        kept: dict = {k: v for k, v in recorded.items() if k != 'note'}
        kept['basis'] = 'recorded'
        return kept

    findings = snapshot.get('findings')
    domains = snapshot.get('launchd_domains') or {}
    view: dict = {'basis': 'inferred_from_findings',
                  'inference_note': 'schema 0.2 has no coverage block; these are derived from '
                                    'the finding vocabulary of the producer and from the '
                                    'domain/repository records it did store'}
    if not isinstance(findings, list):
        # Nothing to infer from: every gate is UNKNOWN, so nothing will be called resolved.
        for key in ('manifest_readable', 'registry_readable', 'installed_scan_complete',
                    'declared_plist_scan_complete', 'launchctl_list_ok', 'ps_ok',
                    'domains_complete', 'document_index_available', 'sync_status_readable'):
            view[key] = None
        view['domains_readable'] = None
        view['drift_measurable'] = None
        view['baseline_sha'] = None
        return view

    rules = {(f.get('rule_code'), f.get('subject')) for f in findings}
    codes = {code for code, _ in rules}
    view['manifest_readable'] = ('SOURCE_UNREADABLE', 'manifest') not in rules
    view['registry_readable'] = ('SOURCE_UNREADABLE', 'registry') not in rules
    view['installed_scan_complete'] = not ({'PLIST_UNREADABLE', 'PLIST_DIR_UNREADABLE'} & codes)
    view['declared_plist_scan_complete'] = 'DECLARED_PLIST_DIR_UNREADABLE' not in codes
    view['launchctl_list_ok'] = 'LAUNCHCTL_LIST_FAILED' not in codes
    view['ps_ok'] = 'PS_FAILED' not in codes
    view['domains_readable'] = {n: d.get('readable') for n, d in domains.items()} or None
    view['domains_complete'] = (all(d.get('readable') is True for d in domains.values())
                                if domains else None)
    idx = snapshot.get('document_index') or {}
    view['document_index_available'] = idx.get('available')
    view['sync_status_readable'] = snapshot.get('code_sync') is not None
    view['drift_measurable'] = {r.get('path'): r.get('drift') is not None
                                for r in snapshot.get('repositories') or []} or None
    view['baseline_sha'] = {r.get('path'): r.get('cached_origin_main')
                            for r in snapshot.get('repositories') or []} or None
    return view


# ── loading: a broken input is an error, never a clean report ────────────────

def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_set(directory):
    """Load one artifact set. Raises IncompatibleInput rather than returning an empty diff."""
    d = Path(directory)
    if not d.is_dir():
        raise IncompatibleInput(f'not a snapshot directory: {d}')
    snap_path = d / 'snapshot.json'
    if not snap_path.is_file():
        raise IncompatibleInput(f'snapshot.json is missing in {d}')
    try:
        snapshot = json.loads(snap_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise IncompatibleInput(
            f'snapshot.json in {d} could not be read ({type(exc).__name__})') from None
    # Full structural validation before anything else: an input error must end the
    # comparison with a named refusal, never produce a plausible report.
    validate_snapshot(snapshot, f'snapshot.json in {d}')
    schema = snapshot['schema_version']

    files, present, extra = {}, {}, {}
    for name in ('snapshot.json', 'system_map.json', 'findings.json'):
        p = d / name
        present[name] = p.is_file()
        if p.is_file():
            files[name] = _sha256(p)
    system_map = None
    if present['system_map.json']:
        try:
            system_map = json.loads((d / 'system_map.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            system_map = None
            present['system_map.json'] = False
            extra['system_map_note'] = 'system_map.json present but unreadable; graph not compared'
    return {'dir': str(d), 'snapshot': snapshot, 'system_map': system_map,
            'files_sha256': files, 'present': present, 'notes': extra,
            'schema_version': schema, 'finished_at': snapshot.get('finished_at'),
            'coverage': coverage_view(snapshot)}


# ── comparison ───────────────────────────────────────────────────────────────

def _by(seq, key):
    """Index a list by an identity key. Order in the file is never significant."""
    out = {}
    for item in seq or []:
        if isinstance(item, dict) and item.get(key) is not None:
            out[str(item[key])] = item
    return out


def compare(old, new):
    """Compare two loaded artifact sets. Pure function of its inputs."""
    changes = []
    limitations = []
    compat = []

    def add(ctype, cls, materiality, subject_kind, subject, old_value, new_value,
            detail=None, note=None, evidence=None):
        assert cls in CHANGE_CLASSES, cls
        assert materiality in MATERIALITY, materiality
        cid = f'{ctype}:{subject_kind}:{subject}' + (f':{detail}' if detail else '')
        changes.append({
            'id': cid, 'type': ctype, 'class': cls, 'materiality': materiality,
            'subject_kind': subject_kind, 'subject': subject, 'detail': detail,
            'old': old_value, 'new': new_value,
            'evidence': evidence or {}, 'note': note,
        })

    os_, ns = old['snapshot'], new['snapshot']
    ocov, ncov = old['coverage'], new['coverage']
    if old['schema_version'] != new['schema_version']:
        compat.append(f"schema differs: old {old['schema_version']} vs new {new['schema_version']}; "
                      'only fields present in BOTH are compared, a field absent on one side is '
                      'reported as a schema gap and never read as False')
    for side, loaded in (('old', old), ('new', new)):
        if loaded['coverage'].get('basis') == 'inferred_from_findings':
            # Which side it is matters: re-check decisions read the NEW run's coverage, so
            # only there does an inference carry into a "resolved" verdict.
            compat.append(
                f'{side} set has no recorded coverage block (schema 0.2): its coverage is '
                'INFERRED from the finding vocabulary of the producer that wrote it'
                + (', and every finding called resolved rests on that inference '
                   '(recheck_basis=inferred_from_findings)' if side == 'new'
                   else '; re-check verdicts do not depend on it, only the coverage '
                        'comparison does'))
        if not loaded['present']['system_map.json']:
            limitations.append(f'{side} set has no readable system_map.json; the graph is not compared')
        if not loaded['present']['findings.json']:
            limitations.append(f'{side} set has no findings.json; findings were read from '
                               'snapshot.json instead')
        limitations.extend(loaded['notes'].values())
    if os_.get('scope') != ns.get('scope'):
        compat.append('the declared observation SCOPE of the two runs differs; entities outside '
                      'the common scope are not comparable')

    old_ents, new_ents = _by(os_['entities'], 'id'), _by(ns['entities'], 'id')
    index = {'entities': set(new_ents),
             'old_baselines': {r.get('path'): r.get('cached_origin_main')
                               for r in os_.get('repositories') or []}}

    def field(obj, name):
        return obj.get(name, _MISSING) if isinstance(obj, dict) else _MISSING

    def cmp_field(ctype, cls, materiality, kind, subject, o, n, name, detail=None,
                  note=None, evidence=None):
        """Compare one field. A field absent on one side is a SCHEMA GAP, not a value."""
        ov, nv = field(o, name), field(n, name)
        if ov is _MISSING or nv is _MISSING:
            if ov is not nv:  # present on exactly one side
                add('SCHEMA_FIELD_ABSENT', 'comparison_basis', 'observation_quality',
                    kind, subject, None if ov is _MISSING else 'present',
                    None if nv is _MISSING else 'present', detail or name,
                    note='field recorded on only one side; not read as a value')
            return
        if ov != nv:
            add(ctype, cls, materiality, kind, subject, ov, nv, detail or name,
                note=note, evidence=evidence)

    # ── components ──────────────────────────────────────────────────────────
    for label in sorted(set(old_ents) | set(new_ents)):
        o, n = old_ents.get(label), new_ents.get(label)

        if o is None or n is None:
            if o is None:
                carriers = _carriers(n)
                add('COMPONENT_APPEARED', 'observed_state', 'material', 'component', label,
                    None, (n or {}).get('status'),
                    note='present in the new snapshot only',
                    evidence={'new_source': carriers or ['no stage is True; the label is '
                                                         'known but nothing places it yet']})
            else:
                carriers = _carriers(o)
                missing = [c for c in carriers if _carrier_available(c, ncov) is not True]
                if missing:
                    add('COMPONENT_ABSENT_UNVERIFIABLE', 'observation_quality',
                        'observation_quality', 'component', label, o.get('status'), None,
                        note='absent from the new snapshot while a source that placed it was '
                             'unavailable or UNKNOWN there; this is NOT a removal',
                        evidence={'old_source': carriers, 'unavailable_in_new': missing})
                else:
                    add('COMPONENT_DISAPPEARED', 'observed_state', 'material', 'component',
                        label, o.get('status'), None,
                        note='every source that placed it was readable again and no longer '
                             'reports it',
                        evidence={'old_source': carriers, 'rechecked_in_new': carriers})
            continue

        # stages: true→null is a loss of knowledge, never a stop
        o_stages, n_stages = o.get('stages') or {}, n.get('stages') or {}
        stage_material, stage_quality = [], []
        for st in STAGES:
            ov, nv = o_stages.get(st), n_stages.get(st)
            if ov == nv:
                continue
            if nv is None:
                add('STAGE_OBSERVATION_LOST', 'observation_quality', 'observation_quality',
                    'component', label, ov, None, st,
                    note='the probe for this stage did not establish a value in the new run; '
                         'this is loss of knowledge, NOT evidence that the stage stopped')
                stage_quality.append(st)
            elif ov is None:
                add('STAGE_OBSERVATION_GAINED', 'observation_quality', 'observation_quality',
                    'component', label, None, nv, st,
                    note='previously UNKNOWN, now observed; the stage may have held this '
                         'value all along')
                stage_quality.append(st)
            elif st == 'RUNNING' and _scheduled(n):
                add('STAGE_CHANGED', 'observed_state', 'expected_schedule', 'component',
                    label, ov, nv, st,
                    note='scheduled component: being between runs and being in a run are '
                         'both normal; this alone is not an incident',
                    evidence={'schedule': n.get('schedule'),
                              'start_interval': _first_plist_value(n, 'start_interval'),
                              'calendar': _first_plist_value(n, 'has_calendar_schedule')})
            else:
                add('STAGE_CHANGED', 'observed_state', 'material', 'component', label,
                    ov, nv, st, evidence={'old_source': (o.get('evidence') or {}).get(st),
                                          'new_source': (n.get('evidence') or {}).get(st)})
                stage_material.append(st)

        if o.get('status') != n.get('status'):
            if stage_material:
                add('STATUS_CHANGED', 'observed_state', 'material', 'component', label,
                    o.get('status'), n.get('status'),
                    note='accompanied by an observed stage change',
                    evidence={'stages_changed': sorted(stage_material)})
            elif stage_quality:
                add('STATUS_CHANGED_BY_OBSERVATION_QUALITY', 'observation_quality',
                    'observation_quality', 'component', label, o.get('status'),
                    n.get('status'),
                    note='the status label moved only because what we could OBSERVE changed; '
                         'no stage was observed to change value',
                    evidence={'stages_unknown_now': sorted(stage_quality)})
            else:
                add('STATUS_CHANGED', 'observed_state', 'material', 'component', label,
                    o.get('status'), n.get('status'),
                    note='status differs without a stage difference — check last_exit and '
                         'declared outputs, which also feed classification')

        # `domains` and `enable_overrides` are MAPS OF VERDICTS, one per launchd domain.
        # Comparing them as plain values reported "101 confirmed changes" when a single
        # domain stopped being readable and every per-label verdict turned null — going
        # blind is not a material change of state, it is loss of observation.
        for name in ENTITY_OBSERVED_FIELDS:
            if name == 'status':
                continue
            if name in VERDICT_MAP_FIELDS:
                _cmp_verdict_map(add, label, name, field(o, name), field(n, name))
                continue
            cmp_field('OBSERVED_FIELD_CHANGED', 'observed_state', 'material',
                      'component', label, o, n, name)
        for name in ENTITY_DECLARED_FIELDS:
            cmp_field('DECLARATION_CHANGED', 'declaration', 'material', 'component',
                      label, o, n, name,
                      note='a declaration changed; this says nothing about what is running',
                      evidence={'old_source': 'architecture/manifest.json (old run)',
                                'new_source': 'architecture/manifest.json (new run)'})

        if o.get('pid') != n.get('pid'):
            add('PID_CHANGED', 'observed_state', 'informational', 'component', label,
                o.get('pid'), n.get('pid'),
                note='a different PID does NOT by itself prove a restart or a fault: PIDs are '
                     'sampled per run, a scheduled job gets a new one every time it runs, and '
                     'the number can be reused by an unrelated process')
        if o.get('last_exit') != n.get('last_exit'):
            add('LAST_EXIT_CHANGED', 'observed_state', 'material', 'component', label,
                o.get('last_exit'), n.get('last_exit'),
                note='launchctl keeps the PREVIOUS exit status, and production declares a '
                     'per-label meaning for exit codes that this comparison does not apply; '
                     'a non-zero value means "last outcome non-zero", not "broken"')

        # installed configuration, keyed by plist path (never by position)
        o_plists, n_plists = _by(o.get('installed_paths'), 'plist'), _by(n.get('installed_paths'), 'plist')
        for pl in sorted(set(o_plists) | set(n_plists)):
            op, np_ = o_plists.get(pl), n_plists.get(pl)
            if op is None or np_ is None:
                available = ncov.get('installed_scan_complete')
                if np_ is None and available is not True:
                    add('INSTALLED_PLIST_ABSENT_UNVERIFIABLE', 'observation_quality',
                        'observation_quality', 'plist', pl, 'present', None,
                        note='plist scan was incomplete in the new run; absence is UNKNOWN')
                else:
                    add('INSTALLED_PLIST_ADDED' if op is None else 'INSTALLED_PLIST_REMOVED',
                        'installed_configuration', 'material', 'plist', pl,
                        None if op is None else 'present', None if np_ is None else 'present',
                        evidence={'component': label})
                continue
            for name in PLIST_FIELDS:
                cmp_field('INSTALLED_CONFIG_CHANGED', 'installed_configuration', 'material',
                          'plist', pl, op, np_, name, evidence={'component': label})
            for name in ENTRYPOINT_FIELDS:
                cmp_field('ENTRYPOINT_CHANGED', 'installed_configuration', 'material',
                          'plist', pl, op.get('entrypoint') or {}, np_.get('entrypoint') or {},
                          name, detail=f'entrypoint.{name}', evidence={'component': label})

        # declared outputs: SLO crossing is a change, ageing is not
        o_out, n_out = _by(o.get('declared_outputs'), 'relpath'), _by(n.get('declared_outputs'), 'relpath')
        for rel in sorted(set(o_out) | set(n_out)):
            oo, no = o_out.get(rel), n_out.get(rel)
            if oo is None or no is None:
                add('DECLARED_OUTPUT_ADDED' if oo is None else 'DECLARED_OUTPUT_REMOVED',
                    'declaration', 'material', 'artifact', f'{label}:{rel}',
                    None if oo is None else 'declared', None if no is None else 'declared',
                    note='the manifest declaration for this artifact changed')
                continue
            for name in OUTPUT_FIELDS:
                if name == 'fresh':
                    ov, nv = oo.get('fresh'), no.get('fresh')
                    if ov == nv:
                        continue
                    if ov is None or nv is None:
                        add('ARTIFACT_FRESHNESS_UNKNOWN', 'observation_quality',
                            'observation_quality', 'artifact', f'{label}:{rel}', ov, nv,
                            'fresh', note='freshness is judged only where the artifact exists '
                                          'and an SLO is declared; UNKNOWN is not stale')
                    else:
                        add('ARTIFACT_SLO_CROSSED', 'observed_state', 'material', 'artifact',
                            f'{label}:{rel}', ov, nv, 'fresh',
                            note='crossed the DECLARED SLO boundary — this is not simple '
                                 'ageing; producer attribution remains UNKNOWN',
                            evidence={'slo_hours': no.get('slo_hours')})
                    continue
                cmp_field('ARTIFACT_STATE_CHANGED', 'observed_state', 'material', 'artifact',
                          f'{label}:{rel}', oo, no, name)

        # governed_by resolution
        o_docs = _by(o.get('document_references'), 'reference')
        n_docs = _by(n.get('document_references'), 'reference')
        for ref in sorted(set(o_docs) | set(n_docs)):
            od, nd = o_docs.get(ref), n_docs.get(ref)
            if od is None or nd is None:
                add('DOC_REFERENCE_ADDED' if od is None else 'DOC_REFERENCE_REMOVED',
                    'declaration', 'material', 'document', f'{label}:{ref}',
                    None if od is None else od.get('outcome'),
                    None if nd is None else nd.get('outcome'))
                continue
            if od.get('outcome') != nd.get('outcome'):
                quality = 'index_unavailable' in (od.get('outcome'), nd.get('outcome'))
                add('DOC_REFERENCE_OUTCOME_CHANGED',
                    'observation_quality' if quality else 'observed_state',
                    'observation_quality' if quality else 'material',
                    'document', f'{label}:{ref}', od.get('outcome'), nd.get('outcome'),
                    note='index_unavailable means no coverage, which is not "document absent"'
                         if quality else None)

    # ── repositories: baseline first, because it decides comparability ───────
    o_repos, n_repos = _by(os_.get('repositories'), 'path'), _by(ns.get('repositories'), 'path')
    baseline_moved = set()
    for path in sorted(set(o_repos) | set(n_repos)):
        orep, nrep = o_repos.get(path), n_repos.get(path)
        if orep is None or nrep is None:
            add('REPOSITORY_ADDED' if orep is None else 'REPOSITORY_REMOVED',
                'comparison_basis', 'observation_quality', 'repository', path,
                None if orep is None else 'observed', None if nrep is None else 'observed',
                note='the set of observed repositories differs between the two runs')
            continue
        o_base = (orep.get('drift') or {}).get('reference_sha') or orep.get('cached_origin_main')
        n_base = (nrep.get('drift') or {}).get('reference_sha') or nrep.get('cached_origin_main')
        if o_base != n_base:
            baseline_moved.add(path)
            add('BASELINE_CHANGED', 'comparison_basis', 'material', 'repository', path,
                o_base, n_base,
                note='the two drift measurements are against DIFFERENT commits. Any decrease '
                     'in a drift list below is therefore NOT evidence that production was '
                     'fixed — the yardstick moved',
                evidence={'old_source': 'reference_sha of the old run',
                          'new_source': 'reference_sha of the new run'})
        cmp_field('REPOSITORY_HEAD_CHANGED', 'observed_state', 'material', 'repository',
                  path, orep, nrep, 'head')
        cmp_field('REMOTE_REF_CHANGED', 'observed_state', 'informational', 'repository',
                  path, orep, nrep, 'remote_origin_main',
                  note='the live remote moved; by itself this says nothing about this machine')

        od, nd = orep.get('drift'), nrep.get('drift')
        if (od is None) != (nd is None):
            add('DRIFT_MEASURABILITY_CHANGED', 'observation_quality', 'observation_quality',
                'repository', path, od is not None, nd is not None,
                note='drift was measurable in exactly one of the two runs; the categories '
                     'below are not comparable for this repository')
            continue
        if od is None:
            continue
        comparable = path not in baseline_moved
        for cat in DRIFT_CATEGORIES:
            before, after = set(od.get(cat) or ()), set(nd.get(cat) or ())
            for p in sorted(after - before):
                add('DRIFT_PATH_ADDED', 'observed_state',
                    'material' if comparable else 'not_comparable', 'drift',
                    f'{path}:{cat}', None, p, p,
                    note=None if comparable else 'baseline moved; not comparable',
                    evidence={'category': cat, 'category_meaning': _drift_meaning(cat),
                              'baseline_old': o_base, 'baseline_new': n_base})
            for p in sorted(before - after):
                add('DRIFT_PATH_REMOVED', 'observed_state',
                    'material' if comparable else 'not_comparable', 'drift',
                    f'{path}:{cat}', p, None, p,
                    note=('no longer differs from the SAME pinned commit'
                          if comparable else
                          'absent under a DIFFERENT baseline; this is not a production fix'),
                    evidence={'category': cat, 'category_meaning': _drift_meaning(cat),
                              'baseline_old': o_base, 'baseline_new': n_base})

    # ── coverage of the runs themselves ─────────────────────────────────────
    for key in sorted(set(ocov) | set(ncov)):
        if key in ('basis', 'inference_note', 'baseline_sha', 'note'):
            continue
        ov, nv = ocov.get(key, _MISSING), ncov.get(key, _MISSING)
        if ov is _MISSING or nv is _MISSING or ov == nv:
            continue
        add('COVERAGE_CHANGED', 'observation_quality', 'observation_quality', 'coverage',
            key, ov, nv,
            note='what the run was able to observe changed; this bounds every conclusion '
                 'drawn from the affected source',
            evidence={'old_basis': ocov.get('basis'), 'new_basis': ncov.get('basis')})

    # ── ollama infrastructure (observed, never inferred) ────────────────────
    o_oll, n_oll = os_.get('ollama') or {}, ns.get('ollama') or {}
    cmp_field('OLLAMA_REACHABILITY_CHANGED', 'observed_state', 'material', 'infrastructure',
              'ollama', o_oll, n_oll, 'api_reachable',
              note='infrastructure observation only; no inference was performed and routing '
                   'was not inspected')

    # ── derived graph: a pure function of the snapshot, so counts only ──────
    if old['system_map'] and new['system_map']:
        for key in ('nodes', 'edges'):
            ov, nv = len(old['system_map'].get(key) or ()), len(new['system_map'].get(key) or ())
            if ov != nv:
                add('GRAPH_SIZE_CHANGED', 'derived_graph', 'informational', 'graph', key,
                    ov, nv, note='the graph is a pure function of the snapshot; this count '
                                 'follows from the component changes above')

    findings_result = _compare_findings(os_, ns, ncov)
    for f in findings_result['new']:
        add('FINDING_NEW', 'observed_state', 'material', 'finding', f['id'], None,
            f.get('rule_code'), note=f.get('reason'))
    for f in findings_result['resolved']:
        add('FINDING_RESOLVED', 'observed_state', 'material', 'finding', f['id'],
            f.get('rule_code'), None,
            note='absent AND the probe that could see it ran again over a comparable scope',
            evidence={'recheck_basis': f['recheck_basis'],
                      'requirements_met': f['requirements']})
    for f in findings_result['not_rechecked']:
        add('FINDING_NOT_RECHECKED', 'observation_quality', 'observation_quality', 'finding',
            f['id'], f.get('rule_code'), None,
            note='absent from the new set, but its absence was NOT established: ' + f['why'],
            evidence={'unmet_requirement': f['why']})
    for f in findings_result['applicability_changed']:
        add('FINDING_APPLICABILITY_CHANGED', 'comparison_basis', 'not_comparable', 'finding',
            f['id'], f.get('rule_code'), None,
            note='the object this rule was about is no longer in scope, so the rule no '
                 'longer applies: ' + f['why'] + '. That is NOT the condition being fixed',
            evidence={'applicability': f['why']})

    ids = [c['id'] for c in changes]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f'change ids must be unique; collisions: {dup[:5]}')
    changes.sort(key=lambda c: (c['type'], c['subject_kind'], c['subject'], c['detail'] or ''))

    counts = {}
    for c in changes:
        counts[c['materiality']] = counts.get(c['materiality'], 0) + 1

    diff = {
        'schema_version': DIFF_SCHEMA,
        'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'volatile_fields': ['generated_at'],
        'derived_state': True,
        'offline': True,
        'offline_note': 'no launchd, git, network or production read; only the two stored '
                        'artifact sets were opened',
        'inputs': {
            'old': _input_record(old),
            'new': _input_record(new),
        },
        'compatibility': compat,
        'limitations': limitations + [
            'Neither snapshot is atomic: probes inside one run are sequential, so a change '
            'may straddle the two windows rather than a single instant.',
            'What a stored snapshot did not record cannot be recovered here; it stays UNKNOWN.',
            'HEALTHY and PRODUCING_OUTPUT are unmeasured in both runs, so no health trend '
            'exists to compare.',
        ],
        'ignored_by_design': list(IGNORED_BY_DESIGN),
        'change_classes': list(CHANGE_CLASSES),
        'materiality_vocabulary': list(MATERIALITY),
        'counts': counts,
        'component_counts': {'old': len(old_ents), 'new': len(new_ents)},
        'process_counts': {'old': len(os_.get('processes') or ()),
                           'new': len(ns.get('processes') or ()),
                           'note': 'process tables turn over constantly and are not compared '
                                   'row by row'},
        'changes': changes,
        'findings': {
            'new': [f['id'] for f in findings_result['new']],
            'persisting': findings_result['persisting'],
            'resolved': [{'id': f['id'], 'rule_code': f.get('rule_code'),
                          'recheck_basis': f['recheck_basis'],
                          'requirements': f['requirements']}
                         for f in findings_result['resolved']],
            'not_rechecked': [{'id': f['id'], 'rule_code': f.get('rule_code'), 'why': f['why']}
                              for f in findings_result['not_rechecked']],
            'applicability_changed': [{'id': f['id'], 'rule_code': f.get('rule_code'),
                                       'why': f['why']}
                                      for f in findings_result['applicability_changed']],
            'rule': 'a finding is RESOLVED only with evidence of a re-check: it is absent, the '
                    'coverage its rule depends on held, its SUBJECT is still in comparable '
                    'scope, and the specific inputs the rule reads were OBSERVED for that '
                    'subject. Absence alone is NOT_RECHECKED; a subject that left the scope '
                    'is APPLICABILITY_CHANGED, which is not a fix.',
        },
        'owner_decision_candidates': _owner_items(ns, findings_result),
    }
    diff['semantic_digest'] = semantic_digest(diff)
    return diff


def _cmp_verdict_map(add, label, field_name, before, after):
    """Compare a per-domain verdict map key by key.

    A verdict turning null, or its domain dropping out of the map entirely, is a LOSS OF
    OBSERVATION. Only a verdict flipping between two known values is a state change.
    """
    if before is _MISSING or after is _MISSING:
        return
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    for domain in sorted(set(before) | set(after)):
        old_v = before.get(domain, _MISSING)
        new_v = after.get(domain, _MISSING)
        if old_v is _MISSING and new_v is _MISSING:
            continue
        if new_v is _MISSING or new_v is None:
            if old_v in (_MISSING, None):
                continue
            add('DOMAIN_VERDICT_OBSERVATION_LOST', 'observation_quality',
                'observation_quality', 'component', label, old_v, None,
                f'{field_name}.{domain}',
                note='домен перестал отвечать по этой метке: знание потеряно, состояние '
                     'сервиса из этого НЕ следует')
        elif old_v is _MISSING or old_v is None:
            add('DOMAIN_VERDICT_OBSERVATION_GAINED', 'observation_quality',
                'observation_quality', 'component', label, None, new_v,
                f'{field_name}.{domain}',
                note='раньше было неизвестно, теперь наблюдено; значение могло держаться '
                     'и прежде')
        elif old_v != new_v:
            add('DOMAIN_VERDICT_CHANGED', 'observed_state', 'material', 'component',
                label, old_v, new_v, f'{field_name}.{domain}')


def _input_record(loaded):
    return {'directory': loaded['dir'], 'schema_version': loaded['schema_version'],
            'finished_at': loaded['finished_at'], 'files_sha256': loaded['files_sha256'],
            'files_present': loaded['present'],
            'coverage_basis': loaded['coverage'].get('basis')}


def _drift_meaning(category):
    return {
        'changed_or_missing_on_disk': 'present in the compared commit, different or absent on disk',
        'production_only_tracked': 'tracked on disk, absent from the compared commit — NOT '
                                   '"retired" and NOT "unneeded"',
        'production_only_untracked': 'untracked on disk, absent from the compared commit — '
                                     'untracked never means retired',
    }[category]


def _carriers(entity):
    """Which sources actually placed this component, per its own stage record."""
    stages = entity.get('stages') or {}
    names = {'DECLARED': 'manifest', 'REGISTERED': 'registry', 'INSTALLED': 'installed_plists',
             'LOADED': 'launchd_domains', 'RUNNING': 'launchctl_list+ps'}
    return sorted(names[st] for st in names if stages.get(st) is True)


def _carrier_available(carrier, cov):
    return {'manifest': cov.get('manifest_readable'),
            'registry': cov.get('registry_readable'),
            'installed_plists': cov.get('installed_scan_complete'),
            'launchd_domains': cov.get('domains_complete'),
            'launchctl_list+ps': (cov.get('launchctl_list_ok') is True
                                  and cov.get('ps_ok') is True) or None,
            }.get(carrier)


def _scheduled(entity):
    if entity.get('schedule'):
        return True
    for p in entity.get('installed_paths') or []:
        if p.get('start_interval') or p.get('has_calendar_schedule'):
            return True
    return False


def _first_plist_value(entity, key):
    for p in entity.get('installed_paths') or []:
        if p.get(key) is not None:
            return p[key]
    return None


def _compare_findings(old_snapshot, new_snapshot, new_cov):
    """Split the two finding sets. Absence is never read as a fix on its own."""
    old_f = _by(old_snapshot.get('findings'), 'id')
    new_f = _by(new_snapshot.get('findings'), 'id')
    index = {
        'entities_old': _by(old_snapshot.get('entities'), 'id'),
        'entities_new': _by(new_snapshot.get('entities'), 'id'),
        'repos_old': _by(old_snapshot.get('repositories'), 'path'),
        'repos_new': _by(new_snapshot.get('repositories'), 'path'),
    }
    result = {'new': [], 'persisting': [], 'resolved': [], 'not_rechecked': [],
              'applicability_changed': []}
    for fid in sorted(new_f):
        if fid not in old_f:
            result['new'].append(new_f[fid])
    result['persisting'] = sorted(set(old_f) & set(new_f))
    for fid in sorted(set(old_f) - set(new_f)):
        f = old_f[fid]
        verdict, why, met = _recheck(f, old_snapshot, new_snapshot, new_cov, index)
        if verdict == RESOLVED:
            result['resolved'].append({**f, 'requirements': met,
                                       'recheck_basis': new_cov.get('basis')})
        elif verdict == APPLICABILITY_CHANGED:
            result['applicability_changed'].append({**f, 'why': why})
        else:
            result['not_rechecked'].append({**f, 'why': why})
    return result


def _owner_items(new_snapshot, findings_result):
    """Items an EXISTING written rule puts on the owner's desk. Nothing is invented here."""
    live = {fid for fid in findings_result['persisting']}
    live |= {f['id'] for f in findings_result['new']}
    by_rule = {}
    for f in (new_snapshot.get('findings') or []):
        if f.get('id') in live:
            by_rule.setdefault(f.get('rule_code'), []).append(f)

    def group(codes):
        out = []
        for code in codes:
            out.extend(by_rule.get(code, []))
        return out

    # `installed_but_not_loaded` is read from the STAGES, never from the DEGRADED label.
    # Measured on this Mac: all three DEGRADED components were LOADED=True and degraded
    # only by a historical non-zero last_exit. Filing those under "installed but not
    # loaded" would misname them, and nothing in the repository makes "last outcome
    # non-zero" the owner's decision — the map explicitly does not interpret exit codes.
    not_loaded = [{'id': e['id']} for e in (new_snapshot.get('entities') or [])
                  if e.get('intent') == 'active'
                  and (e.get('stages') or {}).get('INSTALLED') is True
                  and (e.get('stages') or {}).get('LOADED') is False]
    conditions = {
        'drift_present': group(('DRIFT_CHANGED_OR_MISSING_ON_DISK',
                                'DRIFT_PRODUCTION_ONLY_TRACKED',
                                'DRIFT_PRODUCTION_ONLY_UNTRACKED')),
        'installed_but_not_loaded': not_loaded,
        'orphaned_service': group(('LOADED_WITHOUT_INSTALLED_PLIST',)),
        'cached_vs_remote_diverged': group(('CACHED_VS_REMOTE_DIVERGED',)),
    }
    items = []
    for rule in OWNER_DECISION_RULES:
        hits = conditions.get(rule['condition']) or []
        if not hits:
            continue
        items.append({
            'id': f"owner:{rule['condition']}",
            'condition': rule['condition'],
            'existing_rule': rule['rule'],
            'why_it_is_the_owner_s': rule['why'],
            'count': len(hits),
            'examples': [h['id'] for h in sorted(hits, key=lambda x: x['id'])[:5]],
            'severity': 'POLICY_UNDEFINED',
            'severity_note': 'no prioritisation policy exists in the repository; this '
                             'comparison does not invent one',
            'action_taken': 'NONE — nothing was corrected, deleted or deployed',
        })
    return items


def semantic_view(diff):
    """The diff minus its clock fields — what must be identical between two rebuilds."""
    return {k: v for k, v in diff.items()
            if k not in ('generated_at', 'semantic_digest', 'volatile_fields')}


def semantic_digest(diff):
    blob = json.dumps(semantic_view(diff), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


# ── report ───────────────────────────────────────────────────────────────────

def _group(changes, predicate):
    """Group for a HUMAN: one line per kind of change, not per occurrence.

    The discriminator is the change type plus, for drift, the repository+category — never
    the individual path, or six paths in one category would become six identical headings.
    """
    out = {}
    for c in changes:
        if predicate(c):
            key = (c['type'], c['subject_kind'],
                   c['subject'] if c['subject_kind'] == 'drift' else None)
            out.setdefault(key, []).append(c)
    return out


def changes_markdown(diff):
    """Short report for a person. Full detail stays in diff.json — 77 identical UNKNOWN
    wrappers are one line here and 77 records there."""
    ch = diff['changes']
    old_in, new_in = diff['inputs']['old'], diff['inputs']['new']
    lines = ['# Cartographer — что изменилось между двумя снимками', '',
             f"Старый: `{old_in['directory']}`  ·  снят {old_in['finished_at']}  ·  "
             f"схема `{old_in['schema_version']}`",
             f"Новый:  `{new_in['directory']}`  ·  снят {new_in['finished_at']}  ·  "
             f"схема `{new_in['schema_version']}`",
             '',
             f"Компонентов: {diff['component_counts']['old']} → {diff['component_counts']['new']}  ·  "
             f"изменений: {diff['counts']}",
             '', 'Сравнение offline: ни launchd, ни git, ни сеть, ни production не читались.', '']

    def section(title, items, empty):
        lines.extend([f'## {title}', ''])
        if not items:
            lines.extend([empty, ''])
            return
        for key, group in sorted(items.items(), key=lambda kv: (-len(kv[1]), str(kv[0]))):
            ctype, kind, scope = key
            lines.append(f'- **{ctype}** · {kind}'
                         + (f' · `{scope}`' if scope else '') + f': {len(group)}')
            for c in group[:5]:
                where = c['detail'] if scope else (
                    c['subject'] + (f" · {c['detail']}" if c['detail'] else ''))
                lines.append(f"  - `{where}`: {c['old']!r} → {c['new']!r}")
            if len(group) > 5:
                lines.append(f'  - … ещё {len(group) - 5}; полный список — `diff.json`')
            note = next((c['note'] for c in group if c.get('note')), None)
            if note:
                lines.append(f'  - _{note}_')
        lines.append('')

    section('1. Существенные изменения',
            _group(ch, lambda c: c['materiality'] == 'material'),
            'Существенных изменений нет. Это корректный результат, а не пустое сравнение: '
            'ниже перечислено, что именно проверялось и что осталось неизвестным.')
    section('2. Наблюдение: доступность и качество',
            _group(ch, lambda c: c['materiality'] == 'observation_quality'),
            'Качество наблюдения не менялось: те же источники были доступны в обоих прогонах.')

    lines.extend(['## 3. Сохраняющиеся существенные расхождения', ''])
    persisting = diff['findings']['persisting']
    if persisting:
        by_rule = {}
        for fid in persisting:
            by_rule.setdefault(fid.split(':', 1)[0], []).append(fid)
        for rule, ids in sorted(by_rule.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(f'- `{rule}`: {len(ids)} — держится с прошлого снимка')
            for fid in sorted(ids)[:3]:
                lines.append(f'  - `{fid}`')
            if len(ids) > 3:
                lines.append(f'  - … ещё {len(ids) - 3}')
    else:
        lines.append('- Ни одна находка не перешла из прошлого снимка.')
    lines.append('')

    changed = diff['findings'].get('applicability_changed') or ()
    if changed:
        lines.append(f'- Правило перестало применяться к своему объекту: {len(changed)} '
                     '(объект вышел из области; состояние не проверялось)')
        lines.append('')

    lines.extend(['## 4. Может требовать решения владельца', ''])
    if diff['owner_decision_candidates']:
        for item in diff['owner_decision_candidates']:
            lines.extend([
                f"- **{item['condition']}** — {item['count']} шт.",
                f"  - правило: {item['existing_rule']}",
                f"  - почему владельца: {item['why_it_is_the_owner_s']}",
                f"  - критичность: {item['severity']} ({item['severity_note']})",
                f"  - примеры: " + ', '.join(f'`{x}`' for x in item['examples']),
                f"  - сделано: {item['action_taken']}",
            ])
    else:
        lines.append('- Ни одно существующее правило не ставит наблюдаемое на стол владельца.')
    lines.append('')

    lines.extend(['## 5. Неизвестное и ограничения сравнения', ''])
    for f in diff['findings']['not_rechecked']:
        lines.append(f"- `{f['id']}` исчезло, но **не перепроверено**: {f['why']}")
    for f in diff['findings'].get('applicability_changed') or ():
        lines.append(f"- `{f['id']}`: **изменилась применимость правила**, а не состояние — "
                     f"{f['why']}. Это не исправление.")
    if not diff['findings']['not_rechecked'] and not diff['findings'].get('applicability_changed'):
        lines.append('- Каждая исчезнувшая находка перепроверена доказательством по своему '
                     'правилу и объекту, а не отсутствием строки.')
    for note in diff['compatibility']:
        lines.append(f'- Совместимость: {note}')
    for note in diff['limitations']:
        lines.append(f'- {note}')
    for note in diff['ignored_by_design']:
        lines.append(f'- Не сравнивается намеренно: {note}')
    lines.extend(['', f"Машинный результат: `diff.json` (semantic_digest "
                      f"`{diff['semantic_digest'][:16]}…`). Ничего не исправлено и не удалено.", ''])
    return '\n'.join(lines) + '\n'


# ── output location: validated from the snapshots, without touching the disk ──

def observed_roots(*snapshots):
    """Every tree the snapshots say they observed — production and its worktrees."""
    roots = []
    for s in snapshots:
        for r in s.get('repositories') or []:
            if r.get('path'):
                roots.append(r['path'])
            for w in r.get('worktrees') or []:
                if w.get('worktree'):
                    roots.append(w['worktree'])
    return sorted(set(roots))


def _forbidden_dirs():
    """launchd directories, resolved. A symlinked path to the same directory is the same
    directory, and the guard must treat it as such."""
    out = []
    for p in (Path.home() / 'Library/LaunchAgents', Path('/Library/LaunchAgents'),
              Path('/Library/LaunchDaemons')):
        try:
            out.append(p.resolve())
        except OSError:
            out.append(p)
    return out


def validate_output(output, roots):
    """The report must not land inside anything the snapshots observed.

    Deliberately NOT imported from snapshot.py: that module imports subprocess and urllib,
    and this one stays offline by construction.
    """
    resolved = Path(output).resolve()
    for root in roots:
        try:
            if resolved.is_relative_to(Path(root).resolve()):
                raise ValueError(f'Output must be outside every observed tree ({root})')
        except OSError:
            continue
    # Both sides resolved — see the note in snapshot.validate_output: resolving only the
    # output let a symlinked home defeat this guard entirely.
    if any(resolved.is_relative_to(p) for p in _forbidden_dirs()):
        raise ValueError('Output in a launchd directory is forbidden')
    return resolved


def main(argv=None):
    ap = argparse.ArgumentParser(description='Offline comparison of two Cartographer snapshots')
    ap.add_argument('--old', required=True, type=Path, help='earlier artifact set directory')
    ap.add_argument('--new', required=True, type=Path, help='later artifact set directory')
    ap.add_argument('--output', required=True, type=Path, help='new directory for the report')
    args = ap.parse_args(argv)

    try:
        old, new = load_set(args.old), load_set(args.new)
    except IncompatibleInput as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\n'
                         'No comparison was produced. This is NOT "no changes".')

    roots = observed_roots(old['snapshot'], new['snapshot'])
    output = validate_output(args.output, roots)
    if output.exists():
        raise SystemExit('Choose a new output directory; reports are never overwritten')

    diff = compare(old, new)

    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location('cartographer_sot', Path(__file__).with_name('source_of_truth.py'))
    sot_mod = module_from_spec(spec)
    spec.loader.exec_module(sot_mod)
    sot = sot_mod.build(new['snapshot'], source_dir=new['dir'])
    sot_mod.validate(sot)

    output.mkdir(parents=True, mode=0o700)
    files = [('diff.json', json.dumps(diff, indent=2, ensure_ascii=False)),
             ('changes.md', changes_markdown(diff)),
             ('source_of_truth.json', json.dumps(sot, indent=2, ensure_ascii=False)),
             ('source_of_truth.md', sot_mod.markdown(sot))]
    for name, content in files:
        p = output / name
        with p.open('x', encoding='utf-8') as handle:
            handle.write(content + '\n')
        p.chmod(0o600)
    print(changes_markdown(diff))
    print(f'Artifacts: {", ".join(n for n, _ in files)}  →  {output}')


if __name__ == '__main__':
    main()
