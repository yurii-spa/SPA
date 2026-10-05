"""spa_core/research_factory/registry_loader.py — origins.json + facts.jsonl (ADR-564 review #11/#15).

Package E3 owns the CONTENT of ``registry/origins.json`` and ``registry/facts.jsonl``; this module
owns the LOADER and the validation the frozen interfaces promise (``evidence_contract.FACT_FIELDS``,
the citation rules). A malformed fact row is refused with a NAMED reason, never silently skipped —
a bad line in a git-tracked file must be visible, not invisible. A fact past its own ``expires_at``
is STALE (:func:`is_stale`); the "re-retrieval" judgement itself (review #15: "quote still found ⇒
re-confirmed; not found ⇒ CONFLICTED") belongs to the curating session, not to this loader.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from spa_core.research_factory import contract as c1
from spa_core.research_factory import evidence_contract as ec


class OriginRegistryError(Exception):
    """``origins.json`` is present but malformed (absent is simply an empty registry)."""


class FactRegistryError(Exception):
    """One ``facts.jsonl`` LINE is STRUCTURALLY broken (bad JSON, a missing/invalid required
    field, an unparseable timestamp, a channel/quote mismatch) — halts the WHOLE load. A file
    that fails basic structural validation is corrupted, not merely incomplete; a bad line in a
    git-tracked file must be visible, not invisible, and a partial load of a possibly-corrupted
    file would hide that."""

    def __init__(self, line_no: int, reason: str):
        super().__init__(f"facts.jsonl line {line_no}: {reason}")
        self.line_no = line_no
        self.reason = reason


class FactUnusable(Exception):
    """A STRUCTURALLY VALID fact (passed every ``FactRegistryError`` check) that is not yet
    usable for a SEMANTIC reason — no independent review yet, or its ``ref`` does not match its
    origin's registered ``hosts`` (post-implementation review H6, 2026-10-04). Unlike
    ``FactRegistryError``, this does NOT halt the whole load: :func:`load_facts` excludes just
    THIS fact from the usable set and records it (line, fact_id, reason) into ``refused_out`` —
    visible/auditable, never silently dropped, but scoped to the one fact, not the whole file."""

    def __init__(self, line_no: int, fact_id: Optional[str], reason: str):
        super().__init__(f"facts.jsonl line {line_no} (fact_id={fact_id!r}) unusable: {reason}")
        self.line_no = line_no
        self.fact_id = fact_id
        self.reason = reason


class FactReviewRegistryError(Exception):
    """A ``fact_reviews/*.json`` record file is present but STRUCTURALLY malformed (bad JSON, not
    an object, wrong/missing ``schema``, a missing required field, an entry with an unknown
    ``verdict``). Sibling of :class:`FactRegistryError` for the review registry: a bad review
    record file is corrupted, not an honest "no reviews" — treating it as empty would silently
    fail OPEN every fact that record was meant to vouch for or refuse, which is the exact hole
    re-review H6 (2026-10-04) closes. Raising here halts the WHOLE load, same discipline as a
    malformed ``facts.jsonl`` line."""


def default_origins_path(repo_root: Optional[Path] = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    return root / ec.ORIGIN_REGISTRY_PATH


def default_facts_path(repo_root: Optional[Path] = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    return root / ec.FACT_REGISTRY_PATH


def default_fact_reviews_dir(facts_path: Optional[Path] = None) -> Path:
    """``fact_reviews/`` lives NEXT TO the facts file it reviews (``registry/fact_reviews/`` for
    the real registry) — never a fixed repo-root path, so a caller pointing ``load_facts`` at a
    tmp/alternate facts file gets that file's OWN review directory, not the production one."""
    p = facts_path or default_facts_path()
    return p.parent / "fact_reviews"


def load_origins(path: Optional[Path] = None) -> dict:
    """``{origin_id: {"group": str, "affiliated_with": [...], "appointed_by": str|None, "note": str}}``.
    A missing file is an honestly EMPTY registry (every origin then falls back to its own
    ``unregistered:<origin>`` group via ``evidence_contract.origin_groups`` — never a crash for a
    package whose content another package, E3, writes). A file that EXISTS but cannot be parsed as
    an object of entries raises :class:`OriginRegistryError` — malformed is never confused with
    absent."""
    p = path or default_origins_path()
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise OriginRegistryError(f"{p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise OriginRegistryError(f"{p}: root must be an object of origin_id -> entry")
    out = {}
    for origin_id, entry in raw.items():
        if origin_id.startswith("_"):
            continue  # a top-level metadata key (e.g. "_comment") — not an origin entry
        if not isinstance(entry, dict) or not isinstance(entry.get("group"), str) or not entry.get("group"):
            raise OriginRegistryError(f"{p}: origin {origin_id!r} needs a non-empty string 'group'")
        out[origin_id] = entry
    return out


def load_fact_reviews(dir_path: Optional[Path] = None) -> list:
    """Every entry from every ``fact_reviews/*.json`` record in ``dir_path``, each returned as
    ``{"reviewer": <the record's reviewer>, **entry}`` (``entry`` has
    ``evidence_contract.FACT_REVIEW_ENTRY_FIELDS``). A missing directory is an honestly empty
    list — same pattern as :func:`load_origins` on a missing file: a package whose content
    another session writes must not crash for not having been reviewed yet. A record file that
    EXISTS but is malformed (bad JSON, wrong schema, missing field, unknown verdict) raises
    :class:`FactReviewRegistryError` — re-review H6 (2026-10-04): treating a malformed record as
    "no review" would fail OPEN, silently dropping whatever that record confirmed OR rejected."""
    d = dir_path if dir_path is not None else default_fact_reviews_dir()
    if not d.exists():
        return []
    out = []
    for path in sorted(d.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise FactReviewRegistryError(f"{path}: {exc}") from exc
        if not isinstance(doc, dict):
            raise FactReviewRegistryError(f"{path}: root must be a JSON object")
        if doc.get("schema") != ec.SCHEMA_FACT_REVIEW:
            raise FactReviewRegistryError(
                f"{path}: schema must be {ec.SCHEMA_FACT_REVIEW!r}, got {doc.get('schema')!r}")
        missing = [field for field in ec.FACT_REVIEW_FIELDS if field not in doc]
        if missing:
            raise FactReviewRegistryError(f"{path}: missing field(s) {missing}")
        reviewer = doc.get("reviewer")
        if not isinstance(reviewer, str) or not reviewer:
            raise FactReviewRegistryError(f"{path}: 'reviewer' must be a non-empty string")
        entries = doc.get("facts")
        if not isinstance(entries, list):
            raise FactReviewRegistryError(f"{path}: 'facts' must be a list")
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise FactReviewRegistryError(f"{path}: facts[{i}] must be an object")
            emissing = [field for field in ec.FACT_REVIEW_ENTRY_FIELDS if field not in entry]
            if emissing:
                raise FactReviewRegistryError(f"{path}: facts[{i}] missing field(s) {emissing}")
            if not isinstance(entry.get("fact_id"), str) or not entry["fact_id"]:
                raise FactReviewRegistryError(f"{path}: facts[{i}] fact_id must be a non-empty string")
            if entry.get("verdict") not in ec.FACT_REVIEW_VERDICTS:
                raise FactReviewRegistryError(
                    f"{path}: facts[{i}] verdict {entry.get('verdict')!r} not in {ec.FACT_REVIEW_VERDICTS!r}")
            out.append({"reviewer": reviewer, **entry})
    return out


#: refs with no HTTP host that are still checkable (on-chain reads)
_CHAIN_NATIVE_REF_PREFIXES = ("eth_call:", "chain:")


def _host_of(ref: str) -> Optional[str]:
    """The hostname of ``ref`` when it is an actual URL (has a scheme), else ``None`` — a
    chain-native pointer (``chain:1:0x...:bytecode``, ``eth_call:1:...``) has no HTTP host and
    is not subject to the host check below."""
    if "://" not in ref:
        return None
    return urlsplit(ref).hostname


def _check_independent_review(line_no: int, row: dict, reviews: list) -> None:
    """Post-implementation review H6 (2026-10-04): a fact usable only when ``reviewed_by`` is a
    DIFFERENT session than ``curated_by`` (``evidence_contract.FACT_REQUIRES_INDEPENDENT_REVIEW``)
    AND that review is bound to THIS fact's exact content, not merely to its ``fact_id`` (re-review
    H6, 2026-10-04): a ``reviewed_by`` string alone was a self-certification — editing the fact's
    value/quote after review kept the stamp, because nothing ever checked ``fact_sha256`` or read
    the committed review records at runtime. A fact is reviewed only when (1) its own
    ``fact_sha256`` equals ``evidence_contract.fact_content_sha256(row)`` (the row has not been
    edited since it was stamped) AND (2) a committed record by exactly ``reviewed_by`` contains an
    entry for this ``fact_id`` at exactly that ``fact_sha256`` whose ``verdict`` is ``CONFIRMED``
    (``evidence_contract.FACT_REVIEW_VERDICTS``). Raises :class:`FactUnusable` (scoped to this one
    fact — NOT a structural ``FactRegistryError``; a malformed review record file IS structural,
    see :class:`FactReviewRegistryError`, raised earlier while loading ``reviews``)."""
    if not ec.FACT_REQUIRES_INDEPENDENT_REVIEW:
        return
    fact_id = row.get("fact_id")
    reviewed_by = row.get("reviewed_by")
    curated_by = row.get("curated_by")
    if not reviewed_by:
        raise FactUnusable(line_no, fact_id,
                           "reviewed_by is required (FACT_REQUIRES_INDEPENDENT_REVIEW) — "
                           "a fact with no independent review is unusable")
    if reviewed_by == curated_by:
        raise FactUnusable(line_no, fact_id,
                           f"reviewed_by {reviewed_by!r} equals curated_by {curated_by!r} — "
                           f"needs a DIFFERENT session's review, not the curator's own say-so")
    if reviewed_by not in ec.FACT_REVIEWERS:
        # tail of ADR-564: a review record can be committed under ANY name; only the contract's own
        # reviewer list is accepted, so a new reviewer is a visible, tested contract change
        raise FactUnusable(line_no, fact_id,
                           f"reviewed_by {reviewed_by!r} is not in evidence_contract.FACT_REVIEWERS")
    if curated_by in ec.FACT_REVIEWERS:
        raise FactUnusable(line_no, fact_id,
                           f"curated_by {curated_by!r} is a registered reviewer — a curator never reviews")

    content_hash = ec.fact_content_sha256(row)
    if row.get("fact_sha256") != content_hash:
        raise FactUnusable(line_no, fact_id,
                           f"fact_sha256 {row.get('fact_sha256')!r} does not match this row's own "
                           f"recomputed content hash {content_hash!r} — the fact was edited after "
                           f"being stamped (or never stamped); re-review H6 binds a review to "
                           f"content, not to a fact_id alone")
    named = [e for e in reviews if e.get("reviewer") == reviewed_by and e.get("fact_id") == fact_id]
    if not named:
        raise FactUnusable(line_no, fact_id,
                           f"no committed review record by reviewed_by {reviewed_by!r} names "
                           f"fact_id {fact_id!r} — reviewed_by with no record behind it is a "
                           f"self-certification, not an independent review")
    at_hash = [e for e in named if e.get("fact_sha256") == content_hash]
    if not at_hash:
        raise FactUnusable(line_no, fact_id,
                           f"reviewed_by {reviewed_by!r} has a committed record for {fact_id!r}, "
                           f"but none of it is at this fact's current content hash {content_hash!r} "
                           f"— the content changed since that review confirmed something else")
    confirmed = [e for e in at_hash if e.get("verdict") == "CONFIRMED"]
    if not confirmed:
        verdicts = sorted({e.get("verdict") for e in at_hash})
        raise FactUnusable(line_no, fact_id,
                           f"review record verdict(s) {verdicts!r} for fact_id {fact_id!r} at this "
                           f"content hash are not 'CONFIRMED' (evidence_contract.FACT_REVIEW_VERDICTS) "
                           f"— only a CONFIRMED review makes a fact usable")


def _check_origin_hosts(line_no: int, row: dict, origins: dict) -> None:
    """Post-implementation review H6: a fact's ORIGIN must match the publisher of its ``ref`` —
    checked against that origin's registered ``hosts`` list (E3 owns the content of
    ``origins.json``; this loader owns enforcing it). An issuer-hosted page is the issuer's claim
    whatever party it names — the host, not the prose, decides who is speaking. Scoped to refs
    that ARE http(s) URLs (:func:`_host_of`); a chain-native pointer has no host to check.
    Fail-CLOSED: an origin with no registered ``hosts`` at all cannot be verified, so a URL-ref
    fact citing it is unusable, not silently passed — this IS expected to start excluding facts
    whose origin has not yet been given a ``hosts`` entry, until that entry is added. Raises
    :class:`FactUnusable` (scoped to this one fact)."""
    ref = row.get("ref") or ""
    host = _host_of(ref)
    if host is None:
        # independent fact review (2026-10-04): 32 of 43 refs were free text ("docs.ondo.finance
        # (OUSG fees)") and SKIPPED this check — a fail-OPEN. A ref is either chain-native or an
        # https URL whose host is checked; anything else cannot name its publisher.
        if ref.startswith(_CHAIN_NATIVE_REF_PREFIXES):
            # re-review H6 (2026-10-04): a chain-native PREFIX alone is not enough — it was
            # accepted on ANY channel, so a forged fact {ref: "eth_call:1:0xdead:custodian()",
            # channel: "official_doc", origin: "regulator:sec"} skipped the host check entirely
            # and made a custodian role "DOCUMENTED" on a chain-shaped string nobody actually
            # read on-chain. A no-host ref is checkable only as a genuine chain-native READ:
            # channel must be on_chain AND claim_type must be one evidence_contract.CHAIN_NATIVE_CLAIMS
            # names (the same rule evidence_contract.citation()/role_entry() enforce elsewhere).
            if row.get("channel") == ec.CHANNEL_ON_CHAIN and row.get("claim_type") in ec.CHAIN_NATIVE_CLAIMS:
                return
            raise FactUnusable(line_no, row.get("fact_id"),
                               f"ref {ref[:80]!r} has a chain-native prefix "
                               f"{_CHAIN_NATIVE_REF_PREFIXES!r} but channel {row.get('channel')!r} / "
                               f"claim_type {row.get('claim_type')!r} is not a genuine chain-native "
                               f"read (needs channel={ec.CHANNEL_ON_CHAIN!r} and claim_type in "
                               f"{ec.CHAIN_NATIVE_CLAIMS!r}) — a no-host ref is checkable only as an "
                               f"actual on-chain read, never as a free pass for any channel")
        raise FactUnusable(line_no, row.get("fact_id"),
                           f"ref {ref[:80]!r} is neither an https URL nor a chain-native pointer "
                           f"{_CHAIN_NATIVE_REF_PREFIXES!r} — its publisher cannot be checked")
    if urlsplit(ref).scheme not in ec.HTTP_SCHEMES:
        raise FactUnusable(line_no, row.get("fact_id"),
                           f"ref scheme {urlsplit(ref).scheme!r} not in {ec.HTTP_SCHEMES!r}")
    origin_id = row.get("origin")
    entry = origins.get(origin_id) if isinstance(origins, dict) else None
    hosts = entry.get("hosts") if isinstance(entry, dict) else None
    if not isinstance(hosts, list) or not hosts:
        raise FactUnusable(line_no, row.get("fact_id"),
                           f"origin {origin_id!r} has no registered 'hosts' to verify ref host "
                           f"{host!r} against — cannot confirm the origin actually published this ref")
    if host not in hosts:
        raise FactUnusable(line_no, row.get("fact_id"),
                           f"ref host {host!r} is not among origin {origin_id!r}'s registered hosts "
                           f"{hosts!r} — the origin does not match the publisher of its own citation")


def _parse_fact_line(line_no: int, raw_line: str) -> Optional[dict]:
    line = raw_line.strip()
    if not line:
        return None
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise FactRegistryError(line_no, f"not valid JSON ({exc})") from exc
    if not isinstance(row, dict):
        raise FactRegistryError(line_no, "a fact row must be a JSON object")
    missing = [f for f in ec.FACT_FIELDS if f not in row]
    if missing:
        raise FactRegistryError(line_no, f"missing field(s) {missing}")
    if row.get("schema") != ec.SCHEMA_FACT:
        raise FactRegistryError(line_no, f"schema must be {ec.SCHEMA_FACT!r}, got {row.get('schema')!r}")
    if not isinstance(row.get("fact_id"), str) or not row["fact_id"]:
        raise FactRegistryError(line_no, "fact_id must be a non-empty string")
    if not isinstance(row.get("entity"), str) or not row["entity"]:
        raise FactRegistryError(line_no, "entity must be a non-empty string")
    if not isinstance(row.get("candidate_ids"), list):
        raise FactRegistryError(line_no, "candidate_ids must be a list")
    if row.get("role") is not None and row["role"] not in ec.ROLES:
        raise FactRegistryError(line_no, f"role {row['role']!r} is not in evidence_contract.ROLES")
    if row.get("channel") not in ec.CHANNELS:
        raise FactRegistryError(line_no, f"channel {row.get('channel')!r} is not a known channel")
    if row["channel"] in ec.QUOTE_REQUIRED_CHANNELS and not row.get("quote"):
        raise FactRegistryError(line_no, f"channel {row['channel']!r} requires a quote")
    if row.get("quote") and len(row["quote"]) > ec.QUOTE_MAX_CHARS:
        raise FactRegistryError(line_no, f"quote longer than {ec.QUOTE_MAX_CHARS} chars — fact sentence only")
    if not row.get("ref"):
        raise FactRegistryError(line_no, "ref must name the source (URL or chain: pointer)")
    if c1.parse_ts(row.get("retrieved_at")) is None:
        raise FactRegistryError(line_no, "retrieved_at must be a parseable ISO-8601 timestamp")
    if row.get("effective_from") is not None and c1.parse_ts(row["effective_from"]) is None:
        raise FactRegistryError(line_no, "effective_from, when present, must be a parseable ISO-8601 timestamp")
    if row.get("expires_at") is not None and c1.parse_ts(row["expires_at"]) is None:
        raise FactRegistryError(line_no, "expires_at, when present, must be a parseable ISO-8601 timestamp")
    if row.get("effective_until") is not None and c1.parse_ts(row["effective_until"]) is None:
        raise FactRegistryError(line_no, "effective_until, when present, must be a parseable ISO-8601 timestamp")
    unknown = set(row) - set(ec.FACT_FIELDS) - set(ec.FACT_OPTIONAL_FIELDS)
    if unknown:
        raise FactRegistryError(line_no, f"unknown fact field(s) {sorted(unknown)}")
    if not isinstance(row.get("origin"), str) or not row["origin"]:
        raise FactRegistryError(line_no, "origin must name the producing party")
    return row


def load_facts(path: Optional[Path] = None, *, origins: Optional[dict] = None,
               refused_out: Optional[list] = None, reviews: Optional[list] = None) -> list:
    """Every parsed/validated, USABLE row, in file order. A missing file is an honestly empty
    list. A STRUCTURALLY malformed line raises :class:`FactRegistryError` immediately — the
    whole file is suspect, never silently skipped. A structurally-valid fact that fails a
    SEMANTIC usability check (:class:`FactUnusable` — no independent review yet, or an
    origin/host mismatch, post-implementation review H6) is excluded from the returned list but
    does NOT halt the load of every OTHER fact; it is recorded into ``refused_out`` (when given)
    as ``{"line_no", "fact_id", "reason"}`` — visible and auditable, never silently dropped, just
    scoped to the one fact rather than the whole file. A caller that cares about refusals (run.py
    writes them into the run's own ledger row, same pattern as ``scanner_errors``) passes a list;
    one that doesn't still gets the correct (smaller) usable set, just without the detail.

    ``origins``: the registry :func:`load_origins` returns, needed for the host check. Defaults
    to ``load_origins()`` — a caller that already loaded it (``run.py`` does) should pass the
    SAME dict, not load it twice.

    ``reviews``: the list :func:`load_fact_reviews` returns, needed for the content-bound review
    check (re-review H6, 2026-10-04). Defaults to loading ``<path's directory>/fact_reviews/`` —
    a caller that already loaded it should pass the SAME list, not load it twice."""
    p = path or default_facts_path()
    if not p.exists():
        return []
    origins = load_origins() if origins is None else origins
    reviews = load_fact_reviews(default_fact_reviews_dir(p)) if reviews is None else reviews
    rows = []
    with open(p, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            row = _parse_fact_line(line_no, raw_line)
            if row is None:
                continue
            try:
                _check_independent_review(line_no, row, reviews)
                _check_origin_hosts(line_no, row, origins)
            except FactUnusable as exc:
                if refused_out is not None:
                    refused_out.append({"line_no": exc.line_no, "fact_id": exc.fact_id, "reason": exc.reason})
                continue
            rows.append(row)
    return rows


def is_stale(fact: dict, now: datetime) -> bool:
    """A fact past its own ``expires_at`` is STALE. No ``expires_at`` recorded ⇒ never stale BY
    THIS mechanical check (review #15's re-retrieval judgement is a separate, curator-session
    concern this loader does not perform)."""
    expiry = c1.parse_ts(fact.get("expires_at"))
    if expiry is None:
        return False
    now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return now_aware > expiry


def has_ended(fact: dict, now: datetime) -> bool:
    """The stated claim itself has ended (``effective_until`` on/before ``now``) — e.g. a fee waiver.
    Unlike ``is_stale`` this is not "please re-verify": the fact no longer describes the present."""
    until = c1.parse_ts(fact.get("effective_until"))
    if until is None:
        return False
    now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return now_aware >= until


def facts_for(facts: list, candidate_id: str, *, now: Optional[datetime] = None,
              include_stale: bool = False) -> list:
    """Facts naming ``candidate_id``, newest ``retrieved_at`` first. Stale facts are excluded
    unless ``include_stale=True`` (a caller that needs to KNOW about staleness, not merely avoid
    it, asks for that explicitly) — excluding requires ``now`` (no ``now`` ⇒ staleness is simply
    not judged, never guessed)."""
    out = [f for f in facts if candidate_id in (f.get("candidate_ids") or [])]
    if now is not None:
        out = [f for f in out if not has_ended(f, now)]  # an ended claim is never "the present", stale or not
    if not include_stale and now is not None:
        out = [f for f in out if not is_stale(f, now)]
    out.sort(key=lambda f: f.get("retrieved_at") or "", reverse=True)
    return out
