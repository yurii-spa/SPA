"""Investment CIO — WP-S01 unified capital read model (ADR-554).

Pure read model: projects the engines' own published state (``defi_engine/status.json``,
the per-book paper-trading files, the daily evidenced equity curve, the kill-switch /
de-risk status, the trading-research and market-neutral research ledgers, and the regime
classifiers) into the six capital sleeves of :mod:`spa_core.investment_cio.contract`.

Writes NOTHING. Every number is a :func:`contract.measured` or :func:`contract.absent`
cell; a missing or stale source becomes an explicit ``NOT_MEASURED`` / ``STALE`` cell —
never a silent ``0`` (invariant #17). ``build_sleeves`` never raises on a missing file:
the whole point of a read model over a paper system is that an absent book is a fact to
report, not an exception to catch elsewhere.

# LLM_FORBIDDEN — every rule here is a deterministic, reproducible projection.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.adapters.tier_map import tier_of
from spa_core.investment_cio import contract
from spa_core.utils.observation import observed

POLICY = contract.POLICY
CADENCE_DAILY_H = 26.0
CADENCE_HOURLY_H = 3.0
#: research strands publish daily bars; 3 missed days is a dead strand, not a 400-day-old snapshot
#: (ADR-554 finding 3 — snapshot_retention_days*24h was a retention window, not a freshness cadence).
CADENCE_RESEARCH_STRAND_H = CADENCE_DAILY_H * 3.0

# ── generic file / timestamp plumbing ───────────────────────────────────────────────────

def _read_json(path: Path) -> tuple[Optional[Any], Optional[bytes]]:
    try:
        raw = path.read_bytes()
    except OSError:
        return None, None
    try:
        return json.loads(raw), raw
    except (ValueError, UnicodeDecodeError):
        return None, raw


def _read_jsonl(path: Path) -> tuple[Optional[list], Optional[bytes]]:
    try:
        raw = path.read_bytes()
    except OSError:
        return None, None
    rows: list = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows, raw


def _digest(raw: Optional[bytes]) -> Optional[str]:
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dt_from_ms(ms: Any) -> Optional[datetime]:
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


class Input:
    """One source file: what we read, when it was observed, how old it is now."""

    def __init__(self, name: str, path: Path, data_dir: Path, cadence_hours: Optional[float],
                 as_of_fn: Optional[Callable[[Any], Optional[datetime]]], kind: str = "json"):
        self.name = name
        self.path = path
        self.cadence_hours = cadence_hours
        try:
            self.path_str = str(path.relative_to(data_dir))
        except ValueError:
            self.path_str = str(path)
        self.doc, self.raw = _read_json(path) if kind == "json" else _read_jsonl(path)
        self.digest = _digest(self.raw)
        self.as_of: Optional[datetime] = None
        self.as_of_iso: Optional[str] = None
        self.age_hours: Optional[float] = None
        self.state = contract.NOT_MEASURED
        self.state_reason: Optional[str] = None

    def resolve(self, now: datetime) -> None:
        if self.doc is None:
            self.state = contract.NOT_MEASURED
            self.state_reason = f"{self.name} unavailable"
            return
        as_of_fn = self._as_of_fn
        as_of_dt = as_of_fn(self.doc) if as_of_fn is not None else None
        self.as_of = as_of_dt
        self.as_of_iso = as_of_dt.isoformat() if as_of_dt is not None else None
        if self.cadence_hours is None:
            # no cadence declared for this input: it never claims freshness, so a missing as_of
            # is not an error (finding 3: this is NOT the "declared cadence, no as_of" case below).
            self.state = contract.MEASURED
            return
        if as_of_dt is None:
            # a cadence IS declared (this input claims to be freshness-tracked) but no as_of could
            # be read from it: age is unknown, which is NOT the same as fresh (ADR-554 finding 3).
            self.state = contract.NOT_MEASURED
            self.state_reason = f"{self.name}: age unknown (no as_of in the document)"
            return
        self.age_hours = (now - as_of_dt).total_seconds() / 3600.0
        self.state = contract.STALE if self.age_hours > self.cadence_hours else contract.MEASURED

    @property
    def _as_of_fn(self):
        return self.__dict__.get("_as_of_fn_impl")


def _make_input(name, relpath, data_dir, cadence_hours, as_of_fn, now, kind="json") -> Input:
    inp = Input(name, data_dir / relpath, data_dir, cadence_hours, as_of_fn, kind=kind)
    inp.__dict__["_as_of_fn_impl"] = as_of_fn
    inp.resolve(now)
    return inp


def _manifest_row(inp: Input) -> dict:
    return {
        "name": inp.name,
        "path": inp.path_str,
        "as_of": inp.as_of_iso,
        "age_hours": round(inp.age_hours, 3) if inp.age_hours is not None else None,
        "digest": inp.digest,
        "state": inp.state,
    }


# ── as_of extractors ────────────────────────────────────────────────────────────────────

def _as_of_generated_at(doc):
    return _parse_ts(observed(doc, "generated_at", kind=str)) if isinstance(doc, dict) else None


def _as_of_generated_at_ms(doc):
    return _dt_from_ms(observed(doc, "generated_at_ms", kind=(int, float))) if isinstance(doc, dict) else None


def _as_of_last_cycle_at(doc):
    return _parse_ts(observed(doc, "last_cycle_at", kind=str)) if isinstance(doc, dict) else None


def _as_of_detected_at(doc):
    return _parse_ts(observed(doc, "detected_at", kind=str)) if isinstance(doc, dict) else None


def _as_of_as_of_utc(doc):
    return _parse_ts(observed(doc, "as_of_utc", kind=str)) if isinstance(doc, dict) else None


def _as_of_last_row(key):
    def fn(rows):
        if not isinstance(rows, list) or not rows:
            return None
        last = rows[-1]
        if not isinstance(last, dict):
            return None
        return _parse_ts(last.get(key)) or (None if "as_of" not in last else _parse_ts(last.get("as_of")))
    return fn


def _as_of_sky_live_apy(doc):
    sky = observed(observed(doc, "adapters", kind=dict) or doc, "sky_susds", kind=dict) if isinstance(doc, dict) else None
    v = (sky or {}).get("live_apy_as_of")
    return _parse_ts(v) if isinstance(v, str) else None


def _real_capital(defi_input, tr_input, data_dir: Path):
    """0 only when the DeFi engine and the paper status both declare a paper mode AND every engine that reports
    live capital reports 0; otherwise None (not measured). Never a positive figure (owner subject №1)."""
    import json as _json
    try:
        pts = _json.loads((Path(data_dir) / "paper_trading_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pts = None
    modes = [observed(defi_input.doc, "execution_mode", kind=str) if isinstance(defi_input.doc, dict) else None,
             observed(pts, "execution_mode", kind=str) if isinstance(pts, dict) else None]
    lives = [observed(d.doc, "live_capital_usd", kind=(int, float)) if isinstance(d.doc, dict) else None
             for d in (defi_input, tr_input)]
    if all(m in ("read_only_simulation", "paper") for m in modes) and all(v == 0 for v in lives):
        return 0
    return None


def _hurdle_cell(inp) -> dict:
    """The return-gate hurdle: Sky/sUSDS live savings rate (pct) when the adapter reports it fresh, else absent."""
    doc = inp.doc if isinstance(getattr(inp, "doc", None), dict) else None
    sky = None
    if doc is not None:
        sky = observed(observed(doc, "adapters", kind=dict) or doc, "sky_susds", kind=dict)
    if not isinstance(sky, dict) or not isinstance(sky.get("live_apy"), (int, float)):
        return contract.absent(contract.NOT_MEASURED, reason="Sky/sUSDS live savings rate not readable",
                               source="adapter_status.json sky_susds.live_apy")
    if sky.get("live_apy_fresh") is not True:
        return contract.absent(contract.STALE, reason="Sky/sUSDS live rate not fresh (adapter says live_apy_fresh=false)",
                               source="adapter_status.json sky_susds.live_apy", as_of=sky.get("live_apy_as_of"))
    return contract.measured(float(sky["live_apy"]), unit="pct_apy", source="adapter_status.json sky_susds.live_apy",
                             as_of=sky.get("live_apy_as_of"),
                             note="risk-free proxy hurdle (ADR-554 rule 3); a savings rate, not a forecast")


def _as_of_last_series_point(doc):
    if not isinstance(doc, dict):
        return None
    series = observed(doc, "series", kind=list)
    if not series:
        return _as_of_generated_at(doc)
    last = series[-1]
    if not isinstance(last, dict):
        return None
    return _parse_ts(last.get("ts")) or _parse_ts(last.get("date"))


# ── cell helpers ─────────────────────────────────────────────────────────────────────────

def _cell(value, *, unit, inp: Input, n=None, note=None, nm_reason=None):
    """Build a measured()/absent() cell honoring the input's own freshness state."""
    if inp.state == contract.NOT_MEASURED:
        return contract.absent(contract.NOT_MEASURED,
                                reason=nm_reason or inp.state_reason or f"{inp.name} unavailable",
                                source=inp.path_str, as_of=inp.as_of_iso, n=n)
    if inp.state == contract.STALE:
        age = f"{inp.age_hours:.1f}h" if inp.age_hours is not None else "unknown age"
        return contract.absent(contract.STALE,
                                reason=f"{inp.name} stale: age {age} > {inp.cadence_hours}h cadence",
                                source=inp.path_str, as_of=inp.as_of_iso, n=n)
    if value is None:
        return contract.absent(contract.NOT_MEASURED, reason=nm_reason or f"value absent in {inp.name}",
                                source=inp.path_str, as_of=inp.as_of_iso, n=n)
    return contract.measured(value, unit=unit, source=inp.path_str, as_of=inp.as_of_iso, n=n, note=note)


def _absent_like(cell: dict, reason: str) -> dict:
    """Propagate a non-measured cell's state (NOT_MEASURED/STALE/...) with a new reason."""
    state = cell.get("state", contract.NOT_MEASURED)
    if state == contract.MEASURED:
        state = contract.NOT_MEASURED
    return contract.absent(state, reason=reason, source=cell.get("source"), as_of=cell.get("as_of"),
                            n=cell.get("n"))


def _not_measured(reason: str, source: Optional[str] = None, as_of: Optional[str] = None) -> dict:
    return contract.absent(contract.NOT_MEASURED, reason=reason, source=source, as_of=as_of)


_EMPTY_FIELDS = {k: None for k in contract.SLEEVE_FIELDS}


def _blank_sleeve(sleeve_id: str) -> dict:
    identity = contract.SLEEVES[sleeve_id]
    out = dict(_EMPTY_FIELDS)
    out.update({
        "sleeve_id": sleeve_id,
        "name": identity["name"],
        "mechanism": None,
        "mechanism_class": identity["mechanism_class"],
        "mode": contract.MODE,
        "allocatable": identity["allocatable"],
        "live_admission": None,
        "experiment_id": None,
        "experiment_start": None,
        "versions_closed": [],
        "risk": {axis: {"level": "UNKNOWN", "evidence": "not assessed", "source": None}
                 for axis in contract.RISK_AXES},
        "composition": [],
        "factors": [],
        "correlation_features": {},
        "gates": [],
        "warnings": [],
        "unknowns": [],
    })
    return out


# ── maturity / confidence ───────────────────────────────────────────────────────────────

def _maturity_cell(valid_periods_cell: dict) -> dict:
    if valid_periods_cell.get("state") != contract.MEASURED:
        return _absent_like(valid_periods_cell, "valid_periods not measured; maturity unknown")
    n = valid_periods_cell["value"]
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return _not_measured("valid_periods not numeric")
    if n < POLICY["maturity_developing_min"]:
        label = contract.MATURITY_IMMATURE
    elif n < POLICY["maturity_mature_min"]:
        label = contract.MATURITY_DEVELOPING
    else:
        label = contract.MATURITY_MATURE
    return contract.measured(label, unit=None, source="cio-policy-v1 thresholds + " + str(valid_periods_cell.get("source")),
                              as_of=valid_periods_cell.get("as_of"), n=n,
                              note=f"valid_periods={n}")


def _confidence_cell(maturity_cell: dict, mtm_cell: dict) -> dict:
    if maturity_cell.get("state") != contract.MEASURED:
        return _absent_like(maturity_cell, "maturity unknown; sleeve confidence cannot be assessed")
    label = maturity_cell["value"]
    conf = "LOW" if label == contract.MATURITY_IMMATURE else "MEDIUM"
    note = "HIGH unreachable in v1 (no mark-to-market coverage / price-risk correlation yet)"
    return contract.measured(conf, unit=None, source="cio-policy-v1", as_of=maturity_cell.get("as_of"), note=note)


# ── nearest LIQUIDATING stop (ADR-554 finding 1) ────────────────────────────────────────
# A SOFT_DERISK stop (effect "halt new / no increase") never liquidates the book; it is not a
# worst-case loss BOUND, only a brake. Only a stop that actually ends the position — HARD_KILL
# ("full kill to all-cash") or a book's own kill switch ("book stops") — bounds the loss.

def _is_soft_stop(stop: dict) -> bool:
    name = stop.get("name")
    effect = stop.get("effect")
    if isinstance(name, str) and name.strip().upper() == "SOFT_DERISK":
        return True
    if isinstance(effect, str):
        e = effect.lower()
        if "halt new" in e or "no increase" in e:
            return True
    return False


def _stop_threshold(stop: dict) -> Optional[float]:
    """The stop's own threshold. The live defi_engine schema names it ``drawdown_pct``;
    ``threshold_pct`` is accepted too so a future rename does not silently drop the stop."""
    for key in ("drawdown_pct", "threshold_pct"):
        v = stop.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
    return None


def _nearest_liquidating_stop_cell(book: Optional[dict], defi_input: Input,
                                    loss_budget_doc: dict) -> dict:
    # loss_budget_doc is accepted for call-site compatibility but is deliberately UNUSED: see the
    # "finding 1 residual" note below — it is never a valid stand-in for a liquidating stop.
    del loss_budget_doc
    if defi_input.state != contract.MEASURED:
        return _cell(None, unit="pct", inp=defi_input)
    gate = observed(book, "gate", kind=dict) if book is not None else None
    stops = observed(gate, "stops", kind=list) if gate is not None else None
    if not isinstance(stops, list) or not stops:
        # ADR-554 finding 1 residual: the legacy nearest_enforced_stop_pct field carries NO
        # liquidating/soft distinction — it may itself BE the soft number (it is, for the real
        # conservative book: 5.0 = SOFT_DERISK). Never use it as a stand-in for "the liquidating
        # stop"; without a structured gate.stops list, no liquidating stop is identifiable at all.
        return contract.absent(contract.NOT_MEASURED,
                                reason="no liquidating stop identifiable (no gate.stops published)",
                                source=defi_input.path_str, as_of=defi_input.as_of_iso)
    liquidating, soft = [], []
    for s in stops:
        if not isinstance(s, dict) or _stop_threshold(s) is None:
            continue
        (soft if _is_soft_stop(s) else liquidating).append(s)
    if not liquidating:
        reason = "no liquidating stop declared (only soft de-risk stop(s) found): never SOFT_DERISK alone"
        if soft:
            soft_desc = ", ".join(f"{s.get('name')}={_stop_threshold(s)}pct" for s in soft)
            reason += f" — {soft_desc}"
        return contract.absent(contract.NOT_MEASURED, reason=reason, source=defi_input.path_str,
                                as_of=defi_input.as_of_iso)
    nearest = min(liquidating, key=lambda s: abs(_stop_threshold(s)))
    note = f"nearest liquidating stop: {nearest.get('name')} (effect={nearest.get('effect')!r})"
    if soft:
        soft_desc = ", ".join(f"{s.get('name')}={_stop_threshold(s)}pct (effect={s.get('effect')!r})"
                               for s in soft)
        note += f"; skipped non-liquidating soft stop(s): {soft_desc}"
    return contract.measured(_stop_threshold(nearest), unit="pct", source=defi_input.path_str,
                              as_of=defi_input.as_of_iso, note=note)


# ── worst-case loss (ADR-554 F1 / finding 1) ────────────────────────────────────────────

def _worst_case_loss(mechanism_class: str, stop_cell: dict, stress_cell: dict) -> dict:
    if stop_cell.get("state") != contract.MEASURED:
        return _absent_like(stop_cell, "nearest enforced stop unknown")
    stop_val = stop_cell["value"]
    if mechanism_class == "unlevered_lending":
        return contract.measured(stop_val, unit="pct", source=stop_cell.get("source"), as_of=stop_cell.get("as_of"),
                                  note="bound by a liquidating stop; daily-bar gap and credit/peg events not "
                                       "modelled")
    if stress_cell.get("state") != contract.MEASURED:
        if stress_cell.get("state") == contract.STALE:
            return _absent_like(stress_cell, "stress model stale; a stop alone is a limit, not a loss estimate")
        return _not_measured("no stress model; a stop is a limit, not a loss estimate",
                              source=stop_cell.get("source"), as_of=stop_cell.get("as_of"))
    stress_val = stress_cell["value"]
    worst = max(stop_val, stress_val)
    use_stress = stress_val >= stop_val
    return contract.measured(
        worst, unit="pct",
        source=stress_cell.get("source") if use_stress else stop_cell.get("source"),
        as_of=stress_cell.get("as_of") if use_stress else stop_cell.get("as_of"),
        note=f"max(stop={stop_val}pct, stress={stress_val}pct); {stress_cell.get('note')}",
    )


# ── factors ──────────────────────────────────────────────────────────────────────────────

def _factors_for(protocol_names: list[str], sleeve_id: str) -> list[str]:
    factors: set[str] = set()
    for raw in protocol_names:
        n = str(raw).lower()
        if "maple" in n:
            factors.add("maple_credit")
        if "fluid" in n:
            factors.add("fluid")
        if "susde" in n or "ethena" in n or "usde" in n:
            factors.add("usde_peg")
        if "pendle" in n or "_pt" in n or n.startswith("pt_"):
            factors.add("pendle_pt")
        if "usdc" in n:
            factors.add("usdc_peg")
    if sleeve_id in contract.DEFI_SLEEVES:
        factors.add("smart_contract")
        factors.add("oracle")
    if sleeve_id == "trading_research":
        factors.add("btc_direction")
    if sleeve_id == "market_neutral_basis":
        factors.add("funding_rate")
        factors.add("usde_peg")
    return sorted(factors)


# ── unlevered-by-mandate confirmation (ADR-554 finding 9a) ──────────────────────────────

def _mechanic_exposure_confirms_unlevered(mech_exposure: Optional[dict]) -> bool:
    """True only when the engine's own mechanic_exposure names at least one mechanic and none of
    them is a leveraged (loop) mechanic — the positive source for "no embedded leverage". A missing
    or empty mechanic_exposure proves nothing (ADR-554 finding 9a: absence is not a positive source)."""
    by_mech = (mech_exposure or {}).get("by_mechanic") if isinstance(mech_exposure, dict) else None
    if not isinstance(by_mech, dict) or not by_mech:
        return False
    return all(str(name).strip().lower() != "loop" for name in by_mech)


# ── composition from mechanic_exposure (DeFi sleeves) ───────────────────────────────────

def _composition_from_mechanic_exposure(mech_exposure: Optional[dict], defi_input: Input,
                                         share_basis_note: Optional[str]) -> list[dict]:
    out: list[dict] = []
    by_mech = (mech_exposure or {}).get("by_mechanic") or {}
    for mech_name, bucket in by_mech.items():
        if not isinstance(bucket, dict):
            continue
        protocols = bucket.get("protocols") or []
        bucket_share = bucket.get("share")
        bucket_usd = bucket.get("usd")
        single = len(protocols) == 1
        for proto in protocols:
            tier = tier_of(proto)
            if defi_input.state != contract.MEASURED:
                reason = f"{defi_input.name} {defi_input.state.lower()}"
                share_cell = _absent_like({"state": defi_input.state, "source": defi_input.path_str,
                                            "as_of": defi_input.as_of_iso}, reason)
                usd_cell = _absent_like({"state": defi_input.state, "source": defi_input.path_str,
                                          "as_of": defi_input.as_of_iso}, reason)
            elif single:
                share_cell = contract.measured(bucket_share, unit="share", source=defi_input.path_str,
                                                as_of=defi_input.as_of_iso, note=share_basis_note)
                usd_cell = contract.measured(bucket_usd, unit="usd", source=defi_input.path_str,
                                              as_of=defi_input.as_of_iso)
            else:
                reason = (f"bucket '{mech_name}' aggregates {len(protocols)} protocols "
                          f"(bucket share {bucket_share}); no per-protocol split in defi_engine/status.json")
                share_cell = _not_measured(reason, source=defi_input.path_str, as_of=defi_input.as_of_iso)
                usd_cell = _not_measured(reason, source=defi_input.path_str, as_of=defi_input.as_of_iso)
            out.append({"protocol": proto, "mechanic": mech_name, "tier": tier or "UNKNOWN",
                        "share": share_cell, "usd": usd_cell})
    return out


# ── regime (display-only, shared across every sleeve) ──────────────────────────────────

def _regime_fit(chief_input: Input, funding_input: Input, market_input: Input) -> dict:
    chief_cell = _cell(
        observed(chief_input.doc, "house_view", kind=dict) and
        observed(observed(chief_input.doc, "house_view", kind=dict), "overall_posture", kind=str),
        unit=None, inp=chief_input, note="display-only (ADR-554 WP-A03 §10); no effect on weights",
    )
    funding_cell = _cell(observed(funding_input.doc, "regime", kind=str), unit=None, inp=funding_input,
                          note="UNKNOWN reads as not-GREEN for allocation purposes (display-only here)")
    market_cell = _cell(observed(market_input.doc, "regime", kind=str), unit=None, inp=market_input,
                         note=f"recommendation={observed(market_input.doc, 'recommendation', kind=str)}")
    return {"chief_posture": chief_cell, "funding_regime": funding_cell, "market_regime": market_cell}


# ── conservative stop/kill gate (ADR-554 finding 2) ─────────────────────────────────────

def _conservative_stop_gate(kill_input: Optional[Input],
                             derisk_input: Optional[Input]) -> tuple[Optional[bool], Optional[str]]:
    """(stop_breach, warning). ``None`` stop_breach forces the stop_not_active gate to UNKNOWN —
    a stale/unreadable kill or de-risk file, or a missing/non-bool ``triggered``/``active`` field,
    is NOT the same as "not triggered" (invariant #17). PASS is allowed only for a CLEAR*-state,
    fresh file with ``triggered``/``active`` both measured False; a non-plain-CLEAR state (e.g.
    CLEAR_PARTIAL) still PASSes but is named in a warning."""
    if kill_input is None or derisk_input is None:
        return None, None
    if kill_input.state != contract.MEASURED or derisk_input.state != contract.MEASURED:
        return None, None
    doc_k, doc_d = kill_input.doc, derisk_input.doc
    if not isinstance(doc_k, dict) or not isinstance(doc_d, dict):
        return None, None
    triggered = observed(doc_k, "triggered", kind=bool)
    active = observed(doc_d, "active", kind=bool)
    if not isinstance(triggered, bool) or not isinstance(active, bool):
        return None, None
    breach = triggered or active
    warning = None
    if not breach:
        kill_state = observed(doc_k, "state", kind=str)
        if not isinstance(kill_state, str) or not kill_state.strip().upper().startswith("CLEAR"):
            warning = f"kill_switch_status.state={kill_state!r} is not CLEAR* though triggered=False"
        elif kill_state.strip().upper() != "CLEAR":
            warning = f"kill_switch_status.state={kill_state!r} (CLEAR* but not plain CLEAR)"
    return breach, warning


# ── DeFi gates ───────────────────────────────────────────────────────────────────────────

def _defi_gates(defi_input: Input, pkg_doc: Optional[dict], stop_breach: Optional[bool],
                worst_case_cell: dict) -> list[dict]:
    pkg_doc = pkg_doc or {}
    data_state = observed(pkg_doc, "data", kind=dict) or {}
    work_state = observed(pkg_doc, "work", kind=dict) or {}
    gates = []
    ds = data_state.get("state")
    gates.append({"gate": "data_healthy", "state": "PASS" if ds == "HEALTHY" else ("FAIL" if ds else "UNKNOWN"),
                  "reason": data_state.get("reason") or ds or "no data block in package_status"})
    if defi_input.state == contract.STALE:
        fresh_state, fresh_reason = "FAIL", f"age {defi_input.age_hours:.2f}h > {defi_input.cadence_hours}h"
    elif defi_input.state == contract.NOT_MEASURED:
        fresh_state, fresh_reason = "UNKNOWN", defi_input.state_reason or "source unavailable"
    else:
        fresh_state, fresh_reason = "PASS", (f"age {defi_input.age_hours:.2f}h" if defi_input.age_hours is not None
                                              else "no as_of to age")
    gates.append({"gate": "data_fresh", "state": fresh_state, "reason": fresh_reason})
    ws = work_state.get("state")
    gates.append({"gate": "work_running", "state": "PASS" if ws == "RUNNING" else ("FAIL" if ws else "UNKNOWN"),
                  "reason": work_state.get("reason") or ws or "no work block in package_status"})
    if stop_breach is None:
        gates.append({"gate": "stop_not_active", "state": "UNKNOWN", "reason": "stop/kill state not available"})
    else:
        gates.append({"gate": "stop_not_active", "state": "FAIL" if stop_breach else "PASS",
                      "reason": "own stop or kill-switch triggered" if stop_breach else "no stop/kill triggered"})
    gates.append({"gate": "worst_case_loss_known",
                  "state": "PASS" if worst_case_cell.get("state") == contract.MEASURED else "FAIL",
                  "reason": worst_case_cell.get("reason") or "worst_case_loss measured"})
    return gates


# ── DeFi sleeve builder (conservative / balanced / aggressive) ─────────────────────────

_DEFI_SPEC = {
    "defi_conservative": {"pkg": "conservative", "book_file": None, "leveraged": False, "fixed_rate": False},
    "defi_balanced": {"pkg": "balanced", "book_file": "hy_paper_trading.json", "leveraged": False, "fixed_rate": True},
    "defi_aggressive": {"pkg": "aggressive", "book_file": "lp_paper_trading.json", "leveraged": True, "fixed_rate": False},
}


def _versions_closed(book_doc: Optional[dict]) -> list[dict]:
    out = []
    for exp in observed(book_doc, "experiments", kind=list) or []:
        if isinstance(exp, dict) and exp.get("status") == "closed":
            out.append({"experiment_id": exp.get("experiment_id"), "closed_at": exp.get("closed_at")})
    return out


def _current_version_rows(book_doc: Optional[dict]) -> list[dict]:
    rows = observed(book_doc, "daily_history", kind=list) or []
    current = [r for r in rows if isinstance(r, dict) and r.get("economics_model") == "sleeve-econ-v2"]
    return current if current else [r for r in rows if isinstance(r, dict)]


def _build_defi_sleeve(sleeve_id: str, defi_input: Input, book_input: Optional[Input],
                       equity_curve_input: Optional[Input], kill_input: Optional[Input],
                       derisk_input: Optional[Input], regime_fit: dict, now: datetime) -> dict:
    spec = _DEFI_SPEC[sleeve_id]
    pkg_key = spec["pkg"]
    out = _blank_sleeve(sleeve_id)
    out["correlation_features"] = {}

    books = observed(defi_input.doc, "books", kind=dict) or {}
    packages = observed(defi_input.doc, "packages", kind=dict) or {}
    book = books.get(pkg_key) if isinstance(books, dict) else None
    pkg = packages.get(pkg_key) if isinstance(packages, dict) else None

    out["mechanism"] = observed(pkg, "mechanic", kind=str)
    out["mode"] = observed(observed(pkg, "mode", kind=dict), "state", kind=str) or contract.MODE
    out["live_admission"] = observed(observed(pkg, "mode", kind=dict), "live", kind=str)
    out["experiment_id"] = observed(pkg, "experiment_id", kind=str)
    out["experiment_start"] = observed(pkg, "experiment_start_date", kind=str)
    out["versions_closed"] = _versions_closed(book_input.doc if book_input else None)

    exit_model = observed(book, "exit", kind=dict) or {}
    loss_budget_doc = observed(book, "loss_budget", kind=dict) or {}
    apy_doc = observed(book, "apy", kind=dict) or {}
    history = observed(pkg, "history", kind=dict) or {}

    out["capital_basis"] = _cell(exit_model.get("share_basis"), unit=None, inp=defi_input)
    out["current_equity"] = _cell(observed(book, "nav_usd", kind=(int, float)), unit="usd", inp=defi_input)

    out["observation_window"] = _cell(
        {"first_period": history.get("first_period"), "last_period": history.get("last_period")}
        if history else None,
        unit=None, inp=defi_input,
    )
    out["valid_periods"] = _cell(history.get("valid_periods"), unit="days", inp=defi_input, n=history.get("valid_periods"))
    out["maturity"] = _maturity_cell(out["valid_periods"])

    spot_net = apy_doc.get("book_spot_apy_net") or {}
    out["expected_return"] = _cell(spot_net.get("value"), unit="pct_annualized", inp=defi_input,
                                    nm_reason=spot_net.get("unmeasured_reason") or "book_spot_apy_net unmeasured")

    realized = apy_doc.get("track_realized_apy_net") or {}
    n_bars = realized.get("days")
    n_bars_numeric = isinstance(n_bars, (int, float)) and not isinstance(n_bars, bool)
    if defi_input.state == contract.MEASURED and realized.get("value") is not None:
        if not n_bars_numeric:
            # ADR-554 finding 12: a non-numeric bar count must NOT fall through to "enough bars" —
            # the bar count is unknown, not zero and not large; never MEASURED with n=None.
            out["realized_return"] = contract.absent(
                contract.NOT_ENOUGH_HISTORY,
                reason=f"bar count unknown; raw value {realized.get('value')}%",
                source=defi_input.path_str, as_of=defi_input.as_of_iso, n=None,
            )
        elif n_bars < POLICY["rate_min_bars"]:
            out["realized_return"] = contract.absent(
                contract.NOT_ENOUGH_HISTORY,
                reason=f"only {n_bars} bar(s) < {POLICY['rate_min_bars']} bar minimum; raw {realized.get('value')}%",
                source=defi_input.path_str, as_of=defi_input.as_of_iso, n=n_bars,
            )
        else:
            out["realized_return"] = contract.measured(
                realized.get("value"), unit="pct_annualized", source=defi_input.path_str,
                as_of=defi_input.as_of_iso, n=n_bars,
                note=f"{realized.get('first_date')}..{realized.get('last_date')}",
            )
    else:
        out["realized_return"] = _cell(None, unit="pct_annualized", inp=defi_input,
                                        nm_reason="track_realized_apy_net unavailable")

    # volatility: pstdev of per-row apy_pct (conservative: daily_return_pct) over current economics
    if sleeve_id == "defi_conservative" and equity_curve_input is not None:
        rows = [r for r in (observed(equity_curve_input.doc, "daily", kind=list) or [])
                if isinstance(r, dict) and r.get("evidenced") is True]
        values = [r.get("daily_return_pct") for r in rows if isinstance(r.get("daily_return_pct"), (int, float))]
        n = len(values)
        if equity_curve_input.state != contract.MEASURED:
            out["volatility"] = _cell(None, unit="pct_daily_stdev", inp=equity_curve_input)
            out["max_drawdown"] = _cell(None, unit="pct", inp=equity_curve_input)
        elif n < 2:
            out["volatility"] = contract.absent(contract.NOT_ENOUGH_HISTORY, reason=f"only {n} evidenced bar(s)",
                                                 source=equity_curve_input.path_str,
                                                 as_of=equity_curve_input.as_of_iso, n=n)
            out["max_drawdown"] = _cell(None, unit="pct", inp=equity_curve_input)
        else:
            stdev = statistics.pstdev(values)
            if n < POLICY["rate_min_bars"]:
                out["volatility"] = contract.absent(contract.NOT_ENOUGH_HISTORY,
                                                     reason=f"only {n} bar(s) < {POLICY['rate_min_bars']}; raw {stdev}",
                                                     source=equity_curve_input.path_str,
                                                     as_of=equity_curve_input.as_of_iso, n=n)
            else:
                out["volatility"] = contract.measured(round(stdev, 4), unit="pct_daily_stdev",
                                                        source=equity_curve_input.path_str,
                                                        as_of=equity_curve_input.as_of_iso, n=n)
            summary = observed(equity_curve_input.doc, "summary", kind=dict) or {}
            mdd = summary.get("real_max_drawdown_pct")
            real_days = summary.get("real_days")
            out["max_drawdown"] = contract.measured(mdd, unit="pct", source=equity_curve_input.path_str,
                                                      as_of=equity_curve_input.as_of_iso, n=real_days) \
                if mdd is not None else _not_measured("real_max_drawdown_pct unavailable",
                                                       source=equity_curve_input.path_str,
                                                       as_of=equity_curve_input.as_of_iso)
    else:
        current_rows = _current_version_rows(book_input.doc if book_input else None)
        apy_values = [r.get("apy_pct") for r in current_rows if isinstance(r.get("apy_pct"), (int, float))]
        n = len(apy_values)
        if book_input is None or book_input.state == contract.NOT_MEASURED:
            vol_cell = _cell(None, unit="pct_stdev", inp=book_input) if book_input else \
                _not_measured(f"{spec['book_file']} unavailable")
        elif book_input.state == contract.STALE:
            vol_cell = _absent_like({"state": contract.STALE, "source": book_input.path_str,
                                      "as_of": book_input.as_of_iso}, f"{book_input.name} stale")
        elif n < 2:
            vol_cell = contract.absent(contract.NOT_ENOUGH_HISTORY, reason=f"only {n} current-economics row(s)",
                                        source=book_input.path_str, as_of=book_input.as_of_iso, n=n)
        else:
            stdev = statistics.pstdev(apy_values)
            if n < POLICY["rate_min_bars"]:
                vol_cell = contract.absent(contract.NOT_ENOUGH_HISTORY,
                                            reason=f"only {n} bar(s) < {POLICY['rate_min_bars']}; raw {stdev}",
                                            source=book_input.path_str, as_of=book_input.as_of_iso, n=n)
            else:
                vol_cell = contract.measured(round(stdev, 4), unit="pct_stdev", source=book_input.path_str,
                                              as_of=book_input.as_of_iso, n=n)
        out["volatility"] = vol_cell
        mdd = history.get("observed_drawdown_pct")
        out["max_drawdown"] = _cell(mdd, unit="pct", inp=defi_input, n=history.get("valid_periods"))

    out["liquidity"] = _cell(exit_model.get("share_exitable_24h"), unit="share_of_nav_24h", inp=defi_input,
                              nm_reason=exit_model.get("share_exitable_24h_reason") or "share_exitable_24h unavailable")
    out["time_to_exit"] = _cell(exit_model.get("nav_weighted_exit_latency_hours"), unit="hours", inp=defi_input)

    cash_usd = observed(book, "cash_usd", kind=(int, float))
    nav_usd = observed(book, "nav_usd", kind=(int, float))
    if defi_input.state == contract.MEASURED and cash_usd is not None and nav_usd:
        out["cash_share"] = contract.measured(round(cash_usd / nav_usd, 6), unit="ratio", source=defi_input.path_str,
                                                as_of=defi_input.as_of_iso, note="cash_usd/nav_usd")
    else:
        out["cash_share"] = _cell(None, unit="ratio", inp=defi_input,
                                   nm_reason=observed(book, "cash_reason", kind=str) or
                                   "sleeve state carries no cash field")

    # leverage / gross exposure
    if sleeve_id == "defi_aggressive":
        loop = observed(book_input.doc if book_input else None, "loop", kind=dict) or {}
        lev = observed(observed(observed(loop, "entry", kind=dict), "economics", kind=dict) or {}, "leverage",
                        kind=(int, float))
        out["leverage"] = _cell(lev, unit="x", inp=book_input) if book_input else _not_measured("lp book unavailable")
        val = observed(loop, "last_valuation", kind=dict) or {}
        debt = val.get("debt_value")
        eq = val.get("equity")
        if book_input is not None and book_input.state == contract.MEASURED and debt is not None and eq is not None \
                and nav_usd:
            out["gross_exposure_over_nav"] = contract.measured(round((debt + eq) / nav_usd, 4), unit="ratio",
                                                                source=book_input.path_str, as_of=book_input.as_of_iso,
                                                                note="(loop debt + loop equity) / book nav")
        else:
            out["gross_exposure_over_nav"] = _cell(None, unit="ratio", inp=book_input) if book_input else \
                _not_measured("lp book unavailable")
    else:
        # unlevered-by-mandate (ADR-554 finding 9a): leverage=1.0/gross_exposure=1.0 are MEASURED only
        # when the engine's own mechanic_exposure shows no leveraged (loop) mechanic in this book —
        # a positive source, not an assumption from "this book has no leverage field".
        mech_exposure_for_leverage = observed(book, "mechanic_exposure", kind=dict)
        unlevered_confirmed = (defi_input.state == contract.MEASURED and
                               _mechanic_exposure_confirms_unlevered(mech_exposure_for_leverage))
        if unlevered_confirmed:
            out["leverage"] = contract.measured(
                1.0, unit="x", source=defi_input.path_str, as_of=defi_input.as_of_iso,
                note="unlevered by mandate: engine mechanic_exposure shows no leveraged (loop) mechanic")
            out["gross_exposure_over_nav"] = contract.measured(
                1.0, unit="ratio", source=defi_input.path_str, as_of=defi_input.as_of_iso,
                note="unlevered by mandate: engine mechanic_exposure shows no leveraged (loop) mechanic")
        elif defi_input.state == contract.MEASURED:
            out["leverage"] = contract.absent(contract.NOT_MEASURED, reason="no leverage field in the book",
                                               source=defi_input.path_str, as_of=defi_input.as_of_iso)
            out["gross_exposure_over_nav"] = contract.absent(contract.NOT_MEASURED,
                                                              reason="no leverage field in the book",
                                                              source=defi_input.path_str, as_of=defi_input.as_of_iso)
        else:
            out["leverage"] = _cell(None, unit="x", inp=defi_input)
            out["gross_exposure_over_nav"] = _cell(None, unit="ratio", inp=defi_input)

    out["nearest_enforced_stop"] = _nearest_liquidating_stop_cell(book, defi_input, loss_budget_doc)
    out["loss_budget"] = _cell(loss_budget_doc.get("budget_pct"), unit="pct", inp=defi_input)

    # stress loss
    if spec["leveraged"]:
        loop_stress = observed(book_input.doc if book_input else None, "loop_stress", kind=list) or []
        worst = None
        for scen in loop_stress:
            if not isinstance(scen, dict):
                continue
            chg = scen.get("equity_change_pct")
            if not isinstance(chg, (int, float)):
                continue
            if worst is None or abs(chg) > abs(worst[0]):
                worst = (chg, scen.get("scenario"))
        if book_input is None:
            out["stress_loss"] = _not_measured("book unavailable")
        elif book_input.state != contract.MEASURED:
            out["stress_loss"] = _absent_like({"state": book_input.state, "source": book_input.path_str,
                                                "as_of": book_input.as_of_iso}, f"{book_input.name} not fresh")
        elif worst is None:
            out["stress_loss"] = _not_measured("no loop_stress scenarios published", source=book_input.path_str,
                                                as_of=book_input.as_of_iso)
        else:
            out["stress_loss"] = contract.measured(round(abs(worst[0]), 3), unit="pct", source=book_input.path_str,
                                                    as_of=book_input.as_of_iso,
                                                    note=f"worst modelled scenario: {worst[1]}")
    elif spec["fixed_rate"]:
        out["stress_loss"] = _not_measured(
            "book carries no stress scenario (fixed-rate PT has no loop_stress model)",
            source=book_input.path_str if book_input else None,
            as_of=book_input.as_of_iso if book_input else None,
        )
    else:
        out["stress_loss"] = _not_measured("unlevered lending; no stress model (stop used as the bound)",
                                            source=defi_input.path_str, as_of=defi_input.as_of_iso)

    out["worst_case_loss"] = _worst_case_loss(_DEFI_SPEC[sleeve_id] and contract.SLEEVES[sleeve_id]["mechanism_class"],
                                               out["nearest_enforced_stop"], out["stress_loss"])

    # mtm coverage
    if sleeve_id == "defi_conservative":
        out["mtm_coverage"] = _cell(None, unit="pct", inp=equity_curve_input,
                                     nm_reason="equity_curve_daily.json carries no mtm_coverage_pct field "
                                               "(lending accrual not separately marked)") if equity_curve_input \
            else _not_measured("equity_curve_daily.json unavailable")
    else:
        current_rows = _current_version_rows(book_input.doc if book_input else None)
        mtm_vals = [r.get("mtm_coverage_pct") for r in current_rows if isinstance(r.get("mtm_coverage_pct"), (int, float))]
        if book_input is None:
            out["mtm_coverage"] = _not_measured(f"{spec['book_file']} unavailable")
        elif book_input.state != contract.MEASURED:
            out["mtm_coverage"] = _absent_like({"state": book_input.state, "source": book_input.path_str,
                                                 "as_of": book_input.as_of_iso}, f"{book_input.name} not fresh")
        elif mtm_vals:
            out["mtm_coverage"] = contract.measured(mtm_vals[-1], unit="pct", source=book_input.path_str,
                                                      as_of=book_input.as_of_iso,
                                                      note="daily_history mtm_coverage_pct (latest current-economics row)")
        else:
            out["mtm_coverage"] = _not_measured("no mtm_coverage_pct in daily_history", source=book_input.path_str,
                                                 as_of=book_input.as_of_iso)

    # data_freshness
    if defi_input.state == contract.NOT_MEASURED:
        out["data_freshness"] = _not_measured("defi_engine/status.json unavailable")
    elif defi_input.state == contract.STALE:
        out["data_freshness"] = contract.absent(contract.STALE,
                                                 reason=f"age {defi_input.age_hours:.2f}h > {defi_input.cadence_hours}h",
                                                 source=defi_input.path_str, as_of=defi_input.as_of_iso)
    else:
        out["data_freshness"] = contract.measured(
            {"state": "FRESH", "age_hours": round(defi_input.age_hours, 3) if defi_input.age_hours is not None else None,
             "threshold_hours": defi_input.cadence_hours},
            unit=None, source=defi_input.path_str, as_of=defi_input.as_of_iso,
        )

    out["evidence_state"] = _cell(observed(book, "evidence_level", kind=str), unit=None, inp=defi_input)
    out["regime_fit"] = dict(regime_fit)
    out["confidence"] = _confidence_cell(out["maturity"], out["mtm_coverage"])
    out["capacity"] = _not_measured(
        "capacity not computed per sleeve (ADR-554 Phase 0 finding H: capacity modules unread)")

    # risk axes
    tiers_held = observed(observed(pkg, "composition", kind=dict) or {}, "tiers_held", kind=dict) or {}
    findings = [f for f in (observed(defi_input.doc, "findings", kind=list) or [])
                if isinstance(f, dict) and f.get("book") == pkg_key]
    out["risk"] = _defi_risk_axes(sleeve_id, tiers_held, findings, out, defi_input, apy_doc, exit_model)

    out["composition"] = _composition_from_mechanic_exposure(
        observed(book, "mechanic_exposure", kind=dict), defi_input, exit_model.get("share_basis"))
    protocol_names = [c["protocol"] for c in out["composition"]]
    out["factors"] = _factors_for(protocol_names, sleeve_id)

    out["correlation_features"] = {
        "series_source": book_input.path_str if (spec["book_file"] and book_input) else
                          (equity_curve_input.path_str if equity_curve_input else None),
        "accrual_basis": "per_position_observed_apy" if spec["book_file"] else "evidenced daily bars",
        "current_economics_only": True,
    }

    stop_breach, stop_warning = None, None
    if sleeve_id == "defi_conservative":
        stop_breach, stop_warning = _conservative_stop_gate(kill_input, derisk_input)
    elif book_input is not None and book_input.state == contract.MEASURED:
        # a STALE/unreadable book file must not be read as "stop not breached" (ADR-554 finding
        # N4 — same fail-closed pattern as the conservative gate's finding-2 fix above).
        stop_ref = observed(book_input.doc, "stop_reference", kind=dict)
        if stop_ref and isinstance(stop_ref.get("drawdown_pct"), (int, float)) and \
                isinstance(stop_ref.get("threshold_pct"), (int, float)):
            # strict '<': the books' own stop logic is strict, a drawdown exactly at the threshold
            # has not yet crossed it (ADR-554 finding 17).
            stop_breach = stop_ref["drawdown_pct"] < stop_ref["threshold_pct"]
    out["gates"] = _defi_gates(defi_input, pkg, stop_breach, out["worst_case_loss"])

    findings_texts = [f.get("kind") for f in findings]
    out["warnings"] = [f"{pkg_key}: {f.get('kind')}" for f in findings]
    if stop_warning:
        out["warnings"].append(stop_warning)
    unknowns = ["COUNTERPARTY risk has no source", "capacity not computed per sleeve"]
    unresolved = observed(observed(pkg, "composition", kind=dict) or {}, "unresolved", kind=dict) or {}
    for proto, why in unresolved.items():
        unknowns.append(f"{proto}: {why}")
    out["unknowns"] = unknowns
    return out


def _defi_risk_axes(sleeve_id: str, tiers_held: dict, findings: list[dict], sleeve: dict, defi_input: Input,
                    apy_doc: Optional[dict] = None, exit_model: Optional[dict] = None) -> dict:
    src = defi_input.path_str
    has_t3 = bool(tiers_held.get("T3")) or bool(tiers_held.get("unresolved"))
    has_only_t1 = set(tiers_held.keys()) <= {"T1"}
    protocol_level = "HIGH" if has_t3 else ("LOW" if has_only_t1 else "MEDIUM")
    axes = {
        "PROTOCOL": {"level": protocol_level, "evidence": f"tiers_held={tiers_held}", "source": src},
        "COUNTERPARTY": {"level": "UNKNOWN", "evidence": "no source today", "source": None},
    }
    mtm = sleeve["mtm_coverage"]
    immature = sleeve["maturity"].get("value") == contract.MATURITY_IMMATURE
    mtm_zero = mtm.get("state") == contract.MEASURED and mtm.get("value") == 0.0
    axes["DATA_MODEL"] = {
        "level": "HIGH" if (mtm_zero or immature) else "MEDIUM",
        "evidence": f"maturity={sleeve['maturity'].get('value')}, mtm_coverage={mtm.get('value')}",
        "source": src,
    }
    cap_finding = any(f.get("kind") == "mechanic_cap" for f in findings)
    liq_finding = any(f.get("kind") == "exit_liquidity" for f in findings)

    # ADR-554 finding 9c: evidence strings built from the actual values read — never a hardcoded
    # qualitative claim ("measured and small", "~3.3x", "near the 25% threshold") that would stay
    # on the page unchanged after the real number moved. Not read => level UNKNOWN, "not measured".
    cost_drag = (apy_doc or {}).get("book_cost_drag_30d")
    cost_drag_val = cost_drag.get("value") if isinstance(cost_drag, dict) else None
    cost_drag_window = cost_drag.get("window_days") if isinstance(cost_drag, dict) else None
    cost_drag_known = isinstance(cost_drag_val, (int, float)) and not isinstance(cost_drag_val, bool)
    share_illiquid = (exit_model or {}).get("share_illiquid")
    share_illiquid_known = isinstance(share_illiquid, (int, float)) and not isinstance(share_illiquid, bool)
    leverage_val = contract.value_of(sleeve.get("leverage"))

    def _execution_axis(level_if_known: str) -> dict:
        if cost_drag_known:
            return {"level": level_if_known,
                    "evidence": f"book_cost_drag_30d={cost_drag_val}% over {cost_drag_window}d",
                    "source": src}
        return {"level": "UNKNOWN", "evidence": "not measured", "source": src}

    def _leverage_axis(level_if_known: str, template: str) -> dict:
        if leverage_val is not None:
            return {"level": level_if_known, "evidence": template.format(leverage_val), "source": src}
        return {"level": "UNKNOWN", "evidence": "not measured", "source": src}

    if sleeve_id == "defi_conservative":
        axes["STRATEGY"] = {"level": "LOW", "evidence": "unlevered_lending mechanism_class", "source": src}
        axes["MARKET"] = {"level": "LOW", "evidence": "stablecoin lending, no directional/peg exposure", "source": src}
        axes["EXECUTION"] = _execution_axis("LOW")
        if liq_finding:
            axes["LIQUIDITY"] = {"level": "HIGH", "evidence": "exit_liquidity finding", "source": src}
        elif share_illiquid_known:
            axes["LIQUIDITY"] = {"level": "LOW", "evidence": f"share_illiquid={share_illiquid}", "source": src}
        else:
            axes["LIQUIDITY"] = {"level": "UNKNOWN", "evidence": "not measured", "source": src}
        axes["LEVERAGE"] = _leverage_axis("LOW", "leverage={}, unlevered")
    elif sleeve_id == "defi_balanced":
        axes["STRATEGY"] = {"level": "MEDIUM", "evidence": "fixed_rate_pt mixed with rwa_credit + staked_synthetic",
                             "source": src}
        axes["MARKET"] = {"level": "MEDIUM", "evidence": "susde (USDe peg) exposure in composition", "source": src}
        axes["EXECUTION"] = _execution_axis("MEDIUM")
        if liq_finding:
            axes["LIQUIDITY"] = {"level": "HIGH", "evidence": "exit_liquidity finding: policy_ok=False", "source": src}
        elif share_illiquid_known:
            axes["LIQUIDITY"] = {"level": "MEDIUM", "evidence": f"share_illiquid={share_illiquid}", "source": src}
        else:
            axes["LIQUIDITY"] = {"level": "UNKNOWN", "evidence": "not measured", "source": src}
        axes["LEVERAGE"] = _leverage_axis("LOW", "leverage={}")
    else:  # aggressive
        axes["STRATEGY"] = {"level": "HIGH" if cap_finding else "MEDIUM",
                             "evidence": "leveraged_loop; above advisory mechanic cap" if cap_finding else
                             "leveraged_loop mechanism_class", "source": src}
        axes["MARKET"] = {"level": "HIGH", "evidence": "sUSDe/PYUSD loop; depeg stress scenarios modelled",
                           "source": src}
        axes["EXECUTION"] = {"level": "MEDIUM", "evidence": "loop entry round-trip + amortised cost measured",
                              "source": src}
        if share_illiquid_known:
            axes["LIQUIDITY"] = {"level": "MEDIUM", "evidence": f"share_illiquid={share_illiquid} (policy threshold "
                                                                 f"0.25)", "source": src}
        else:
            axes["LIQUIDITY"] = {"level": "UNKNOWN", "evidence": "not measured", "source": src}
        axes["LEVERAGE"] = _leverage_axis("HIGH", "loop entry leverage {}x")
    return axes


# ── cash sleeve ──────────────────────────────────────────────────────────────────────────

def _build_cash_sleeve(books_doc: dict, regime_fit: dict, now: datetime) -> dict:
    out = _blank_sleeve("cash")
    out["mechanism"] = "idle USDC buffer (RiskPolicy min_cash_pct, look-through across books)"
    out["mode"] = contract.MODE
    out["live_admission"] = "NOT_APPLICABLE"
    nowiso = now.isoformat()
    out["capital_basis"] = contract.measured("look-through cash across the three DeFi books", unit=None,
                                              source="ADR-554 WP-A03 §5", as_of=nowiso)
    out["observation_window"] = _not_measured("cash is a buffer, not a tracked experiment; no window to report")
    out["valid_periods"] = _not_measured("cash is a buffer, not a tracked experiment; no valid_periods counter")
    out["maturity"] = _maturity_cell(out["valid_periods"])

    cash_vals = []
    all_known = True
    for pkg_key, book in (books_doc or {}).items():
        if not isinstance(book, dict):
            continue
        c = book.get("cash_usd")
        if c is None:
            all_known = False
        else:
            cash_vals.append(c)
    if all_known and cash_vals:
        out["current_equity"] = contract.measured(round(sum(cash_vals), 2), unit="usd",
                                                    source="defi_engine/status.json books.*.cash_usd",
                                                    as_of=nowiso, note="sum across books")
    else:
        out["current_equity"] = _not_measured(
            "at least one book carries no cash field; look-through cash is UNKNOWN, never assumed "
            "(ADR-554 WP-A03 §5)", source="defi_engine/status.json books.*.cash_usd")

    note0 = "no accrual exists for idle cash (ADR-554 audit)"
    out["expected_return"] = contract.definitional(0.0, unit="pct_annualized", basis=note0, as_of=nowiso)
    out["realized_return"] = contract.definitional(0.0, unit="pct_annualized", basis=note0, as_of=nowiso)
    out["volatility"] = contract.definitional(0.0, unit="pct_stdev", basis="idle cash, no price variance",
                                              as_of=nowiso)
    out["max_drawdown"] = contract.definitional(0.0, unit="pct", basis="idle cash; no drawdown possible by construction",
                                                as_of=nowiso)
    out["liquidity"] = contract.measured(1.0, unit="share_of_nav_24h", source="definitional", as_of=nowiso,
                                          note="cash is immediately exitable by definition")
    out["time_to_exit"] = contract.measured(0.0, unit="hours", source="definitional", as_of=nowiso)
    out["cash_share"] = contract.measured(1.0, unit="ratio", source="definitional", as_of=nowiso,
                                           note="this sleeve IS cash by definition")
    out["gross_exposure_over_nav"] = contract.measured(0.0, unit="ratio", source="definitional", as_of=nowiso,
                                                        note="idle cash has no market exposure")
    out["leverage"] = contract.measured(0.0, unit="x", source="definitional", as_of=nowiso,
                                         note="no position; idle cash")
    out["nearest_enforced_stop"] = _not_measured("cash carries no enforced stop (no position at risk)")
    out["loss_budget"] = _not_measured("no loss budget defined for idle cash")
    out["stress_loss"] = _not_measured("no stress model for idle cash")
    out["worst_case_loss"] = _not_measured(
        "no stop and no stress model for idle cash (USDC depeg/custody risk not modelled)")
    out["mtm_coverage"] = _not_measured("no mark-to-market concept for cash")
    out["data_freshness"] = _not_measured("cash has no engine feed to measure freshness against")
    out["evidence_state"] = contract.measured("definitional", unit=None, source="ADR-554 audit", as_of=nowiso,
                                               note="no evidence track; defined by policy, not observed")
    out["regime_fit"] = dict(regime_fit)
    out["confidence"] = contract.definitional("HIGH", unit=None, basis="cash's 0% accrual is definitional, not estimated",
                                              as_of=nowiso)
    out["capacity"] = _not_measured("no capacity constraint modelled for cash (buffer, not a deployed position)")
    out["risk"] = {
        "PROTOCOL": {"level": "LOW", "evidence": "idle USDC, no protocol exposure", "source": None},
        "STRATEGY": {"level": "LOW", "evidence": "no strategy; buffer", "source": None},
        "MARKET": {"level": "LOW", "evidence": "no directional exposure", "source": None},
        "EXECUTION": {"level": "LOW", "evidence": "no trade executed", "source": None},
        "LIQUIDITY": {"level": "LOW", "evidence": "immediately exitable by definition", "source": None},
        "COUNTERPARTY": {"level": "UNKNOWN", "evidence": "USDC issuer/custody risk has no source", "source": None},
        "LEVERAGE": {"level": "LOW", "evidence": "no position", "source": None},
        "DATA_MODEL": {"level": "MEDIUM", "evidence": "no accrual/pricing model for idle cash", "source": None},
    }
    out["composition"] = [{
        "protocol": "usdc", "mechanic": "cash_buffer", "tier": "UNKNOWN",
        "share": contract.measured(1.0, unit="share", source="definitional", as_of=nowiso),
        "usd": out["current_equity"],
    }]
    out["factors"] = _factors_for(["usdc"], "cash")
    out["correlation_features"] = {"series_source": None,
                                    "note": "no return series; 0% by definition, not a traded series"}
    out["gates"] = [
        {"gate": "data_healthy", "state": "UNKNOWN", "reason": "no engine feed for cash"},
        {"gate": "data_fresh", "state": "UNKNOWN", "reason": "no engine feed for cash"},
        {"gate": "work_running", "state": "UNKNOWN", "reason": "no scheduled job for a buffer"},
        {"gate": "stop_not_active", "state": "UNKNOWN", "reason": "no stop defined"},
        {"gate": "worst_case_loss_known", "state": "UNKNOWN",
         "reason": "cash is the always-feasible residual, not an eligibility-gated risk sleeve; USDC peg/custody "
                   "risk is not modelled (named under factors)"},
    ]
    out["warnings"] = []
    out["unknowns"] = [
        "no accrual model for idle cash beyond the definitional 0%",
        "COUNTERPARTY (USDC issuer/custody) risk has no source",
        "look-through cash total across books is UNKNOWN when any book's own cash field is unmeasured",
    ]
    return out


# ── trading_research sleeve ─────────────────────────────────────────────────────────────

def _build_trading_research_sleeve(tr_input: Input, regime_fit: dict) -> dict:
    out = _blank_sleeve("trading_research")
    doc = tr_input.doc or {}
    out["mechanism"] = "BTC rule-based directional strategies; backtest-qualified, shortlisted into forward paper"
    out["mode"] = observed(doc, "mode", kind=str) or "PAPER_RESEARCH_ONLY"
    out["live_admission"] = out["mode"]

    # ADR-554 finding 18: a missing live_capital_usd defaulted to a MEASURED 0.0 whenever the file
    # was merely fresh — a fabricated zero, not an observed one (invariant #17). Only an EXPLICIT
    # value in the document (0 included) is measured; absence stays NOT_MEASURED.
    live_cap = observed(doc, "live_capital_usd", kind=(int, float))
    out["current_equity"] = _cell(live_cap, unit="usd", inp=tr_input,
                                   nm_reason="live_capital_usd not published",
                                   note="observe-only, no capital deployed (PAPER_RESEARCH_ONLY)")
    out["capital_basis"] = _not_measured("observe-only; no committed capital basis (live_capital_usd=0 by design)")
    out["observation_window"] = _cell(
        {"forward_since_ms": observed(doc, "forward_since_ms", kind=(int, float))}, unit=None, inp=tr_input)
    out["valid_periods"] = _not_measured(
        "trading_research tracks forward_observations per candidate, not a single sleeve-level "
        "valid_periods counter")
    out["maturity"] = _maturity_cell(out["valid_periods"])
    out["expected_return"] = _not_measured(
        "no forward-return expectation published at sleeve level (per-candidate OOS metrics only)")
    # ADR-590 fix D8: "forward_candidates" is the lifecycle-derived FORWARD_PAPER/ROBUST set;
    # "shortlist" is the backtest top-5 after de-dup and is read here only as a fallback for a
    # status.json written before this field existed.
    forward_candidates = (observed(doc, "forward_candidates", kind=list)
                          or observed(doc, "shortlist", kind=list) or [])
    # fix D1: "forward_observations" is the real COUNT(*); "forward_bars" (older files) carries a
    # +1 synthetic seed point and is only a fallback here, never preferred when both are present.
    min_obs = min((s.get("forward_observations", s.get("forward_bars")) for s in forward_candidates
                   if isinstance(s, dict) and
                   isinstance(s.get("forward_observations", s.get("forward_bars")), (int, float))),
                  default=None)
    out["realized_return"] = contract.absent(
        contract.NOT_ENOUGH_HISTORY,
        reason=f"best candidate has only {min_obs} forward bar(s); no blended sleeve return" if min_obs is not None
        else "no forward bars published", source=tr_input.path_str, as_of=tr_input.as_of_iso, n=min_obs)
    out["volatility"] = _not_measured("no blended sleeve-level return series")
    out["max_drawdown"] = _not_measured(
        "only per-candidate OOS max_drawdown exists (shortlist), not a blended sleeve figure")
    out["liquidity"] = contract.measured(1.0, unit="share_of_nav_24h", source=tr_input.path_str,
                                          as_of=tr_input.as_of_iso, note="BTC spot, highly liquid") \
        if tr_input.state == contract.MEASURED else _cell(None, unit="share_of_nav_24h", inp=tr_input)
    # ADR-554 finding 9b: 0.0/1.0 here used to be inferred from a shortlist id TAG ("spot_long"),
    # not read from a declared field — a fabricated source. No such field is published today, so
    # both stay NOT_MEASURED until a real per-candidate leverage/lockup field exists to read.
    out["time_to_exit"] = _not_measured(
        "no lockup/time-to-exit field published per shortlist candidate (id-tag inference is not a measurement)")
    out["cash_share"] = _not_measured("sleeve state carries no cash field (observe-only, no book)")
    out["gross_exposure_over_nav"] = _not_measured("no book; observe-only, no capital basis for gross exposure")
    out["leverage"] = _not_measured(
        "no leverage field published per shortlist candidate (id-tag inference is not a measurement)")
    out["nearest_enforced_stop"] = _not_measured("observe-only; no enforced stop (outside paper money-path)")
    out["loss_budget"] = _not_measured("observe-only; no loss budget defined")
    out["stress_loss"] = _not_measured("no stress model published for trading-research candidates")
    out["worst_case_loss"] = _not_measured("no stop and no stress model; observe-only")
    out["mtm_coverage"] = _not_measured("no mtm concept published for trading_research")
    if tr_input.state == contract.NOT_MEASURED:
        out["data_freshness"] = _not_measured("trading_research/status.json unavailable")
    elif tr_input.state == contract.STALE:
        out["data_freshness"] = contract.absent(contract.STALE,
                                                 reason=f"age {tr_input.age_hours:.2f}h > {tr_input.cadence_hours}h",
                                                 source=tr_input.path_str, as_of=tr_input.as_of_iso)
    else:
        out["data_freshness"] = contract.measured(
            {"state": "FRESH", "age_hours": round(tr_input.age_hours, 3) if tr_input.age_hours is not None else None},
            unit=None, source=tr_input.path_str, as_of=tr_input.as_of_iso)
    out["evidence_state"] = contract.measured(
        f"backtest_qualified={observed(doc, 'backtest_qualified', kind=int)}, "
        f"forward_paper={observed(doc, 'forward_paper', kind=int)}, "
        f"evidence_verified={observed(doc, 'evidence_verified', kind=bool)}",
        unit=None, source=tr_input.path_str, as_of=tr_input.as_of_iso) \
        if tr_input.state == contract.MEASURED else _cell(None, unit=None, inp=tr_input)
    out["regime_fit"] = dict(regime_fit)
    out["confidence"] = contract.measured("LOW", unit=None, source="cio-policy-v1", as_of=tr_input.as_of_iso,
                                           note="observe-only, tiny forward-paper samples")
    out["capacity"] = _not_measured("no capacity model (research-only, no live capital)")
    out["risk"] = {
        "PROTOCOL": {"level": "LOW", "evidence": "BTC spot/futures, no lending-protocol exposure", "source": None},
        "STRATEGY": {"level": "HIGH", "evidence": "directional momentum strategies, 133/138 rejected", "source": tr_input.path_str},
        "MARKET": {"level": "HIGH", "evidence": "btc_direction factor, full directional exposure", "source": tr_input.path_str},
        "EXECUTION": {"level": "MEDIUM", "evidence": "forward-paper simulation, no live slippage model", "source": tr_input.path_str},
        "LIQUIDITY": {"level": "LOW", "evidence": "BTC spot, highly liquid", "source": None},
        "COUNTERPARTY": {"level": "UNKNOWN", "evidence": "no source today", "source": None},
        "LEVERAGE": {"level": "LOW", "evidence": "spot_long, no leverage disclosed", "source": tr_input.path_str},
        "DATA_MODEL": {"level": "HIGH", "evidence": f"forward bars 3-18; min={min_obs}", "source": tr_input.path_str},
    }
    out["composition"] = [
        {"protocol": s.get("id"), "mechanic": "directional_trading", "tier": "UNKNOWN",
         "share": _not_measured("no capital allocated (observe-only)"),
         "usd": _not_measured("no capital allocated (observe-only)")}
        for s in forward_candidates if isinstance(s, dict)
    ]
    out["factors"] = _factors_for([], "trading_research")
    out["correlation_features"] = {"series_source": None,
                                    "note": "no blended equity series published at sleeve level"}
    ok = observed(doc, "ok", kind=bool)
    out["gates"] = [
        {"gate": "data_healthy", "state": "PASS" if ok else ("FAIL" if ok is not None else "UNKNOWN"),
         "reason": f"status.ok={ok}"},
        {"gate": "data_fresh",
         "state": "FAIL" if tr_input.state == contract.STALE else
                  ("UNKNOWN" if tr_input.state == contract.NOT_MEASURED else "PASS"),
         "reason": "see data_freshness cell"},
        {"gate": "work_running", "state": "UNKNOWN", "reason": "no scheduled-job state published"},
        {"gate": "stop_not_active", "state": "UNKNOWN", "reason": "no stop defined (observe-only)"},
        {"gate": "worst_case_loss_known", "state": "FAIL", "reason": "no stop/stress model"},
    ]
    out["warnings"] = []
    out["unknowns"] = ["no blended sleeve-level return or drawdown, only per-candidate OOS metrics",
                       "no capacity or stress model published"]
    return out


# ── market_neutral_basis sleeve ─────────────────────────────────────────────────────────

def _frozen_pendle_timestamp(doc: Any) -> tuple:
    """``(datetime_or_None, display_date_string_or_None)`` for when
    ``rates_desk/pendle_pt_history.json``'s inputs are frozen at.

    Prefers ``generated_at``'s FULL precision (hour-of-day matters for the age-vs-cadence
    judgement in :func:`_susde_dn_effective_state` — REWORK M6a found that truncating to a bare
    date before computing age could move a boundary case by several hours and flip the verdict);
    falls back to the declared ``window.end``, else the latest per-market series date, ONLY when
    ``generated_at`` itself is absent/unparseable — those two fallbacks never carry a time-of-day,
    so their datetime is midnight UTC on that date (a conservative, explicitly-approximate lower
    bound on freshness, never silently treated as more precise than it is).
    ``(None, None)`` only when nothing at all is readable."""
    if not isinstance(doc, dict):
        return None, None
    gen = _as_of_generated_at(doc)
    if gen is not None:
        return gen, gen.date().isoformat()
    window = observed(doc, "window", kind=dict) or {}
    end = window.get("end")
    if isinstance(end, str) and end:
        return _parse_ts(end), end
    best = None
    for market in (observed(doc, "markets", kind=dict) or {}).values():
        for row in (market or {}).get("series") or []:
            d = (row or {}).get("date")
            if isinstance(d, str) and (best is None or d > best):
                best = d
    return (_parse_ts(best) if best else None), best


def _susde_dn_effective_state(susde_input: Input, pendle_history_input: Input, now: datetime) -> tuple:
    """ADR-560 Phase-0 repair, REWORK M6(a): susde_dn's forward rows are frozen replays of
    ``rates_desk/pendle_pt_history.json``'s inputs (the real-history feeds load the deep Pendle
    dataset ONCE — ``aggressive_lab/run.py`` ``_real_history_feeds`` — and ``feeds.py``'s
    ``MarketSnapshot`` then always returns that same last point). Judge staleness by the FROZEN
    DATE'S AGE against the same cadence already used for this strand
    (``susde_input.cadence_hours`` == ``CADENCE_RESEARCH_STRAND_H``) — never a hardcoded
    unconditional STALE, which would never clear even if the upstream Pendle dataset were
    repaired. When the pendle file itself cannot be read or dated, fall back to the strand's own
    file-cadence judgement (never silently MEASURED just because we can't check the frozen date).

    Returns ``(state, reason_or_None)`` only — this NEVER touches ``.as_of``/``.age_hours``: those
    stay the FILE's true observation. Moving them would also move ``policy.recommend``'s
    ``evidence_cutoff`` (every input's ``as_of`` feeds ``min(as_ofs)`` there), which REWORK M6(c)
    forbids."""
    frozen_as_of, frozen_date = _frozen_pendle_timestamp(pendle_history_input.doc)
    cadence = susde_input.cadence_hours or CADENCE_RESEARCH_STRAND_H
    if frozen_as_of is not None:
        age_h = (now - frozen_as_of).total_seconds() / 3600.0
        if age_h > cadence:
            return contract.STALE, (f"inputs frozen at {frozen_date} (pendle_pt_history generated_at), "
                                    f"{age_h:.1f}h old > {cadence:.0f}h limit")
        return contract.MEASURED, None
    # pendle file unreadable/undated: can't judge by its age — fall back to the strand's own
    # file-cadence state rather than inventing a verdict.
    return susde_input.state, susde_input.state_reason


def _build_market_neutral_sleeve(variant_input: Input, susde_input: Input, pendle_history_input: Input,
                                 regime_fit: dict, now: datetime) -> dict:
    """ADR-560 Phase-0 audit repairs (three genuine defects, none of them a weight change — every
    cell here stays ``allocatable=False``, OBSERVE_ONLY):

    (a) The sleeve used to carry a third strand labelled "rates_desk (fixed carry)" that read
        ``rates_desk/equity_track.jsonl`` — which IS the go-live equity hash chain
        (``spa_core/audit/equity_proof_chain.py``, co-located under ``rates_desk/`` for historical
        reasons only). Conservative was being counted a SECOND time under a different name, both
        here and in correlation's research pairs. The strand is removed; nothing is substituted.
    (b) ``variant_n`` was mislabelled "swarm blend" — there is no swarm book behind it, it is an
        LRT-collateral loop paired with a short ETH perp. Relabelled "LRT + short ETH perp
        (variant_n)" throughout (mechanism text, risk evidence, composition).
    (c) ``susde_dn``'s forward rows are frozen replays of 2026-07-05 inputs: judged by
        :func:`_susde_dn_effective_state` (age-based, never hardcoded — REWORK M6a), and the
        verdict is applied to ``susde_input.state``/``.state_reason`` by the CALLER
        (:func:`build_sleeves`), BEFORE this function runs, so the general input manifest (every
        other reader of ``susde_input``) sees the SAME verdict (REWORK M6b) — this function simply
        trusts ``susde_input.state`` like it already trusts ``variant_input.state``. The sleeve's
        overall freshness is governed by the OLDEST strand input, never the freshest — the old
        code picked ``max(as_of)``, which let a daily-touched-but-frozen file look "fresh" because
        its row timestamp kept advancing even though its content never did; for susde_dn
        specifically, "its own input as_of" is the frozen Pendle date, not the wrapper file's row
        timestamp (that date never feeds ``evidence_cutoff`` — see REWORK M6c).
    """
    out = _blank_sleeve("market_neutral_basis")
    out["mechanism"] = ("two independent paper/backtest basis strands (LRT + short ETH perp (variant_n), "
                        "sUSDe delta-neutral) — no unified book, no mandate")
    out["mode"] = "OBSERVE_ONLY"
    out["live_admission"] = "NOT_APPLICABLE / outside RiskPolicy (no mandate)"
    out["capital_basis"] = _not_measured("two independent paper strands, no single book basis")
    out["current_equity"] = _not_measured("not a single book; strands run independent paper equity (see composition)")
    out["observation_window"] = _not_measured("no unified window across two independent strands")
    out["valid_periods"] = _not_measured("no unified valid_periods counter across the strands")
    out["maturity"] = _maturity_cell(out["valid_periods"])
    out["expected_return"] = _not_measured(
        "no blended return across two unrelated strands (would mix backtest and forward incomparably)")
    out["realized_return"] = _not_measured("no blended realized return across two unrelated strands")
    out["volatility"] = _not_measured("no blended return series")
    out["max_drawdown"] = _not_measured("no blended drawdown across two unrelated strands")
    out["liquidity"] = _not_measured("exit model not published for research strands")
    out["time_to_exit"] = _not_measured("exit model not published for research strands")
    out["cash_share"] = _not_measured("sleeve carries no cash field")
    out["gross_exposure_over_nav"] = _not_measured("leverage not uniformly disclosed across the strands")
    out["leverage"] = _not_measured("leverage not uniformly disclosed across the strands")
    out["nearest_enforced_stop"] = _not_measured("no mandate; outside RiskPolicy, no enforced stop")
    out["loss_budget"] = _not_measured("no mandate; outside RiskPolicy, no loss budget")
    out["stress_loss"] = _not_measured("no unified stress model across the strands")
    out["worst_case_loss"] = _not_measured("no stop and no stress model; outside RiskPolicy")

    susde_last = (susde_input.doc or [None])[-1] if isinstance(susde_input.doc, list) and susde_input.doc else None
    out["mtm_coverage"] = contract.measured(susde_last.get("mtm_today_pct"), unit="pct", source=susde_input.path_str,
                                             as_of=susde_input.as_of_iso,
                                             note="susde_dn only; no unified mtm coverage across both strands") \
        if susde_last and isinstance(susde_last.get("mtm_today_pct"), (int, float)) else \
        _not_measured("no unified mtm coverage across both strands")

    # susde_input.state/.state_reason already carry the age-judged verdict (set by build_sleeves,
    # via _susde_dn_effective_state, before this function runs — REWORK M6a/b). Here we only need
    # the frozen date again for DISPLAY (its own input as_of for the "oldest wins" rule and for
    # human-readable text) — a pure, side-effect-free recomputation of the same inputs.
    frozen_as_of, frozen_date = _frozen_pendle_timestamp(pendle_history_input.doc)
    frozen_as_of = frozen_as_of or susde_input.as_of
    if susde_input.state == contract.MEASURED:
        susde_stale_reason = "pendle_pt_history within cadence"
    else:
        susde_stale_reason = susde_input.state_reason or "susde_dn freshness not judgeable"

    strand_states = [
        {"name": "variant_n", "label": "LRT + short ETH perp (variant_n)", "input": variant_input,
         "state": variant_input.state, "age_hours": variant_input.age_hours, "as_of": variant_input.as_of,
         "as_of_iso": variant_input.as_of_iso, "path_str": variant_input.path_str,
         "reason": variant_input.state_reason},
        {"name": "susde_dn", "label": "susde_dn (delta-neutral)", "input": susde_input,
         "state": susde_input.state, "age_hours": susde_input.age_hours, "as_of": frozen_as_of,
         "as_of_iso": frozen_as_of.isoformat() if frozen_as_of else susde_input.as_of_iso,
         "path_str": susde_input.path_str, "reason": susde_input.state_reason},
    ]
    readable_strands = [s for s in strand_states if s["input"].doc is not None]
    if not readable_strands:
        out["data_freshness"] = _not_measured("neither strand is readable")
    else:
        oldest = min(readable_strands, key=lambda s: (s["as_of"] or datetime.min.replace(tzinfo=timezone.utc)))
        if oldest["state"] == contract.NOT_MEASURED:
            out["data_freshness"] = _not_measured(f"oldest strand ({oldest['name']}) has no readable as_of")
        elif oldest["state"] == contract.STALE:
            out["data_freshness"] = contract.absent(
                contract.STALE,
                reason=oldest["reason"] or (f"oldest strand ({oldest['name']}) still "
                                            f"{(oldest['age_hours'] or 0):.1f}h old"),
                source=oldest["path_str"], as_of=oldest["as_of_iso"])
        else:
            out["data_freshness"] = contract.measured({"state": "FRESH", "oldest_strand": oldest["name"]},
                                                        unit=None, source=oldest["path_str"],
                                                        as_of=oldest["as_of_iso"])

    susde_evidence_text = (f"susde_dn forward rows are FROZEN REPLAYS, not live forward evidence "
                           f"({susde_stale_reason})" if susde_input.state != contract.MEASURED else
                           "susde_dn forward rows within the pendle_pt_history cadence")
    out["evidence_state"] = contract.measured(
        f"mixed: {susde_evidence_text}; variant_n is continuous paper", unit=None, source="two strands",
        as_of=None, note="not a unified evidence level")
    out["regime_fit"] = dict(regime_fit)
    out["confidence"] = contract.measured("LOW", unit=None, source="cio-policy-v1", as_of=None,
                                           note="observe-only, no mandate, heterogeneous strands")
    out["capacity"] = _not_measured("no capacity model across two unrelated strands")
    out["risk"] = {
        "PROTOCOL": {"level": "MEDIUM", "evidence": "variant_n / susde_dn mix pools and venues", "source": None},
        "STRATEGY": {"level": "MEDIUM", "evidence": "delta_neutral; funding/basis risk remains despite hedge",
                     "source": None},
        "MARKET": {"level": "MEDIUM", "evidence": "usde_peg + funding_rate factors", "source": None},
        "EXECUTION": {"level": "MEDIUM", "evidence": "rebalancing cost of delta-neutral legs not modelled uniformly",
                      "source": None},
        "LIQUIDITY": {"level": "UNKNOWN", "evidence": "no exit model published", "source": None},
        "COUNTERPARTY": {"level": "UNKNOWN", "evidence": "no source today", "source": None},
        "LEVERAGE": {"level": "UNKNOWN", "evidence": "not uniformly disclosed across strands", "source": None},
        "DATA_MODEL": {"level": "HIGH" if susde_input.state != contract.MEASURED else "MEDIUM",
                       "evidence": (f"susde_dn forward rows are frozen — {susde_stale_reason}"
                                   if susde_input.state != contract.MEASURED else
                                   "susde_dn forward rows within cadence; still a heterogeneous mix with variant_n"),
                       "source": susde_input.path_str},
    }
    comp = []
    for s in strand_states:
        inp = s["input"]
        last_equity = None
        if isinstance(inp.doc, dict):
            series = inp.doc.get("series") or []
            if series and isinstance(series[-1], dict):
                last_equity = series[-1].get("equity_usd")
        elif isinstance(inp.doc, list) and inp.doc:
            last = inp.doc[-1]
            if isinstance(last, dict):
                last_equity = last.get("equity_usd") or last.get("close_equity")
        comp.append({"protocol": s["label"], "mechanic": "market_neutral_basis", "tier": "UNKNOWN",
                    "share": _not_measured("no portfolio weight; independent paper strand"),
                    "usd": contract.measured(last_equity, unit="usd", source=inp.path_str, as_of=inp.as_of_iso,
                                              note="strand's own paper equity, not a book allocation")
                    if last_equity is not None else _not_measured("strand equity unavailable",
                                                                   source=inp.path_str, as_of=inp.as_of_iso)})
    out["composition"] = comp
    out["factors"] = _factors_for([], "market_neutral_basis")
    out["correlation_features"] = {
        "strands": {"variant_n": variant_input.path_str, "susde_dn": susde_input.path_str},
    }
    readable = [s["name"] for s in strand_states if s["input"].doc is not None]
    out["gates"] = [
        {"gate": "data_healthy", "state": "PASS" if readable else "FAIL",
         "reason": f"readable strands: {readable}" if readable else "neither strand is readable"},
        {"gate": "data_fresh",
         "state": "PASS" if susde_input.state == contract.MEASURED else "FAIL",
         "reason": f"susde_dn: {susde_stale_reason}" if susde_input.state != contract.MEASURED else
                   "susde_dn: pendle_pt_history within cadence"},
        {"gate": "work_running", "state": "UNKNOWN", "reason": "no scheduled single job; independent strands"},
        {"gate": "stop_not_active", "state": "UNKNOWN", "reason": "no mandate, no stop defined"},
        {"gate": "worst_case_loss_known", "state": "FAIL", "reason": "no stop/stress model; outside RiskPolicy"},
    ]
    out["warnings"] = ["outside RiskPolicy v1.0; no owner mandate (ADR-554 Phase 0)",
                       f"susde_dn: {susde_stale_reason}"]
    out["unknowns"] = ["no unified return/vol/drawdown across the strands", "leverage not disclosed",
                       "COUNTERPARTY risk has no source"]
    return out


# ── top-level entry point ───────────────────────────────────────────────────────────────

def build_sleeves(data_dir: Path, now: datetime) -> dict:
    """Project every live source into the six ADR-554 capital sleeves. Never writes, never raises
    on a missing file — an absent source becomes NOT_MEASURED cells, a stale one STALE cells."""
    data_dir = Path(data_dir)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    defi_input = _make_input("defi_engine_status", "defi_engine/status.json", data_dir, CADENCE_HOURLY_H,
                              _as_of_generated_at, now)
    hy_input = _make_input("hy_paper_trading", "hy_paper_trading.json", data_dir, CADENCE_HOURLY_H,
                            _as_of_last_cycle_at, now)
    lp_input = _make_input("lp_paper_trading", "lp_paper_trading.json", data_dir, CADENCE_HOURLY_H,
                            _as_of_last_cycle_at, now)
    equity_curve_input = _make_input("equity_curve_daily", "equity_curve_daily.json", data_dir, CADENCE_DAILY_H,
                                      _as_of_generated_at, now)
    kill_input = _make_input("kill_switch_status", "kill_switch_status.json", data_dir, CADENCE_DAILY_H,
                              _as_of_generated_at, now)
    derisk_input = _make_input("derisk_status", "derisk_status.json", data_dir, CADENCE_DAILY_H,
                                _as_of_generated_at, now)
    tr_input = _make_input("trading_research_status", "trading_research/status.json", data_dir, CADENCE_HOURLY_H,
                            _as_of_generated_at_ms, now)
    variant_input = _make_input("variant_n_series", "strategy_lab_paper/variant_n_series.json", data_dir,
                                 CADENCE_RESEARCH_STRAND_H, _as_of_last_series_point, now)
    susde_input = _make_input("susde_dn_realized_series", "aggressive_lab/susde_dn/realized_series.jsonl", data_dir,
                               CADENCE_RESEARCH_STRAND_H, _as_of_last_row("as_of"), now, kind="jsonl")
    # ADR-560 Phase-0 repair: NOT a market_neutral_basis strand (that was "rates_desk (fixed
    # carry)", removed — it read the go-live equity chain and double-counted Conservative). This
    # is read ONLY to judge susde_dn's freshness (REWORK M6a) — it is deliberately kept OUT of the
    # `inputs` manifest list below (REWORK M6c): policy.recommend()'s `evidence_cutoff` is
    # `min(i["as_of"] for i in inputs)`, and this file's own as_of is frozen at 2026-07-05 — were
    # it ever counted there, it would drag today's cutoff back to July, changing what cio-policy-v1
    # outputs. No cadence of its own: it is read for ITS DATE only, never displayed as a
    # freshness-tracked input in its own right.
    pendle_history_input = _make_input("rates_desk_pendle_pt_history", "rates_desk/pendle_pt_history.json",
                                       data_dir, None, _as_of_generated_at, now)
    # REWORK M6b: the general input manifest must show the SAME verdict the sleeve uses for
    # susde_dn, not the file's own (misleadingly fresh) row-touch cadence. Mutating `.state` here —
    # before `inputs` is assembled below and before the sleeve is built — makes this the ONE place
    # that decides it; `.as_of`/`.age_hours` are deliberately left untouched (see the comment above).
    susde_input.state, susde_input.state_reason = _susde_dn_effective_state(susde_input, pendle_history_input, now)
    chief_input = _make_input("chief_investment", "investment_os/chief_investment.json", data_dir, CADENCE_DAILY_H,
                               _as_of_generated_at, now)
    funding_input = _make_input("funding_regime", "swarm/funding_regime.json", data_dir, CADENCE_DAILY_H,
                                 _as_of_as_of_utc, now)
    market_input = _make_input("market_regime", "market_regime.json", data_dir, CADENCE_DAILY_H, _as_of_detected_at,
                                now)

    regime_fit = _regime_fit(chief_input, funding_input, market_input)
    adapters_input = _make_input("adapter_status", "adapter_status.json", data_dir, CADENCE_DAILY_H,
                                 _as_of_sky_live_apy, now)

    books_doc = observed(defi_input.doc, "books", kind=dict) or {}

    sleeves = {
        "defi_conservative": _build_defi_sleeve("defi_conservative", defi_input, None, equity_curve_input,
                                                kill_input, derisk_input, regime_fit, now),
        "defi_balanced": _build_defi_sleeve("defi_balanced", defi_input, hy_input, None, None, None, regime_fit, now),
        "defi_aggressive": _build_defi_sleeve("defi_aggressive", defi_input, lp_input, None, None, None, regime_fit,
                                              now),
        "cash": _build_cash_sleeve(books_doc, regime_fit, now),
        "trading_research": _build_trading_research_sleeve(tr_input, regime_fit),
        "market_neutral_basis": _build_market_neutral_sleeve(variant_input, susde_input, pendle_history_input,
                                                              regime_fit, now),
    }

    # exposure.py / correlation.py imported lazily to avoid any import-order surprise.
    from spa_core.investment_cio import exposure as _exposure
    from spa_core.investment_cio import correlation as _correlation

    seed_weight = round(1.0 / 3.0, 6)
    seed_split_weights = {sid: seed_weight for sid in contract.DEFI_SLEEVES}

    # REWORK M6c: rates_desk_pendle_pt_history is deliberately NOT in this list — see the comment
    # where it is built, above. susde_input IS here, as before; only its `.state` changed (M6b),
    # never its `.as_of`/`.age_hours`, so evidence_cutoff (min of every input's as_of, in
    # policy.recommend) is unaffected by either of those fixes.
    inputs = [defi_input, hy_input, lp_input, equity_curve_input, kill_input, derisk_input, tr_input, variant_input,
              susde_input, chief_input, funding_input, market_input, adapters_input]

    return {
        "schema": contract.SCHEMA_SLEEVES,
        "generated_at": now.isoformat(),
        "sleeves": sleeves,
        "inputs": [_manifest_row(i) for i in inputs],
        "exposure": _exposure.build(sleeves),
        "correlation": _correlation.build(data_dir, sleeves, now),
        "seed_split_weights": seed_split_weights,
        # real capital: 0 only when every engine declares paper and reports 0 live capital — never a literal
        "real_capital_usd": _real_capital(defi_input, tr_input, data_dir),
        # ADR-554 rule 3: the named hurdle for the MATURE return gate (risk-free proxy: Sky savings rate)
        "hurdle": _hurdle_cell(adapters_input),
        # ADR-554 rule 10: display-only regime, identical for every sleeve
        "regime": dict(regime_fit),
    }
