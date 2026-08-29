"""Куратор тиров обязан судить по канону, а не по снимку.

# LLM_FORBIDDEN

`tier_curator` — модуль, чья работа целиком в том, чтобы судить о тирах:
он каждый цикл выдаёт DEMOTE_SIGNAL / PROMOTE_CANDIDATE / KEEP. Тир он берёт
из `adapter_orchestrator_status.json` и `adapter_status.json` — снимков, а не
из канона `protocol_risk_map.PROTOCOL_RISK_SCORES` (`docs/tier_criteria.md` §2).

Замер 2026-08-29 по живому отчёту: расхождений **2 из 34**.

* `morpho_steakhouse` — куратор судит как **T1** и выносит **KEEP**, то есть
  ежедневно ПОДТВЕРЖДАЕТ тир, который канон отменил решением владельца
  ADR-070 п.6. Источник прослежен: класс адаптера (`TIER = "T1"`) → снимок
  оркестратора → куратор.
* `ethena_susde` — куратор судит как **T3**, при том что канон, реестр И класс
  согласно говорят **T2**. Откуда взялся T3 — НЕ ИЗМЕРЕНО: в
  `adapter_status.json` строки с таким ключом нет. Записано как открытый
  вопрос, а не как догадка.

Устройство теста. Логика сверки проверяется на ФИКСТУРЕ и работает всегда —
иначе в worktree и в CI (`data/` там нет по построению) тест молча пропускался
бы целиком и был бы украшением. Живой отчёт — второй слой: он даёт теням
настоящие числа там, где цикл его пишет, и честно пропускается там, где нет.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.adapters.tier_map import tier_of
from spa_core.risk.protocol_risk_map import PROTOCOL_RISK_SCORES as CANON

_REPORT = Path(__file__).resolve().parents[2] / "data" / "tier_curator_report.json"

# Расхождения куратора с каноном, названные поимённо. Список может ТОЛЬКО
# СОКРАЩАТЬСЯ; пополнять его, чтобы погасить падение, запрещено.
# Карточка: owner-decision-tier-steakhouse-2026-08-29.
# `morpho_steakhouse` УБРАН 2026-08-29: решение ADR-070 п.6 исполнено, снимок
# оркестратора пересобран циклом, куратор теперь судит его как T2.
# `ethena_susde` остаётся: его T3 приходит из `data/adapter_registry.json`
# (пятый источник тира), и там файл СТРОЖЕ канона — приводить к канону
# значило бы послабить, это решение владельца.
KNOWN_CURATOR_DISAGREEMENT = {"ethena_susde"}

# Протоколы, чей тир куратор УТВЕРЖДАЕТ, а обосновать его нечем: ни записи
# в каноне, ни алиаса в `tier_map`. Вердикт у них честный (UNCHECKED), но
# сама метка тира взята из снимка и ничем не подкреплена — а тир это потолок.
# `sky_susds` при этом судится как T1 (потолок 40 %) при инварианте 10
# («Sky/sUSDS = 0 % до подтверждения GSM Pause Delay ≥ 48 ч»).
# Список может ТОЛЬКО СОКРАЩАТЬСЯ.
KNOWN_TIER_FROM_NOWHERE = {"notional_v3", "sky_susds"}


def _rows_from(doc: dict) -> dict[str, dict]:
    rows = doc.get("verdicts")
    assert isinstance(rows, (dict, list)), "в отчёте нет verdicts — схема изменилась"
    if isinstance(rows, dict):
        return {k: v for k, v in rows.items() if isinstance(v, dict)}
    return {r["protocol"]: r for r in rows if isinstance(r, dict) and r.get("protocol")}


def _verdict_rows() -> dict[str, dict]:
    if not _REPORT.exists():
        pytest.skip(f"нет {_REPORT.name} — в worktree отчёт не создаётся; "
                    "проверка выполняется там, где цикл его пишет")
    return _rows_from(json.loads(_REPORT.read_text(encoding="utf-8")))


def _disagreements(rows: dict[str, dict]) -> dict[str, tuple[str, str]]:
    out = {}
    for proto, row in rows.items():
        judged = str(row.get("current_tier") or row.get("tier") or "").upper()
        # Канон — PROTOCOL_RISK_SCORES; для алиасов и вариантных ключей тир
        # законно живёт в `tier_map` (docs/tier_criteria.md §1.4). Проверять
        # только по первой таблице было СЛИШКОМ СТРОГО: пять алиасов
        # (pendle_pt, ondo_usdy, aave_v3_wsteth …) выглядели бы находкой,
        # не будучи ею. Измерено 2026-08-29: 30 из 34 обоснованы.
        canon = (CANON.get(proto) or {}).get("tier") or tier_of(proto)
        if judged and canon and judged != str(canon).upper():
            out[proto] = (judged, str(canon).upper())
    return out


def test_report_is_not_vacuous():
    """Без этого «расхождений нет» означало бы «нечего сравнивать»."""
    rows = _verdict_rows()
    assert len(rows) >= 20, f"в отчёте всего {len(rows)} протоколов — сверка ослабла"
    comparable = [p for p in rows if p in CANON]
    assert len(comparable) >= 20, (
        f"с каноном сопоставимы только {len(comparable)} из {len(rows)}")


def test_no_new_protocol_is_judged_against_the_canon():
    rows = _verdict_rows()
    bad = _disagreements(rows)
    new = sorted(set(bad) - KNOWN_CURATOR_DISAGREEMENT)
    assert not new, (
        f"куратор судит по тиру, которого нет в каноне: "
        f"{ {p: bad[p] for p in new} }. Тир объявляется в PROTOCOL_RISK_SCORES "
        "и только там (docs/tier_criteria.md §2). В список известных НЕ добавлять.")
    fixed = sorted(KNOWN_CURATOR_DISAGREEMENT - set(bad))
    assert not fixed, (
        f"расхождение починено для {fixed} — убери из KNOWN_CURATOR_DISAGREEMENT.")


def test_the_steakhouse_case_is_still_the_owner_decision_one():
    """Не «какое-нибудь» расхождение: куратор ежедневно подтверждает отменённый тир."""
    rows = _verdict_rows()
    row = rows.get("morpho_steakhouse")
    assert row is not None, "протокол пропал из отчёта — перепроверь замер"
    assert str(row.get("current_tier", "")).upper() == "T1"
    assert CANON["morpho_steakhouse"]["tier"] == "T2"
    assert "ADR-070" in CANON["morpho_steakhouse"].get("note", "")


def test_no_new_tier_comes_from_nowhere():
    """Тир — это потолок. Утверждать его, не имея основания, нельзя."""
    rows = _verdict_rows()
    nowhere = {p for p in rows if p not in CANON and not tier_of(p)}
    new = sorted(nowhere - KNOWN_TIER_FROM_NOWHERE)
    assert not new, (
        f"куратор утверждает тир, не обоснованный ни каноном, ни tier_map: {new}")
    fixed = sorted(KNOWN_TIER_FROM_NOWHERE - nowhere)
    assert not fixed, f"основание появилось для {fixed} — убери из списка"


# ── логика сверки: работает всегда, без живого data/ ─────────────────────
def _fixture(**tiers) -> dict:
    return {"verdicts": {p: {"current_tier": t, "verdict": "KEEP"} for p, t in tiers.items()}}


def test_logic_catches_a_planted_mismatch():
    """Положительный контроль: без него сверка могла бы не сравнивать ничего."""
    canon_proto = next(p for p, v in CANON.items() if v["tier"] == "T2")
    bad = _disagreements(_rows_from(_fixture(**{canon_proto: "T1"})))
    assert bad == {canon_proto: ("T1", "T2")}


def test_logic_stays_quiet_when_everything_agrees():
    """Обратный контроль: сторож, кричащий всегда, — не сторож."""
    agree = {p: v["tier"] for p, v in list(CANON.items())[:5]}
    assert _disagreements(_rows_from(_fixture(**agree))) == {}


def test_logic_ignores_protocols_absent_from_the_canon():
    """Отсутствие записи — отдельный вид, его ловит свой тест, а не этот."""
    assert _disagreements(_rows_from(_fixture(**{"нет_такого": "T1"}))) == {}


def test_a_missing_tier_is_not_silently_treated_as_agreement():
    rows = _rows_from({"verdicts": {"morpho_steakhouse": {"verdict": "KEEP"}}})
    assert _disagreements(rows) == {}, "пустой тир — это не расхождение"
    assert rows["morpho_steakhouse"].get("current_tier") is None


def test_an_alias_whose_tier_diverges_is_also_caught():
    """Опора на `tier_map` не украшение: расхождение по АЛИАСУ обязано ловиться.

    Сегодняшними данными эта ветка не проверяется — все пять алиасов
    (`pendle_pt`, `ondo_usdy`, `aave_v3_wsteth`, `aerodrome_usdc_lp`,
    `pendle_yt_susde`) судятся ровно тем тиром, что даёт `tier_of`. Мутация
    «снять fallback» поэтому НЕ краснела, то есть проверка держалась на удаче.
    Здесь расхождение подкладывается явно.
    """
    alias = "pendle_yt_susde"
    real = tier_of(alias)
    assert real == "T3" and alias not in CANON, "алиас сменил смысл — перепроверь тест"
    bad = _disagreements(_rows_from(_fixture(**{alias: "T1"})))
    assert bad == {alias: ("T1", "T3")}
