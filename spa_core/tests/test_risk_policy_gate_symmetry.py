"""ХАРАКТЕРИЗАЦИОННЫЙ тест: симметрия порогов RiskPolicy между путём ВХОДА
(``check_new_position``) и путём ПРОВЕРКИ КНИГИ (``check_portfolio_health``).

    ЭТО ФИКСАЦИЯ ТЕКУЩЕГО ПОВЕДЕНИЯ, А НЕ ЕГО ОДОБРЕНИЕ.

Ни один assert ниже не утверждает, что молчание портфельного пути ПРАВИЛЬНО.
Каждый утверждает лишь то, что оно ИЗМЕРЕНО и с этого момента ВИДИМО: если
кто-то добавит недостающую проверку — тест покраснеет и потребует осознанного
решения (ADR + владелец), а не проскочит незамеченным. Обратное тоже верно:
если кто-то УБЕРЁТ одну из немногих симметричных проверок (позитивные контроли
ниже), тест тоже покраснеет. Инвариант 16 CLAUDE.md соблюдён: тест ничего не
ослабляет, он делает заметным то, что раньше было невидимо.

Замер 2026-08-18 (карточка
``nimbalyst-local/tracker/agent-t2-total-cap-ne-proveryaetsya-na-portfele.md``).
Отправная точка карточки — «T2 суммарно ≤ 50 % не перепроверяется на портфеле» —
воспроизведена и подтверждена, но класс оказался ШИРЕ одного порога: из
проверяемых RiskPolicy порогов симметричны как VIOLATION на обоих путях только
per-protocol концентрация (T1 40 % / T2 20 %) и лестница просадки. Остальные
либо молчат на портфельном пути, либо понижены там до warning (approved=True).

ПОЧЕМУ ЭТО НЕ ЧИСТО ТЕОРЕТИЧЕСКИ. Тир — ДИНАМИЧЕСКИЙ (ADR-055: кураторы двигают
протоколы T3↔T2↔T1), поэтому книга может нарушить суммарный потолок БЕЗ единой
сделки — достаточно демоушена уже удерживаемого протокола. Путь входа такую
книгу никогда не увидит: он проверяет только приращение.

ЧТО ЗДЕСЬ НЕ ПРОВЕРЯЕТСЯ. Второй портфельный сторож —
``policy_enforcer.validate_positions`` (ADR-062) — суммарный T2/T3 на КНИГЕ
проверяет. Его покрытие пришпилено отдельно
(``test_policy_enforcer_coverage_caps.py``), и здесь не дублируется. Но он
считает тир по СТАТИЧЕСКИМ литеральным множествам ``T1_ADAPTERS``/``T3_ADAPTERS``
и потому слеп ровно к тому сценарию динамического демоушена, ради которого
портфельная перепроверка и нужна; это зафиксировано последним тестом файла.

Пороги НЕ МЕНЯЮТСЯ (RiskPolicy v1.0). Тест детерминированный и офлайновый:
никаких обращений к ``data/``, сети или живому реестру.
"""
from __future__ import annotations

import pytest

from spa_core.risk.policy import (
    Position,
    PortfolioState,
    RiskConfig,
    RiskPolicy,
)

CAP = 100_000.0
CFG = RiskConfig()


def _pos(key: str, tier: str, pct: float, chain: str = "ethereum",
         pnl_pct: float = 0.0, apy: float = 5.0) -> Position:
    amount = CAP * pct
    return Position(
        protocol_key=key,
        tier=tier,
        asset="USDC",
        amount_usd=amount,
        apy_at_open=apy,
        current_apy=apy,
        unrealized_pnl_usd=amount * pnl_pct,
        days_held=30.0,
        chain=chain,
    )


def _book(*positions: Position) -> PortfolioState:
    return PortfolioState(total_capital_usd=CAP, positions=list(positions))


def _health(state: PortfolioState):
    # check_capacity/ check_axes off: they need external maps and are warn-only,
    # so they cannot influence the approved verdict this test characterises.
    return RiskPolicy().check_portfolio_health(state, check_capacity=False)


def _mentions(messages, *needles) -> bool:
    joined = " ".join(messages).lower()
    return all(n.lower() in joined for n in needles)


# ── Позитивные контроли: пороги, которые ДЕЙСТВИТЕЛЬНО симметричны ──────────
# Они здесь не для красоты: без них файл нельзя было бы отличить от теста,
# который просто утверждает «портфельный путь ничего не проверяет».

def test_positive_control_per_protocol_t1_cap_is_symmetric():
    """T1 40 % на протокол — VIOLATION и на входе, и на портфеле."""
    entry = RiskPolicy().check_new_position(
        _book(_pos("aave_v3", "T1", 0.30)),
        "aave_v3", "T1", CAP * 0.15, current_apy=5.0, tvl_usd=500e6,
    )
    assert entry.approved is False
    assert _mentions(entry.violations, "concentration")

    health = _health(_book(_pos("aave_v3", "T1", 0.45), _pos("morpho_blue", "T2", 0.10)))
    assert health.approved is False
    assert _mentions(health.violations, "concentration breach", "aave_v3")


def test_positive_control_per_protocol_t2_cap_is_symmetric():
    """T2 20 % на протокол — VIOLATION и на входе, и на портфеле."""
    entry = RiskPolicy().check_new_position(
        _book(_pos("morpho_blue", "T2", 0.10)),
        "morpho_blue", "T2", CAP * 0.15, current_apy=5.0, tvl_usd=500e6,
    )
    assert entry.approved is False

    health = _health(_book(_pos("morpho_blue", "T2", 0.25), _pos("aave_v3", "T1", 0.30)))
    assert health.approved is False
    assert _mentions(health.violations, "concentration breach", "morpho_blue")


def test_positive_control_drawdown_ladder_is_symmetric():
    """Лестница просадки (ADR-034/048) блокирует оба пути — де-риск быстрый."""
    drawn = _book(_pos("aave_v3", "T1", 0.40, pnl_pct=-0.15))  # −6 % от капитала
    entry = RiskPolicy().check_new_position(
        drawn, "morpho_blue", "T2", CAP * 0.10, current_apy=5.0, tvl_usd=500e6,
    )
    assert entry.approved is False
    assert _mentions(entry.violations, "drawdown")

    health = _health(drawn)
    assert health.approved is False
    assert health.drawdown_tier == "SOFT_DERISK"


# ── Класс А: порог есть на входе и ПОЛНОСТЬЮ отсутствует на портфеле ────────

def test_measured_t2_total_cap_absent_from_portfolio_path():
    """Отправная точка карточки, перемерена: книга 60 % в T2 одобряется.

    ФИКСАЦИЯ, НЕ ОДОБРЕНИЕ. Вход третьего T2 отказывает, книга — нет.

    ИЗМЕНЕНО 2026-08-19 (инвариант 16 CLAUDE.md — намеренно, с обоснованием).
    Гейт НЕ ТРОНУТ: `approved is True` и `violations == []` остались как были,
    и именно они охраняют money-path. Ослаблен ровно один assert —
    «портфельный путь не упоминает T2» → «упоминает, но только в warnings».
    Причина: в `check_portfolio_health` добавлено НАБЛЮДЕНИЕ `T2_TOTAL_WARN`
    (warn-only), чтобы нарушение потолка на книге НАЗЫВАЛОСЬ. Разница
    «не проверяем» → «проверяем и называем, но не гейтим» сохранена и теперь
    закреплена в обе стороны: если наблюдение исчезнет — тест краснеет; если
    оно превратится в violation — краснеет тоже. Запись в
    `docs/journal/2026-W34.md`.
    """
    pre = _book(
        _pos("aave_v3", "T1", 0.35),
        _pos("morpho_blue", "T2", 0.20),
        _pos("euler_v2", "T2", 0.20),
    )
    entry = RiskPolicy().check_new_position(
        pre, "pendle", "T2", CAP * 0.20, current_apy=8.0, tvl_usd=500e6,
    )
    assert entry.approved is False
    assert _mentions(entry.violations, "total t2 allocation"), entry.violations

    breached = _book(*pre.positions, _pos("pendle", "T2", 0.20))
    assert breached.t2_allocation_pct() == pytest.approx(0.60)
    assert breached.t2_allocation_pct() > CFG.max_total_t2_allocation

    health = _health(breached)
    # ИЗМЕРЕНО 2026-08-18: approved=True, violations=[], warnings=[].
    assert health.approved is True, (
        "Портфельный путь начал проверять суммарный T2 — это ИЗМЕНЕНИЕ money-path. "
        "Обновить этот характеризационный тест можно только вместе с ADR и решением "
        "владельца (см. карточку agent-t2-total-cap-ne-proveryaetsya-na-portfele.md)."
    )
    assert health.violations == []
    # Наблюдение (не гейт): нарушение названо в warnings и НИГДЕ больше.
    assert _mentions(health.warnings, "t2_total_warn"), health.warnings
    assert not _mentions(health.violations, "t2")


def test_measured_t3_total_cap_absent_from_both_paths():
    """T3 суммарно ≤ 15 % (ADR-020) в RiskPolicy не проверяется ВООБЩЕ.

    На входе блок суммарного потолка гейтит только ``tier == "T2"``
    (policy.py, «8. Лимит T2 совокупно»), поэтому T3 мимо него проходит;
    на портфеле суммарных потолков нет вовсе. Единственный, кто считает
    ``t3_max_pct`` на книге, — ``policy_enforcer`` (другая поверхность,
    свой статический тир-мап).
    """
    pre = _book(
        _pos("aave_v3", "T1", 0.40),
        _pos("susde", "T3", 0.15),
        _pos("stusd", "T3", 0.15),
    )
    entry = RiskPolicy().check_new_position(
        pre, "usual_usd0pp", "T3", CAP * 0.15, current_apy=9.0, tvl_usd=500e6,
    )
    assert entry.approved is True, entry.violations
    assert not _mentions(entry.violations, "t3")

    breached = _book(*pre.positions, _pos("usual_usd0pp", "T3", 0.15))
    t3_total = sum(p.amount_usd for p in breached.positions if p.tier == "T3") / CAP
    assert t3_total == pytest.approx(0.45)
    assert t3_total > CFG.max_total_t3_allocation

    health = _health(breached)
    assert health.approved is True
    assert not _mentions(health.violations + health.warnings, "t3")


def test_measured_l2_total_cap_absent_from_portfolio_path():
    """L2 суммарно ≤ 50 %: VIOLATION на входе, тишина на портфеле."""
    pre = _book(
        _pos("aave_arbitrum", "T1", 0.35, chain="arbitrum"),
        _pos("aave_v3", "T1", 0.40, chain="ethereum"),
    )
    entry = RiskPolicy().check_new_position(
        pre, "moonwell_base", "T2", CAP * 0.20,
        current_apy=6.0, tvl_usd=500e6, chain="base",
    )
    assert entry.approved is False
    assert _mentions(entry.violations, "total l2 allocation")

    breached = _book(*pre.positions, _pos("moonwell_base", "T2", 0.20, chain="base"))
    assert breached.l2_allocation_pct() == pytest.approx(0.55)
    assert breached.l2_allocation_pct() > CFG.max_l2_total_allocation

    health = _health(breached)
    assert health.approved is True
    assert not _mentions(health.violations, "l2")


def test_measured_apy_bounds_absent_from_portfolio_path():
    """Коридор APY 1…30 % проверяется только при входе.

    Доходность позиции ДРЕЙФУЕТ после входа (``current_apy`` — живое поле),
    но портфельный путь его не смотрит: ни 45 %, ни 0.2 % не порождают ни
    violation, ни warning.
    """
    hot = _pos("morpho_blue", "T2", 0.20, apy=45.0)
    cold = _pos("euler_v2", "T2", 0.20, apy=0.2)

    entry_hot = RiskPolicy().check_new_position(
        _book(_pos("aave_v3", "T1", 0.40)),
        "morpho_blue", "T2", CAP * 0.20, current_apy=45.0, tvl_usd=500e6)
    entry_cold = RiskPolicy().check_new_position(
        _book(_pos("aave_v3", "T1", 0.40)),
        "euler_v2", "T2", CAP * 0.20, current_apy=0.2, tvl_usd=500e6)
    assert entry_hot.approved is False and _mentions(entry_hot.violations, "apy")
    assert entry_cold.approved is False and _mentions(entry_cold.violations, "apy")

    health = _health(_book(_pos("aave_v3", "T1", 0.40), hot))
    assert health.approved is True
    assert not _mentions(health.violations + health.warnings, "apy")

    health_cold = _health(_book(_pos("aave_v3", "T1", 0.40), cold))
    assert health_cold.approved is True
    assert not _mentions(health_cold.violations + health_cold.warnings, "apy")


def test_measured_tvl_floor_has_no_portfolio_equivalent():
    """TVL-floor $5M — вход-only СТРУКТУРНО: у ``check_portfolio_health``
    вообще нет аргумента с живым TVL позиции (``tvl_map`` идёт только в
    warn-only capacity-проверку). Просевший TVL уже удерживаемого пула
    портфельным путём не виден.
    """
    import inspect

    entry = RiskPolicy().check_new_position(
        _book(_pos("aave_v3", "T1", 0.40)),
        "morpho_blue", "T2", CAP * 0.20, current_apy=5.0, tvl_usd=1_000_000.0)
    assert entry.approved is False
    assert _mentions(entry.violations, "tvl")

    sig = inspect.signature(RiskPolicy.check_portfolio_health)
    assert "tvl_usd" not in sig.parameters
    assert "tvl_map" in sig.parameters  # только warn-only capacity (ADR-009)

    health = _health(_book(_pos("aave_v3", "T1", 0.40), _pos("morpho_blue", "T2", 0.20)))
    assert health.approved is True
    assert not _mentions(health.violations, "tvl")


def test_measured_max_protocols_absent_from_riskpolicy_entirely():
    """``max_protocols`` (ALLOC-002, 8 позиций) не проверяется НИ на входе,
    НИ на портфеле — только аллокатором/тюнером и ``policy_enforcer``.

    На входе девятая позиция отказывает по кэш-буферу, а НЕ по числу
    протоколов — легко принять одно за другое, поэтому проверяем текст.
    """
    nine = [
        _pos("aave_v3", "T1", 0.10), _pos("compound_v3", "T1", 0.10),
        _pos("morpho_blue", "T2", 0.10), _pos("euler_v2", "T2", 0.10),
        _pos("pendle", "T2", 0.10), _pos("maple", "T2", 0.10),
        _pos("yearn_v3", "T2", 0.10), _pos("clearpool", "T2", 0.05),
        _pos("goldfinch", "T2", 0.05),
    ]
    assert len(nine) > CFG.max_protocols

    entry = RiskPolicy().check_new_position(
        _book(*nine[:-1]), "goldfinch", "T2", CAP * 0.05,
        current_apy=5.0, tvl_usd=500e6)
    assert not _mentions(entry.violations, "protocols"), entry.violations

    health = _health(_book(*nine))
    assert not _mentions(health.violations + health.warnings, "protocols")


# ── Класс Б: порог есть на обоих путях, но на портфеле ПОНИЖЕН до warning ───
# Опаснее молчания: отчёт выглядит «пройденным» (approved=True), а нарушение
# лежит в warnings, где его никто не гейтит.

def test_measured_cash_floor_is_downgraded_to_warning_on_portfolio_path():
    """Кэш-буфер 5 %: VIOLATION при входе → WARNING на портфеле."""
    entry = RiskPolicy().check_new_position(
        _book(_pos("aave_v3", "T1", 0.40), _pos("compound_v3", "T1", 0.40)),
        "morpho_blue", "T2", CAP * 0.18, current_apy=5.0, tvl_usd=500e6)
    assert entry.approved is False
    assert _mentions(entry.violations, "cash buffer")

    thin = _book(_pos("aave_v3", "T1", 0.40), _pos("compound_v3", "T1", 0.40),
                 _pos("morpho_blue", "T2", 0.18))
    assert thin.cash_pct == pytest.approx(0.02)

    health = _health(thin)
    assert health.approved is True          # ← понижение, а не отсутствие
    assert _mentions(health.warnings, "cash buffer")
    assert not _mentions(health.violations, "cash buffer")


def test_measured_single_chain_cap_is_downgraded_to_warning_on_portfolio_path():
    """Single-chain 90 %: VIOLATION при входе → warn-only на портфеле.

    На портфеле сообщение приходит из ДРУГОГО источника — warn-only
    MP-203 ``chain_limits``, а не из ``max_single_chain_allocation``.
    """
    pre = _book(_pos("aave_v3", "T1", 0.35), _pos("morpho_blue", "T2", 0.20),
                _pos("euler_v2", "T2", 0.20))
    entry = RiskPolicy().check_new_position(
        pre, "compound_v3", "T1", CAP * 0.20, current_apy=5.0, tvl_usd=500e6)
    assert entry.approved is False
    assert _mentions(entry.violations, "chain concentration")

    breached = _book(*pre.positions, _pos("compound_v3", "T1", 0.20))
    assert breached.chain_allocation_pct("ethereum") == pytest.approx(0.95)

    health = _health(breached)
    assert health.approved is True
    assert _mentions(health.warnings, "chain_limit_warn")
    assert health.violations == []


# ── Почему второй сторож не закрывает класс ────────────────────────────────

def test_measured_enforcer_book_check_is_blind_to_dynamic_tier_demotion():
    """``policy_enforcer`` считает суммарный T2 на книге — но по СТАТИЧЕСКИМ
    множествам имён, а не по фактическому тиру позиции.

    Сценарий ADR-055 (кураторы демоутят удерживаемый протокол T1 → T2):
    фактический суммарный T2 = 75 % при потолке 50 %, и МОЛЧАТ ОБА
    портфельных сторожа — RiskPolicy потому, что проверки нет, а enforcer
    потому, что для него это по-прежнему T1. ФИКСАЦИЯ, НЕ ОДОБРЕНИЕ.
    """
    from spa_core.risk.policy_enforcer import (
        T1_ADAPTERS,
        _normalize_tier,
        validate_positions,
    )

    demoted = {"aave_v3": 20_000.0, "compound_v3": 20_000.0,
               "spark_susds": 15_000.0}
    book_usd = dict(demoted, morpho_blue=20_000.0)   # 75 % размещено, 25 % кэш

    for key in demoted:
        assert key in T1_ADAPTERS
        assert _normalize_tier(key) == "T1"          # ← куратор для него не существует

    state = _book(*[_pos(k, "T2", v / CAP) for k, v in book_usd.items()])
    assert state.t2_allocation_pct() == pytest.approx(0.75)
    assert state.t2_allocation_pct() > CFG.max_total_t2_allocation

    health = _health(state)
    assert health.approved is True
    assert health.violations == []

    enforced = validate_positions(
        book_usd, CAP, cash_usd=25_000.0,
        chain_map={k: "ethereum" for k in book_usd},
    )
    assert enforced.passed is True
    assert [v.rule for v in enforced.violations] == []
