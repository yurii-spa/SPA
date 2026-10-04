"""spa_core/research_factory/_funding_row_parsers.py — a COPY, with attribution, of the five
per-venue funding-rate ROW parsers from ``spa_core/strategy_lab/data/funding_feed.py``
(``_rows_binance`` / ``_rows_bybit`` / ``_rows_okx`` / ``_rows_kucoin`` / ``_rows_hyperliquid``,
plus their shared ``_finite_rate`` helper), copied as of 2026-10-04 (lines ~269-430 of that file).

Post-implementation review M7 (2026-10-04): ``collectors/funding_venues.py`` used to import these
five functions DIRECTLY from ``funding_feed.py``, which loads the WHOLE module — and
``funding_feed.py`` imports ``spa_core.strategy_lab.data._http`` (``http_fetch``), a SECOND
network client (raw ``urllib.request``) outside this package's sanctioned surface
(``http_client`` / ``capital_shadow.rpc`` only). A pure parsing function (schema-validate JSON →
``[(ts_ms, rate)]``, no network of its own) has no business dragging in a transport module just
because it happens to live in a file that also has one.

**``funding_feed.py`` itself is NEVER modified** — other agents/engines depend on it exactly as
it is. This is a COPY, not a shared import, and it is deliberately a narrow, pure-function slice:
no network, no file I/O, no clients. If ``funding_feed.py``'s venue schemas ever change, this copy
must be updated by hand (it will not happen automatically) — that is the accepted cost of cutting
the transitive network-import edge.

LLM_FORBIDDEN, stdlib only, NO network import of any kind (enforced by
``spa_core/tests/test_research_evidence_tracks.py``'s collector/scanner import allowlist walk).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
from typing import List, Tuple


class InvalidDataError(ValueError):
    """Local equivalent of ``spa_core.strategy_lab.base.InvalidDataError`` — a plain
    ``ValueError`` subclass, redeclared here (rather than imported) so this module has ZERO
    import edge back into ``strategy_lab`` at all, not even a network-clean one."""


def _finite_rate(raw, venue: str) -> float:
    """Parse a funding-rate field to a FINITE float, fail-CLOSED — verbatim copy of
    ``funding_feed._finite_rate`` (``float()`` admits ``"NaN"``/``"Infinity"``; a non-finite rate
    raises exactly like an unparseable one, never a silently fabricated value)."""
    try:
        rate = float(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidDataError(f"{venue} funding: unparseable rate {raw!r}") from exc
    if not math.isfinite(rate):
        raise InvalidDataError(f"{venue} funding: non-finite rate {raw!r} (NaN/inf)")
    return rate


def rows_binance(payload: object) -> List[Tuple[int, float]]:
    """Binance fundingRate -> [(ts_ms, rate)]. Raises on bad schema / empty / missing field."""
    if not isinstance(payload, list) or not payload:
        raise InvalidDataError(f"binance funding: expected non-empty list, got {type(payload).__name__}")
    rows: List[Tuple[int, float]] = []
    for row in payload:
        if not isinstance(row, dict):
            raise InvalidDataError("binance funding: row is not an object")
        if "fundingRate" not in row or row.get("fundingRate") in (None, ""):
            raise InvalidDataError("binance funding: missing/empty 'fundingRate'")
        ts = row.get("fundingTime")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool) or not math.isfinite(ts):
            raise InvalidDataError("binance funding: missing/invalid 'fundingTime'")
        rate = _finite_rate(row["fundingRate"], "binance")
        rows.append((int(ts), rate))
    if not rows:
        raise InvalidDataError("binance funding: produced no datapoints")
    return rows


def rows_bybit(payload: object) -> List[Tuple[int, float]]:
    """Bybit funding history -> [(ts_ms, rate)]. Raises on bad schema / empty / missing field."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"bybit funding: expected object, got {type(payload).__name__}")
    if payload.get("retCode") != 0:
        raise InvalidDataError(f"bybit funding: retCode={payload.get('retCode')} ({payload.get('retMsg')})")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise InvalidDataError("bybit funding: missing 'result' object")
    raw = result.get("list")
    if not isinstance(raw, list) or not raw:
        raise InvalidDataError("bybit funding: 'result.list' missing or empty")
    rows: List[Tuple[int, float]] = []
    for row in raw:
        if not isinstance(row, dict):
            raise InvalidDataError("bybit funding: row is not an object")
        if "fundingRate" not in row or row.get("fundingRate") in (None, ""):
            raise InvalidDataError("bybit funding: missing/empty 'fundingRate'")
        ts = row.get("fundingRateTimestamp")
        try:
            ts_ms = int(ts)
        except (TypeError, ValueError) as exc:
            raise InvalidDataError(f"bybit funding: invalid timestamp {ts!r}") from exc
        rate = _finite_rate(row["fundingRate"], "bybit")
        rows.append((ts_ms, rate))
    if not rows:
        raise InvalidDataError("bybit funding: produced no datapoints")
    return rows


def rows_okx(payload: object) -> List[Tuple[int, float]]:
    """OKX funding-rate-history -> [(ts_ms, rate)]. Raises on bad schema / empty / missing field.

    Schema: {"code":"0","msg":"","data":[ {"fundingRate":str,"fundingTime":str(ms), ...} ]}.
    OKX `code` is a STRING ("0" = ok). 8h settlement."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"okx funding: expected object, got {type(payload).__name__}")
    if str(payload.get("code")) != "0":
        raise InvalidDataError(f"okx funding: code={payload.get('code')!r} ({payload.get('msg')!r})")
    raw = payload.get("data")
    if not isinstance(raw, list) or not raw:
        raise InvalidDataError("okx funding: 'data' missing or empty")
    rows: List[Tuple[int, float]] = []
    for row in raw:
        if not isinstance(row, dict):
            raise InvalidDataError("okx funding: row is not an object")
        if "fundingRate" not in row or row.get("fundingRate") in (None, ""):
            raise InvalidDataError("okx funding: missing/empty 'fundingRate'")
        ts = row.get("fundingTime")
        try:
            ts_ms = int(ts)
        except (TypeError, ValueError) as exc:
            raise InvalidDataError(f"okx funding: invalid 'fundingTime' {ts!r}") from exc
        rate = _finite_rate(row["fundingRate"], "okx")
        rows.append((ts_ms, rate))
    if not rows:
        raise InvalidDataError("okx funding: produced no datapoints")
    return rows


def rows_kucoin(payload: object) -> List[Tuple[int, float]]:
    """KuCoin futures funding-rates -> [(ts_ms, rate)]. Raises on bad schema / empty / missing.

    Schema: {"code":"200000","data":[ {"symbol","fundingRate":float,"timepoint":int(ms)} ]}.
    KuCoin `code` is a STRING ("200000" = ok). 8h settlement."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"kucoin funding: expected object, got {type(payload).__name__}")
    if str(payload.get("code")) != "200000":
        raise InvalidDataError(f"kucoin funding: code={payload.get('code')!r} ({payload.get('msg')!r})")
    raw = payload.get("data")
    if not isinstance(raw, list) or not raw:
        raise InvalidDataError("kucoin funding: 'data' missing or empty")
    rows: List[Tuple[int, float]] = []
    for row in raw:
        if not isinstance(row, dict):
            raise InvalidDataError("kucoin funding: row is not an object")
        if "fundingRate" not in row or row.get("fundingRate") in (None, ""):
            raise InvalidDataError("kucoin funding: missing/empty 'fundingRate'")
        ts = row.get("timepoint")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool) or not math.isfinite(ts):
            raise InvalidDataError(f"kucoin funding: missing/invalid 'timepoint' {ts!r}")
        rate = _finite_rate(row["fundingRate"], "kucoin")
        rows.append((int(ts), rate))
    if not rows:
        raise InvalidDataError("kucoin funding: produced no datapoints")
    return rows


def rows_hyperliquid(payload: object) -> List[Tuple[int, float]]:
    """Hyperliquid fundingHistory -> [(ts_ms, HOURLY rate)]. Raises on bad schema / empty /
    missing. Schema: list[ {"coin","fundingRate":str,"premium":str,"time":int(ms)} ]. These are
    HOURLY rates — ``collectors.funding_venues`` normalises via ``rate_per_8h``."""
    if not isinstance(payload, list) or not payload:
        raise InvalidDataError(f"hyperliquid funding: expected non-empty list, got {type(payload).__name__}")
    rows: List[Tuple[int, float]] = []
    for row in payload:
        if not isinstance(row, dict):
            raise InvalidDataError("hyperliquid funding: row is not an object")
        if "fundingRate" not in row or row.get("fundingRate") in (None, ""):
            raise InvalidDataError("hyperliquid funding: missing/empty 'fundingRate'")
        ts = row.get("time")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool) or not math.isfinite(ts):
            raise InvalidDataError(f"hyperliquid funding: missing/invalid 'time' {ts!r}")
        rate = _finite_rate(row["fundingRate"], "hyperliquid")
        rows.append((int(ts), rate))
    if not rows:
        raise InvalidDataError("hyperliquid funding: produced no datapoints")
    return rows
