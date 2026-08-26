# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — единственная литеральная дата здесь это якорь `NOW`, который
# ВСЕГДА передаётся в проверяемый код параметром `now=`, а каждая отметка в фикстуре считается
# от него же (`NOW - timedelta(hours=N)`). Закреплены обе стороны, поэтому календарь на исход не
# влияет: сдвинь дату якоря на год — все вердикты те же. Единственный тест, читающий НАСТОЯЩУЮ
# разметку, берёт часы от её собственной отметки, а не от якоря.
"""
Сторож ежедневного аудита протокол-слепоты (#367) — приёмка.

Каждый тест здесь ВОСПРОИЗВОДИТ настоящую аварию, а не иллюстрирует замысел
(`.claude/rules/deployment.md`, «проверка сторожа сторожей»): аудит #3 (20.08) обнаружил, что
дифференциальный аудит `scripts/audit_protocol_blindness.py` молча стоял **13 суток** — от
07.08 до 20.08, — и метрика владельца (директива 03.08, ~90 % рабочего аналитического слоя)
за эти сутки не сдвинулась ни на один модуль. Молчание измерителя не увидел никто, потому что
у самого измерителя сторожа не было.

Время — ВХОД, а не окружение (правило доставки, порядок предпочтения №1): всюду инъектируется
`now`, а отметки в фикстурах ставятся ОТНОСИТЕЛЬНО него. Литеральных дат здесь нет: тест обязан
переживать календарь, потому что предмет проверки — «сколько прошло», а не «какое сегодня число».
"""
# LLM_FORBIDDEN

import json
from datetime import datetime, timedelta, timezone

from spa_core.monitoring import analytics_audit_freshness as aaf
from spa_core.monitoring import artifact_freshness as af

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)  # часы теста, не календарь машины

_MARKUP_TEMPLATE = '''"""фикстура разметки — форма как у настоящей."""
from typing import Dict, FrozenSet

AUDIT_GENERATED_AT = {stamp!r}

PROTOCOL_BLIND_DETAIL: Dict[str, str] = {{
    "alpha_analyzer": "blind_equal",
    "beta_analyzer": "blind_constant",
    "gamma_analyzer": "blind_constant",
    "delta_analyzer": "nondeterministic",
}}

PROTOCOL_BLIND_MODULES: FrozenSet[str] = frozenset(PROTOCOL_BLIND_DETAIL)

WIDE_OK_MODULES: FrozenSet[str] = frozenset({{
    "honest_coarse_one",
    "honest_coarse_two",
}})
'''


def _markup(tmp_path, *, hours_ago=None, stamp=None, name="_protocol_blindness.py"):
    """Файл разметки с отметкой, заданной ОТНОСИТЕЛЬНО `NOW` (или сырой строкой)."""
    if stamp is None:
        stamp = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    path = tmp_path / name
    path.write_text(_MARKUP_TEMPLATE.format(stamp=stamp), encoding="utf-8")
    return path


# ── авария 2026-08-07…08-20: измеритель молчал 13 суток ──────────────────────────────

def test_thirteen_day_silence_is_stale_not_quiet(tmp_path):
    """ГЛАВНЫЙ положительный контроль: ровно тот простой, которого никто не заметил."""
    doc = aaf.build_status(_markup(tmp_path, hours_ago=13 * 24), now=NOW)
    assert doc["status"] == aaf.STALE, doc
    assert doc["age_hours"] == 312.0
    # вердикт обязан НАЗЫВАТЬ, что именно молчит — иначе он снова прочитается как фон
    assert "измеритель молчит" in doc["reason"]


def test_audit_run_today_is_fresh(tmp_path):
    """Обратный контроль: цикл #366 прогнал аудит в 09:13Z — сторож обязан быть зелёным."""
    doc = aaf.build_status(_markup(tmp_path, hours_ago=1.4), now=NOW)
    assert doc["status"] == aaf.FRESH, doc
    assert doc["age_hours"] == 1.4


def test_edge_of_the_window_is_still_fresh_and_one_hour_later_is_not(tmp_path):
    """Такт — граница, а не настроение: 30ч ещё проход, 31ч уже нет."""
    assert aaf.build_status(_markup(tmp_path, hours_ago=30.0), now=NOW)["status"] == aaf.FRESH
    assert aaf.build_status(_markup(tmp_path, hours_ago=31.0), now=NOW)["status"] == aaf.STALE


# ── fail-CLOSED: отсутствие данных никогда не читается как отсутствие проблемы ────────

def test_missing_markup_is_missing_not_a_clean_pass(tmp_path):
    doc = aaf.build_status(tmp_path / "no_such_file.py", now=NOW)
    assert doc["status"] == aaf.MISSING, doc
    assert doc["status"] != aaf.FRESH


def test_unparseable_stamp_is_unchecked_not_fresh(tmp_path):
    doc = aaf.build_status(_markup(tmp_path, stamp="позавчера"), now=NOW)
    assert doc["status"] == aaf.UNCHECKED, doc


def test_stamp_from_the_future_is_unchecked_not_just_now(tmp_path):
    """#291: общий `_hours_since` зажимал возраст в 0.0 — испорченные часы читались как «только что»."""
    doc = aaf.build_status(_markup(tmp_path, hours_ago=-48), now=NOW)
    assert doc["status"] == aaf.UNCHECKED, doc
    assert "из будущего" in doc["reason"]


def test_broken_markup_syntax_is_unchecked(tmp_path):
    path = tmp_path / "_protocol_blindness.py"
    path.write_text("AUDIT_GENERATED_AT = '2026-08-\n", encoding="utf-8")
    assert aaf.build_status(path, now=NOW)["status"] == aaf.UNCHECKED


# ── метрику владельца не переопределяем ───────────────────────────────────────────────

def test_partial_measurement_is_never_passed_off_as_the_owner_metric(tmp_path):
    """Знаменатель 736 охватывает все тиры; разметка — Tier B. Частичное ≠ целое."""
    doc = aaf.build_status(_markup(tmp_path, hours_ago=1.0), now=NOW)
    assert doc["metric_90pct"] is None
    assert "736" in doc["metric_unmeasured_reason"]
    assert doc["tier"] == "B"


def test_counts_come_from_the_markup_itself(tmp_path):
    """Классы считаются по разметке аудита, а не задаются руками."""
    doc = aaf.build_status(_markup(tmp_path, hours_ago=1.0), now=NOW)
    assert doc["counts"] == {
        "blind_total": 4, "wide_ok": 2,
        "blind_constant": 2, "blind_equal": 1, "nondeterministic": 1,
    }


def test_real_markup_in_this_tree_parses(tmp_path):
    """Разбор обязан работать по НАСТОЯЩЕМУ файлу, а не только по фикстуре."""
    got = aaf.read_markup(aaf.repo_root() / aaf.MARKUP_REL)
    assert got["exists"], got
    assert aaf._parse_ts(got["stamp_raw"]) is not None, got
    assert got["counts"]["blind_total"] > 0


# ── анти-украшение: вердикт судит часы ПРЕДМЕТА, а не часы писателя ──────────────────

def test_registry_reads_the_audits_clock_not_the_writers(tmp_path):
    """Свежий `derived_at` поверх 13-суточного `as_of` обязан остаться STALE.

    Эта авария — не гипотеза: артефакт переписывается КАЖДЫМ прогоном сторожа свежести,
    поэтому положи мы в него `generated_at`, реестр был бы вечно зелёным о предмете,
    которого не касался. Проверка краснеет, если поля переставить.
    """
    doc = aaf.build_status(_markup(tmp_path, hours_ago=13 * 24), now=NOW)
    assert "generated_at" not in doc, "`generated_at` вернул бы вердикту часы писателя"
    (tmp_path / aaf.STATUS_FILENAME).write_text(json.dumps(doc), encoding="utf-8")

    art = next(a for a in af.ARTIFACT_REGISTRY if a.path == aaf.STATUS_FILENAME)
    res = next(r for r in af.check_freshness(tmp_path, now=NOW) if r.name == art.name)
    assert res.status == af.STALE, res


def test_rewriting_the_file_cannot_fake_freshness_via_mtime(tmp_path):
    """Вторая лазейка: без отметки предмета файл не имеет права быть свежим по mtime."""
    art = next(a for a in af.ARTIFACT_REGISTRY if a.path == aaf.STATUS_FILENAME)
    assert art.allow_mtime is False
    (tmp_path / aaf.STATUS_FILENAME).write_text(
        json.dumps({"derived_at": NOW.isoformat(), "status": "FRESH"}), encoding="utf-8")
    res = next(r for r in af.check_freshness(tmp_path, now=NOW) if r.name == art.name)
    assert res.status == af.UNCHECKED, res


def test_registered_with_a_daily_cadence_and_a_named_producer():
    art = next(a for a in af.ARTIFACT_REGISTRY if a.path == aaf.STATUS_FILENAME)
    assert 24.0 <= art.max_age_hours <= 30.0, art
    assert "audit_protocol_blindness" in art.producer
    assert art.required is True


# ── подключён при рождении: снимите вызов — тест краснеет ────────────────────────────

def test_freshness_agent_actually_produces_the_artifact(tmp_path):
    """Мутировать проводку, а не детали: без вызова из `write_report` артефакта нет вовсе."""
    report = af.write_report(tmp_path, now=NOW)
    written = tmp_path / aaf.STATUS_FILENAME
    assert written.exists(), "write_report обязан вывести артефакт аудита"
    doc = json.loads(written.read_text(encoding="utf-8"))
    assert doc["subject"].startswith("audit_protocol_blindness")
    # и он же обязан попасть в отчёт как обычная строка реестра
    names = {a["name"] for a in report["artifacts"]}
    assert "analytics_90pct_status" in names


def test_produced_artifact_judges_this_trees_real_markup(tmp_path):
    """Сторож судит ДОСТАВЛЕННУЮ разметку своего дерева — в проде это синк `spa_core/`."""
    # обе стороны закреплены: часы берутся ОТ САМОЙ отметки, поэтому тест не зависит ни от
    # календаря, ни от того, когда в этом дереве последний раз гоняли аудит.
    stamp = aaf._parse_ts(aaf.read_markup(aaf.repo_root() / aaf.MARKUP_REL)["stamp_raw"])
    assert stamp is not None, "настоящая разметка обязана нести разбираемую отметку"
    doc = aaf.write_status(tmp_path, now=stamp + timedelta(hours=1))
    assert doc["source"] == aaf.MARKUP_REL
    assert doc["status"] == aaf.FRESH, doc  # настоящий файл читается, разбирается и судится
