"""Shared reader for ``data/adapter_status.json`` (ADR-063 / D1).

ONE place that knows the file's schema, so an adapter can never again read the
wrong shape and silently report a hardcoded constant as a live yield.

The defect this replaces (measured 2026-08-02): the file moved its per-protocol
payload under ``adapters``, but twelve adapters still looked for their block at
the TOP level. Every one of them therefore found nothing on every call. Nine
answered with their hardcoded ``DEFAULT_APY_PCT`` — which the WS1.1 provider then
stamped ``apy_source="live"``, so a literal from 2026-06 ranked money-path capital
as if it were an observation (e.g. ``spark_susds`` ranked at 5.5 % while its
observed 3.3192 % sat unread in the same file). The other three answered ``None``
honestly but were equally blind: their live values were in the file too.

Contract — what counts as an observation:

* ``adapters[<protocol>].live_apy`` — the producer's explicit "I observed this".
  ``null`` means it did NOT, and then the sibling ``apy`` field merely echoes
  ``fallback_apy``. So ``apy`` is NEVER read from this section: it cannot
  distinguish a reading from a literal.
* Legacy top-level blocks (``morpho_steakhouse``, ``aave_arbitrum``, ``pendle_pt``)
  predate the ``adapters`` section and carry no ``live_apy`` field; there the
  block's own ``apy`` IS the producer's reading. Only consulted when the modern
  section is absent for that protocol.

No fake fallback (``.claude/rules/adapters.md``): no data ⇒ ``None``. Callers must
treat ``None`` as "no live data", never as 0 %.

Pure stdlib. Never raises.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
STATUS_FILENAME = "adapter_status.json"

# Upper sanity bound for a live APY in PERCENT. Above this the feed is malformed,
# not generous (mirrors DeFiLlama's APY_SANITY_MAX) → treated as no reading.
#
# There is deliberately NO lower bound. An observed 0 % or negative APY is DATA:
# a pool really can pay nothing, or cost more than it earns. Rejecting it here
# would collapse "we observed zero" into "we observed nothing" — the exact
# conflation this module exists to end, and it would silently drop a genuine
# warning signal. Whether such a pool may receive capital is a POLICY question,
# decided downstream (the allocator's own live band already excludes apy ≤ 0).
# Existing compound_v3 tests pin this: an observed -1 % / 0 % must survive.
_MAX_APY_PCT = 200.0


def _valid_pct(value: object) -> Optional[float]:
    """Return ``value`` as a percent float when it is a usable live reading."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    f = float(value)
    if not math.isfinite(f):
        return None
    if f > _MAX_APY_PCT:
        return None
    return f


def read_status_doc(data_dir: Optional[Path] = None) -> dict:
    """Load ``adapter_status.json``. Returns ``{}`` on any error. Never raises."""
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    try:
        with open(ddir / STATUS_FILENAME, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        logger.debug("status_reader: %s unreadable (%s)", STATUS_FILENAME, exc)
        return {}


def read_status_block(protocol: str, data_dir: Optional[Path] = None) -> dict:
    """Return the per-protocol block, modern schema first, then legacy keys.

    Separator variants are treated as the same protocol. Adapters spell their key
    both ways — ``MoonwellBaseAdapter.PROTOCOL`` is ``"moonwell-base"`` while the
    status file writes ``moonwell_base`` — and a lookup that insisted on one form
    returned ``{}`` for the other. That failure is silent by construction: an
    empty block is indistinguishable from "this protocol was not observed", so
    the caller draws a fail-CLOSED conclusion from a key mismatch rather than
    from the data. Knowing the file's shape is exactly this module's job
    (ADR-063), so the tolerance belongs here and not in eleven adapters.
    """
    doc = read_status_doc(data_dir)
    candidates = []
    for form in (protocol, str(protocol).replace("-", "_"), str(protocol).replace("_", "-")):
        if form not in candidates:
            candidates.append(form)

    adapters = doc.get("adapters")
    if isinstance(adapters, dict):
        for key in candidates:
            block = adapters.get(key)
            if isinstance(block, dict):
                return block
    for key in candidates:
        for legacy_key in (key, "{}_adapter".format(key)):
            block = doc.get(legacy_key)
            if isinstance(block, dict):
                return block
    return {}


def observed_apy_pct_from_block(block: object) -> Optional[float]:
    """Observed APY in PERCENT from an ALREADY-LOADED modern ``adapters[<p>]`` block.

    Same contract as :func:`read_live_apy_pct`, exposed for callers that already
    hold the block — the ranking aggregator walks the whole ``adapters`` dict once
    and must not re-open the file per protocol. Keeping it here means "what counts
    as an observation" has ONE definition; a second caller re-deriving it from
    ``apy`` is exactly how the ADR-063 defect spread in the first place.

    ``live_apy`` is the only field that proves observation. ``apy`` is never
    consulted: it echoes ``fallback_apy`` when the producer observed nothing, so
    it cannot distinguish a reading from a literal.
    """
    if not isinstance(block, dict):
        return None
    return _valid_pct(block.get("live_apy"))


#: Сколько часов наблюдение остаётся свидетельством (ADR-061 / ADR-089 п.3).
#:
#: КАНОНИЧЕСКИЙ ДОМ окна свежести. Генератор носит последнее удачное наблюдение
#: вперёд (``live_apy_as_of`` хранит время САМОГО наблюдения, не время записи
#: файла) именно для того, чтобы сетевая икота не двигала капитал; решение «сколько
#: оно ещё годно» принимает потребитель — и потребитель обязан быть один.
#:
#: Аллокатор держит свою приватную копию (``allocator._EVIDENCE_MAX_AGE_H``): он
#: money-path, править его в этой задаче нельзя (ADR-089 п.3 — отдельное решение
#: владельца). Расходиться копиям не даёт храповик
#: ``spa_core/tests/test_apy_one_definition.py``: как только числа перестанут
#: совпадать, тест краснеет. Правильный конец истории — аллокатор импортирует
#: ЭТУ константу и своей не имеет.
EVIDENCE_MAX_AGE_H = 36.0

#: Причины, по которым наблюдения нет. Строки — часть контракта: «не наблюдали»
#: и «наблюдали, но давно» — разные факты, и молчаливый ``None`` их путает.
APY_OBSERVED = "observed"
APY_NOT_OBSERVED = "not_observed"
APY_STALE = "stale"
APY_UNKNOWN_AGE = "unknown_age"


def _parse_ts(value: object) -> "Optional[datetime]":
    """ISO-8601 → aware datetime; ``None`` когда не разбирается. Не бросает."""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def observed_apy_pct_fresh(
    block: object,
    now: "Optional[datetime]" = None,
    max_age_h: Optional[float] = None,
) -> "tuple[Optional[float], str]":
    """(APY в ПРОЦЕНТАХ, причина) — наблюдение, ещё годное как свидетельство.

    Одно определение на репозиторий из двух половин, которые до ADR-089 п.3 жили
    порознь: ЧТО считается наблюдением (:func:`observed_apy_pct_from_block` —
    только ``live_apy``) и КАК ДОЛГО оно им остаётся (:data:`EVIDENCE_MAX_AGE_H`
    по ``live_apy_as_of``). Отчёт знал первую половину неверно, а второй не знал
    вовсе — поэтому печатал литерал из ``apy`` возрастом 11 суток как доходность.

    ``now`` — ВХОД, а не окружение (`.claude/rules/deployment.md`): тест
    закрепляет обе стороны и не протухает от календаря.

    Fail-CLOSED: нет ``live_apy`` ⇒ ``(None, "not_observed")``; неразбираемая или
    отсутствующая отметка времени ⇒ ``(None, "unknown_age")`` — неизвестный
    возраст не свидетельство; старше окна ⇒ ``(None, "stale")``.
    """
    pct = observed_apy_pct_from_block(block)
    if pct is None:
        return None, APY_NOT_OBSERVED
    assert isinstance(block, dict)  # observed_apy_pct_from_block гарантировал
    dt = _parse_ts(block.get("live_apy_as_of"))
    if dt is None:
        return None, APY_UNKNOWN_AGE
    ref = now or datetime.now(timezone.utc)
    limit = EVIDENCE_MAX_AGE_H if max_age_h is None else float(max_age_h)
    if (ref - dt).total_seconds() / 3600.0 > limit:
        return None, APY_STALE
    return pct, APY_OBSERVED


def read_live_apy_pct(protocol: str, data_dir: Optional[Path] = None) -> Optional[float]:
    """Observed APY in PERCENT for ``protocol``, or ``None`` when not observed.

    ``None`` is returned for: file missing/unreadable, protocol absent,
    ``live_apy: null`` (the producer could not observe it), or a value outside
    the sanity band. A hardcoded literal is never returned in place of a reading.
    """
    doc = read_status_doc(data_dir)
    adapters = doc.get("adapters")
    if isinstance(adapters, dict):
        block = adapters.get(protocol)
        if isinstance(block, dict):
            # Modern schema: live_apy is the ONLY field that proves observation.
            return observed_apy_pct_from_block(block)

    # Legacy top-level block: no live_apy field exists there; the block is written
    # by a live producer, so its own ``apy`` is the reading.
    for legacy_key in (protocol, "{}_adapter".format(protocol)):
        block = doc.get(legacy_key)
        if isinstance(block, dict):
            return _valid_pct(block.get("apy"))

    return None


# ── GSM confirmation ─────────────────────────────────────────────────────────

# How long an on-chain governance-delay reading stays evidence. A pause delay
# changes only by a governance vote, so this is generous compared to an APY
# window — but it is NOT unbounded, because "no upper bound" is how a producer
# that quietly died keeps a gate open on a reading nobody has refreshed in
# months (the class that left riskwire 840 hours stale while still being read).
GSM_MAX_AGE_H = 168.0  # 7 days


def gsm_confirmed(
    block: dict,
    min_hours: float,
    max_age_h: float = GSM_MAX_AGE_H,
    now: "object | None" = None,
) -> bool:
    """Is the GSM pause delay OBSERVED, fresh, and at or above *min_hours*?

    Fail-CLOSED on every uncertainty, because the question this answers is
    "may capital enter" and the safe answer to "I don't know" is no:

    * field absent / non-numeric  → False (never defaulted to a passing value)
    * timestamp absent or unparseable → False (unknown age is not freshness)
    * older than *max_age_h*      → False (the reading has expired, and the
      gate closing by itself is the whole point — a dead producer must not
      leave the door open)
    * below the threshold         → False

    ``now`` is an input, not ambient state, so a test can pin both sides of the
    window and stay valid regardless of the calendar.
    """
    from datetime import datetime, timezone

    hours = block.get("gsm_hours")
    if not isinstance(hours, (int, float)) or isinstance(hours, bool):
        return False
    if not math.isfinite(float(hours)) or float(hours) < float(min_hours):
        return False

    stamp = block.get("gsm_hours_as_of")
    if not stamp:
        return False
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    ref = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    return (ref - dt).total_seconds() / 3600.0 <= float(max_age_h)


# ── TVL floor ────────────────────────────────────────────────────────────────

# The RiskPolicy floor. Read here so the verdict below cannot drift from policy
# by being restated; if the policy value is unavailable the caller supplies it.
_DEFAULT_TVL_FLOOR_USD = 5_000_000.0


def read_live_tvl_usd(protocol: str, data_dir: Optional[Path] = None) -> Optional[float]:
    """Observed TVL (USD) for *protocol*, or ``None`` when it was not observed.

    Only ``tvl_source == "live"`` counts, which the producer stamps solely on a
    pinned pool-UUID match (ADR-064). A literal is never an observation, whatever
    its size.
    """
    block = read_status_block(protocol, data_dir)
    if block.get("tvl_source") != "live":
        return None
    value = block.get("tvl_usd")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def tvl_floor_verdict(
    protocol: str,
    data_dir: Optional[Path] = None,
    floor_usd: float = _DEFAULT_TVL_FLOOR_USD,
) -> Optional[bool]:
    """Does *protocol* clear the RiskPolicy TVL floor? ``None`` = not measured.

    Eleven adapters used to answer this with ``self.TVL_USD >= 5_000_000``, where
    ``TVL_USD`` is a hardcoded class constant. Every one of those constants is
    larger than the floor, so the check could not return False **for any input**:
    it was the literal ``True`` wearing the name of a risk gate.

    That is not academic. ``moonwell_base`` carries ``TVL_USD = 500_000_000``
    against $2.6M observed — a 190x overstatement — so a pool that genuinely
    fails the floor reported passing it, every time, with nothing to notice.

    Three outcomes, not two:

    * ``True``  — observed TVL is at or above the floor;
    * ``False`` — observed TVL is below it (the case the old check could never
      produce);
    * ``None``  — no observation, so the floor is UNMEASURED. Deliberately not
      ``True``: an unmeasured gate that reports "pass" is the failure this
      replaces. It is equally deliberately not ``False``, because "we did not
      look" is not the same claim as "it fails" — the allocator already freezes
      unverified pools (ADR-053), and overstating this as a failure would push
      work into a queue that can never clear it.
    """
    observed = read_live_tvl_usd(protocol, data_dir)
    if observed is None:
        return None
    return observed >= float(floor_usd)
