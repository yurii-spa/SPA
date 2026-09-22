#!/usr/bin/env python3
"""Director Web Projection (v1.1 Epic 1) — производный слой, пригодный для ЗАКРЫТОГО веба.

Зачем он есть
=============
Страницы Director OS v1 собираются для машины владельца и честно печатают то, что видят:
абсолютные пути с именем пользователя, метки launchd, внутренние порты. На локальном диске
это правильно — там путь есть адрес улики. В вебе, даже закрытом, это лишняя поверхность.

Этот модуль НЕ новый источник правды и НЕ второй реестр. Он читает уже принятые снимки
Director/Cartographer и отдаёт одну проекцию, разложенную по трём слоям владельца
(CAPITAL / STUDIO / BUILD), где каждое поле прошло через объявленную политику.

Четыре класса, и третьего смысла у них нет
==========================================
``SAFE_FOR_PRIVATE_WEB`` — значение уходит как есть.
``REDACTED``             — значение уходит ИЗМЕНЁННЫМ, и изменение названо вслух.
``LOCAL_ONLY``           — значение не уходит вовсе; в проекции остаётся только счётчик.
``UNKNOWN``              — политика для этого поля НЕ объявлена ⇒ **не публикуется**.

Умолчание — ``UNKNOWN``, то есть «не публиковать». Поле, про которое никто не решил, что оно
безопасно, безопасным не считается: иначе новая строка в снимке однажды уедет в веб молча.

Честная оговорка про метки launchd
==================================
Метка ``com.spa.site_freshness`` превращается в имя службы ``site_freshness``. Это
ПЕРЕИМЕНОВАНИЕ, а не сокрытие: состав флота по-прежнему виден, и притворяться, что топология
скрыта, было бы обманом владельца. Убрана ровно одна вещь — точная строка, которой служба
зовётся в менеджере процессов. Кому нужен полный список меток — он в локальных страницах v1.

Значения секретов не переносятся никогда: текст проходит ``reliability.redact()``, а сверх
того вырезаются ИМЕНА переменных-секретов (``*_KEY``, ``*_TOKEN``, ``*_SECRET``, ``*_PAT``) —
имя не секрет, но оно называет, что искать.

LLM здесь запрещён. Сети здесь нет. Ничего не исполняется.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.cartographer import diff as diff_mod  # noqa: E402
from scripts.cartographer import investments as investments_mod  # noqa: E402
from scripts.cartographer import reliability as reliability_mod  # noqa: E402

SCHEMA = 'director_web_projection/1'

CLASSES = ('SAFE_FOR_PRIVATE_WEB', 'REDACTED', 'LOCAL_ONLY', 'UNKNOWN')

#: Семейства, которые политика узнаёт по ФОРМЕ значения, а не по имени поля.
#: Имя поля обманчиво: `note` может нести путь, а `path` — быть безобидным именем раздела.
_LAUNCHD_LABEL = re.compile(r'\bcom\.(spa|studiobridge)\.([A-Za-z0-9_.-]+)')
_ABS_HOME_PATH = re.compile(r'/Users/[A-Za-z0-9_.-]+(/[A-Za-z0-9_./-]*)?')
_TILDE_PATH = re.compile(r'~/[A-Za-z0-9_./-]+')
_INTERNAL_HOSTPORT = re.compile(r'\b(?:127\.0\.0\.1|localhost|0\.0\.0\.0)(?::\d{2,5})?\b')
_BARE_PORT = re.compile(r'(?<![\d.])[:](?:8765|8766|8871|5173|8000)\b')
#: Ключевое слово стоит НЕ обязательно в конце: `TELEGRAM_BOT_TOKEN_SPA`, `GITHUB_PAT_SPA`.
#: Первая редакция требовала конца имени и пропускала оба — поймано собственным тестом.
_SECRET_NAME = re.compile(
    r'\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:KEY|TOKEN|SECRET|PAT|PASSWORD)(?:_[A-Z0-9]+)*\b')
_PID = re.compile(r'\bpid[ =:]+\d{2,7}\b', re.IGNORECASE)

#: Корень прод-дерева режется до repo-relative: смысл улики сохраняется, имя человека уходит.
_PRODUCTION_MARKERS = ('/Documents/SPA_Claude/', '/Documents/SPA_mirror/')


def _now():
    return datetime.now(timezone.utc)


def redact_text(value):
    """Строка, пригодная для закрытого веба. Каждое изменение ВИДНО в самой строке.

    Порядок намеренный: сначала значения секретов, потом пути, потом метки, потом имена
    секретов. Если резать имена раньше путей, `…/ETHERSCAN_API_KEY.md` потерял бы путь
    целиком и улика стала бы нечитаемой.
    """
    out = reliability_mod.redact(value)

    def _path(match):
        text = match.group(0)
        for marker in _PRODUCTION_MARKERS:
            if marker in text:
                return text.split(marker, 1)[1] or '.'
        return '[ПУТЬ ВНЕ ПРОД-ДЕРЕВА]'

    out = _ABS_HOME_PATH.sub(_path, out)
    out = _TILDE_PATH.sub('[ПУТЬ ВНЕ ПРОД-ДЕРЕВА]', out)
    out = _LAUNCHD_LABEL.sub(lambda m: m.group(2), out)
    out = _INTERNAL_HOSTPORT.sub('[ВНУТРЕННИЙ АДРЕС]', out)
    out = _BARE_PORT.sub(':[ПОРТ]', out)
    out = _PID.sub('[PID ВЫРЕЗАН]', out)
    out = _SECRET_NAME.sub('[ИМЯ СЕКРЕТА ВЫРЕЗАНО]', out)
    # Идентификаторы кошельков и счетов — NEVER, независимо от имени поля и режима.
    out = _WALLET_SHAPE.sub('[ИДЕНТИФИКАТОР ВЫРЕЗАН]', out)
    out = _IBAN_SHAPE.sub('[ИДЕНТИФИКАТОР ВЫРЕЗАН]', out)
    return out


def classify_text(value):
    """Класс строки ДО редактирования: понадобилось ли вмешательство и какое."""
    text = str(value)
    if reliability_mod.redact(text) != text:
        return 'LOCAL_ONLY'  # форма секрета в значении — такое поле не публикуется вовсе
    touched = (_ABS_HOME_PATH.search(text) or _TILDE_PATH.search(text)
               or _LAUNCHD_LABEL.search(text) or _INTERNAL_HOSTPORT.search(text)
               or _BARE_PORT.search(text) or _SECRET_NAME.search(text)
               or _PID.search(text))
    if _WALLET_SHAPE.search(text) or _IBAN_SHAPE.search(text):
        return 'LOCAL_ONLY'  # идентификатор счёта не редактируют — поле выбрасывают
    return 'REDACTED' if touched else 'SAFE_FOR_PRIVATE_WEB'


class Policy:
    """Объявленная политика по ключам. Чего здесь нет — то UNKNOWN и не публикуется.

    ``count_maps`` — отдельный род ключа, и без него политика ошибается систематически.
    У словаря-счётчика (``by_mode``, ``by_owner_view_state``) ключами служат ЗНАЧЕНИЯ
    словаря предметной области: ``PAPER``, ``IN_PROGRESS``, ``TESTED``. Обходить их как
    имена полей — значит требовать политику на каждое слово вокабуляра и блокировать весь
    счётчик целиком. Поэтому такой ключ объявляется счётчиком ОДИН раз, и его карта уходит
    целиком; строковые значения внутри всё равно проходят редактирование.
    """

    def __init__(self, safe=(), redacted=(), local_only=(), count_maps=()):
        self.safe = set(safe)
        self.redacted = set(redacted)
        self.local_only = set(local_only)
        self.count_maps = set(count_maps)

    def verdict(self, key):
        if key in self.local_only:
            return 'LOCAL_ONLY'
        if key in self.count_maps:
            return 'COUNT_MAP'
        if key in self.redacted:
            return 'REDACTED'
        if key in self.safe:
            return 'SAFE_FOR_PRIVATE_WEB'
        return 'UNKNOWN'


# ── Отдельная политика для РЕАЛЬНЫХ денег (решение ARB 20.09) ────────────────
#
# Правило написано на будущее и потому важнее нынешнего состояния: сегодня режим REAL не
# доказан ни одним источником, и соблазн велик — «когда появится, покажем». Ровно так
# приватная выкладка расширяется МОЛЧА: источник дорос, поле поехало, политику никто не
# перечитывал. Поэтому REAL живёт в своём словаре классов, а не в общем.
REAL_CLASSES = (
    'REAL_CAPITAL_SUMMARY',        # сводная величина: сколько всего
    'REAL_POSITION_DETAIL',        # разбивка по позициям/протоколам
    'WALLET_ACCOUNT_IDENTIFIER',   # адрес кошелька, номер счёта, id аккаунта
    'RAW_INVESTMENT_EVIDENCE',     # сырые улики: выписки, ответы узлов, хеши сделок
)

#: Вердикт по классу. ``BLOCKED`` = не публикуется до ЯВНОГО одобрения владельцем;
#: ``NEVER`` = не публикуется ни при каком одобрении — это не настройка, а граница.
REAL_WEB_POLICY = {
    'REAL_CAPITAL_SUMMARY': 'BLOCKED',
    'REAL_POSITION_DETAIL': 'BLOCKED',
    'WALLET_ACCOUNT_IDENTIFIER': 'NEVER',
    'RAW_INVESTMENT_EVIDENCE': 'BLOCKED',
}

#: Ключи, которые относятся к REAL-капиталу по СМЫСЛУ, а не по режиму записи.
#: Классифицируем по назначению поля: `positions` остаётся деталью позиций и тогда,
#: когда запись помечена PAPER, — иначе достаточно переставить ярлык режима.
REAL_KEY_CLASS = {
    'capital_value': 'REAL_CAPITAL_SUMMARY',
    'value': 'REAL_CAPITAL_SUMMARY',
    'equity': 'REAL_CAPITAL_SUMMARY',
    'net_pnl': 'REAL_CAPITAL_SUMMARY',
    'positions': 'REAL_POSITION_DETAIL',
    'position_value': 'REAL_POSITION_DETAIL',
    'allocation': 'REAL_POSITION_DETAIL',
    'by_protocol': 'REAL_POSITION_DETAIL',
    'by_venue': 'REAL_POSITION_DETAIL',
    'wallet': 'WALLET_ACCOUNT_IDENTIFIER',
    'wallet_address': 'WALLET_ACCOUNT_IDENTIFIER',
    'address': 'WALLET_ACCOUNT_IDENTIFIER',
    'account': 'WALLET_ACCOUNT_IDENTIFIER',
    'account_id': 'WALLET_ACCOUNT_IDENTIFIER',
    'safe_address': 'WALLET_ACCOUNT_IDENTIFIER',
    'evidence': 'RAW_INVESTMENT_EVIDENCE',
    'raw_evidence': 'RAW_INVESTMENT_EVIDENCE',
    'tx_hash': 'RAW_INVESTMENT_EVIDENCE',
    'statement': 'RAW_INVESTMENT_EVIDENCE',
}

#: Формы идентификаторов, которые не уходят НИКОГДА, независимо от имени поля.
_WALLET_SHAPE = re.compile(r'\b(0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b')
_IBAN_SHAPE = re.compile(r'\b[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}\b')


def real_class_of(key):
    """Класс поля с точки зрения РЕАЛЬНЫХ денег, либо ``None``."""
    return REAL_KEY_CLASS.get(key)


def real_verdict(key):
    """Что делать с полем REAL-режима. Неизвестный класс ⇒ ``BLOCKED``, не публикуем."""
    cls = real_class_of(key)
    if cls is None:
        return 'BLOCKED', None  # новое поле REAL — умолчание запрещает публикацию
    return REAL_WEB_POLICY.get(cls, 'BLOCKED'), cls


def project_real_record(record, stats):
    """Запись РЕАЛЬНОГО режима. По умолчанию не уходит НИЧЕГО, кроме факта режима.

    Возвращает то, что разрешено, плюс перечень заблокированных классов — чтобы владелец
    видел, что данные есть, но закрыты, а не думал, что их нет.
    """
    out, blocked = {}, {}
    for key, value in record.items():
        if key in ('mode', 'freshness', 'observed_at'):
            out[key] = value if not isinstance(value, str) else redact_text(value)
            continue
        verdict, cls = real_verdict(key)
        label = cls or 'UNCLASSIFIED_REAL_FIELD'
        blocked[label] = blocked.get(label, 0) + 1
        stats['REAL_BLOCKED'] = stats.get('REAL_BLOCKED', 0) + 1
        stats.setdefault('real_blocked_classes', {})
        stats['real_blocked_classes'][label] = \
            stats['real_blocked_classes'].get(label, 0) + 1
        del verdict, value  # ничего не публикуем: ветки «опубликовать» здесь нет намеренно
    if blocked:
        out['blocked_classes'] = blocked
        out['blocked_reason'] = ('поля режима REAL закрыты по умолчанию до ЯВНОГО '
                                 'одобрения владельцем; идентификаторы кошельков и счетов '
                                 'не публикуются ни при каком одобрении')
    return out


#: Политики по слоям. Списки коротки намеренно: проекция владельцу — не выгрузка снимка.
CAPITAL_POLICY = Policy(
    safe=('metric_type', 'mode', 'value', 'currency', 'currency_basis', 'observed_at',
          'real_capital_proven', 'real_capital_note', 'passed', 'total', 'ready',
          'status', 'triggered', 'reason', 'note', 'objects', 'mode_unknown',
          'proven_unique_strategies', 'lifecycle_state', 'promotion_status',
          'owner_approval', 'owner_approval_status', 'freshness', 'title',
          'capital_value', 'capital_currency', 'backtest_status', 'canary_status',
          'rnd_status', 'rnd_objects', 'with_capital', 'conflicting_facts',
          'cross_source_merges', 'proven_unique_strategy_ids'),
    redacted=('source', 'source_field', 'where', 'detail', 'rnd_pipeline',
              'lifecycle_source', 'strategy_name', 'risk_classification'),
    local_only=('facts_by_source', 'evidence', 'id_namespace', 'strategy_id',
                'mode_evidence', 'strategy_source_records', 'blockers',
                'performance_metrics', 'yield_metrics', 'risk_limits'),
    count_maps=('by_mode', 'by_lifecycle_state', 'by_promotion_status',
                'by_owner_approval', 'capital_by_mode', 'rnd_stage_counts'),
)

STUDIO_POLICY = Policy(
    safe=('classification', 'severity', 'status', 'freshness', 'category', 'as_of',
          'finding_title', 'finding_type', 'occurrences', 'occurrence_count',
          'corroborated_by', 'first_seen', 'last_seen', 'active_confirmed',
          'active_unverified', 'critical_confirmed_now', 'critical_unverified',
          'warning_confirmed_now', 'warning_unverified', 'corroborated',
          'owner_view_state', 'acceptance_status', 'acceptance_applicability',
          'blocker_status', 'work_type', 'recovery_state', 'permission_class',
          'permission_zone', 'approval_required', 'authority_source',
          'adr_number_collisions', 'backups_observed', 'restore_proven',
          'recovery_tested', 'recovery_documented_untested', 'recovery_missing',
          'recovery_not_applicable', 'recovery_unknown', 'recovery_documented_total',
          'autonomous_rules', 'emergency_rules', 'owner_gated', 'zone_required',
          'zone_defined', 'zone_not_applicable', 'zone_required_but_missing',
          'zone_scope_unknown', 'system_state', 'system_state_reason',
          'production_drift', 'authority_undefined', 'measured', 'count',
          'accepted', 'blocked', 'in_progress', 'completed_total', 'waiting_owner',
          'acceptance_state_conflicts', 'unresolved_identity_records',
          'explicit_task_links', 'mention_only_matches', 'no_task_relation',
          'sources_read', 'sources_unavailable', 'sources_with_declared_slo',
          'sources_freshness_unknown', 'security_items', 'gaps',
          'proven_unique_work_count', 'unknown_severity', 'unknown_state',
          'execution_claim_known', 'owner_role_known', 'claim_is_a_verified_agent',
          'claim_not_an_agent', 'reliability_explicit', 'reliability_mention_only',
          'reliability_none', 'done_acceptance_not_applicable',
          'done_acceptance_unconfirmed', 'done_acceptance_unknown',
          'rules', 'invariants', 'permissions', 'decisions', 'items'),
    redacted=('affected_entity', 'authoritative_source', 'classification_reason',
              'title', 'note', 'basis', 'governs', 'owner', 'decision_ref',
              'authority_quote', 'freshness_rule', 'service_name', 'verdict_reason'),
    local_only=('evidence', 'path', 'sources', 'claimed_by', 'claim_kind',
                'acceptance_evidence', 'blocker_evidence', 'finding_id',
                'governance_id', 'work_id', 'record_path', 'merged_ids',
                'linked_tasks', 'related_work', 'related_findings',
                'related_decisions', 'source_records', 'occurrence_basis',
                'source_age_hours', 'by_source', 'source_status', 'source_authority'),
    count_maps=('by_classification', 'by_severity', 'by_status', 'by_freshness',
                'by_category', 'by_owner_view_state', 'by_acceptance_status',
                'by_acceptance_applicability', 'by_blocker_status', 'by_claim_kind',
                'by_work_type', 'by_permission_class', 'by_permission_zone',
                'by_recovery_state', 'by_recovery_status', 'by_authority_source',
                'by_zone_scope', 'by_source_state'),
)

#: Службы флота. Метка менеджера процессов превращается в ИМЯ службы (переименование,
#: не сокрытие); всё остальное — состояние, роль, расписание и стадии — уходит как есть.
SERVICE_POLICY = Policy(
    safe=('status', 'intent', 'layer', 'role', 'schedule', 'last_exit', 'kind',
          'stages', 'DECLARED', 'REGISTERED', 'INSTALLED', 'LOADED', 'RUNNING',
          'PRODUCING_OUTPUT', 'HEALTHY', 'name'),
    redacted=('id', 'health_reason', 'last_exit_basis'),
    local_only=('evidence', 'installed_paths', 'declared_program', 'declared_plist_source',
                'declared_plist_in_repo', 'pid', 'domains', 'enable_overrides',
                'declared_outputs', 'declared_consumes', 'declared_governed_by',
                'document_references'),
)

#: История капитала: числа и даты. Ни адресов, ни идентификаторов здесь нет по составу.
HISTORY_POLICY = Policy(
    safe=('date', 'equity', 'daily_return_pct', 'cumulative_return_pct', 'drawdown_pct',
          'daily_yield_usd', 'apy_today', 'evidenced', 'is_warmup', 'nav', 'ts',
          'daily_pnl', 'cycle_number', 'positions', 'open_equity', 'close_equity',
          'high_equity', 'low_equity', 'snapshots', 'num_days', 'real_days',
          'evidenced_days', 'num_snapshots', 'start_equity', 'end_equity',
          'total_return_pct', 'max_drawdown_pct', 'best_day', 'worst_day',
          'real_start_equity', 'real_end_equity', 'real_total_return_pct',
          'usd', 'apy_pct', 'apy_source', 'protocol', 'severity', 'category',
          'message', 'action', 'strategy_id', 'reason', 'metrics', 'sharpe_30d',
          'calmar_30d', 'days_active', 'total_flags', 'by_category', 'by_severity',
          'by_protocol'),
    redacted=('source', 'note', 'as_of', 'detected_at'),
    local_only=('evidence', 'source_file', 'wallet', 'address', 'tx_hash'),
    count_maps=('by_category', 'by_severity', 'by_protocol', 'positions'),
)

BUILD_POLICY = Policy(
    safe=('action', 'verdict', 'destructive', 'owner_approval_required',
          'missing_properties', 'required_properties', 'red_zone', 'ready_for_ui',
          'not_ready', 'candidates', 'actions', 'ui_exposes_actions',
          'intake_kind', 'available', 'stage', 'title', 'state'),
    redacted=('canonical_executor', 'currently_used_by', 'input', 'note'),
    local_only=('evidence', 'properties'),
    count_maps=('by_missing_property',),
)


def project_count_map(value, stats):
    """Словарь-счётчик целиком: ключи здесь — слова вокабуляра, а не имена полей.

    Строковые значения всё равно редактируются, а вложенность глубже одного уровня
    отбрасывается: счётчик, в котором вдруг появилась запись, — уже не счётчик, и
    публиковать его как счётчик значило бы обойти политику.
    """
    if not isinstance(value, dict):
        stats['SAFE_FOR_PRIVATE_WEB'] = stats.get('SAFE_FOR_PRIVATE_WEB', 0) + 1
        return value
    out = {}
    for term, count in value.items():
        if isinstance(count, dict):
            out[term] = project_count_map(count, stats)
        elif isinstance(count, str):
            shape = classify_text(count)
            if shape == 'LOCAL_ONLY':
                stats['LOCAL_ONLY'] = stats.get('LOCAL_ONLY', 0) + 1
                continue
            stats[shape] = stats.get(shape, 0) + 1
            out[term] = redact_text(count) if shape == 'REDACTED' else count
        elif isinstance(count, (int, float, bool)) or count is None:
            stats['SAFE_FOR_PRIVATE_WEB'] = stats.get('SAFE_FOR_PRIVATE_WEB', 0) + 1
            out[term] = investments_mod.json_safe(count) if isinstance(count, float) \
                else count
        else:
            stats['LOCAL_ONLY'] = stats.get('LOCAL_ONLY', 0) + 1
    return out


def project_value(value, policy, key, stats):
    """Одно поле через политику. Возвращает (публиковать?, значение)."""
    verdict = policy.verdict(key)
    if verdict == 'UNKNOWN':
        stats['UNKNOWN'] = stats.get('UNKNOWN', 0) + 1
        stats.setdefault('unknown_keys', set()).add(key)
        return False, None
    if verdict == 'LOCAL_ONLY':
        stats['LOCAL_ONLY'] = stats.get('LOCAL_ONLY', 0) + 1
        return False, None
    if verdict == 'COUNT_MAP':
        return True, project_count_map(value, stats)

    if isinstance(value, str):
        shape = classify_text(value)
        if shape == 'LOCAL_ONLY':
            stats['LOCAL_ONLY'] = stats.get('LOCAL_ONLY', 0) + 1
            return False, None
        if shape == 'REDACTED':
            stats['REDACTED'] = stats.get('REDACTED', 0) + 1
            return True, redact_text(value)
        stats['SAFE_FOR_PRIVATE_WEB'] = stats.get('SAFE_FOR_PRIVATE_WEB', 0) + 1
        return True, value
    if isinstance(value, float):
        # Не-конечное число НАЗЫВАЕТСЯ, а не теряется: `promotion_report.json` содержит
        # `-Infinity`, и такой файл перестаёт быть валидным JSON — браузер молча
        # остаётся без раздела. Приём переиспользован из слоя инвестиций (фаза 7).
        safe = investments_mod.json_safe(value)
        stats['SAFE_FOR_PRIVATE_WEB'] = stats.get('SAFE_FOR_PRIVATE_WEB', 0) + 1
        return True, safe
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            keep, projected = project_value(v, policy, k, stats)
            if keep:
                out[k] = projected
        return True, out
    if isinstance(value, list):
        out = []
        for item in value:
            keep, projected = project_value(item, policy, key, stats)
            if keep:
                out.append(projected)
        return True, out
    stats['SAFE_FOR_PRIVATE_WEB'] = stats.get('SAFE_FOR_PRIVATE_WEB', 0) + 1
    return True, value


def project_record(record, policy, stats):
    """Одна запись снимка. Ключи вне политики отбрасываются молча — но СЧИТАЮТСЯ."""
    out = {}
    for key, value in record.items():
        keep, projected = project_value(value, policy, key, stats)
        if keep:
            out[key] = projected
    return out


def _capital(inv, stats, *, history=None, positions=None, risk_config=None,
             red_flags=None, golive=None, promotion=None):
    if inv is None:
        return {'state': 'NOT_READ',
                'note': 'снимок инвестиций не прочитан — это НЕ значит, что капитала нет'}
    layer = {
        'real_capital_proven': bool(inv.get('real_capital_proven')),
        'real_capital_note': redact_text(inv.get('real_capital_note') or ''),
        'mode_vocabulary': list(inv.get('mode_vocabulary') or ()),
        'metric_vocabulary': list(inv.get('metric_vocabulary') or ()),
        # Счётчик, а не запись: ключи здесь — режимы (PAPER/REAL/…), и обходить их как
        # имена полей значило бы заблокировать всю разбивку капитала по режимам.
        'capital_by_mode': project_count_map(inv.get('capital_by_mode') or {}, stats),
        'capital_metrics': [project_record(m, CAPITAL_POLICY, stats)
                            for m in inv.get('capital_metrics') or ()],
        'kill_switch': project_record(inv.get('kill_switch') or {}, CAPITAL_POLICY, stats),
        'golive': project_record(inv.get('golive') or {}, CAPITAL_POLICY, stats),
        'rnd_stage_counts': dict(inv.get('rnd_stage_counts') or {}),
        'counts': project_record(inv.get('counts') or {}, CAPITAL_POLICY, stats),
        # Запись РЕАЛЬНОГО режима идёт по своей политике, а не по общей: иначе поле,
        # появившееся в будущем источнике, расширило бы выкладку молча.
        'strategies': [(project_real_record(o, stats)
                        if str(o.get('mode') or '').upper() == 'REAL'
                        else project_record(o, CAPITAL_POLICY, stats))
                       for o in inv.get('objects') or ()],
        'real_web_policy': dict(REAL_WEB_POLICY),
        'real_class_vocabulary': list(REAL_CLASSES),
        'real_policy_note':
            'любое НОВОЕ поле режима REAL закрыто по умолчанию (UNKNOWN → BLOCKED) до '
            'явного одобрения владельцем. Идентификаторы кошельков и счетов — NEVER: '
            'это граница, а не настройка. Значения режима PAPER остаются как приняты',
        'limits': [redact_text(x) for x in inv.get('limits') or ()],
    }
    if not layer['real_capital_proven']:
        layer['real_capital_headline'] = 'REAL CAPITAL: NOT PROVEN'

    # ── История. Ряд публикуется ТОЛЬКО если он действительно ряд: одна точка
    #    графиком не становится, и делать из снимка «историю» запрещено.
    layer['history'] = _capital_history(history, stats)
    layer['positions'] = _positions(positions, stats)
    layer['risk_config'] = project_record(risk_config or {}, HISTORY_POLICY, stats) \
        if risk_config else {'state': 'NOT_MEASURED'}
    layer['red_flags'] = _red_flags(red_flags, stats)
    layer['golive'] = {**(layer.get('golive') or {}),
                       **_golive(golive, stats)} if golive else layer.get('golive')
    layer['promotion'] = _promotion(promotion, stats)
    return layer


def _capital_history(history, stats):
    """Ряд эквити и доходности. Меньше двух точек — это НЕ история."""
    if not history:
        return {'state': 'NOT_MEASURED',
                'note': 'источник истории не подан — это НЕ значит, что истории нет'}
    daily = [project_record(r, HISTORY_POLICY, stats) for r in history.get('daily') or ()]
    metrics = [project_record(r, HISTORY_POLICY, stats)
               for r in history.get('metrics_history') or ()]
    out = {
        'state': 'READ',
        'mode': history.get('mode'),
        'mode_basis': history.get('mode_basis'),
        'daily': daily,
        'daily_points': len(daily),
        'metrics_history': metrics,
        'metrics_points': len(metrics),
        'summary': project_record(history.get('summary') or {}, HISTORY_POLICY, stats),
        'is_a_series': len(daily) >= 2,
        'series_rule': ('график строится только при двух и более точках: одна точка — '
                        'снимок, а не история'),
    }
    return out


def _positions(positions, stats):
    """Позиции по протоколам. Ни адресов, ни счетов здесь нет по составу источника."""
    if not positions:
        return {'state': 'NOT_MEASURED'}
    detail = positions.get('positions_detail') or {}
    rows = []
    for name, rec in (detail.items() if isinstance(detail, dict) else ()):
        row = project_record(rec if isinstance(rec, dict) else {}, HISTORY_POLICY, stats)
        row['protocol'] = redact_text(name)
        rows.append(row)
    total = sum(r.get('usd') or 0 for r in rows)
    capital = positions.get('capital_usd')
    return {
        'state': 'READ',
        'mode': positions.get('execution_mode'),
        'capital_usd': capital,
        'deployed_usd': total or None,
        'cash_usd': (capital - total) if (capital is not None and rows) else None,
        'positions': sorted(rows, key=lambda r: -(r.get('usd') or 0)),
        'count': len(rows),
    }


def _red_flags(red_flags, stats):
    if not red_flags:
        return {'state': 'NOT_MEASURED'}
    flags = [project_record(f, HISTORY_POLICY, stats)
             for f in red_flags.get('red_flags') or ()]
    return {'state': 'READ', 'flags': flags, 'count': len(flags),
            'summary': project_count_map(red_flags.get('summary') or {}, stats)}


def _golive(golive, stats):
    if not golive:
        return {}
    blockers = [redact_text(b) for b in (golive.get('blockers') or ())]
    return {'blockers': blockers, 'blocker_count': len(blockers),
            'real_track_days': golive.get('real_track_days')}


def _promotion(promotion, stats):
    """Решения о продвижении. Это НАБЛЮДЁННЫЕ решения, а не рекомендации слоя."""
    if not promotion:
        return {'state': 'NOT_MEASURED'}
    rows = [project_record(d, HISTORY_POLICY, stats)
            for d in promotion.get('decisions') or ()]
    by_action = {}
    for r in rows:
        by_action[r.get('action') or 'UNKNOWN'] = by_action.get(r.get('action') or 'UNKNOWN', 0) + 1
    return {'state': 'READ', 'decisions': rows, 'count': len(rows),
            'by_action': by_action,
            'note': 'это наблюдённые решения источника, а не рекомендации кокпита'}


def _studio(rel, work, gov, director, stats, *, services=None, drift=None,
            memory=None):
    layer = {}
    if director is not None:
        layer['system_state'] = director.get('system_state')
        layer['system_state_reason'] = redact_text(director.get('system_state_reason') or '')
        layer['has_health_score'] = bool(director.get('has_health_score'))
        # Полное число лежит в `count`, а не в `total`. Первая редакция брала `total`,
        # и владелец видел «5 из не измерено» — честно, но бесполезно.
        layer['blocks'] = {name: {'shown': (block or {}).get('shown'),
                                  'count': (block or {}).get('count'),
                                  'empty_means': redact_text((block or {}).get('empty_means') or '')}
                           for name, block in (director.get('blocks') or {}).items()}
    if rel is not None:
        layer['reliability'] = {
            'counts': project_record(rel.get('counts') or {}, STUDIO_POLICY, stats),
            'findings': [project_record(f, STUDIO_POLICY, stats)
                         for f in rel.get('findings') or ()],
            'limits': [redact_text(x) for x in rel.get('limits') or ()],
        }
    if work is not None:
        layer['work'] = {
            'counts': project_record(work.get('counts') or {}, STUDIO_POLICY, stats),
            'identity': {'proven_unique_work_count':
                         (work.get('identity') or {}).get('proven_unique_work_count'),
                         'proven_unique_reason':
                         redact_text((work.get('identity') or {}).get('proven_unique_reason') or '')},
            'limits': [redact_text(x) for x in work.get('limits') or ()],
        }
    if gov is not None:
        layer['governance'] = {
            'counts': project_record(gov.get('counts') or {}, STUDIO_POLICY, stats),
            'recovery_vocabulary': list(gov.get('recovery_vocabulary') or ()),
            'limits': [redact_text(x) for x in gov.get('limits') or ()],
        }
    layer['services'] = _services(services, stats)
    layer['drift'] = _drift(drift, stats)
    layer['memory'] = memory or {'state': 'NOT_MEASURED'}
    if rel is not None:
        layer['reliability']['top_findings'] = _top_findings(rel, stats)
    return layer


#: Род службы выводится из НАБЛЮДЁННОГО расписания, а не из имени. Метка launchd
#: агентом сама по себе не является — это требование ARB и оно измеримо: `daemon`
#: против `interval:` против `calendar:` против `manual` — разные роды, и род
#: «AGENT» здесь не присваивается никому, потому что ни один источник его не объявляет.
SERVICE_KIND_BY_SCHEDULE = (
    ('daemon', 'DAEMON'),
    ('interval:', 'SCHEDULED'),
    ('calendar:', 'SCHEDULED'),
    ('manual', 'MANUAL'),
)


def service_kind(schedule):
    """Род службы по расписанию. Неизвестное расписание — ``UNKNOWN``, не догадка."""
    s = str(schedule or '')
    for prefix, kind in SERVICE_KIND_BY_SCHEDULE:
        if s.startswith(prefix):
            return kind
    return 'UNKNOWN'


def _services(services, stats):
    """Флот: состояние, род, роль, стадии. Метка превращается в имя службы.

    Слово «агент» здесь не употребляется ни к одной записи: ни один источник не
    объявляет сущность агентом, а называть агентом метку менеджера процессов —
    ровно та подмена, которую ARB запретил.
    """
    if not services:
        return {'state': 'NOT_MEASURED'}
    rows = []
    for e in services.get('entities') or ():
        row = project_record(e, SERVICE_POLICY, stats)
        row['name'] = redact_text(e.get('id') or '')
        row['kind'] = service_kind(e.get('schedule'))
        rows.append(row)
    def tally(key):
        out = {}
        for r in rows:
            out[str(r.get(key))] = out.get(str(r.get(key)), 0) + 1
        return out
    stages_measured = sum(1 for r in rows
                          if (r.get('stages') or {}).get('HEALTHY') is not None)
    return {
        'state': 'READ',
        'count': len(rows),
        'services': rows,
        'by_status': tally('status'),
        'by_kind': tally('kind'),
        'by_role': tally('role'),
        'by_intent': tally('intent'),
        'health_measured': stages_measured,
        'health_not_measured': len(rows) - stages_measured,
        'agent_note': ('род выведен из наблюдённого расписания. Слово «агент» не '
                       'присвоено никому: ни один источник его не объявляет, а метка '
                       'менеджера процессов агентом не является'),
    }


def _drift(drift, stats):
    """Расхождение источника правды: девять состояний, и ни одно не «ошибка»."""
    if not drift:
        return {'state': 'NOT_MEASURED'}
    counts = drift.get('counts') or {}
    return {
        'state': 'READ',
        'entities': counts.get('entities'),
        'by_drift_status': project_count_map(counts.get('by_drift_status') or {}, stats),
        'by_severity': project_count_map(counts.get('by_severity') or {}, stats),
        'by_entity_type': project_count_map(counts.get('by_entity_type') or {}, stats),
        'definitions': {k: redact_text(v) for k, v in
                        (drift.get('drift_status_definitions') or {}).items()},
    }


#: Сколько находок показывать по существу. Полный список — 313 записей — это выгрузка,
#: а не экран; бюджет тот же, что у центра директора.
TOP_FINDINGS = 12


def _top_findings(rel, stats):
    """Подтверждённые находки по убыванию тяжести. Неподтверждённое сюда НЕ входит."""
    order = {'CRITICAL': 0, 'WARNING': 1, 'INFO': 2, 'UNKNOWN': 3}
    confirmed = [f for f in rel.get('findings') or ()
                 if f.get('status') == 'ACTIVE_CONFIRMED']
    confirmed.sort(key=lambda f: (order.get(f.get('severity'), 9),
                                  str(f.get('finding_title') or '')))
    rows = [project_record(f, STUDIO_POLICY, stats) for f in confirmed[:TOP_FINDINGS]]
    return {'rows': rows, 'shown': len(rows), 'confirmed_total': len(confirmed),
            'note': ('показаны только ПОДТВЕРЖДЁННЫЕ сейчас; неподтверждённое — '
                     'отдельное состояние, а не более слабая находка')}


def _build(actions, bridge, intake, stats, *, pipeline=None):
    layer = {'actions_enabled': False,
             'actions_enabled_note':
                 'Epic 1 остаётся READ-ONLY: ни одной кнопки действия не показывается'}
    if actions is not None:
        layer['action_audit'] = {
            'counts': project_record(actions.get('counts') or {}, BUILD_POLICY, stats),
            'red_zone': list(actions.get('red_zone') or ()),
            'required_properties': list(actions.get('required_properties') or ()),
            'ui_exposes_actions': bool(actions.get('ui_exposes_actions')),
            'actions': [project_record(a, BUILD_POLICY, stats)
                        for a in actions.get('actions') or ()],
        }
    layer['bridge'] = bridge or {'state': 'NOT_MEASURED',
                                 'note': 'состояние Bridge в эту проекцию не подавали'}
    layer['owner_intake'] = intake or []
    layer['pipeline'] = _pipeline(pipeline, stats)
    return layer


#: Стадии конвейера разработки. Состояние каждой — НАБЛЮДЕНИЕ, подаваемое снаружи;
#: выдумывать «работает» по факту существования документа запрещено.
PIPELINE_STAGE_VOCABULARY = ('LIVE', 'PARTIAL', 'DOCUMENTED_ONLY', 'NOT_FOUND', 'UNKNOWN')


def _pipeline(pipeline, stats):
    """Где автономия останавливается сегодня — по стадиям, а не по обещаниям."""
    if not pipeline:
        return {'state': 'NOT_MEASURED',
                'note': 'состояние стадий не подавали — это НЕ значит, что их нет'}
    rows = []
    for s in pipeline:
        state = s.get('state')
        rows.append({
            'stage': redact_text(s.get('stage') or ''),
            'state': state if state in PIPELINE_STAGE_VOCABULARY else 'UNKNOWN',
            'basis': redact_text(s.get('basis') or ''),
        })
    tally = {}
    for r in rows:
        tally[r['state']] = tally.get(r['state'], 0) + 1
    first_gap = next((r['stage'] for r in rows if r['state'] != 'LIVE'), None)
    return {'state': 'READ', 'stages': rows, 'count': len(rows), 'by_state': tally,
            'vocabulary': list(PIPELINE_STAGE_VOCABULARY),
            'autonomy_stops_at': first_gap,
            'note': ('«где останавливается автономия» — это ПЕРВАЯ стадия не в LIVE '
                     'по порядку конвейера, а не оценка зрелости')}


def build_projection(*, investments=None, reliability=None, work=None, governance=None,
                     director=None, actions=None, bridge=None, intake=None, now=None,
                     services=None, drift=None, capital_history=None, positions=None,
                     risk_config=None, red_flags=None, golive=None, promotion=None,
                     pipeline=None, memory=None):
    """Одна проекция из уже принятых снимков. Ничего не считает заново."""
    now = now or _now()
    stats = {}
    projection = {
        'schema_version': SCHEMA,
        'generated_at': now.isoformat(),
        'derived_state': True,
        'is_not_a_source_of_truth':
            'проекция для закрытого веба: пересобирается из принятых снимков Director OS и '
            'не является ни новым реестром, ни источником правды',
        'web_safe': True,
        'classification_vocabulary': list(CLASSES),
        'classification_definitions': {
            'SAFE_FOR_PRIVATE_WEB': 'значение уходит как есть',
            'REDACTED': 'значение уходит изменённым, и изменение видно в самой строке',
            'LOCAL_ONLY': 'значение не уходит; остаётся только счётчик',
            'UNKNOWN': 'политика не объявлена ⇒ НЕ публикуется (умолчание)',
        },
        # Сама эта строка НЕ вправе содержать метку целиком: контракт ниже ищет форму метки
        # по всему опубликованному тексту, и пояснение политики стало бы её нарушением.
        'launchd_label_note':
            'полная метка менеджера процессов публикуется как короткое имя службы. Это '
            'ПЕРЕИМЕНОВАНИЕ, а не сокрытие: состав флота по-прежнему виден, и притворяться, '
            'что топология скрыта, было бы обманом',
        'layers': {
            'CAPITAL': _capital(investments, stats, history=capital_history,
                                positions=positions, risk_config=risk_config,
                                red_flags=red_flags, golive=golive, promotion=promotion),
            'STUDIO': _studio(reliability, work, governance, director, stats,
                              services=services, drift=drift, memory=memory),
            'BUILD': _build(actions, bridge, intake, stats, pipeline=pipeline),
        },
    }
    # Перечень заблокированного публикуется НАМЕРЕННО: владелец должен видеть, что
    # именно было удержано, иначе «умолчание не публиковать» непроверяемо. Но имя поля
    # тоже бывает говорящим, поэтому список проходит то же редактирование, что и
    # значения: имя секрета или путь в имени поля наружу не уходят.
    unknown_keys = sorted(redact_text(k) for k in stats.pop('unknown_keys', set()))
    projection['redaction_stats'] = {
        'SAFE_FOR_PRIVATE_WEB': stats.get('SAFE_FOR_PRIVATE_WEB', 0),
        'REDACTED': stats.get('REDACTED', 0),
        'LOCAL_ONLY': stats.get('LOCAL_ONLY', 0),
        'UNKNOWN_BLOCKED': stats.get('UNKNOWN', 0),
    }
    projection['unknown_keys_blocked'] = unknown_keys
    projection['semantic_digest'] = semantic_digest(projection)
    return projection


#: Листья, зависящие от ЧАСОВ, а не от наблюдаемого факта. Исключаются на ЛЮБОЙ
#: глубине, и это измеренная необходимость, а не осторожность: два прогона подряд,
#: между которыми в системе не изменилось ничего, давали РАЗНЫЕ дайджесты — 458
#: различающихся листьев, и все до единого `as_of`/`last_seen` внутри находок
#: надёжности. На таком дайджесте замысел «публиковать по смене смысла» не держится:
#: он публиковал бы каждый час.
#:
#: Граница проста: момент НАБЛЮДЕНИЯ — не факт. Если у находки изменился только
#: `last_seen`, в системе не изменилось ничего, кроме времени взгляда на неё.
VOLATILE_LEAF_KEYS = frozenset({
    'generated_at', 'observed_at', 'as_of', 'first_seen', 'last_seen',
    'checked_at', 'built_at', 'last_check', 'last_successful_build',
    'age_hours', 'source_age_hours', 'run_started_at', 'page_generated_at',
})


def _strip_volatile(value):
    """Дерево без листьев-часов. Структура сохраняется: пропажа поля — тоже смысл."""
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in value.items()
                if k not in VOLATILE_LEAF_KEYS}
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    return value


def semantic_view(projection):
    """Смысловой срез: без собственных часов И без часов на любой глубине."""
    return _strip_volatile({k: v for k, v in projection.items()
                            if k not in ('generated_at', 'semantic_digest')})


def semantic_digest(projection):
    payload = json.dumps(semantic_view(projection), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


class WebProjectionError(Exception):
    pass


def validate_projection(projection, where):
    """Контракт. Отказывает, а не чинит."""
    def need(cond, message):
        if not cond:
            raise WebProjectionError(f'{where}: {message}')

    need(projection.get('schema_version') == SCHEMA, 'чужая схема')
    need(projection.get('derived_state') is True, 'проекция обязана объявить себя производной')
    need(projection.get('web_safe') is True, 'проекция обязана объявить себя web-safe')
    need(isinstance(projection.get('is_not_a_source_of_truth'), str),
         'проекция обязана назвать, чем она НЕ является')
    need(set(projection.get('layers') or {}) == {'CAPITAL', 'STUDIO', 'BUILD'},
         'слоёв обязано быть ровно три: CAPITAL, STUDIO, BUILD')
    need(projection['layers']['BUILD'].get('actions_enabled') is False,
         'Epic 1 read-only: actions_enabled обязан быть False')

    # Главная проверка: в опубликованном тексте не осталось ни одной запретной формы.
    payload = json.dumps(projection, ensure_ascii=False)
    for pattern, name in ((_ABS_HOME_PATH, 'абсолютный путь с именем пользователя'),
                          (_TILDE_PATH, 'путь через ~/'),
                          (_LAUNCHD_LABEL, 'метка launchd'),
                          (_INTERNAL_HOSTPORT, 'внутренний адрес'),
                          (_PID, 'номер процесса')):
        hits = pattern.findall(payload)
        need(not hits, f'в проекции осталось запретное: {name} ({len(hits)} шт)')
    # Имена секретов: своё собственное объяснение политики их называть не может.
    for hit in _SECRET_NAME.findall(payload):
        need(False, f'в проекции осталось имя секрета: {hit}')
    need(reliability_mod.redact(payload) == payload,
         'в проекции осталась ФОРМА секрета — значения не переносятся никогда')
    for pattern, name in ((_WALLET_SHAPE, 'адрес кошелька'),
                          (_IBAN_SHAPE, 'номер счёта')):
        hits = pattern.findall(payload)
        need(not hits, f'в проекции остался идентификатор ({name}, {len(hits)} шт) — '
                       'класс WALLET_ACCOUNT_IDENTIFIER не публикуется НИКОГДА')
    # Политика REAL обязана быть объявлена в самой проекции, а не жить только в коде:
    # контракт, о котором нельзя прочитать в артефакте, проверить снаружи нечем.
    capital = (projection.get('layers') or {}).get('CAPITAL') or {}
    if capital.get('state') != 'NOT_READ':
        need(capital.get('real_web_policy') == REAL_WEB_POLICY,
             'слой капитала обязан объявить политику REAL дословно')
        need(capital['real_web_policy'].get('WALLET_ACCOUNT_IDENTIFIER') == 'NEVER',
             'идентификаторы кошельков и счетов обязаны быть NEVER, а не BLOCKED')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--bundle', required=True, help='каталог с принятыми снимками Director OS')
    ap.add_argument('--bridge', help='JSON с наблюдённым состоянием Bridge')
    ap.add_argument('--intake', help='JSON-список доступных каналов приёма владельца')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)

    bundle = Path(args.bundle)
    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} уже существует; каждый прогон пишет новый каталог')

    def read(name):
        doc, _ = reliability_mod._read_json(bundle / name)
        return doc

    load = lambda raw: (json.loads(raw) if raw else None)  # noqa: E731
    try:
        projection = build_projection(
            investments=read('investment_snapshot.json'),
            reliability=read('reliability_snapshot.json'),
            work=read('work_snapshot.json'),
            governance=read('governance_snapshot.json'),
            director=read('director_center.json'),
            actions=read('action_authority_audit.json'),
            bridge=load(args.bridge), intake=load(args.intake))
        validate_projection(projection, 'freshly built')
    except (WebProjectionError, ValueError) as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nПроекция не построена.')

    diff_mod.validate_output(final, [bundle])
    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} остался от прерванного прогона; отодвиньте его')
    staging.mkdir(parents=True, mode=0o700)
    path = staging / 'director_web_projection.json'
    with path.open('x', encoding='utf-8') as handle:
        json.dump(projection, handle, ensure_ascii=False, indent=1, allow_nan=False)
    os.chmod(path, 0o600)
    os.rename(staging, final)

    stats = projection['redaction_stats']
    print(f"Проекция → {final / 'director_web_projection.json'}")
    print(f"  как есть: {stats['SAFE_FOR_PRIVATE_WEB']} · отредактировано: {stats['REDACTED']} "
          f"· только локально: {stats['LOCAL_ONLY']} · заблокировано как UNKNOWN: "
          f"{stats['UNKNOWN_BLOCKED']}")
    print(f"  REAL CAPITAL PROVEN: {projection['layers']['CAPITAL'].get('real_capital_proven')}")
    print(f"  действия включены: {projection['layers']['BUILD']['actions_enabled']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
