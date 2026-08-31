#!/usr/bin/env python3
"""Deterministic RiskPolicy gate for the paper-trading cycle (N12 decomposition).

PURE-MOVE EXTRACTION from ``cycle_runner.py``: the MP-005 RiskPolicy gate, the
ALLOC-002 pre-diff compliant-target collapse, the policy-block audit writer and
the policy-version helper. Bodies are byte-identical to their originals — no
behaviour change. ``cycle_runner`` re-exports every name below for back-compat.

LLM FORBIDDEN — deterministic, pure in-memory checks (the gate reads no files,
writes no files and touches no capital). stdlib only.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

from spa_core.paper_trading._cycle_io import (
    MAX_POLICY_BLOCKS,
    POSITIONS_FILENAME,
    RISK_BLOCKS_FILENAME,
    _atomic_write_json,
    _read_json,
)

log = logging.getLogger("spa.cycle_runner")


_NON_FINITE_SENTINEL = float("nan")


def _coerce_feed_value(value) -> float:
    """Coerce a feed value to float, FAIL-CLOSED on a *present* non-finite value.

    Replaces the old ``float(value or 0.0)`` idiom, which was the NaN bypass:
    NaN is truthy so ``nan or 0.0`` → nan, and that non-finite value then
    defeated EVERY RiskPolicy bounds comparison (NaN compares always False).

    Semantics (preserving the legitimate "not provided → 0.0 → registry
    fallback" path that the gate already handles):
      * None / missing / non-numeric  → ``0.0`` (treated as "not provided";
        the MP-1180 registry-fallback path fills it, exactly as before).
      * a finite number               → that number.
      * a PRESENT NaN / Inf           → ``float('nan')`` sentinel so the caller
        rejects it (a corrupt feed must NOT be silently masked as 0.0).
    """
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    fv = float(value)
    return fv if math.isfinite(fv) else _NON_FINITE_SENTINEL


def _compliant_target(
    target_usd: dict[str, float],
    capital_usd: float,
    ddir: "Path",
    write: bool,
) -> tuple[dict[str, float], bool]:
    """ALLOC-002: collapse the raw allocator target to a policy-compliant book
    *before* the rebalance diff is computed.

    ROOT-CAUSE FIX (allocation oscillation): ``StrategyAllocator.allocate()`` has
    per-protocol concentration caps but NO protocol-*count* cap, so it natively
    emits ~24 protocols. Previously the rebalance diff compared the persisted
    ≤8-protocol book against this fresh 24-protocol target → always a large diff
    → a phantom ~$122K rebalance every cycle, then ALLOC-002 collapsed the book
    to ≤8 *after* the trade was already recorded. The next cycle's allocator
    emitted 24 again → endless 24↔8 churn on an unchanged market.

    This helper makes the count-capped, policy-compliant book the *target* the
    diff is computed against. When the raw target already passes the enforcer it
    is returned unchanged. When it violates (e.g. ``max_protocols`` / ``t1_min``)
    we derive the compliant book from the DETERMINISTIC ``portfolio_rebalancer``
    (``random.Random(42)`` candidate search + deterministic safe-fallback). Same
    market data → same compliant book every cycle → held-compliant vs
    new-compliant diff ≈ 0 (no phantom turnover).

    Returns ``(compliant_target, was_collapsed)``. Fail-open: any error returns
    the original target unchanged (ALLOC-002 post-check still guards the write).
    """
    try:
        from spa_core.risk.policy_enforcer import validate_positions as _pe
        _cash = capital_usd - sum(target_usd.values())
        _chk = _pe(positions=target_usd, capital_usd=capital_usd, cash_usd=_cash)
        if _chk.passed:
            return target_usd, False
        # Scope: this pre-diff collapse targets the OSCILLATION root cause —
        # the protocol-*count* explosion (~24 protocols) that the allocator has
        # no native cap for. Other policy violations (per-protocol concentration,
        # t1_min, etc.) on an already-small book are left to the existing gate +
        # post-write ALLOC-002 check (unchanged behaviour). We only intervene
        # pre-diff when the count cap is breached, which is what flaps the diff.
        _viol_rules = {v.rule for v in _chk.violations}
        if "max_protocols" not in _viol_rules:
            return target_usd, False
        # Over-diversified raw target: derive the deterministic compliant book
        # from the rebalancer.
        from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio as _rb
        if _rb(capital_usd=capital_usd, data_dir=ddir, write=write, send_alert=False):
            _pos = (
                _read_json(ddir / POSITIONS_FILENAME, {}).get("positions", {}) or {}
            )
            if _pos:
                _c = _pe(
                    positions=_pos,
                    capital_usd=capital_usd,
                    cash_usd=capital_usd - sum(float(v) for v in _pos.values()),
                )
                if _c.passed:
                    return {str(p): float(v) for p, v in _pos.items()}, True
        # Rebalancer could not produce a compliant book (e.g. no adapter snapshot
        # available). Fall back to the DETERMINISTIC known-good safe portfolio so
        # the cycle output is STILL count-capped and stable — never the raw
        # 24-protocol target. This is the same hardcoded book the rebalancer uses
        # as its own fallback, validated below before adoption.
        from spa_core.tuner.portfolio_rebalancer import (
            _build_safe_fallback_positions as _safe,
        )
        _safe_pos, _safe_cash = _safe(capital_usd)
        _safe_chk = _pe(
            positions=_safe_pos, capital_usd=capital_usd, cash_usd=_safe_cash
        )
        if _safe_chk.passed:
            return {str(p): float(v) for p, v in _safe_pos.items()}, True
        # Even the safe fallback failed validation — keep raw target; the
        # downstream ALLOC-002 post-check still guards the persisted write.
        return target_usd, False
    except Exception as exc:  # noqa: BLE001 — fail-open, never break the cycle
        log.warning("ALLOC-002: pre-diff compliant collapse skipped (%s)", exc)
        return target_usd, False


def hold_reason(diff_usd: float, threshold_usd: float, *, churn_allowed: bool,
                churn_detail: str = "", safety_failed: bool = False,
                policy_blocked: bool = False) -> str:
    """Почему книга НЕ переложена — настоящая причина, а не первая попавшаяся.

    Замер 30.08: цикл печатал «no rebalance: |Δ|=$28,684 ≤ $200 threshold» — утверждение
    ложное ($28 684 не меньше $200). Строка писалась БЕЗУСЛОВНО в else-ветке, хотя
    удержаний четыре: не прошла проверка безопасности, заблокировала политика, дельта
    ниже порога и не пустил анти-черн (ADR-168). Настоящей в тот раз была четвёртая.

    Читатель такого отчёта чинит не то. Меня самого эта строка едва не увела: я искал
    ошибку в вычислении дельты там, где капитал держал 72-часовой демпфер.
    """
    if safety_failed:
        return "не переложено: проверка безопасности не выполнилась — держим позиции (LAW 1)"
    if policy_blocked:
        return "не переложено: заблокировано политикой риска"
    if not churn_allowed:
        return (f"не переложено: анти-черн не пустил (ADR-168) — {churn_detail}; "
                f"перераздача одобрена и ждёт, |Δ|=${diff_usd:,.0f}")
    return f"no rebalance: |Δ|=${diff_usd:,.0f} ≤ ${threshold_usd:,.0f} threshold."


def _sequential_remainder(capital: float, target: dict[str, float]) -> float:
    """Остаток так, КАК ЕГО СЧИТАЕТ ГЕЙТ: по одной ноге, в его порядке.

    Порядок гейта — по убыванию суммы, затем по имени (см. `_apply_risk_policy_gate`).
    Совпадение с ним обязательно: спор об отказе идёт о последних битах, и другой
    порядок сложения даёт другой ответ на том же наборе чисел.
    """
    prior: list[float] = []
    cash = float(capital)
    for _pool, usd in sorted(target.items(), key=lambda kv: (-kv[1], kv[0])):
        # ИМЕННО ТАК, как считает гейт: `cash_usd` это `капитал − sum(позиции)`,
        # то есть на каждой ноге остаток = `капитал − sum(предыдущие) − сумма`,
        # а НЕ последовательное вычитание. Разница — в последних битах, и ровно
        # она решила исход 29.08: сумма-и-вычесть давала ровно 5000.0, а способ
        # гейта — 4999.999999999996, то есть отказ. Пока запись считала иначе,
        # она оправдывала цель, которую гейт отверг.
        cash = float(capital) - sum(prior) - float(usd)
        prior.append(float(usd))
    return cash


def redistribution_refusal_record(target_usd: dict[str, float],
                                  capital_usd: float,
                                  added: dict[str, float] | None,
                                  violations, error=None,
                                  gate_target: dict[str, float] | None = None) -> dict:
    """Машинный след отказа повторного гейта (ADR-072). Отказ обязан быть ПРОВЕРЯЕМЫМ.

    Замер 29.08: три цикла подряд отказ «cash buffer 5.0% < minimum 5.0%» оставлял
    33.7 % капитала без работы (дневная доходность 4.21 % → 3.17 %), и воспроизвести
    его снаружи не удалось НИ РАЗУ: три независимые реконструкции дают остаток
    5000.000000000001, а вызов настоящего гейта на восстановленной цели — APPROVED.
    Значит гейт судил по цели, которой в отчёте не было. Мандат владельца 29.08:
    сделать отказ проверяемым.

    Возвращает то, чего не хватало: САМУ поданную цель, её сумму, капитал (знаменатель
    буфера) и добавленные ноги. Ничего не решает — только называет.
    """
    # НЕ ОКРУГЛЯТЬ. Первая версия записи (29.08) округляла ноги до центов — и
    # первый же живой отказ стал невоспроизводимым: сумма вышла ровно 95 000.00,
    # остаток ровно 5 000.00 = 5.0 %, а гейт при этом отказал. Спор идёт о
    # ПОСЛЕДНИХ БИТАХ (ноги — точные девятнадцатые доли вроде 6578.947368421053),
    # и округление стёрло ровно ту улику, ради которой запись и строилась.
    # Округлённые числа остаются рядом — они для человека, сырые для арифметики.
    raw = {k: float(v) for k, v in sorted((target_usd or {}).items())}
    raw_total = sum(raw.values())
    tgt = {k: round(v, 2) for k, v in raw.items()}
    total = round(raw_total, 2)
    cap = float(capital_usd)
    return {
        "capital_usd": round(cap, 2),
        "submitted_sum_usd": total,
        "legs": len(tgt),
        "submitted_target": tgt,
        "added": {k: round(float(v), 2) for k, v in sorted((added or {}).items())},
        # Остаток и его доля — ровно те числа, о которых спорит отказ.
        "remaining_cash_usd": round(cap - raw_total, 2),
        "remaining_cash_pct": (round((cap - raw_total) / cap * 100.0, 4) if cap else None),
        # Сырьё для арифметики до последнего бита: по этим числам отказ обязан
        # воспроизводиться повторным вычитанием, иначе спорить не о чем.
        "raw_target": {k: repr(v) for k, v in raw.items()},
        "raw_sum": repr(raw_total),
        # ДВА РАЗНЫХ ЧИСЛА, и в этом весь смысл. «Сложить и вычесть один раз» и
        # «вычитать по одной ноге» расходятся в последних битах, а гейт вычитает
        # ПОСЛЕДОВАТЕЛЬНО, в своём порядке (по убыванию суммы, затем по имени).
        # Первая версия записи считала первым способом и потому показывала чистые
        # 5 000.00 там, где гейт видел меньше, — запись оправдывала цель, которую
        # гейт отверг. Теперь записываются оба, и спорить есть о чём предметно.
        "raw_remaining_naive": repr(cap - raw_total),
        "raw_remaining_sequential": repr(_sequential_remainder(cap, raw)),
        "raw_remaining_frac": (repr(_sequential_remainder(cap, raw) / cap) if cap else None),
        "violations": list(violations or []),
        "error": error,
        # ЧТО ГЕЙТ ВЕРНУЛ САМ. Живой отказ 29.08 дал остаток РОВНО 5000.0 и долю РОВНО
        # 0.05 — а `0.05 < 0.05` ложь, то есть на ПОДАННОЙ цели отказывать было не за
        # что. Значит внутри гейт работает с изменённым набором (потолки ёмкости,
        # заморозка непроверенного TVL, подрезка под буфер). Пока не видно, чем именно
        # он отличается, спор упирается в невидимое.
        "gate_target": ({k: repr(float(v)) for k, v in sorted(gate_target.items())}
                        if gate_target else None),
        "gate_sum": (repr(sum(float(v) for v in gate_target.values()))
                     if gate_target else None),
        "gate_differs_from_submitted": (
            None if gate_target is None
            else {k: [repr(raw.get(k)), repr(float(v))]
                  for k, v in sorted(gate_target.items())
                  if k not in raw or float(v) != raw[k]}),
    }


def _apply_risk_policy_gate(
    target_usd: dict[str, float],
    capital_usd: float,
    adapters: list[dict],
    ddir: "Path | None" = None,
    current_positions: "dict[str, float] | None" = None,
) -> dict:
    """Validate the allocator's target against ``RiskPolicy`` (MP-005).

    The target is replayed position-by-position through
    ``RiskPolicy.check_new_position()`` on a fresh ``PortfolioState`` so the
    cumulative limits (per-protocol concentration, total-T2 cap, cash buffer)
    see the *whole* target allocation, not just one trade.

    min-cash handling: a target that deploys past ``1 - min_cash_pct`` of
    capital is trimmed proportionally instead of blocked (per MP-005 spec).

    TVL-floor verification (ADR-053, fail-CLOSED): the $5M TVL floor is only
    checked against a TVL the adapter snapshot DECLARED live
    (``tvl_source == "live"`` and a finite positive value). A pool whose TVL is
    missing, zero, or a static/committed constant cannot verify the floor →
    it receives NO fresh capital: its target is capped at the currently-held
    amount (hold + reduce stay allowed) and it is dropped from the target when
    not held. The pre-ADR-053 behaviour — substituting a fabricated $20M that
    always passed the floor — is removed; no TVL value is ever invented.

    Returns a dict::

        approved       bool — False → the rebalance trade must NOT be recorded
        violations     list[str] — blocking violations ("<pool>: <reason>")
        warnings       list[str] — non-blocking policy warnings
        trimmed        bool — target was scaled down to the min-cash buffer
        target_usd     dict — the (possibly trimmed/TVL-capped) allocation
        tvl_unverified list[str] — pools frozen fail-closed (no live TVL)
        error          str | None — the gate itself failed → fail-closed (FIX-P0)

    Never raises: any unexpected exception is captured into ``error`` so a
    broken gate degrades to a logged WARNING and a BLOCKED trade (fail-closed).
    Previously this was fail-open; changed to fail-closed for live-capital safety.
    """
    out: dict = {
        "approved": True,
        "violations": [],
        "warnings": [],
        "trimmed": False,
        "target_usd": dict(target_usd),
        "tvl_unverified": [],
        "error": None,
    }
    try:
        from spa_core.risk.policy import PortfolioState, Position, RiskPolicy

        policy = RiskPolicy()
        cfg = policy.config

        meta: dict[str, dict] = {}
        for a in adapters:
            if isinstance(a, dict) and a.get("protocol"):
                meta[str(a["protocol"])] = a

        # ── MP-1180: load adapter_registry.json fallbacks (APY only) ────────
        # When the live orchestrator returns apy=None (network errors), the
        # gate sees APY=0% → policy_blocked=True → 0 trades. We resolve this by
        # loading researched fallback APY values from the registry (keyed by
        # snake_case adapter name, matching target_usd keys). fallback_apy is a
        # decimal fraction (0.035 = 3.5%) converted to percentage units for
        # RiskPolicy.check_new_position(). TVL is NOT taken from the registry
        # (ADR-053): a registry literal cannot verify the $5M floor — a pool
        # without a live TVL is frozen fail-closed below, never given $20M.
        _reg_fallbacks: dict[str, dict] = {}
        if ddir is not None:
            try:
                _reg_doc = _read_json(Path(ddir) / "adapter_registry.json", {})
                if isinstance(_reg_doc, dict):
                    _reg_adapters = _reg_doc.get("adapters", {})
                    if isinstance(_reg_adapters, dict):
                        _reg_fallbacks = {
                            k: v
                            for k, v in _reg_adapters.items()
                            if isinstance(v, dict)
                        }
            except Exception as _rfb_exc:
                log.warning(
                    "MP-1180 registry fallback load failed (%s) — gate continues",
                    _rfb_exc,
                )

        # FAIL-CLOSED (architect P5-1): drop bool and keep only FINITE positive
        # amounts. `Inf > 0` is True, so a non-finite amount could otherwise reach
        # the gate and defeat the cash/concentration bounds (NaN/Inf comparisons).
        # Non-finite target amounts are refused here (excluded from the deployed
        # book) and recorded as a violation below.
        adjusted = {
            str(p): float(v)
            for p, v in target_usd.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(float(v)) and float(v) > 0
        }
        non_finite_amounts = [
            str(p)
            for p, v in target_usd.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
            and not math.isfinite(float(v))
        ]

        # ── ADR-053: TVL-floor verification (fail-CLOSED per pool) ───────────
        # A pool may satisfy the $5M floor ONLY with a TVL the adapter snapshot
        # declared live (tvl_source == "live", finite, > 0). Missing / zero /
        # static-constant TVL cannot be verified → the pool gets NO fresh
        # capital: target capped at the currently-held amount (hold + reduce
        # stay allowed), dropped entirely when not held. A PRESENT non-finite
        # TVL is left to the replay loop below, which records it as a blocking
        # violation (corrupt feed ≠ merely missing feed).
        _held_map: dict[str, float] = {
            str(k): float(v)
            for k, v in (current_positions or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(float(v)) and float(v) > 0
        }
        _tvl_frozen: set[str] = set()
        warnings: list[str] = []
        for pool in sorted(adjusted):
            m = meta.get(pool, {})
            tvl_probe = _coerce_feed_value(m.get("tvl_usd"))
            if not math.isfinite(tvl_probe):
                continue  # present-but-corrupt → blocking violation in the loop
            tvl_is_live = (
                m.get("tvl_source") == "live" and tvl_probe > 0
            )
            if tvl_is_live:
                continue
            src = m.get("tvl_source") or ("missing" if tvl_probe == 0.0 else "static")
            held = _held_map.get(pool, 0.0)
            capped = min(adjusted[pool], held)
            _tvl_frozen.add(pool)
            if capped > 0:
                adjusted[pool] = capped
                warnings.append(
                    f"{pool}: TVL unverified ({src}) — fail-closed: no fresh "
                    f"allocation, target capped at held ${capped:,.0f}"
                )
            else:
                del adjusted[pool]
                warnings.append(
                    f"{pool}: TVL unverified ({src}) — fail-closed: excluded "
                    "from fresh allocation (not held)"
                )
        if _tvl_frozen:
            log.warning(
                "ADR-053: TVL unverified for %s — fail-closed, no fresh capital",
                sorted(_tvl_frozen),
            )

        # min_cash: trim to the deployable maximum, do not block (MP-005 spec).
        # floor() keeps the trimmed total strictly ≤ the cap despite rounding.
        max_deploy = capital_usd * (1.0 - cfg.min_cash_pct)
        total = sum(adjusted.values())
        if total > max_deploy and total > 0:
            scale = max_deploy / total
            adjusted = {
                p: math.floor(v * scale * 100) / 100.0 for p, v in adjusted.items()
            }
            out["trimmed"] = True

        state = PortfolioState(total_capital_usd=capital_usd, positions=[])
        violations: list[str] = []
        for _p in non_finite_amounts:
            violations.append(f"{_p}: non-finite target amount refused (fail-closed)")
        for pool, usd in sorted(adjusted.items(), key=lambda kv: (-kv[1], kv[0])):
            m = meta.get(pool, {})
            tier = str(m.get("tier") or "T2").upper()
            # FAIL-CLOSED finiteness coercion (architect P5-1). The previous
            # `float(m.get("apy_pct") or 0.0)` was a NaN bypass: NaN is truthy so
            # `nan or 0.0` → nan, and that non-finite value then defeated EVERY
            # bounds check in RiskPolicy (NaN compares always False). A PRESENT
            # non-finite feed value (NaN/Inf) must be REJECTED, not silently
            # masked as 0.0 (which would also defeat the bad-feed detection).
            # Missing/None stays 0.0 → the MP-1180 registry-fallback path below
            # fills it, exactly as before (no behaviour change for that path).
            apy = _coerce_feed_value(m.get("apy_pct"))
            tvl = _coerce_feed_value(m.get("tvl_usd"))
            if not math.isfinite(apy):
                violations.append(f"{pool}: non-finite feed apy_pct={m.get('apy_pct')!r}")
            if not math.isfinite(tvl):
                violations.append(f"{pool}: non-finite feed tvl_usd={m.get('tvl_usd')!r}")
            # Chain-level limits apply only when the adapter reports its chain.
            # Without it, a per-pool placeholder prevents the single-chain cap
            # from falsely lumping every pool onto "ethereum".
            chain = str(m.get("chain") or f"unknown:{pool}")

            # ── MP-1180: registry fallback when live APY is missing ───────────
            # Live orchestrator returns None→0 for APY on network errors.
            # Prefer registry APY fallback over blocking the rebalance entirely.
            # Live values (apy>0) are never overwritten. TVL is NEVER filled
            # from the registry (ADR-053) — the $20M fabrication that made the
            # floor decorative is removed; unverified-TVL pools were already
            # frozen (capped at held / dropped) before this loop.
            if pool in _reg_fallbacks:
                _fb = _reg_fallbacks[pool]
                if apy == 0.0:
                    # registry stores fraction (0.035); gate expects pct (3.5)
                    _fb_apy_frac = _fb.get("live_apy") or _fb.get("fallback_apy")
                    if isinstance(_fb_apy_frac, (int, float)) and _fb_apy_frac > 0:
                        apy = float(_fb_apy_frac) * 100.0
                        log.warning(
                            "MP-1180 %s: live apy missing → registry fallback"
                            " apy=%.3f%% (was 0.0%%)",
                            pool,
                            apy,
                        )
                # fill tier/chain from registry when meta was empty
                if not m.get("tier") and _fb.get("tier") is not None:
                    _t = _fb["tier"]
                    tier = f"T{_t}".upper() if isinstance(_t, int) else str(_t).upper()
                if chain.startswith("unknown:") and _fb.get("chain"):
                    chain = str(_fb["chain"])
            if pool in _tvl_frozen:
                # ADR-053: TVL cannot be verified live → the amount here is
                # already capped at the currently-held USD (a holdover, not a
                # fresh allocation). Running check_new_position with tvl=0
                # would fabricate a floor violation over a holdover; instead
                # the pool is recorded (warning above) and still appended to
                # ``state`` below so the cumulative T2/concentration limits
                # account for the held capital.
                pass
            else:
                res = policy.check_new_position(
                    state,
                    protocol_key=pool,
                    tier=tier,
                    amount_usd=usd,
                    current_apy=apy,
                    tvl_usd=tvl,
                    chain=chain,
                )
                warnings.extend(res.warnings)
                if not res.approved:
                    violations.extend(f"{pool}: {v}" for v in res.violations)
            # Add the position regardless of the verdict so cumulative limits
            # (T2 total, concentration) are evaluated over the full target.
            state.positions.append(
                Position(
                    protocol_key=pool,
                    tier=tier,
                    asset="USDC",
                    amount_usd=usd,
                    apy_at_open=apy,
                    current_apy=apy,
                    chain=chain,
                )
            )

        out["violations"] = violations
        out["warnings"] = warnings
        out["approved"] = not violations
        out["target_usd"] = adjusted
        out["tvl_unverified"] = sorted(_tvl_frozen)
    except Exception as exc:  # gate must never crash the cycle (MP-005 spec)
        # FIX-P0 (fail-closed): any exception inside the gate BLOCKS the trade.
        # Previously this was fail-open (approved=True on exception), which is
        # a critical vulnerability for live capital — an error could silently
        # bypass all risk checks.  Now: exception → approved=False, trade blocked.
        log.warning(
            "FAIL-CLOSED: risk gate exception, blocking trade: %s",
            exc,
        )
        out["approved"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["violations"] = out.get("violations") or [
            f"gate_exception: {type(exc).__name__}: {exc}"
        ]
    return out


def _record_policy_block(
    ddir: Path,
    *,
    run_ts: str,
    date: str,
    gate: dict,
    current_positions: dict[str, float],
    capital_usd: float,
) -> None:
    """Append one audit record to ``risk_policy_blocks.json`` (ring-buffer 100)."""
    blocks = _read_json(ddir / RISK_BLOCKS_FILENAME, [])
    if not isinstance(blocks, list):
        blocks = []
    blocks.append(
        {
            "ts": run_ts,
            "date": date,
            "source": "cycle_runner",
            "policy_version": _policy_version(),
            "violations": list(gate.get("violations") or []),
            "warnings": list(gate.get("warnings") or []),
            "blocked_target_usd": {
                p: round(float(v), 2)
                for p, v in (gate.get("target_usd") or {}).items()
            },
            "held_positions_usd": {
                p: round(float(v), 2) for p, v in current_positions.items()
            },
            "capital_usd": capital_usd,
        }
    )
    blocks = blocks[-MAX_POLICY_BLOCKS:]  # ring-buffer
    _atomic_write_json(ddir / RISK_BLOCKS_FILENAME, blocks)


def _policy_version() -> str:
    """Active RiskConfig version for audit records (best-effort)."""
    try:
        from spa_core.risk.policy import RiskConfig

        return RiskConfig().version
    except Exception:
        return "unknown"


# ── ADR-072 (мандат владельца 2026-08-07): срезанный бюджет не выбрасывается ──

def redistribute_freed_budget(
    gate_target: dict[str, float],
    pre_gate_target: dict[str, float],
    capital_usd: float,
    adapters: list[dict],
    gate_result: dict,
    *,
    min_cash_pct: float = 0.05,
    t1_cap_pct: "float | None" = None,
    t2_cap_pct: "float | None" = None,
    t2_total_cap_pct: "float | None" = None,
    max_protocols: "int | None" = None,
    max_single_chain_pct: "float | None" = None,
    max_l2_total_pct: "float | None" = None,
    allocator_trims_by_protocol: "dict[str, float] | None" = None,
    chain_trims_by_protocol: "dict[str, float] | None" = None,
) -> dict:
    """Перераздаёт бюджет, СРЕЗАННЫЙ гейтом, в оставшихся честных кандидатов.

    Диагноз 2026-08-07: оптимизатор раздаёт 95% капитала, защитные тримы гейта
    (below-median, TVL-freeze ADR-053) срезают веса — и освобождённые ~20%
    просто выбрасывались в кэш под 0%, хотя рядом стояли live-кандидаты с
    положительной доходностью и свободными потолками (compound_v3 3.3%,
    yearn 3.3%, euler 3.1%). Для простаивающего кэша правильная планка
    сравнения — 0%, а не лучшая позиция книги (ADR-055: молчаливый простой
    запрещён; владелец 07.08: «кэш обязан работать — срочно»).

    Правила честности:
      * кандидат обязан иметь ``tvl_source == "live"`` и конечный APY > 0
        из снимка адаптеров (та же доказательная база, что у самого гейта;
        литералы не годятся — ADR-061/063);
      * пулы, которые гейт ТОЛЬКО ЧТО срезал или заморозил
        (pre_gate > gate_target, tvl_unverified), капитал НЕ получают —
        перераздача не смеет отменять слово гейта;
      * потолки тиров и суммарный T2 — ЗЕРКАЛО RiskConfig (ADR-144),
        не собственные литералы; ALLOC-002
        (≤ max_protocols) соблюдаются здесь И перепроверяются повторным
        проходом самого гейта у вызывающего — ГЕЙТ ОСТАЁТСЯ ПОСЛЕДНИМ СЛОВОМ
        (инвариант 1); буфер min_cash неприкосновенен;
      * ADR-160 (решение владельца 28.08, вариант 3): срезанное ВНУТРИ аллокатора
        (потолки протокола, суммарные T2/T3, потолки сети) тоже перераздаётся —
        раньше оно было невидимо, потому что `freed` считался разницей сумм ГЕЙТА
        и для этих тримов давал ноль. Пулы, чей потолок и срезал вес, капитала НЕ
        получают: вернуть деньги туда — инерция, а ADR-055 требует, чтобы
        концентрация следовала за доходностью и риском. Владелец выбрал это
        СТРОЖЕ рекомендации автора карточки;
      * каждое размещение возвращается именованным (ADR-055 provenance).

    Возвращает ``{"target_usd", "added": {proto: usd}, "freed_usd", "notes"}``;
    при freed ≤ эпсилон — вход без изменений. Пороги RiskPolicy не меняются.
    """
    # 2026-08-08 (решение владельца, вариант 1 карточки
    # `owner-decision-posle-strahovki-dengi-ostayutsya-sirotam`): потолки сети
    # берутся из RiskConfig — того же источника, по которому судит повторный
    # гейт. Собственная копия порога здесь — это будущий разъезд, а он уже раз
    # стоил 20 % капитала.
    if max_single_chain_pct is None or max_l2_total_pct is None:
        _chain_cap, _l2_cap = 0.90, 0.50
        try:
            from spa_core.risk.policy import RiskConfig

            _cfg = RiskConfig()
            _chain_cap = float(_cfg.max_single_chain_allocation)
            _l2_cap = float(_cfg.max_l2_total_allocation)
        except Exception:  # noqa: BLE001 — RiskConfig недоступен ⇒ консервативно
            log.warning("ADR-073: RiskConfig недоступен — потолки сети по умолчанию")
        if max_single_chain_pct is None:
            max_single_chain_pct = _chain_cap
        if max_l2_total_pct is None:
            max_l2_total_pct = _l2_cap

    # ADR-144 (решение владельца 26.08): «два источника лимитов в одной системе —
    # не двойная страховка, а гарантированный разъезд; ужесточение только через
    # изменение САМОЙ политики». Тогда зеркало навели у тюнера и ребалансера, а
    # здесь остался литерал `t2_total_cap_pct = 0.35` — ровно то число, которое
    # ADR-144 и называл. Политика разрешает 0.50.
    #
    # Замер 31.08, цена расхождения: гейт срезал ethereum до его потолка 90 %,
    # свободной осталась только сеть base, а добавка туда упёрлась в 35 % —
    # книга стояла на T2 = 35.00 %, то есть ровно на ЭТОМ умолчании, при
    # политике 50 %. $17 368 (17.4 % капитала) остались в кэше под 0 % при живых
    # кандидатах 4.2–5.2 %. Именно это следствие ADR-144 и предсказывал.
    #
    # Граница риска не здесь: после перераздачи цикл ПОВТОРНО прогоняет
    # RiskPolicy (`_gate2`) и принимает результат, только если он APPROVED без
    # нарушений (инвариант #1). Зеркало не ослабляет гейт, оно лишь перестаёт
    # запрещать то, что политика разрешает.
    if (t1_cap_pct is None or t2_cap_pct is None
            or t2_total_cap_pct is None or max_protocols is None):
        _t1, _t2, _t2tot, _maxp = 0.40, 0.20, 0.50, 8
        try:
            from spa_core.risk.policy import RiskConfig

            _c = RiskConfig()
            _t1 = float(_c.max_concentration_t1)
            _t2 = float(_c.max_concentration_t2)
            _t2tot = float(_c.max_total_t2_allocation)
            _maxp = int(_c.max_protocols)
        except Exception:  # noqa: BLE001 — RiskConfig недоступен ⇒ консервативно
            log.warning("ADR-144: RiskConfig недоступен — потолки тиров по умолчанию")
        if t1_cap_pct is None:
            t1_cap_pct = _t1
        if t2_cap_pct is None:
            t2_cap_pct = _t2
        if t2_total_cap_pct is None:
            t2_total_cap_pct = _t2tot
        if max_protocols is None:
            max_protocols = _maxp

    out = {"target_usd": dict(gate_target), "added": {}, "freed_usd": 0.0,
           "notes": [], "freed_from_allocator_usd": 0.0, "blocked_by_allocator": []}
    try:
        cap = float(capital_usd)
        if not math.isfinite(cap) or cap <= 0:
            return out
        deployable_max = cap * (1.0 - max(0.0, float(min_cash_pct)))
        deployed = sum(float(v) for v in gate_target.values())
        asked = sum(float(v) for v in pre_gate_target.values())
        # Строго мандат: перераздаётся ТОЛЬКО то, что срезал гейт (asked-deployed),
        # и никогда сверх буфера. Недобор самого аллокатора (маленькая книга по
        # его собственному решению) — не наш предмет: заполнять его значило бы
        # отменять решение модели, а не спасать срезанный бюджет.
        gate_cut = max(0.0, asked - deployed)
        # ADR-160: тримы аллокатора приходят ДОЛЯМИ капитала — переводим в USD.
        # Без этого слагаемого перезаполнитель видел ноль там, где реально срезано
        # 20 п.п. (замер 08.08: 25 % в кэше при буфере 5 %).
        alloc_trims = {str(k): float(v) for k, v in (allocator_trims_by_protocol or {}).items()
                       if float(v) > 0}
        alloc_cut = sum(alloc_trims.values()) * cap
        freed = min(deployable_max - deployed, gate_cut + alloc_cut)
        out["freed_usd"] = round(max(0.0, freed), 2)
        out["freed_from_allocator_usd"] = round(alloc_cut, 2)
        out["blocked_by_allocator"] = sorted(alloc_trims)
        if freed <= cap * 0.005:  # < 0.5% капитала — не гоняем копейки
            return out

        frozen = set(gate_result.get("tvl_unverified") or [])
        reduced_by_gate = {
            p for p, pre in pre_gate_target.items()
            if float(pre) - float(gate_target.get(p, 0.0)) > 1e-6
        }
        # ADR-160, вариант 3: к срезанным гейтом добавляются срезанные АЛЛОКАТОРОМ.
        # Оба списка — «кому потолок только что отказал»; вернуть им капитал значило бы
        # частично отменить решение защиты.
        reduced_by_allocator = set(alloc_trims)
        # Решение владельца 31.08 (карточка `own-dengi-stoyat-iz-za-starogo-potolka`,
        # вариант «нет, не считать»): срез по СОВОКУПНОМУ признаку — сети — не есть
        # приговор каждому протоколу на ней. Он говорит «здесь суммарно много», а не
        # «этот протокол плох», поэтому такие протоколы остаются в получателях.
        #
        # Замер 30.08, ради которого правка: гейт снял `fluid_fusdc`, у сети появился
        # запас — но `compound_v3` (7.87 %) и `fluid_usdc` были исключены как срезанные
        # СЕТЕВЫМ потолком, и капитал ушёл в единственный не исключённый ethereum-адрес
        # `aave_v3` под 3.26 %, худший из десяти при медиане 4.93 %. Так и родилось
        # нарушение ECON-10.
        #
        # Потолок сети НЕ ослаблен: ниже, в цикле, запас каждого кандидата отдельно
        # ограничен `cap * max_single_chain_pct - chain_usd[chain]`, а после перераздачи
        # цикл ПОВТОРНО прогоняет RiskPolicy (инвариант #1). Меняется лишь то, кого
        # считать наказанным, а не сколько ему можно.
        _chain_only = {str(k) for k, v in (chain_trims_by_protocol or {}).items()
                       if float(v) > 0}
        reduced_by_allocator -= _chain_only
        blocked = frozen | reduced_by_gate | reduced_by_allocator

        # ADR-072.1: цепочка кандидата — из снимка, иначе из канонической карты,
        # иначе КОНСЕРВАТИВНО «ethereum» (занижает headroom, не завышает).
        # Без этого перераздача предлагала заведомо отвергаемое: гейт валил её
        # на «Chain concentration on ethereum 91% > 90%» (замер 08.08).
        try:
            from spa_core.risk.chain_limits import get_default_chain_map
            chain_map = dict(get_default_chain_map())
        except Exception:  # noqa: BLE001
            chain_map = {}

        def _chain_of(proto: str, meta: dict | None = None) -> str:
            if meta and meta.get("chain"):
                return str(meta["chain"]).lower()
            return str(chain_map.get(proto, "ethereum")).lower()

        tier_of: dict[str, str] = {}
        chain_of: dict[str, str] = {}
        candidates: list[tuple[float, str]] = []
        for a in adapters:
            if not isinstance(a, dict):
                continue
            p = a.get("protocol")
            if not p:
                continue
            # ADR-073: карты тира и сети строятся по ВСЕМ адаптерам, включая
            # заблокированные. Раньше блокированные сюда не попадали, и
            # ``tier_of.get(p, "T2")`` записывал T1-позицию в СУММАРНЫЙ лимит
            # T2 — потолок «съедался» деньгами, которых в нём нет. Замер на
            # фикстуре инцидента: morpho_steakhouse (T1, $5 000) один занимал
            # 5 п.п. чужого лимита и не пускал туда live-кандидата.
            tier = str(a.get("tier", "T2")).upper()
            tier_of[p] = tier
            chain_of[str(p)] = _chain_of(str(p), a)
            if p in blocked:
                continue          # в КАНДИДАТЫ не идёт — слово гейта свято
            apy = a.get("apy_pct")
            tvl_live = (a.get("tvl_source") == "live")
            if (tvl_live and isinstance(apy, (int, float))
                    and not isinstance(apy, bool)
                    and math.isfinite(apy) and apy > 0.0):
                candidates.append((-float(apy), str(p)))
        candidates.sort()

        new_target = dict(gate_target)
        t2_deployed = sum(float(v) for p, v in new_target.items()
                          if str(tier_of.get(p, "T2")).upper() != "T1")
        # текущая экспозиция по цепочкам (доли от КАПИТАЛА — как считает гейт)
        chain_usd: dict[str, float] = {}
        for p, v in new_target.items():
            c = chain_of.get(p) or _chain_of(str(p))
            chain_usd[c] = chain_usd.get(c, 0.0) + float(v)
        # ADR-073: суммарный L2 (50 %) — второй потолок сети, который проверит
        # повторный гейт; без него перераздача снова предложит непроходное.
        _L2_CHAINS = {"arbitrum", "base"}
        l2_usd = sum(v for c, v in chain_usd.items() if c in _L2_CHAINS)
        funded = {p for p, v in new_target.items() if float(v) > 1e-6}

        for _neg_apy, p in candidates:
            if freed <= 1e-6:
                break
            tier = tier_of.get(p, "T2")
            cap_pct = t1_cap_pct if tier == "T1" else t2_cap_pct
            headroom = cap * cap_pct - float(new_target.get(p, 0.0))
            if tier != "T1":
                headroom = min(headroom, cap * t2_total_cap_pct - t2_deployed)
            # лимит одной цепочки (ADR-062, 90% капитала): предлагаем только то,
            # что гейт СМОЖЕТ принять — иначе он отвергает перераздачу целиком
            chain = chain_of.get(p, "ethereum")
            headroom = min(headroom,
                           cap * max_single_chain_pct - chain_usd.get(chain, 0.0))
            if chain in _L2_CHAINS:
                headroom = min(headroom, cap * max_l2_total_pct - l2_usd)
            if headroom <= 1e-6:
                continue
            if p not in funded and len(funded) >= max_protocols:
                continue  # ALLOC-002: новых имён сверх лимита не открываем
            add = min(freed, headroom)
            new_target[p] = float(new_target.get(p, 0.0)) + add
            out["added"][p] = round(out["added"].get(p, 0.0) + add, 2)
            if tier != "T1":
                t2_deployed += add
            chain_usd[chain] = chain_usd.get(chain, 0.0) + add
            if chain in _L2_CHAINS:
                l2_usd += add
            funded.add(p)
            freed -= add
            out["notes"].append(
                f"ADR-072: +${add:,.0f} → {p} ({tier}, {-_neg_apy:.2f}% live) — "
                f"срезанный гейтом бюджет вместо кэша под 0%")

        if freed > cap * 0.005:
            # ADR-073: cap_bound ниже ловит только «не разместили НИЧЕГО».
            # Сегодняшний случай — частичный: $20 000 ушли, $5 000 остались.
            # Молчаливый частичный остаток запрещён так же, как полный (ADR-055).
            out["unplaceable_usd"] = round(freed, 2)
            out["notes"].append(
                f"ADR-072/073: ${freed:,.0f} разместить НЕ УДАЛОСЬ — свободной ёмкости "
                f"под потолками (тир / суммарный T2 / одна сеть "
                f"{max_single_chain_pct:.0%} / L2 {max_l2_total_pct:.0%} / "
                "ALLOC-002) не осталось")

        if out["added"]:
            out["target_usd"] = new_target
        elif out["freed_usd"] > 0:
            out["notes"].append(
                "ADR-072: свободный бюджет $"
                f"{out['freed_usd']:,.0f} размещать НЕКУДА под лимитами "
                "(цепочка/тир/ALLOC-002) — cap-bound, не «непонятный простой»")
            out["cap_bound"] = True
    except Exception as exc:  # noqa: BLE001 — перераздача не смеет валить цикл
        log.warning("ADR-072 redistribute_freed_budget failed (%s) — вход без изменений", exc)
        return {"target_usd": dict(gate_target), "added": {}, "freed_usd": 0.0,
                "notes": [f"ADR-072: перераздача упала ({type(exc).__name__}) — кэш остался"]}
    return out
