#!/usr/bin/env python3
"""Reliability & Problems (Director OS Phase 4) — что сломано, что деградирует, что
повторяется, и чем это доказано.

READ-ONLY и OFFLINE ПО ПОСТРОЕНИЮ. Модуль не импортирует ни ``subprocess``, ни
``socket``, ни ``urllib``: он читает уже существующие артефакты — журналы здоровья в
``data/``, принятые комплекты Cartographer и Authority Map, карточки трекера — и пишет
ровно один производный файл в ``--output``.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО:

* нового хранилища проблем. Снимок — ПРОИЗВОДНЫЙ: он пересобирается из тех же входов и
  ничего не помнит между прогонами. Источник правды остаётся там, где был;
* второго бэклога. Задачи не создаются. Если карточка уже есть — показывается связь; если
  нет — так и сказано, и это не приглашение завести;
* root cause. Ни одно поле его не хранит. ``classification_reason`` называет только то,
  что измерено, и НАЗЫВАЕТ ИСТОЧНИК измерения;
* выдуманной severity, владельца и срока годности. Если источник их не даёт, стоит
  ``UNKNOWN`` / ``None``, а не догадка (инвариант #17: «не измерено» — отдельное
  значение, а не ноль и не успех).

INCIDENT против PROBLEM_CANDIDATE решает ДОКАЗАТЕЛЬСТВО, а не тон записи:

* ``PROBLEM_CANDIDATE`` — есть измеренная повторяемость (>= 2 наблюдений у источника,
  который считает их сам) ИЛИ измеренная длительность (>= 24 ч между первым и последним
  наблюдением при живом состоянии);
* ``INCIDENT`` — конкретный наблюдаемый сбой с отметкой времени, но без доказанной
  повторяемости;
* ``CONDITION`` — устойчивое СОСТОЯНИЕ устройства системы (лишний код в проде, не
  объявленная каноничность, объявлено-но-не-наблюдается), а не событие;
* ``UNKNOWN`` — доказательств не хватает даже на это.

Одно наблюдение никогда не становится проблемой само по себе, и «код умеет искать X» не
основание показать X: запись рождается только из прочитанной улики.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import diff as diff_mod  # noqa: E402  (свой каталог, не сторонний пакет)

SCHEMA = 'cartographer.reliability_snapshot/0.1'

# ── словарь значений ─────────────────────────────────────────────────────────

CLASSIFICATIONS = ('INCIDENT', 'PROBLEM_CANDIDATE', 'CONDITION', 'UNKNOWN')

CLASSIFICATION_DEFINITIONS = {
    'INCIDENT': 'конкретный наблюдаемый сбой или деградация с отметкой времени; '
                'повторяемость НЕ доказана',
    'PROBLEM_CANDIDATE': 'состояние повторяется или держится, и повторяемость/длительность '
                         'ИЗМЕРЕНА источником, а не предположена',
    'CONDITION': 'устойчивое свойство устройства системы, а не событие: лишний код в '
                 'проде, не объявленная каноничность, объявленное но не наблюдаемое',
    'UNKNOWN': 'улик не хватает даже на CONDITION; отсутствие вердикта названо вслух',
}

STATUSES = ('ACTIVE_CONFIRMED', 'ACTIVE_UNVERIFIED', 'RESOLVED', 'UNKNOWN')

STATUS_DEFINITIONS = {
    'ACTIVE_CONFIRMED': 'источник говорит «есть» И сам он свежее собственного объявленного '
                        'срока — состояние подтверждено сейчас',
    'ACTIVE_UNVERIFIED': 'источник запись не отзывал, но подтвердить её «сейчас» нечем: '
                         'источник просрочен либо срок для него не объявлен. Это НЕ '
                         '«закрыто» и НЕ «показалось»',
    'RESOLVED': 'источник ЯВНО сказал, что состояние закрыто. Молчание источника таким '
                'высказыванием не является',
    'UNKNOWN': 'источник сам назвал предмет неизмеренным',
}

# внутренний маркер адаптера: «источник говорит — есть». Чем это станет в снимке,
# решает свежесть источника, а не адаптер.
_ACTIVE = 'ACTIVE'

SEVERITIES = ('CRITICAL', 'WARNING', 'INFO', 'UNKNOWN')

# severity берётся у источника ДОСЛОВНО; карта только приводит написание. Значения, которых
# здесь нет, становятся UNKNOWN — выдумывать уровень запрещено.
SEVERITY_ALIASES = {
    'CRITICAL': 'CRITICAL', 'CRIT': 'CRITICAL', 'ERROR': 'CRITICAL', 'FAIL': 'CRITICAL',
    'WARNING': 'WARNING', 'WARN': 'WARNING', 'DEGRADED': 'WARNING',
    'INFO': 'INFO', 'NOTICE': 'INFO', 'OK': 'INFO',
}

CATEGORIES = ('health', 'fleet', 'cycle', 'delivery', 'drift', 'authority', 'freshness',
              'loop', 'observation')

# Событие против состояния. Тип решает, чем запись МОЖЕТ стать при нехватке улик:
# событие без повторяемости — INCIDENT, состояние без длительности — CONDITION.
EVENT_TYPES = frozenset((
    'health_check_failed', 'watchdog_check_failed', 'agent_unhealthy', 'cycle_check_failed',
    'uptime_check_failed', 'sync_failed', 'loop_finding',
))
STRUCTURAL_TYPES = frozenset((
    'retired_code_in_production', 'local_only_code', 'code_drift', 'authority_undefined',
    'declared_not_observed', 'observed_not_declared', 'stale_artifact',
    'unknown_observation', 'fleet_parity',
))

FRESHNESS_VALUES = ('FRESH', 'STALE', 'UNKNOWN')

FRESHNESS_DEFINITIONS = {
    'FRESH': 'источник моложе срока, ОБЪЯВЛЕННОГО для него репозиторием',
    'STALE': 'источник старше собственного объявленного срока',
    'UNKNOWN': 'срок годности для источника не объявлен нигде — свежесть НЕ измерена; '
               'это не «просрочен» и не «свеж»',
}

REPETITION_MIN = 2          # сколько наблюдений источник обязан ПОСЧИТАТЬ САМ
PERSISTENCE_HOURS = 24.0    # какой измеренный разрыв first→last считаем устойчивостью


class ReliabilityInputError(Exception):
    """Вход не соответствует контракту. Отказ, а не молчаливая догадка."""


# ── контракты источников (ответ на вопрос «чем это вообще можно доказать») ────
#
# basis: observed — прибор смотрел на живую систему; derived — вычислено из других
# артефактов; authoritative — источник сам является правилом.

SOURCE_CONTRACTS = {
    'system_health.json': {
        'measures': 'пятьдесят доменных проверок здоровья системы с устойчивыми id',
        'basis': 'observed', 'has_severity': True, 'has_timestamps': True,
        'has_stable_id': True, 'usable_as_evidence': True,
        'counts_occurrences': False,
        'limit': 'история хранит только счётчики прогона, не судьбу каждой проверки — '
                 'повторяемость по конкретной проверке отсюда НЕ измерима',
    },
    'watchdog_report.json': {
        'measures': 'история прогонов сторожа: у каждого прогона список проверок и статус',
        'basis': 'observed', 'has_severity': True, 'has_timestamps': True,
        'has_stable_id': True, 'usable_as_evidence': True,
        'counts_occurrences': True,
        'limit': 'кольцевой буфер — «первый раз» не старше самого старого прогона в файле',
    },
    'agent_health.json': {
        'measures': 'состояние каждого агента флота и системные замечания',
        'basis': 'observed', 'has_severity': True, 'has_timestamps': True,
        'has_stable_id': True, 'usable_as_evidence': True,
        'counts_occurrences': False,
        'limit': 'один снимок без истории — повторяемость отсюда не измерима',
    },
    'cycle_health.json': {
        'measures': 'здоровье дневного цикла по именованным проверкам',
        'basis': 'observed', 'has_severity': True, 'has_timestamps': True,
        'has_stable_id': True, 'usable_as_evidence': True,
        'counts_occurrences': False,
        'limit': 'один снимок; пороги объявлены внутри самих проверок',
    },
    'uptime_status.json': {
        'measures': 'живость служб и портов',
        'basis': 'observed', 'has_severity': False, 'has_timestamps': True,
        'has_stable_id': True, 'usable_as_evidence': True,
        'counts_occurrences': False,
        'limit': 'severity источник НЕ объявляет — у записей остаётся UNKNOWN',
    },
    'code_sync_status.json': {
        'measures': 'исход последней синхронизации прод-дерева с origin и имена '
                    'отставленного кода',
        'basis': 'observed', 'has_severity': False, 'has_timestamps': True,
        'has_stable_id': False, 'usable_as_evidence': True,
        'counts_occurrences': False,
        'limit': 'severity и длительность не объявлены; файл описывает ПОСЛЕДНИЙ прогон',
    },
    'deployment_drift.json': {
        'measures': 'расхождение прод-дерева с origin по денежному пути и точкам входа',
        'basis': 'observed', 'has_severity': True, 'has_timestamps': True,
        'has_stable_id': False, 'usable_as_evidence': True,
        'counts_occurrences': False,
        'limit': 'называет причины, но не историю',
    },
    'loop_health.json': {
        'measures': 'повторяемость находок петли и судьба заведённых по ним карточек',
        'basis': 'derived', 'has_severity': False, 'has_timestamps': True,
        'has_stable_id': True, 'usable_as_evidence': True,
        'counts_occurrences': True,
        'limit': 'severity не объявлена; «live» источник считает сам',
    },
    'findings_bridge_state.json': {
        'measures': 'находки моста с числом наблюдений, первым появлением и карточкой',
        'basis': 'derived', 'has_severity': True, 'has_timestamps': True,
        'has_stable_id': True, 'usable_as_evidence': True,
        'counts_occurrences': True,
        'limit': 'состояние моста; свежесть файла проверяется отдельно',
    },
    'authority_map.json': {
        'measures': 'где по правилам живёт истина и где живая система с ней расходится',
        # ПРОИЗВОДНЫЙ, пересобираемый снимок. Он ЦИТИРУЕТ авторитетный источник (коммит
        # origin/main), но сам им не является и источником правды называться не вправе:
        # назвать карту authoritative значило бы завести второй SSOT ровно там, где
        # Phase 3 его старательно не заводила. Настоящий авторитет каждой записи едет
        # отдельным полем authoritative_source.
        'basis': 'derived', 'rebuildable_artifact': True,
        'names_authoritative_source_inside': True,
        'has_severity': True, 'has_timestamps': True,
        'has_stable_id': True, 'usable_as_evidence': True,
        'counts_occurrences': False,
        'limit': 'производная карта: пересобирается из git и наблюдения; сколько длится '
                 'расхождение — отсюда не видно',
    },
    'snapshot.json': {
        'measures': 'наблюдение машины Cartographer: находки, свежесть, неизвестность',
        # severity снимок не объявляет НИ У ОДНОЙ находки — замерено, поле пустое у всех;
        # написать здесь True значило бы соврать в той самой таблице, ради которой
        # раздел про источники и существует
        'basis': 'observed', 'has_severity': False, 'has_timestamps': True,
        'has_stable_id': True, 'usable_as_evidence': True,
        'counts_occurrences': False,
        'limit': 'один снимок',
    },
}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _parse_ts(value):
    """Отметка времени или None. Неразобранная строка — именно None, а не «сейчас»."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace('Z', '+00:00')
    try:
        stamp = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def _age_hours(value, now):
    stamp = _parse_ts(value)
    if stamp is None:
        return None
    return round((now - stamp).total_seconds() / 3600.0, 3)


def _severity(raw):
    if raw is None:
        return 'UNKNOWN'
    return SEVERITY_ALIASES.get(str(raw).strip().upper(), 'UNKNOWN')


# Улика копирует КУСОК ЧУЖОГО ФАЙЛА, и в журнале здоровья может оказаться токен. Форма
# секрета вырезается до записи: снимок производный, но он всё равно файл на диске.
_SECRET_SHAPES = (
    (re.compile(r'gh[pousr]_[A-Za-z0-9]{16,}'), 'github-token'),
    (re.compile(r'github_pat_[A-Za-z0-9_]{20,}'), 'github-pat'),
    (re.compile(r'sk-[A-Za-z0-9]{20,}'), 'api-key'),
    (re.compile(r'AKIA[0-9A-Z]{12,}'), 'aws-key'),
    (re.compile(r'(?i)bearer\s+[A-Za-z0-9._\-]{16,}'), 'bearer-token'),
    (re.compile(r'(?i)\b(?:token|secret|password|passwd|api[_-]?key)\b\s*[=:]\s*'
                r'["\']?[A-Za-z0-9._\-]{8,}'), 'named-credential'),
)


def redact(text):
    """Строка без форм секретов. Вырезано ВИДНО: молчаливая правка хуже пометки."""
    out = str(text)
    for pattern, label in _SECRET_SHAPES:
        out = pattern.sub(f'[ВЫРЕЗАНО:{label}]', out)
    return out


def _evidence(kind, detail, where=None):
    return {'kind': kind, 'detail': redact(str(detail)[:600]), 'where': where}


def declared_slo_hours(production):
    """Сроки годности артефактов, ОБЪЯВЛЕННЫЕ самим репозиторием.

    Источник правила — `architecture/manifest.json`: у каждого артефакта там назван
    производитель и `slo_hours`. Это и есть единственный законный ответ на вопрос «когда
    этот файл считается протухшим»; выдумывать собственный универсальный порог запрещено —
    ровно так появляется «свежесть», которую никто не объявлял.

    Возвращает {путь: (часы, чем объявлено)}. Чего в манифесте нет — того нет и здесь.
    """
    manifest, state = _read_json(Path(production) / 'architecture/manifest.json')
    if state != 'READ' or not isinstance(manifest, dict):
        return {}, state
    out = {}
    for art in manifest.get('artifacts') or []:
        if isinstance(art, dict) and art.get('path') and art.get('slo_hours') is not None:
            out[art['path']] = (float(art['slo_hours']),
                                f"architecture/manifest.json: artifacts[{art['path']}]."
                                f"slo_hours={art['slo_hours']}, производитель "
                                f"{art.get('producer')}")
    for agent in manifest.get('agents') or []:
        for produced in (agent.get('produces') or []):
            if not isinstance(produced, dict):
                continue
            path, slo = produced.get('artifact'), produced.get('slo_hours')
            if path and slo is not None and path not in out:
                out[path] = (float(slo),
                             f"architecture/manifest.json: {agent.get('label')} produces "
                             f"{path} со slo_hours={slo}")
    return out, 'READ'


def _freshness(source_name, generated_at, slo_map, now):
    """(вердикт, правило, объявленный срок). Третий исход — полноправный.

    Не объявлен срок ⇒ UNKNOWN, и это НЕ «протух»: объявить протухшим по собственному
    усмотрению значило бы придумать SLA за того, кто его не давал.
    """
    key = f'data/{source_name}'
    declared = slo_map.get(key)
    age = _age_hours(generated_at, now)
    if declared is None:
        return 'UNKNOWN', (f'срок годности для {key} не объявлен ни в artifacts, ни в '
                           'produces манифеста — свежесть НЕ измерена'), None
    if age is None:
        return 'UNKNOWN', (f'{declared[1]}; но собственной отметки времени у источника '
                           'прочитать не удалось — свежесть НЕ измерена'), declared[0]
    verdict = 'FRESH' if age <= declared[0] else 'STALE'
    # Само ЧИСЛО возраста в правило не вписывается намеренно: оно функция часов, и, попав
    # в текст, оно утекало бы в semantic_digest — два прогона на одних и тех же файлах
    # расходились бы просто оттого, что между ними прошло семь минут. Возраст живёт
    # отдельным полем age_hours, вердикт — здесь.
    return verdict, (f'{declared[1]}; на момент наблюдения источник '
                     f'{"моложе" if verdict == "FRESH" else "СТАРШЕ"} этого срока'), \
        declared[0]


def _read_json(path):
    """(данные, состояние источника). Нечитаемое НЕ выдаётся за пустое."""
    p = Path(path)
    if not p.is_file():
        return None, 'ABSENT'
    try:
        return json.loads(p.read_text(encoding='utf-8')), 'READ'
    except (OSError, ValueError):
        return None, 'UNREADABLE'


# ── одна запись ──────────────────────────────────────────────────────────────

def _finding(finding_id, finding_type, affected_entity, title, *, status, severity,
             source, source_status, category, evidence, first_seen=None, last_seen=None,
             occurrence_count=None, occurrence_basis=None, observed_at=None,
             as_of=None, authoritative_source=None):
    """Запись находки. Все поля объявлены явно, включая незаполненные.

    ``occurrence_basis`` обязателен, когда счёт ЕСТЬ: число без названного прибора — это
    мнение. Когда счёта нет, обязан остаться ``None``, а не ноль: ноль означал бы
    «наблюдений не было», а мы просто не считали.
    """
    if occurrence_count is not None and not occurrence_basis:
        raise ReliabilityInputError(
            f'{finding_id}: occurrence_count={occurrence_count} без occurrence_basis — '
            'число без названного прибора не является измерением')
    return {
        'finding_id': finding_id,
        'finding_type': finding_type,
        'affected_entity': affected_entity,
        'title': redact(title),
        'status': status,
        'severity': severity,
        'first_seen': first_seen,
        'last_seen': last_seen,
        'source': source,
        'source_status': source_status,
        'evidence': list(evidence),
        'category': category,
        'occurrence_count': occurrence_count,
        'occurrence_basis': occurrence_basis,
        'observed_at': observed_at,
        # когда ИСТОЧНИК в последний раз говорил, и сколько с тех пор прошло: без этого
        # «ACTIVE» читается как «сейчас», хотя источник мог замолчать недели назад
        'as_of': as_of if as_of is not None else (last_seen or observed_at),
        'source_age_hours': None,
        'sources': [source],
        # где живёт НАСТОЯЩИЙ авторитет по этому предмету, если производный источник его
        # назвал. Сам производный снимок авторитетом не становится ни при каких условиях.
        'authoritative_source': authoritative_source,
        'freshness': None,
        'freshness_rule': None,
        'merged_ids': [],
        'corroborated_by': [],
        'linked_tasks': [],
        # заполняется классификатором, чтобы вердикт нельзя было принести из адаптера
        'classification': None,
        'classification_reason': None,
    }


def classify(finding):
    """(классификация, причина). Чистая функция улик — без догадок и без root cause.

    Порядок намеренный: измеренная повторяемость сильнее измеренной длительности, та —
    сильнее отдельного события, а состояние устройства системы вообще не событие.
    """
    n = finding.get('occurrence_count')
    basis = finding.get('occurrence_basis')
    status = finding.get('status')
    ftype = finding.get('finding_type')

    if status == 'RESOLVED':
        return 'CONDITION' if ftype in STRUCTURAL_TYPES else 'INCIDENT', (
            'источник ЯВНО назвал состояние закрытым; запись оставлена как история. '
            'Молчание источника таким высказыванием не является и сюда не попадает')

    if n is not None and n >= REPETITION_MIN:
        return 'PROBLEM_CANDIDATE', (
            f'повторяемость ИЗМЕРЕНА: {n} наблюдений, прибор — {basis}. '
            f'Порог {REPETITION_MIN}. Причина не устанавливается.')

    first, last = _parse_ts(finding.get('first_seen')), _parse_ts(finding.get('last_seen'))
    if first and last:
        held = (last - first).total_seconds() / 3600.0
        if held >= PERSISTENCE_HOURS and str(status).startswith('ACTIVE'):
            return 'PROBLEM_CANDIDATE', (
                f'длительность ИЗМЕРЕНА: состояние держится {held:.1f} ч '
                f'({finding["first_seen"]} → {finding["last_seen"]}), порог '
                f'{PERSISTENCE_HOURS:.0f} ч. Причина не устанавливается.')

    if ftype in STRUCTURAL_TYPES:
        return 'CONDITION', (
            'свойство устройства системы, а не событие; ни повторяемость, ни длительность '
            'ни одним доступным источником не измерены')

    if ftype in EVENT_TYPES and (finding.get('last_seen') or finding.get('observed_at')):
        return 'INCIDENT', (
            'единичное наблюдение с отметкой времени; повторяемость НЕ измерена — '
            'это не значит, что её нет')

    return 'UNKNOWN', ('улик не хватает ни на событие, ни на состояние: у записи нет ни '
                       'отметки времени, ни счёта наблюдений')


def _classified(findings):
    for f in findings:
        verdict, reason = classify(f)
        f['classification'] = verdict
        f['classification_reason'] = reason
    return findings


# ── адаптеры источников ──────────────────────────────────────────────────────
#
# Каждый возвращает (findings, source_record). Отсутствующий или нечитаемый источник даёт
# ПУСТОЙ список и запись с состоянием — ни одной выдуманной находки.

def _source_record(name, path, status, *, generated_at=None, now=None, note='',
                   slo_map=None):
    contract = SOURCE_CONTRACTS.get(name, {})
    fresh, rule, declared = _freshness(name, generated_at, slo_map or {}, now or _now())
    return {
        'source': name,
        'path': str(path),
        'status': status,
        'generated_at': generated_at,
        'age_hours': _age_hours(generated_at, now) if (generated_at and now) else None,
        'freshness': fresh,
        'freshness_rule': rule,
        'declared_slo_hours': declared,
        'measures': contract.get('measures'),
        'basis': contract.get('basis'),
        'rebuildable_artifact': contract.get('rebuildable_artifact', False),
        'names_authoritative_source_inside':
            contract.get('names_authoritative_source_inside', False),
        'has_severity': contract.get('has_severity'),
        'has_timestamps': contract.get('has_timestamps'),
        'has_stable_id': contract.get('has_stable_id'),
        'counts_occurrences': contract.get('counts_occurrences'),
        'usable_as_evidence': contract.get('usable_as_evidence'),
        'limit': contract.get('limit'),
        'note': note,
    }


def from_system_health(data_dir, now, slo_map=None):
    name = 'system_health.json'
    path = Path(data_dir) / name
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, dict):
        return [], _source_record(name, path, state, now=now, slo_map=slo_map)
    gen = doc.get('generated_at')
    rec = _source_record(name, path, 'READ', generated_at=gen, now=now, slo_map=slo_map)
    out = []
    for check in doc.get('checks') or []:
        if not isinstance(check, dict):
            continue
        st = str(check.get('status', '')).upper()
        if st in ('OK', 'SKIPPED', ''):
            continue
        cid = check.get('id') or 'unnamed'
        ev = [_evidence('check', f"{cid}: {check.get('title')}", name)]
        if check.get('evidence'):
            ev.append(_evidence('source_evidence',
                                json.dumps(check['evidence'], ensure_ascii=False), name))
        if check.get('error'):
            ev.append(_evidence('error', check['error'], name))
        out.append(_finding(
            f'health:{cid}', 'health_check_failed', cid, str(check.get('title') or cid),
            status=_ACTIVE, severity=_severity(st), source=name, source_status='READ',
            category='health', evidence=ev, last_seen=gen, observed_at=gen))
    return out, rec


def from_watchdog(data_dir, now, slo_map=None):
    """Единственный источник, который СЧИТАЕТ повторения сам: история прогонов.

    Повторение здесь — «сколько прогонов подряд видели эту проверку не-OK», и окно
    ограничено кольцевым буфером: «первый раз» не может быть старше самого старого
    прогона в файле, и это сказано в улике, чтобы число не читалось как абсолютное.
    """
    name = 'watchdog_report.json'
    path = Path(data_dir) / name
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, list) or not doc:
        return [], _source_record(name, path, state if state != 'READ' else 'EMPTY', now=now,
                                 slo_map=slo_map)
    runs = [r for r in doc if isinstance(r, dict)]
    last_run = runs[-1]
    rec = _source_record(name, path, 'READ', generated_at=last_run.get('checked_at'),
                         now=now, note=f'{len(runs)} прогонов в окне', slo_map=slo_map)
    window_start = runs[0].get('checked_at')

    history = {}
    for run in runs:
        stamp = run.get('checked_at')
        for check in run.get('checks') or []:
            if not isinstance(check, dict):
                continue
            st = str(check.get('status', '')).upper()
            if st in ('OK', ''):
                continue
            key = check.get('check') or 'unnamed'
            h = history.setdefault(key, {'count': 0, 'first': None, 'last': None,
                                         'severity': st, 'message': check.get('message')})
            h['count'] += 1
            h['first'] = h['first'] or stamp
            h['last'] = stamp
            h['severity'] = st
            h['message'] = check.get('message')

    active = {str(c.get('check')) for c in (last_run.get('checks') or [])
              if isinstance(c, dict) and str(c.get('status', '')).upper() not in ('OK', '')}
    out = []
    for key, h in sorted(history.items()):
        ev = [_evidence('history', f"не-OK в {h['count']} из {len(runs)} прогонов окна",
                        name),
              _evidence('window', f'окно начинается {window_start} — «первый раз» не '
                                  f'может быть старше этой отметки', name)]
        if h['message']:
            ev.append(_evidence('message', h['message'], name))
        out.append(_finding(
            f'watchdog:{key}', 'watchdog_check_failed', key,
            str(h['message'] or key), status=_ACTIVE if key in active else 'RESOLVED',
            severity=_severity(h['severity']), source=name, source_status='READ',
            category='health', evidence=ev, first_seen=h['first'], last_seen=h['last'],
            occurrence_count=h['count'],
            occurrence_basis=f'{name}: подсчёт не-OK по {len(runs)} прогонам окна',
            observed_at=last_run.get('checked_at')))
    return out, rec


def from_agent_health(data_dir, now, slo_map=None):
    name = 'agent_health.json'
    path = Path(data_dir) / name
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, dict):
        return [], _source_record(name, path, state, now=now, slo_map=slo_map)
    gen = doc.get('timestamp')
    rec = _source_record(name, path, 'READ', generated_at=gen, now=now, slo_map=slo_map)
    out = []
    for agent in doc.get('agents') or []:
        if not isinstance(agent, dict):
            continue
        st = str(agent.get('status', '')).upper()
        if st in ('OK', ''):
            continue
        label = agent.get('label') or 'unnamed'
        ev = [_evidence('agent', f"статус {st}, выход {agent.get('last_exit')}, "
                                 f"возраст журнала {agent.get('log_age_min')} мин", name)]
        if agent.get('issue'):
            ev.append(_evidence('issue', agent['issue'], name))
        out.append(_finding(
            f'agent:{label}', 'agent_unhealthy', label,
            str(agent.get('issue') or f'агент в состоянии {st}'),
            status=_ACTIVE, severity=_severity(st), source=name, source_status='READ',
            category='fleet', evidence=ev, last_seen=gen, observed_at=gen))
    for i, issue in enumerate(doc.get('system_issues') or []):
        out.append(_finding(
            f'fleet:{i}', 'fleet_parity', 'флот launchd', str(issue)[:200],
            status=_ACTIVE, severity='UNKNOWN', source=name, source_status='READ',
            category='fleet', evidence=[_evidence('system_issue', issue, name)],
            last_seen=gen, observed_at=gen))
    return out, rec


def from_cycle_health(data_dir, now, slo_map=None):
    name = 'cycle_health.json'
    path = Path(data_dir) / name
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, dict):
        return [], _source_record(name, path, state, now=now, slo_map=slo_map)
    gen = doc.get('checked_at')
    rec = _source_record(name, path, 'READ', generated_at=gen, now=now, slo_map=slo_map)
    out = []
    checks = doc.get('checks')
    items = checks.items() if isinstance(checks, dict) else ()
    for key, body in items:
        if not isinstance(body, dict):
            continue
        st = str(body.get('status', '')).upper()
        if st in ('OK', ''):
            continue
        out.append(_finding(
            f'cycle:{key}', 'cycle_check_failed', key, f'проверка цикла {key}: {st}',
            status=_ACTIVE, severity=_severity(st), source=name, source_status='READ',
            category='cycle',
            evidence=[_evidence('check', json.dumps(body, ensure_ascii=False), name)],
            last_seen=gen, observed_at=gen))
    for key in doc.get('unchecked') or []:
        out.append(_finding(
            f'cycle-unchecked:{key}', 'unknown_observation', str(key),
            f'проверка цикла {key} НЕ измерена',
            status='UNKNOWN', severity='UNKNOWN', source=name, source_status='READ',
            category='observation',
            evidence=[_evidence('unchecked', f'{key} назван источником как не измеренный',
                                name)],
            last_seen=gen, observed_at=gen))
    return out, rec


def from_uptime(data_dir, now, slo_map=None):
    name = 'uptime_status.json'
    path = Path(data_dir) / name
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, dict):
        return [], _source_record(name, path, state, now=now, slo_map=slo_map)
    ts = doc.get('ts')
    gen = (dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()
           if isinstance(ts, (int, float)) else None)
    rec = _source_record(name, path, 'READ', generated_at=gen, now=now, slo_map=slo_map)
    out = []
    checks = doc.get('checks')
    items = checks.items() if isinstance(checks, dict) else ()
    for key, body in items:
        if not isinstance(body, dict):
            continue
        if body.get('running') and not body.get('error'):
            continue
        ev = [_evidence('probe', json.dumps(body, ensure_ascii=False), name)]
        out.append(_finding(
            f'uptime:{key}', 'uptime_check_failed', key,
            str(body.get('error') or f'{key}: служба не отвечает'),
            # severity источник не объявляет — и мы её не придумываем
            status=_ACTIVE, severity='UNKNOWN', source=name, source_status='READ',
            category='fleet', evidence=ev, last_seen=gen, observed_at=gen))
    return out, rec


def from_code_sync(data_dir, now, slo_map=None):
    name = 'code_sync_status.json'
    path = Path(data_dir) / name
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, dict):
        return [], _source_record(name, path, state, now=now, slo_map=slo_map)
    gen = doc.get('timestamp')
    rec = _source_record(name, path, 'READ', generated_at=gen, now=now, slo_map=slo_map)
    out = []
    result = str(doc.get('result', '')).upper()
    if result and result != 'SYNCED':
        out.append(_finding(
            'sync:last_run', 'sync_failed', 'code_sync_from_origin',
            f"последняя синхронизация: {result} — {doc.get('detail')}",
            status=_ACTIVE, severity='UNKNOWN', source=name, source_status='READ',
            category='delivery',
            evidence=[_evidence('result', json.dumps(
                {k: doc.get(k) for k in ('result', 'detail', 'origin_main')},
                ensure_ascii=False), name)],
            last_seen=gen, observed_at=gen))
    for kind, key, ftype, title in (
            ('retired_code', 'retired', 'retired_code_in_production',
             'код отставлен на origin, но остаётся в прод-дереве'),
            ('retired_instructions', 'retired-rules', 'retired_code_in_production',
             'правило отставлено на origin, но остаётся в прод-дереве')):
        for p in doc.get(kind) or []:
            out.append(_finding(
                f'{key}:{p}', ftype, str(p), title,
                status=_ACTIVE, severity='UNKNOWN', source=name, source_status='READ',
                category='delivery',
                evidence=[_evidence(
                    kind, 'checkout не удаляет: файл, удалённый на origin, остаётся здесь '
                          'и назван синхронизацией', name),
                    _evidence('authoritative_commit', str(doc.get('origin_main')), name)],
                last_seen=gen, observed_at=gen))
    return out, rec


def from_deployment_drift(data_dir, now, slo_map=None):
    name = 'deployment_drift.json'
    path = Path(data_dir) / name
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, dict):
        return [], _source_record(name, path, state, now=now, slo_map=slo_map)
    gen = doc.get('checked_at')
    rec = _source_record(name, path, 'READ', generated_at=gen, now=now, slo_map=slo_map)
    st = str(doc.get('status', '')).upper()
    if st in ('OK', 'IN_SYNC', ''):
        return [], rec
    ev = [_evidence('reason', r, name) for r in (doc.get('reasons') or [])]
    ev.append(_evidence('position', f"отстаёт на {doc.get('commits_behind')} коммит(ов), "
                                    f"опережает на {doc.get('commits_ahead')}", name))
    return [_finding(
        'deployment:drift', 'code_drift', 'прод-дерево против origin',
        f'дерево, из которого работает флот, расходится с origin: {st}',
        status=_ACTIVE, severity=_severity(st), source=name, source_status='READ',
        category='drift', evidence=ev, last_seen=gen, observed_at=gen)], rec


def from_loop_health(data_dir, now, slo_map=None):
    name = 'loop_health.json'
    path = Path(data_dir) / name
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, dict):
        return [], _source_record(name, path, state, now=now, slo_map=slo_map)
    gen = doc.get('generated_at')
    rec = _source_record(name, path, 'READ', generated_at=gen, now=now, slo_map=slo_map)
    out = []
    for item in doc.get('recurring_findings') or []:
        if not isinstance(item, dict):
            continue
        key = item.get('key') or 'unnamed'
        n = item.get('recurrences')
        live = item.get('live')
        ev = [_evidence('recurrences', f"источник насчитал {n} повторений", name),
              _evidence('liveness', f"live={live}, статус карточки {item.get('status')}",
                        name)]
        out.append(_finding(
            f'loop:{key}', 'loop_finding', key, f'повторяющаяся находка петли: {key}',
            status=_ACTIVE if live else 'RESOLVED', severity='UNKNOWN', source=name,
            source_status='READ', category='loop', evidence=ev,
            last_seen=item.get('last_seen'),
            occurrence_count=(n if isinstance(n, int) and n > 0 else None),
            occurrence_basis=(f'{name}: поле recurrences' if isinstance(n, int) and n > 0
                              else None),
            observed_at=gen))
    return out, rec


def from_findings_bridge(data_dir, now, slo_map=None):
    name = 'findings_bridge_state.json'
    path = Path(data_dir) / name
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, dict):
        return [], _source_record(name, path, state, now=now, slo_map=slo_map)
    gen = doc.get('generated_at')
    rec = _source_record(name, path, 'READ', generated_at=gen, now=now, slo_map=slo_map)
    out = []
    findings = doc.get('findings')
    items = findings.items() if isinstance(findings, dict) else ()
    for key, body in items:
        if not isinstance(body, dict):
            continue
        seen = body.get('seen_count')
        status = str(body.get('status', '')).lower()
        ev = [_evidence('seen_count', f"источник насчитал {seen} наблюдений", name)]
        if body.get('closed_at'):
            ev.append(_evidence('closed_at', body['closed_at'], name))
        f = _finding(
            f'bridge:{key}', 'loop_finding', key, f'находка моста: {key}',
            status='RESOLVED' if status == 'closed' else _ACTIVE,
            severity=_severity(body.get('severity')), source=name, source_status='READ',
            category='loop', evidence=ev, first_seen=body.get('first_seen'),
            last_seen=body.get('last_seen'),
            occurrence_count=(seen if isinstance(seen, int) and seen > 0 else None),
            occurrence_basis=(f'{name}: поле seen_count' if isinstance(seen, int)
                              and seen > 0 else None),
            observed_at=gen)
        card = body.get('card')
        if card:
            f['linked_tasks'].append({
                'task': str(card), 'relation': 'EXPLICIT_LINK',
                'basis': 'источник назвал карточку полем card',
                'source': name})
        out.append(f)
    return out, rec


# статус расхождения из Authority Map → тип записи здесь. Словарь Phase 3 не
# переименовывается: он принят, и перевод существует только ради классификации.
DRIFT_TO_TYPE = {
    'EXTRA_IN_PRODUCTION': 'retired_code_in_production',
    'MISSING_IN_ORIGIN': 'local_only_code',
    'MODIFIED': 'code_drift',
    'MISSING_IN_PRODUCTION': 'code_drift',
    'AUTHORITY_UNDEFINED': 'authority_undefined',
    'DECLARED_NOT_OBSERVED': 'declared_not_observed',
    'OBSERVED_NOT_DECLARED': 'observed_not_declared',
    'STALE': 'stale_artifact',
    'UNKNOWN': 'unknown_observation',
}
DRIFT_CATEGORY = {
    'authority_undefined': 'authority', 'stale_artifact': 'freshness',
    'unknown_observation': 'observation',
}


def from_authority_map(the_map, now, where='authority_map.json', slo_map=None):
    name = 'authority_map.json'
    if not isinstance(the_map, dict):
        return [], _source_record(name, where, 'ABSENT', now=now, slo_map=slo_map)
    gen = the_map.get('observed_at') or the_map.get('generated_at')
    rec = _source_record(name, where, 'READ', generated_at=gen, now=now,
                         note=f"авторитетный коммит "
                              f"{str(the_map.get('authoritative_commit'))[:12]}",
                         slo_map=slo_map)
    out = []
    for e in the_map.get('entities') or []:
        if not isinstance(e, dict):
            continue
        ftype = DRIFT_TO_TYPE.get(e.get('drift_status'))
        if not ftype:
            continue
        path = e.get('path') or e.get('entity_id') or 'unnamed'
        ev = [_evidence('drift_status', f"{e.get('drift_status')}: "
                                        f"{e.get('severity_basis')}", name)]
        for x in e.get('evidence') or []:
            if isinstance(x, dict):
                ev.append(_evidence(x.get('kind', 'evidence'), x.get('detail', ''), name))
        out.append(_finding(
            f"authority:{e.get('entity_id')}", ftype, str(path),
            f"{e.get('drift_status')} — {e.get('entity_type')}",
            authoritative_source=e.get('authoritative_source'),
            status=_ACTIVE, severity=_severity(e.get('severity')), source=name,
            source_status='READ',
            category=DRIFT_CATEGORY.get(ftype, 'drift'), evidence=ev,
            last_seen=e.get('observed_at') or gen, observed_at=e.get('observed_at') or gen))
    return out, rec


# находки наблюдения машины, которые говорят о надёжности. Остальные коды Cartographer
# сюда не переносятся: раздел не пересказывает снимок, он берёт из него улики.
SNAPSHOT_CODES = {
    'STATUS_STALE': ('stale_artifact', 'freshness'),
    'STATUS_DEGRADED': ('agent_unhealthy', 'fleet'),
    'HEALTH_UNMEASURED': ('unknown_observation', 'observation'),
    'STATUS_UNCLASSIFIABLE': ('unknown_observation', 'observation'),
    'EXIT_SEMANTICS_NOT_APPLIED': ('unknown_observation', 'observation'),
    'ENABLE_OVERRIDE_WITHOUT_SERVICE': ('declared_not_observed', 'fleet'),
    'WRAPPER_TARGET_UNDECLARED': ('declared_not_observed', 'fleet'),
}


def from_snapshot(snapshot, now, where='snapshot.json', slo_map=None):
    name = 'snapshot.json'
    if not isinstance(snapshot, dict):
        return [], _source_record(name, where, 'ABSENT', now=now, slo_map=slo_map)
    gen = snapshot.get('finished_at') or snapshot.get('started_at')
    rec = _source_record(name, where, 'READ', generated_at=gen, now=now, slo_map=slo_map)
    out = []
    for f in snapshot.get('findings') or []:
        if not isinstance(f, dict):
            continue
        mapped = SNAPSHOT_CODES.get(f.get('rule_code'))
        if not mapped:
            continue
        ftype, category = mapped
        out.append(_finding(
            f"observation:{f.get('id')}", ftype, str(f.get('subject') or 'unnamed'),
            str(f.get('reason') or f.get('rule_code')),
            # снимок severity не объявляет ни у одной находки — проверено, поле пустое
            status=_ACTIVE, severity=_severity(f.get('severity')), source=name,
            source_status='READ', category=category,
            evidence=[_evidence('rule_code', f"{f.get('rule_code')} · {f.get('context')}",
                                name)],
            last_seen=gen, observed_at=gen))
    return out, rec


# ── связь с существующими карточками (ничего не создаём) ─────────────────────

_TRACKER_GLOB = 'nimbalyst-local/tracker/*.md'


def link_tasks(findings, production, limit_per_finding=3):
    """Показать УЖЕ СУЩЕСТВУЮЩУЮ карточку, если улика на связь есть. Не заводить новую.

    Рода улики ДВА, и они не сливаются в одно слово «связана»:

    * ``EXPLICIT_LINK`` — источник САМ назвал карточку (поле ``card``). Утверждение о
      связи сделал тот, кто её знает;
    * ``MENTION_MATCH`` — объект находки дословно встречается в тексте карточки, но связь
      никто не объявлял. Это совпадение имени, а не заявленное отношение.

    Догадок по смыслу нет: совпадение по теме без общего имени связью здесь не считается,
    а упоминание НИКОГДА не повышается до объявленной связи.
    """
    cards = sorted(Path(production).glob(_TRACKER_GLOB))
    texts = {}
    for c in cards:
        try:
            texts[c] = c.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
    linked = 0
    for f in findings:
        # у уже объявленной связи род не переписывается совпадением имени
        entity = str(f.get('affected_entity') or '')
        # достаточно отличимый токен: путь или метка launchd, иначе совпадение будет шумом
        if not (('/' in entity and len(entity) > 8) or entity.startswith('com.spa.')):
            continue
        already = {t['task'] for t in f['linked_tasks']}
        hits = 0
        for path, text in texts.items():
            if hits >= limit_per_finding:
                break
            rel = str(path.relative_to(production))
            if rel in already:
                continue
            if entity in text:
                f['linked_tasks'].append({
                    'task': rel,
                    'relation': 'MENTION_MATCH',
                    'basis': f'объект «{entity}» встречается в тексте карточки дословно; '
                             'связь источником НЕ объявлена',
                    'source': 'nimbalyst-local/tracker'})
                hits += 1
                linked += 1
    return {'cards_scanned': len(texts), 'mention_matches_added': linked,
            'relation_kinds': {
                'EXPLICIT_LINK': 'источник сам назвал карточку',
                'MENTION_MATCH': 'объект дословно встречается в тексте карточки; связь '
                                 'не объявлена'},
            'never_promotes_mention_to_link': True}


def merge_corroborating(findings):
    """Один предмет — одна запись, даже если о нём говорят два источника.

    Подтверждение (corroboration) и повторение (repetition) — РАЗНЫЕ вещи, и смешать их
    значило бы сфабриковать проблему из простого дублирования: то, что об одном и том же
    отставленном файле говорят и синхронизация, и карта авторитетности, не есть два
    наблюдения во времени. Поэтому счёт наблюдений здесь берётся МАКСИМАЛЬНЫЙ из
    источников, а не сумма, и подтверждение записывается отдельным полем.
    """
    groups = {}
    for f in findings:
        groups.setdefault((f['finding_type'], f['affected_entity']), []).append(f)
    out = []
    rank = {'CRITICAL': 3, 'WARNING': 2, 'INFO': 1, 'UNKNOWN': 0}
    for key, group in groups.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        group.sort(key=lambda f: (-rank.get(f['severity'], 0), f['finding_id']))
        base = group[0]
        others = group[1:]
        base['merged_ids'] = sorted(f['finding_id'] for f in others)
        base['sources'] = sorted({f['source'] for f in group})
        base['corroborated_by'] = sorted({f['source'] for f in others})
        for f in others:
            base['evidence'].extend(f['evidence'])
            base['linked_tasks'].extend(t for t in f['linked_tasks']
                                        if t not in base['linked_tasks'])
        stamps = [_parse_ts(f['first_seen']) for f in group if _parse_ts(f['first_seen'])]
        if stamps:
            base['first_seen'] = min(stamps).isoformat()
        lasts = [_parse_ts(f['last_seen']) for f in group if _parse_ts(f['last_seen'])]
        if lasts:
            base['last_seen'] = max(lasts).isoformat()
        # авторитет по предмету мог назвать ЛЮБОЙ из источников — при слиянии он не
        # теряется оттого, что базой стала запись от другого
        if base['authoritative_source'] is None:
            named = [f['authoritative_source'] for f in group
                     if f['authoritative_source']]
            base['authoritative_source'] = named[0] if named else None
        counted = [f for f in group if f['occurrence_count'] is not None]
        if counted:
            best = max(counted, key=lambda f: f['occurrence_count'])
            base['occurrence_count'] = best['occurrence_count']
            base['occurrence_basis'] = best['occurrence_basis']
        base['evidence'].append(_evidence(
            'corroboration',
            'об этом же предмете говорят источники: ' + ', '.join(base['sources'])
            + '. Подтверждение НЕ является повторением — счёт наблюдений взят '
              'максимальный из источников, а не сумма.',
            'reliability'))
        out.append(base)
    return out


# ── сборка снимка ────────────────────────────────────────────────────────────

DATA_ADAPTERS = (from_system_health, from_watchdog, from_agent_health, from_cycle_health,
                 from_uptime, from_code_sync, from_deployment_drift, from_loop_health,
                 from_findings_bridge)

LIMITS = (
    'Снимок ПРОИЗВОДНЫЙ: он пересобирается из тех же входов и ничего не помнит между '
    'прогонами. Источником правды ни для одной записи он не является.',
    'Повторяемость видна только там, где её считает САМ источник. У снимка без истории '
    'occurrence_count остаётся null — это «не считали», а не «повторений не было».',
    'Длительность состояния измеряется только по отметкам источника. Для отставленного '
    'кода ни один доступный источник даты не даёт, поэтому такие записи остаются '
    'CONDITION, а не PROBLEM_CANDIDATE.',
    'Причина (root cause) не устанавливается нигде и ни для одной записи.',
    'Severity берётся у источника дословно. Источник без severity даёт UNKNOWN, и это не '
    'то же самое, что INFO.',
    'Связь с карточкой — улика, а не решение. Задачи не создаются; «нет связанной задачи» '
    'означает только отсутствие найденной улики связи.',
    'Подтверждение «сейчас» требует, чтобы САМ источник был моложе срока, объявленного '
    'ему в architecture/manifest.json. Где срок не объявлен, свежесть остаётся UNKNOWN, '
    'и запись идёт в ACTIVE_UNVERIFIED: она не скрыта, но и не выдана за подтверждённую. '
    'Собственного порога свежести этот слой не изобретает.',
    'Связь с карточкой бывает двух родов: объявленная источником (EXPLICIT_LINK) и '
    'совпадение имени в тексте (MENTION_MATCH). Второе никогда не повышается до первого.',
    'Карта авторитетности — ПРОИЗВОДНЫЙ пересобираемый снимок, а не источник правды. '
    'Настоящий авторитет записи едет отдельным полем authoritative_source.',
    'Окно watchdog ограничено кольцевым буфером: «первый раз» не может быть старше самого '
    'старого прогона в файле.',
)


def build_reliability_snapshot(production, cartographer_set=None, authority_path=None,
                               now=None):
    now = now or _now()
    production = Path(production)
    data_dir = production / 'data'

    slo_map, slo_state = declared_slo_hours(production)

    findings, sources = [], []
    for adapter in DATA_ADAPTERS:
        got, rec = adapter(data_dir, now, slo_map)
        findings.extend(got)
        sources.append(rec)

    if cartographer_set:
        p = Path(cartographer_set)
        p = p if p.is_file() else p / 'snapshot.json'
        doc, state = _read_json(p)
        if state == 'READ':
            got, rec = from_snapshot(doc, now, where=str(p), slo_map=slo_map)
            findings.extend(got)
        else:
            rec = _source_record('snapshot.json', p, state, now=now, slo_map=slo_map)
        sources.append(rec)
    else:
        sources.append(_source_record('snapshot.json', '—', 'NOT_GIVEN', now=now,
                                      note='комплект Cartographer не передан',
                                      slo_map=slo_map))

    if authority_path:
        p = Path(authority_path)
        p = p if p.is_file() else p / 'authority_map.json'
        doc, state = _read_json(p)
        if state == 'READ':
            got, rec = from_authority_map(doc, now, where=str(p), slo_map=slo_map)
            findings.extend(got)
        else:
            rec = _source_record('authority_map.json', p, state, now=now, slo_map=slo_map)
        sources.append(rec)
    else:
        sources.append(_source_record('authority_map.json', '—', 'NOT_GIVEN', now=now,
                                      note='карта авторитетности не передана',
                                      slo_map=slo_map))

    findings = merge_corroborating(findings)
    fresh_by_source = {s['source']: (s['freshness'], s['freshness_rule']) for s in sources}
    for f in findings:
        # Возраст источника СЧИТАЕТСЯ, но в смысл снимка не входит: он функция часов, а не
        # входов. Показывает его страница; иначе два прогона на одних и тех же файлах
        # давали бы разный digest просто оттого, что между ними прошло семь минут.
        f['source_age_hours'] = _age_hours(f['as_of'], now)
        # Свежесть записи — свежесть САМОГО СВЕЖЕГО из говорящих о ней источников.
        ranked = [fresh_by_source.get(name, ('UNKNOWN', 'источник не прочитан'))
                  for name in f['sources']]
        order = {'FRESH': 0, 'UNKNOWN': 1, 'STALE': 2}
        f['freshness'], f['freshness_rule'] = min(
            ranked, key=lambda pair: order.get(pair[0], 1))
        if f['status'] == _ACTIVE:
            # Вот здесь и проходит граница, из-за которой раздел переписан: «источник не
            # отзывал» и «подтверждено сейчас» — РАЗНЫЕ утверждения, и второе требует,
            # чтобы сам источник был моложе объявленного ему срока.
            f['status'] = ('ACTIVE_CONFIRMED' if f['freshness'] == 'FRESH'
                           else 'ACTIVE_UNVERIFIED')
    linking = link_tasks(findings, production)
    _classified(findings)
    findings.sort(key=lambda f: (f['finding_id'],))

    by = lambda key: {k: sum(1 for f in findings if f[key] == k)  # noqa: E731
                      for k in sorted({f[key] for f in findings})}
    confirmed = [f for f in findings if f['status'] == 'ACTIVE_CONFIRMED']
    unverified = [f for f in findings if f['status'] == 'ACTIVE_UNVERIFIED']
    explicit = [f for f in findings
                if any(t['relation'] == 'EXPLICIT_LINK' for t in f['linked_tasks'])]
    mention_only = [f for f in findings
                    if f['linked_tasks'] and f not in explicit]
    counts = {
        'findings': len(findings),
        'active_confirmed': len(confirmed),
        'active_unverified': len(unverified),
        'by_classification': by('classification'),
        'by_severity': by('severity'),
        'by_status': by('status'),
        'by_category': by('category'),
        'by_freshness': by('freshness'),
        # СЕЙЧАС означает «подтверждено свежим источником», и только это
        'critical_confirmed_now': sum(1 for f in confirmed if f['severity'] == 'CRITICAL'),
        'warning_confirmed_now': sum(1 for f in confirmed if f['severity'] == 'WARNING'),
        'critical_unverified': sum(1 for f in unverified if f['severity'] == 'CRITICAL'),
        'warning_unverified': sum(1 for f in unverified if f['severity'] == 'WARNING'),
        'unknown_severity': sum(1 for f in findings if f['severity'] == 'UNKNOWN'),
        'explicit_task_links': len(explicit),
        'mention_only_matches': len(mention_only),
        'no_task_relation': sum(1 for f in findings if not f['linked_tasks']),
        'corroborated': sum(1 for f in findings if f['corroborated_by']),
        'sources_read': sum(1 for s in sources if s['status'] == 'READ'),
        'sources_unavailable': sum(1 for s in sources if s['status'] != 'READ'),
        'sources_with_declared_slo': sum(
            1 for s in sources if s.get('declared_slo_hours') is not None),
        'sources_freshness_unknown': sum(
            1 for s in sources if s['freshness'] == 'UNKNOWN'),
    }

    snapshot = {
        'schema_version': SCHEMA,
        'generated_at': now.isoformat(),
        'derived_state': True,
        'is_not_a_source_of_truth':
            'производный снимок надёжности: пересобирается из перечисленных источников и '
            'не является ни новым реестром проблем, ни вторым бэклогом',
        'creates_tasks': False,
        'performs_repair': False,
        'production': str(production),
        'classification_definitions': dict(CLASSIFICATION_DEFINITIONS),
        'status_definitions': dict(STATUS_DEFINITIONS),
        'freshness_definitions': dict(FRESHNESS_DEFINITIONS),
        'freshness_rule_source': 'architecture/manifest.json (artifacts[].slo_hours и '
                                 'agents[].produces[].slo_hours). Собственного '
                                 'универсального порога у этого слоя НЕТ',
        'classification_rule': {
            'repetition_min': REPETITION_MIN,
            'persistence_hours': PERSISTENCE_HOURS,
            'corroboration_is_not_repetition':
                'запись об одном предмете от двух источников объединяется; счёт '
                'наблюдений берётся максимальный, а не суммируется',
            'order': ['измеренная повторяемость', 'измеренная длительность',
                      'событие с отметкой времени', 'свойство устройства системы',
                      'улик не хватает'],
        },
        'severity_vocabulary': list(SEVERITIES),
        'status_vocabulary': list(STATUSES),
        'freshness_vocabulary': list(FRESHNESS_VALUES),
        'category_vocabulary': list(CATEGORIES),
        'sources': sources,
        'counts': counts,
        'findings': findings,
        'task_linking': dict(linking, creates_tasks=False,
                             note='показана только уже существующая карточка'),
        'limits': list(LIMITS),
    }
    snapshot['semantic_digest'] = semantic_digest(snapshot)
    return snapshot


def semantic_view(snapshot):
    """Смысл снимка без летучих полей — для сравнения двух прогонов и пересборки."""
    view = {k: v for k, v in snapshot.items()
            if k not in ('generated_at', 'semantic_digest', 'sources', 'findings')}
    view['findings'] = [{k: v for k, v in f.items() if k != 'source_age_hours'}
                        for f in snapshot.get('findings', [])]
    view['sources'] = [{k: v for k, v in s.items() if k not in ('age_hours',)}
                       for s in snapshot.get('sources', [])]
    return view


def semantic_digest(snapshot):
    payload = json.dumps(semantic_view(snapshot), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


def validate_reliability_snapshot(snapshot, where):
    """Строгая проверка входного контракта. Несовпадение — отказ, а не тихая правка."""
    def need(cond, message):
        if not cond:
            raise ReliabilityInputError(f'{where}: {message}')

    need(isinstance(snapshot, dict), 'снимок не является объектом')
    need(snapshot.get('schema_version') == SCHEMA,
         f"схема {snapshot.get('schema_version')!r}, ожидалась {SCHEMA!r}")
    for key in ('generated_at', 'sources', 'counts', 'findings', 'limits',
                'classification_definitions', 'classification_rule',
                'status_definitions', 'freshness_definitions', 'freshness_rule_source'):
        need(key in snapshot, f'поле {key} отсутствует')
    for rec in snapshot['sources']:
        need(rec.get('freshness') in FRESHNESS_VALUES,
             f"источник {rec.get('source')}: свежесть {rec.get('freshness')!r} вне словаря")
        need(not (rec.get('rebuildable_artifact') and rec.get('basis') == 'authoritative'),
             f"источник {rec.get('source')}: пересобираемый производный артефакт объявлен "
             'авторитетным — это завело бы второй источник правды')
    need(snapshot.get('creates_tasks') is False, 'creates_tasks обязан быть False')
    need(snapshot.get('performs_repair') is False, 'performs_repair обязан быть False')
    need(isinstance(snapshot['findings'], list), 'findings не список')
    seen = set()
    for i, f in enumerate(snapshot['findings']):
        need(isinstance(f, dict), f'findings[{i}] не объект')
        for key in ('finding_id', 'finding_type', 'affected_entity', 'title', 'status',
                    'severity', 'first_seen', 'last_seen', 'source', 'source_status',
                    'evidence', 'category', 'occurrence_count', 'occurrence_basis',
                    'classification', 'classification_reason', 'observed_at',
                    'linked_tasks', 'as_of', 'source_age_hours', 'sources',
                    'corroborated_by', 'merged_ids', 'freshness', 'freshness_rule',
                    'authoritative_source'):
            need(key in f, f'findings[{i}] без поля {key}')
        need(f['finding_id'] not in seen, f'дубль finding_id {f["finding_id"]!r}')
        seen.add(f['finding_id'])
        need(f['classification'] in CLASSIFICATIONS,
             f'findings[{i}] классификация {f["classification"]!r} вне словаря')
        need(f['severity'] in SEVERITIES,
             f'findings[{i}] severity {f["severity"]!r} вне словаря')
        need(f['status'] in STATUSES, f'findings[{i}] статус {f["status"]!r} вне словаря')
        need(f['freshness'] in FRESHNESS_VALUES,
             f'findings[{i}] свежесть {f["freshness"]!r} вне словаря')
        need(not (f['status'] == 'ACTIVE_CONFIRMED' and f['freshness'] != 'FRESH'),
             f'findings[{i}] объявлен подтверждённым сейчас, хотя свежесть источника '
             f'{f["freshness"]!r}: «источник не отзывал» не есть «подтверждено»')
        for t in f['linked_tasks']:
            need(t.get('relation') in ('EXPLICIT_LINK', 'MENTION_MATCH'),
                 f'findings[{i}] связь с задачей без рода улики')
            need(bool(t.get('basis')), f'findings[{i}] связь без названного основания')
        need(f['classification_reason'], f'findings[{i}] без причины классификации')
        need(isinstance(f['evidence'], list), f'findings[{i}] evidence не список')
        if f['occurrence_count'] is not None:
            need(isinstance(f['occurrence_count'], int) and f['occurrence_count'] > 0,
                 f'findings[{i}] occurrence_count не положительное целое')
            need(bool(f['occurrence_basis']),
                 f'findings[{i}] счёт без названного прибора')
        else:
            need(f['occurrence_basis'] is None,
                 f'findings[{i}] прибор назван, а счёта нет')
        if f['classification'] == 'PROBLEM_CANDIDATE':
            proven = (f['occurrence_count'] is not None
                      and f['occurrence_count'] >= REPETITION_MIN)
            first, last = _parse_ts(f['first_seen']), _parse_ts(f['last_seen'])
            held = (first and last
                    and (last - first).total_seconds() / 3600.0 >= PERSISTENCE_HOURS)
            need(proven or held,
                 f'findings[{i}] объявлен PROBLEM_CANDIDATE без измеренной '
                 'повторяемости и без измеренной длительности')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--production', type=Path, default=Path.home() / 'Documents/SPA_Claude')
    ap.add_argument('--cartographer', type=Path,
                    help='принятый комплект Cartographer (для находок наблюдения)')
    ap.add_argument('--authority', type=Path,
                    help='комплект Authority Map (Phase 3): каталог или authority_map.json')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)

    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} уже существует; каждый прогон пишет новый каталог')
    try:
        snapshot = build_reliability_snapshot(args.production, args.cartographer,
                                              args.authority)
        validate_reliability_snapshot(snapshot, 'freshly built')
    except ReliabilityInputError as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nСнимок не построен. Это НЕ '
                         '«проблем нет».')

    protected = [Path(args.production)]
    for extra in (args.cartographer, args.authority):
        if extra:
            protected.append(Path(extra))
    diff_mod.validate_output(final, protected)

    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} остался от прерванного прогона; отодвиньте его')
    staging.mkdir(parents=True, mode=0o700)
    p = staging / 'reliability_snapshot.json'
    with p.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(snapshot, indent=2, ensure_ascii=False) + '\n')
    p.chmod(0o600)
    os.rename(staging, final)

    c = snapshot['counts']
    print(f"Источников прочитано: {c['sources_read']} · недоступно: "
          f"{c['sources_unavailable']}")
    print(f"Со своим объявленным сроком годности: {c['sources_with_declared_slo']} · "
          f"свежесть не измерена: {c['sources_freshness_unknown']}")
    print(f"Находок: {c['findings']} · подтверждено сейчас: {c['active_confirmed']} · "
          f"требует перепроверки: {c['active_unverified']}")
    print(f"CRITICAL сейчас: {c['critical_confirmed_now']} · CRITICAL без подтверждения: "
          f"{c['critical_unverified']} · WARNING сейчас: {c['warning_confirmed_now']}")
    print(f"По классификации: {c['by_classification']} · по свежести: {c['by_freshness']}")
    print(f"Объявленная связь с задачей: {c['explicit_task_links']} · только упоминание: "
          f"{c['mention_only_matches']} · без связи: {c['no_task_relation']} "
          "(задачи НЕ создавались)")
    print(f"Снимок → {final / 'reliability_snapshot.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
