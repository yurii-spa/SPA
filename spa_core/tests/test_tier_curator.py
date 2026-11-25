"""Тесты tier_curator (Y4, ADR-055 «тир — динамический», первый шаг —
advisory-отчёт кураторов).

Ключевые положительные контроли fail-CLOSED:
* деградация (мёртвый фид / Tier-A BLOCK / TVL<floor / held без живого TVL)
  → DEMOTE_SIGNAL, не KEEP;
* стабильность с ПОЛНЫМ пакетом доказательств → PROMOTE_CANDIDATE
  (T2→T1 owner-gated);
* отсутствие данных → UNCHECKED, НЕ KEEP (молчание ≠ подтверждение);
* отсутствие Tier-A записи блокирует промоушен (нет оценки ≠ «чисто»);
* advisory-инвариант: отчёт никто не потребляет для смены тира, модуль не
  импортирует execution/kill/gates, curate() ничего не пишет.
"""
from __future__ import annotations

import json
import ast
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.analytics import _apy_series
from spa_core.analytics import tier_curator as tc
from spa_core.monitoring.tier_touch import describe, tier_touches
from spa_core.monitoring.tier_report_consumption import (
    TierReportConsumptionUnmeasured,
    consumes_report,
    describe as describe_consumption,
    mentions as curator_mentions,
)
from spa_core.risk.policy import RiskConfig

NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
ISO = NOW.isoformat()
SPA_CORE = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _fresh_series_cache():
    _apy_series.clear_cache()
    yield
    _apy_series.clear_cache()


def _orch_row(proto: str, tier: str = "T2", *, status: str = "ok",
              live: bool = True, tvl_source: str = "live",
              tvl: float = 30_000_000.0, apy: float = 4.0,
              error: str | None = None) -> dict:
    return {"protocol": proto, "tier": tier, "status": status,
            "live_data": live, "tvl_source": tvl_source,
            "tvl_usd": (tvl if tvl_source else None),
            "apy_pct": apy, "error": error}


def _write(data_dir: Path, *, orch_rows=None, status_adapters=None,
           positions=None, feed=None, tier_a=None, tier_b=None,
           series=None, ts: str = ISO) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    if orch_rows is not None:
        (data_dir / tc.ORCH_FILE).write_text(json.dumps(
            {"generated_at": ts, "adapters": orch_rows}), encoding="utf-8")
    if status_adapters is not None:
        (data_dir / tc.ADAPTER_STATUS_FILE).write_text(json.dumps(
            {"generated_at": ts, "adapters": status_adapters}),
            encoding="utf-8")
    if positions is not None or feed is not None:
        (data_dir / tc.POSITIONS_FILE).write_text(json.dumps(
            {"generated_at": ts, "positions": positions or {},
             "feed_coverage": feed or {}}), encoding="utf-8")
    if tier_a is not None:
        (data_dir / tc.TIER_A_FILE).write_text(json.dumps(
            {"generated_at": ts, "signals": tier_a, "protocols": tier_a}),
            encoding="utf-8")
    if tier_b is not None:
        (data_dir / tc.TIER_B_FILE).write_text(json.dumps(
            {"generated_at": ts, "signals": tier_b, "protocols": tier_b}),
            encoding="utf-8")
    if series is not None:
        (data_dir / "apy_series_daily.json").write_text(json.dumps(
            {"series": series}), encoding="utf-8")
    return data_dir


def _stable_series(proto: str, n: int = 30, apy: float = 4.0) -> dict:
    last = NOW.date()
    rows = [[(last - timedelta(days=n - 1 - i)).isoformat(), apy]
            for i in range(n)]
    return {proto: rows}


# ─── Демоут-сигналы (деградация → немедленно, fail-CLOSED) ───────────────────

def test_dead_feed_is_demote_signal(tmp_path):
    dd = _write(tmp_path, orch_rows=[
        _orch_row("morpho_blue", status="error", live=False,
                  tvl_source=None, tvl=0, apy=None, error="live_feed_unavailable")])
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["morpho_blue"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("feed_dead" in r for r in v["reasons"])


def test_tier_a_block_is_demote_signal(tmp_path):
    dd = _write(tmp_path,
                orch_rows=[_orch_row("euler_v2")],
                tier_a={"euler_v2": {"signal": "BLOCK", "score": 82.0,
                                     "reason": "oracle=score 82.0",
                                     "triggered_by": ["oracle"]}})
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["euler_v2"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("tier_a_block" in r for r in v["reasons"])


def test_held_without_live_tvl_is_demote_and_flagged(tmp_path):
    """Реальный кейс живой книги: morpho_steakhouse $40k при tvl_source=static."""
    dd = _write(tmp_path,
                status_adapters={"morpho_steakhouse": {"tier": 1, "active": True}},
                positions={"morpho_steakhouse": 40_000.0},
                feed={"tvl_sources": {"morpho_steakhouse": "static"},
                      "apy_sources": {"morpho_steakhouse": "live"}})
    rep = tc.curate(data_dir=dd, now=NOW)
    v = rep["verdicts"]["morpho_steakhouse"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("held_without_live_tvl" in r for r in v["reasons"])
    assert rep["summary"]["held_flagged"] == ["morpho_steakhouse"]


def test_live_tvl_below_floor_is_demote_signal(tmp_path):
    dd = _write(tmp_path, orch_rows=[_orch_row("pendle", tier="T3",
                                               tvl=3_000_000.0)])
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["pendle"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("tvl_below_floor" in r for r in v["reasons"])


def test_apy_outside_policy_bounds_is_demote_signal(tmp_path):
    dd = _write(tmp_path, orch_rows=[_orch_row("pendle", tier="T3", apy=45.0)])
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["pendle"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("apy_out_of_policy_bounds" in r for r in v["reasons"])


def test_stale_book_held_position_still_demotes(tmp_path):
    """Протухшая книга (5 дней) не отбеливает held-позицию: провенанс из
    протухшего feed_coverage не считается живым → DEMOTE (fail-CLOSED)."""
    old = (NOW - timedelta(days=5)).isoformat()
    dd = _write(tmp_path,
                positions={"maple": 20_000.0},
                feed={"tvl_sources": {"maple": "live"},
                      "apy_sources": {"maple": "live"}},
                ts=old)
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["maple"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("held_without_live_tvl" in r for r in v["reasons"])


# ─── Промоушен (только рекомендация, полный пакет доказательств) ─────────────

def _promotable(tmp_path, proto="yearn_v3", tier="T2"):
    return _write(
        tmp_path,
        orch_rows=[_orch_row(proto, tier=tier, tvl=30_000_000.0, apy=4.0)],
        tier_a={proto: {"signal": "OK", "score": 12.0,
                        "reason": "no_active_tier_a_signal",
                        "triggered_by": []}},
        tier_b={proto: {"composite_risk_0_100": 41.0}},
        series=_stable_series(proto))


def test_stable_t2_is_promote_candidate_owner_gated(tmp_path):
    dd = _promotable(tmp_path)
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["yearn_v3"]
    assert v["verdict"] == tc.VERDICT_PROMOTE
    assert v["target_tier"] == "T1"
    assert v["owner_gated"] is True  # промоушен в T1 owner-gated (ADR-055)


def test_stable_t3_targets_t2_not_owner_gated(tmp_path):
    dd = _promotable(tmp_path, proto="pendle", tier="T3")
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["pendle"]
    assert v["verdict"] == tc.VERDICT_PROMOTE
    assert v["target_tier"] == "T2"
    assert v["owner_gated"] is False


def test_missing_tier_a_entry_blocks_promotion(tmp_path):
    """Fail-CLOSED контроль: «нет Tier-A записи» ≠ «чисто». Тот же полный
    пакет, но без Tier-A оценки → KEEP, не PROMOTE_CANDIDATE."""
    proto = "yearn_v3"
    dd = _write(
        tmp_path,
        orch_rows=[_orch_row(proto, tvl=30_000_000.0, apy=4.0)],
        tier_b={proto: {"composite_risk_0_100": 41.0}},
        series=_stable_series(proto))
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"][proto]
    assert v["verdict"] == tc.VERDICT_KEEP
    assert any("tier_a_not_evaluated_fresh" in r for r in v["reasons"])


def test_tier_a_warn_blocks_promotion(tmp_path):
    dd = _promotable(tmp_path)
    doc = json.loads((dd / tc.TIER_A_FILE).read_text())
    doc["signals"]["yearn_v3"] = {"signal": "WARN", "score": 55.0,
                                  "reason": "x=score 55.0",
                                  "triggered_by": ["x"]}
    doc["protocols"] = doc["signals"]
    (dd / tc.TIER_A_FILE).write_text(json.dumps(doc))
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["yearn_v3"]
    assert v["verdict"] == tc.VERDICT_KEEP
    assert any("tier_a_not_clean" in r for r in v["reasons"])


def test_short_history_blocks_promotion(tmp_path):
    dd = _promotable(tmp_path)
    (dd / "apy_series_daily.json").write_text(json.dumps(
        {"series": _stable_series("yearn_v3", n=5)}))
    _apy_series.clear_cache()
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["yearn_v3"]
    assert v["verdict"] == tc.VERDICT_KEEP
    assert any("apy_history_short" in r for r in v["reasons"])


def test_unstable_apy_blocks_promotion(tmp_path):
    dd = _promotable(tmp_path)
    last = NOW.date()
    rows = [[(last - timedelta(days=29 - i)).isoformat(),
             2.0 if i % 2 else 9.0] for i in range(30)]
    (dd / "apy_series_daily.json").write_text(json.dumps(
        {"series": {"yearn_v3": rows}}))
    _apy_series.clear_cache()
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["yearn_v3"]
    assert v["verdict"] == tc.VERDICT_KEEP
    assert any("apy_unstable" in r for r in v["reasons"])


def test_t1_is_never_promote_candidate(tmp_path):
    dd = _promotable(tmp_path, proto="aave_v3", tier="T1")
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["aave_v3"]
    assert v["verdict"] == tc.VERDICT_KEEP
    assert any("already_T1" in r for r in v["reasons"])


# ─── UNCHECKED — не KEEP (положительный контроль fail-CLOSED) ────────────────

def test_no_evidence_is_unchecked_not_keep(tmp_path):
    """Протокол есть только в adapter_status со static-литералами: живого
    провенанса нет, Tier-A не оценивал → UNCHECKED. KEEP был бы fail-OPEN."""
    dd = _write(tmp_path, status_adapters={
        "sfrax": {"tier": 2, "active": True, "tvl_usd": 800_000_000.0,
                  "apy": 6.0}})
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["sfrax"]
    assert v["verdict"] == tc.VERDICT_UNCHECKED
    assert v["verdict"] != tc.VERDICT_KEEP
    assert any("no_live_evidence" in r for r in v["reasons"])


def test_stale_orchestrator_downgrades_to_unchecked(tmp_path):
    """Свежая вчера, протухшая сегодня: та же строка оркестратора возрастом
    5 дней перестаёт быть доказательством → UNCHECKED (контроль в обе
    стороны: со свежим ts тот же протокол — KEEP)."""
    row = [_orch_row("euler_v2", tvl=8_000_000.0, apy=3.0)]
    fresh = tc.curate(data_dir=_write(tmp_path / "a", orch_rows=row),
                      now=NOW)["verdicts"]["euler_v2"]
    assert fresh["verdict"] == tc.VERDICT_KEEP
    old_ts = (NOW - timedelta(days=5)).isoformat()
    stale = tc.curate(data_dir=_write(tmp_path / "b", orch_rows=row, ts=old_ts),
                      now=NOW)["verdicts"]["euler_v2"]
    assert stale["verdict"] == tc.VERDICT_UNCHECKED


def test_empty_and_broken_data_dir_do_not_raise(tmp_path):
    rep = tc.curate(data_dir=tmp_path / "empty", now=NOW)
    assert rep["verdicts"] == {} and rep["summary"]["total"] == 0
    bad = tmp_path / "bad"
    bad.mkdir()
    for name in (tc.ORCH_FILE, tc.ADAPTER_STATUS_FILE, tc.POSITIONS_FILE,
                 tc.TIER_A_FILE, tc.TIER_B_FILE):
        (bad / name).write_text("{not json", encoding="utf-8")
    rep = tc.curate(data_dir=bad, now=NOW)
    assert rep["verdicts"] == {}


def test_summary_counts_are_consistent(tmp_path):
    dd = _promotable(tmp_path)
    _write(dd, orch_rows=None, status_adapters={
        "sfrax": {"tier": 2, "active": True}})
    # _write выше перезаписал только adapter_status; orch/tier_a/series целы
    rep = tc.curate(data_dir=dd, now=NOW)
    s = rep["summary"]
    assert s["total"] == len(rep["verdicts"])
    assert (s["keep"] + s["demote_signal"] + s["promote_candidate"]
            + s["unchecked"]) == s["total"]


# ─── Пороги — из RiskPolicy v1.0, не выдуманы (parity) ───────────────────────

def test_thresholds_match_riskconfig():
    cfg = RiskConfig()
    assert tc.TVL_FLOOR_USD == float(cfg.min_tvl_usd)
    assert tc.APY_MIN_PCT == float(cfg.min_apy_for_new_position)
    assert tc.APY_MAX_PCT == float(cfg.max_apy_for_new_position)
    from spa_core.analytics.signal_aggregator import (BLOCK_THRESHOLD,
                                                      WARN_THRESHOLD)
    rep_thr = tc.curate(data_dir=Path("/nonexistent"), now=NOW)["thresholds"]
    assert rep_thr["tvl_floor_usd"] == float(cfg.min_tvl_usd)
    assert rep_thr["tier_a_block"] == BLOCK_THRESHOLD
    assert rep_thr["tier_a_warn"] == WARN_THRESHOLD


# ─── Запись: только через write_report, атомарно; curate read-only ──────────

def test_curate_is_read_only(tmp_path):
    dd = _promotable(tmp_path)
    before = {p.name: p.stat().st_mtime_ns for p in dd.iterdir()}
    tc.curate(data_dir=dd, now=NOW)
    after = {p.name: p.stat().st_mtime_ns for p in dd.iterdir()}
    assert after == before
    assert not (dd / tc.REPORT_FILENAME).exists()


def test_write_report_writes_atomically_and_matches(tmp_path, monkeypatch):
    dd = _promotable(tmp_path)
    calls = []
    from spa_core.utils import atomic as atomic_mod
    real = atomic_mod.atomic_save

    def spy(data, path, indent=2):
        calls.append(str(path))
        return real(data, path, indent)

    monkeypatch.setattr(atomic_mod, "atomic_save", spy)
    doc = tc.write_report(data_dir=dd, now=NOW)
    assert calls == [str(dd / tc.REPORT_FILENAME)]
    on_disk = json.loads((dd / tc.REPORT_FILENAME).read_text(encoding="utf-8"))
    assert on_disk == doc
    assert doc["summary"]["promote_candidate"] == 1
    assert not list(dd.glob("*.tmp"))  # никаких хвостов временных файлов


def test_report_carries_advisory_note(tmp_path):
    doc = tc.curate(data_dir=tmp_path, now=NOW)
    note = doc["advisory_note"]
    assert "never changes tiers" in note
    assert "separate ADR" in note
    assert "owner-gated" in note


# ─── Advisory-инвариант на уровне исходников ─────────────────────────────────

def test_curator_never_imports_execution_or_gate_domains():
    text = (SPA_CORE / "analytics" / "tier_curator.py").read_text(
        encoding="utf-8")
    for forbidden in ("spa_core.execution", "kill_switch", "cycle_gates",
                      "pre_cutover_gate"):
        assert forbidden not in text, forbidden


def _mentions_curator_in_code(text: str) -> bool:
    """Добирается ли модуль до ОТЧЁТА куратора — одна дверь, один вопрос.

    ИЗМЕНЕНО ОСОЗНАННО (инв. #16; цикл #1241, карточка
    `inbox-storozh-tira-sudit-podstrokoi-imya-kurat`, ADR-1096). Здесь жила своя
    мера, и она спрашивала о ФАЙЛЕ, а не о вхождении: любая строковая константа с
    именем `tier_curator` вне докстроки считалась потреблением, а невинность
    снималась ОТДЕЛЬНЫМ механизмом на ВЕСЬ файл — признаком «сгенерированная
    разметка» (`_is_generated_markup`) либо входом `data_names_ok`. Оба механизма
    УДАЛЕНЫ вместе с мерой: роль вхождения знает разбор, и спрашивать её у класса
    файла значило держать два правила на один вопрос — ровно так перечень
    `allowed` дорос до пяти имён и покраснел на четвёртом невинном модуле.

    Мера живёт ОДНОЙ копией у двери
    `spa_core/monitoring/tier_report_consumption.py`; второй копии здесь нет
    намеренно — на двух копиях одного правила уже разъезжался перечень канона
    (цикл #875).

    Неразбираемое судится СТРОГО: третий исход двери сторож превращает в
    «потребление», потому что ложный зелёный за опечатку опаснее красного. Сам
    третий исход при этом НЕ исчезает — он назван у двери и отдельной развилкой
    в сторо́же ниже (инв. #17).
    """
    try:
        return consumes_report(text)
    except TierReportConsumptionUnmeasured:
        return True


def _guard_own_instruments() -> set:
    """Приборы самого сторожа — ВЫВЕДЕНЫ из его ввозов, а не перечислены именами.

    ADR-1096. Прибор, которым сторож меряет, в население сторожа не входит: он не
    читает ни одного файла (текст приходит ему аргументом) и тир сменить не может
    ничем. Прежде такой прибор дописывали ИМЕНЕМ в `allowed` — так перечень дорос
    до пяти имён, и четвёртый невинный модуль покраснел всё равно. Здесь имя не
    пишут: его называет сам ввоз, и список не может разойтись с кодом молча.

    Положительный контроль у вывода есть, и в обе стороны —
    `test_the_guard_derives_its_instruments_from_its_own_imports`.
    """
    own = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(own):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if len(parts) == 3 and parts[:2] == ["spa_core", "monitoring"]:
                found.add(SPA_CORE / "monitoring" / f"{parts[2]}.py")
    return found
def test_no_module_consumes_report_to_mutate_tiers():
    """Никто в runtime-коде не ЧИТАЕТ tier_curator_report.json и не импортирует
    curate() для смены тира: упоминания допустимы только в самом модуле
    (константа) и в cycle_runner (только write_report, писатель)."""
    # ИЗМЕНЕНО ОСОЗНАННО (инв. #16; журнал W37, 13.09). Прежняя редакция запрещала ЛЮБОГО
    # читателя отчёта — и это был не сторож инварианта, а причина дефекта: отчёт годами
    # писался, и ни один модуль не смел его открыть (замер 11.09: читателей 0). Инвариант
    # модуля — «никто не читает отчёт ДЛЯ СМЕНЫ ТИРА»; читать его, чтобы завести карточку
    # агенту, инвариант не нарушает. Разрешён ровно один читатель — findings_bridge, и его
    # чистота проверяется ниже ПОЛОЖИТЕЛЬНЫМ контролем, а не доверием к списку.
    reader = SPA_CORE / "monitoring" / "findings_bridge.py"
    # ИЗМЕНЕНО ОСОЗНАННО (инв. #16; журнал W37, 13.09, #55): второй читатель — исходная проба
    # приёмки `tier_promotion_loop_closed` (card_acceptance.py, #54): она кладёт отчёт куратора
    # в ОДНОРАЗОВОЕ дерево и меряет, родилась ли карточка. Её чистота проверяется тем же
    # положительным контролем, что у моста, — ниже.
    probe = SPA_CORE / "monitoring" / "card_acceptance.py"
    # Прибор признака `monitoring/tier_touch.py` стоя́л здесь ЧЕТВЁРТЫМ именем с
    # цикла #875 — ровно с оговоркой «имя модуля стои́т у него ДАННЫМИ». С ADR-1096
    # перечень СОКРАЩЁН: роль «элемент данных» мера знает сама, и держать для неё
    # имя в белом списке больше не надо. Перечень может только УМЕНЬШАТЬСЯ
    # (карточка `inbox-storozh-tira-sudit-podstrokoi-imya-kurat`, п. 4); его
    # чистота проверяется ниже тем же положительным контролем, что у читателей.
    instrument = SPA_CORE / "monitoring" / "tier_touch.py"
    allowed = {SPA_CORE / "analytics" / "tier_curator.py",
               SPA_CORE / "paper_trading" / "cycle_runner.py",
               reader, probe} | _guard_own_instruments()
    offenders = []
    unmeasured = []
    data_only = []
    for py in SPA_CORE.rglob("*.py"):
        if py.parts and "tests" in py.parts:
            continue
        if py in allowed:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        if "tier_curator" not in text:
            continue
        # Три исхода РАЗЛИЧИМЫ (инв. #17): потребляет · называет имя данными ·
        # НЕ ИЗМЕРЕНО. Прежняя редакция знала два, и неразбираемый файл попадал в
        # тот же список, что настоящий потребитель, — вердикт о нём был верен, а
        # причина терялась.
        try:
            found = curator_mentions(text)
        except TierReportConsumptionUnmeasured as exc:
            unmeasured.append(f"{py}: {exc}")
            continue
        if any(m.consuming for m in found):
            offenders.append(describe_consumption(str(py), found))
        else:
            data_only.append(str(py))
    assert unmeasured == [], unmeasured
    assert offenders == [], offenders
    # «Измерено и равно нулю» названо вслух: вхождения ЕСТЬ, и все они данные.
    # Пустой `data_only` означал бы, что мера перестала видеть класс вовсе, —
    # то есть сторож зеленеет не потому, что чисто (обратная половина ниже).
    assert data_only, ("ни одного модуля с именем куратора в роли ДАННЫХ — мера "
                       "перестала видеть класс, а не подтвердила чистоту")
    # Разрешённый читатель НЕ вправе трогать тир: ни канон оценок, ни реестр адаптеров,
    # ни разрешатель имён, ни политику — он превращает вердикт в карточку, и только.
    # ИЗМЕНЕНО ОСОЗНАННО (инв. #16; цикл #875, карточка
    # `inbox-storozh-tira-sudit-podstrokoi-i-krasen-n`). Здесь стояло
    # `assert forbidden not in text` по двум спискам имён, и этот признак был НЕВЕРЕН
    # в обе стороны. Ложный КРАСНЫЙ: с 02.10 сторож падал на верном состоянии —
    # `RiskConfig` стои́т в `card_acceptance.py` дважды, и оба раза ПРОЗА (докстрока о
    # ЧУЖОМ приборе и текст сообщения в f-строке). Ложный ЗЕЛЁНЫЙ, который опаснее и
    # которого не видел никто: настоящий ввоз, записанный иначе — `import
    # spa_core.risk.policy`, псевдоним `as RC`, `getattr(m, "RiskConfig")`,
    # `importlib.import_module(...)` — подстрочным списком не ловился ВООБЩЕ.
    #
    # Правило сторожа НЕ ослаблено: кому канон трогать нельзя — то же самое, и набор
    # имён стал ОБЪЕДИНЕНИЕМ двух прежних списков (у моста он был на одно имя длиннее).
    # Сменился ПРИЗНАК: вопрос «стои́т ли символ в файле» заменён вопросом «стои́т ли он
    # в КОДЕ» (`spa_core/monitoring/tier_touch.py`, разбор AST). Перечень канона живёт
    # ОДНОЙ копией — у прибора; держать его список здесь значило бы снова два места для
    # одного правила. Контроль в обе стороны — `spa_core/tests/test_tier_touch.py`,
    # приёмка по исходу — проба `tier_guard_judges_code_not_prose`.
    bridge = reader.read_text(encoding="utf-8")
    assert _mentions_curator_in_code(bridge), "читатель обязан читать именно отчёт"
    assert tier_touches(bridge) == [], describe(str(reader), tier_touches(bridge))
    probe_text = probe.read_text(encoding="utf-8")
    assert _mentions_curator_in_code(probe_text), (
        "проба обязана класть именно отчёт куратора")
    assert tier_touches(probe_text) == [], describe(str(probe), tier_touches(probe_text))
    inst_text = instrument.read_text(encoding="utf-8")
    assert not _mentions_curator_in_code(inst_text), (
        "прибор признака назвал ОТЧЁТ куратора — читать его прибору незачем")
    assert tier_touches(inst_text) == [], describe(str(instrument),
                                                  tier_touches(inst_text))
    # cycle_runner: только write_report, самого файла отчёта он не читает
    runner = (SPA_CORE / "paper_trading" / "cycle_runner.py").read_text(
        encoding="utf-8")
    assert "from spa_core.analytics.tier_curator import write_report" in runner
    assert "tier_curator_report.json" not in runner.replace(
        "data/tier_curator_report.json", "")  # упоминание только в комменте
    assert "import curate" not in runner


def test_cycle_hook_is_non_critical():
    """Хук в цикле обёрнут в try/except и на падении лишь предупреждает."""
    runner = (SPA_CORE / "paper_trading" / "cycle_runner.py").read_text(
        encoding="utf-8")
    m = re.search(
        r"try:\s*\n\s*from spa_core\.analytics\.tier_curator import "
        r"write_report", runner)
    assert m, "tier_curator import must live inside a try-block"
    assert "tier_curator report failed (non-critical)" in runner


def test_the_consumer_guard_tells_code_from_prose():
    """Контроль в обе стороны: проза не ловится, чтение отчёта — ловится."""
    prose = '"""Читает apy_ranking.json, а не data/tier_curator_report.json."""\nX = 1\n'
    assert not _mentions_curator_in_code(prose), "докстрока — не потребление"

    reads = 'p = "data/tier_curator_report.json"\nopen(p)\n'
    assert _mentions_curator_in_code(reads), "построение пути для чтения обязано ловиться"

    imports = "from spa_core.analytics.tier_curator import curate\n"
    assert _mentions_curator_in_code(imports), "импорт curate() обязан ловиться"

    unparseable = "def broken(:\n  tier_curator\n"
    assert _mentions_curator_in_code(unparseable), "неразбираемое судится строго"


def test_the_measure_judges_the_role_of_the_mention_not_the_class_of_the_file():
    """Контроль в обе стороны у СУЖЕНИЯ ADR-1096 — по роли вхождения, а не по файлу.

    ИЗМЕНЕНО ОСОЗНАННО (инв. #16; цикл #1241, карточка
    `inbox-storozh-tira-sudit-podstrokoi-imya-kurat`, запись в
    `docs/journal/2026-W48.md`). Прежняя редакция звалась
    `test_generated_markup_names_modules_as_data_but_keeps_its_teeth` и закрепляла
    ПРОТИВОПОЛОЖНОЕ последним своим утверждением: «тот же текст БЕЗ отметки замера
    перестал быть нарушением — сужение расползлось за класс сгенерированной
    разметки». То есть голое имя модуля элементом словаря объявлялось нарушением в
    РУКОПИСНОМ модуле и невинностью в СГЕНЕРИРОВАННОМ при дословно одинаковом
    вхождении.

    Утверждение снято потому, что ИЗМЕРЕНО как причина дефекта, а не как защита:
    класс файла не отвечает на вопрос «добирается ли модуль до отчёта». Под его
    защитой перечень `allowed` дорос до пяти имён (#875 внёс `tier_touch.py` с
    оговоркой «имя стои́т у него ДАННЫМИ»), и 25.11 четвёртый невинный модуль —
    `analytics/cadence_census.py`, где имя стои́т элементом кортежа ключевых слов
    классификатора такта, — покраснил сторожа на ВЕРНОМ состоянии. Перепись
    населения в тот же день: модулей с именем **7**, роль «данные и только» —
    **3**, НЕ РАЗОБРАНО — **0**.

    Сторож НЕ ослаблен, и проверяются ОБЕ стороны: ввоз, псевдоним, имя ОТЧЁТА,
    обращение к атрибуту, имя в не-данной роли и СБОРКА пути ловятся по-прежнему,
    каждое своей сценой.
    """
    data = "NOT_A_SIGNAL_MODULE = {'tier_curator': 'нет публичного класса с входом'}\n"

    # ── сторона первая: роль ДАННЫХ молчит, и молчит БЕЗ всякой отметки файла ──
    assert not _mentions_curator_in_code(data), (
        "голое имя модуля элементом словаря объявлено потреблением — сужение "
        "ADR-1096 не работает, и пятый невинный модуль покраснеет снова")

    keywords = 'TACT = {"Tier change": ("tier_curator", "tier_", "promotion")}\n'
    assert not _mentions_curator_in_code(keywords), (
        "дословная сцена 25.11 (имя элементом кортежа ключевых слов) всё ещё "
        "считается потреблением")

    stamp = "AUDIT_GENERATED_AT = '2026-01-01T00:00:00Z'\n"
    assert not _mentions_curator_in_code(stamp + data), (
        "сгенерированная разметка покраснела — прежний класс файлов обязан "
        "остаться невинным и ПОСЛЕ снятия механизма, который его различал")

    # ── сторона вторая: каждый зуб на своей сцене ──
    assert _mentions_curator_in_code(
        data + "from spa_core.analytics.tier_curator import curate\n"), (
        "ввоз curate() рядом с данными прошёл — это дыра")

    assert _mentions_curator_in_code(
        data + "from spa_core.analytics import tier_curator as _tc\n"), (
        "ввоз модуля под псевдонимом прошёл — это дыра")

    # Форма `ast.Import` отличается от `ast.ImportFrom` узлом, и своей сцены у неё не
    # было ни у сторожа, ни у пробы: дыру нашёл мутационный замер #1241, а не вычитка.
    assert _mentions_curator_in_code(
        data + "import spa_core.analytics.tier_curator\n"), (
        "ПЛОСКИЙ ввоз модуля прошёл — это дыра")

    assert _mentions_curator_in_code(data + "P = 'data/tier_curator_report.json'\n"), (
        "строка, называющая ОТЧЁТ, прошла — зубы потеряны")

    # Роль ДАННЫХ оправдывает ГОЛОЕ имя модуля, а не путь к ОТЧЁТУ: контейнер с
    # именем отчёта — тот же путь, только в скобках. Сцену нашла выжившая мутация
    # M01 замера #1241, а не вычитка.
    assert _mentions_curator_in_code('P = ("data/tier_curator_report.json",)\n'), (
        "имя ОТЧЁТА внутри кортежа объявлено данными — контейнер оправдывает голое "
        "имя модуля, а не путь к отчёту")

    assert _mentions_curator_in_code("v = mod.tier_curator_report\n"), (
        "обращение к атрибуту с именем отчёта прошло — зубы потеряны")

    assert _mentions_curator_in_code('open(os.path.join("data", "tier_curator"))\n'), (
        "имя в аргументе вызова объявлено данными — аргумент вызова не данные")

    assert _mentions_curator_in_code('N = "tier_curator"\n'), (
        "имя в присваивании объявлено данными — присваивание не литеральный контейнер")


def test_the_data_role_closes_the_assembly_route_it_opens():
    """Замыкание сужения: голое имя ПЛЮС СБОРКА второй половины пути — потребление.

    Сужение по роли открывает ровно одну дверь, которую прежняя подстрока держала
    закрытой: положить имя в контейнер, а путь собрать из элемента. Замыкание
    закрывает её, и проверяется В ОБЕ стороны — иначе «сторож теперь всегда зелен»
    прошло бы незамеченным.

    Вторая половина ищется только в роли СБОРКИ (склейка либо f-строка), а не по
    НАЛИЧИЮ: перепись артефактов, перечисляющая `*_report.json` данными, путей не
    строит, и краснеть на ней значило бы воспроизвести тот же класс на шаг позже.
    Замер 25.11: ни один из трёх живых модулей класса `data` не называет
    `report.json` НИ РАЗУ — замыкание сегодня не ложно ни на одном из них.
    """
    evasion = ('KEYS = ["tier_curator"]\n'
               'p = "data/" + KEYS[0] + "_report.json"\n'
               'open(p)\n')
    assert _mentions_curator_in_code(evasion), (
        "путь, собранный из имени-данных склейкой, прошёл — сужение открыло дверь")

    evasion_fstring = ('KEYS = ["tier_curator"]\n'
                       'p = f"data/{KEYS[0]}_report.json"\n')
    assert _mentions_curator_in_code(evasion_fstring), (
        "путь, собранный f-строкой, прошёл — сужение открыло дверь")

    # Обратная половина: те же байты второй половины, но в роли ДАННЫХ, а не сборки.
    census = ('KEYS = ["tier_curator"]\n'
              'ARTIFACTS = ["apy_report.json", "tvl_report.json"]\n')
    assert not _mentions_curator_in_code(census), (
        "перепись, перечисляющая `*_report.json` ДАННЫМИ, объявлена сборкой пути")


def test_the_measure_names_the_third_outcome_instead_of_swallowing_it():
    """Неразбираемый исходник — НЕ «чисто»: у двери он третий исход (инв. #17).

    Сторож судит его СТРОГО (ложный зелёный за опечатку опаснее красного), но
    строгость не смеет стирать причину: `consumes_report` поднимает исключение с
    номером строки, а не возвращает `True` молча.
    """
    broken = "def broken(:\n  tier_curator\n"
    with pytest.raises(TierReportConsumptionUnmeasured) as caught:
        consumes_report(broken)
    assert "НЕ ИЗМЕРЕНО" in str(caught.value), (
        "третий исход не назван словами — вызывающий не отличит его от вердикта")

    assert _mentions_curator_in_code(broken), (
        "сторож проглотил неразбираемый исходник — это ложный зелёный")


def test_the_measure_separates_absence_from_data_only_mentions():
    """«Вхождений нет вовсе» и «все вхождения — данные» — РАЗНЫЕ наблюдения.

    Сторож опирается на это различие (`data_only` обязан быть непустым), поэтому
    дверь обязана их различать, а не отвечать одним `False` на оба.
    """
    assert curator_mentions("X = 1\n") == ()
    found = curator_mentions("K = ('tier_curator',)\n")
    assert [m.kind for m in found] == ["data"]
    assert not any(m.consuming for m in found)
    assert "потребления нет" in describe_consumption("f.py", found)


def test_the_guard_derives_its_instruments_from_its_own_imports():
    """Приборы сторожа ВЫВЕДЕНЫ из его ввозов — контроль в обе стороны.

    Положительная сторона: оба прибора, которыми сторож меряет, найдены выводом, и
    на диске они ЕСТЬ. Обратная: модуль, который сторож не ввозит, прибором не
    числится — иначе вывод стал бы тем же белым списком, только неявным.
    """
    found = _guard_own_instruments()
    assert SPA_CORE / "monitoring" / "tier_touch.py" in found
    assert SPA_CORE / "monitoring" / "tier_report_consumption.py" in found
    for path in found:
        assert path.exists(), f"выведенный прибор не существует: {path}"
    assert SPA_CORE / "monitoring" / "findings_bridge.py" not in found, (
        "не ввезённый сторожем модуль числится его прибором — вывод стал списком")


def test_the_consumption_door_is_the_measure_it_claims_to_be():
    """Дверь меры ОБЯЗАНА называть отчёт — иначе она не та мера.

    Зеркало к утверждению о приборе признака выше: `tier_touch.py` отчёт называть
    НЕ вправе (читать его прибору незачем), а дверь потребления — обязана, потому
    что имя отчёта и есть её предмет. Без этой половины «прибор исключён из
    населения» означало бы «мера может стать пустой молча».
    """
    door = SPA_CORE / "monitoring" / "tier_report_consumption.py"
    text = door.read_text(encoding="utf-8")
    assert _mentions_curator_in_code(text), (
        "дверь потребления перестала называть отчёт — мера опустела, а сторож "
        "остался зелёным")
    assert tier_touches(text) == [], describe(str(door), tier_touches(text))
