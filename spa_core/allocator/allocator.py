"""StrategyAllocator (SPA-V388) — advisory-распределение $100K paper-капитала.

CANONICAL live money-path allocator. Это единственный аллокатор, который запускает
ежедневный цикл: cycle_runner ``_build_real_allocator`` → ``StrategyAllocator(...)``
→ target allocation → RiskPolicy gate → virtual rebalance. Прочие аллокаторы
(``dynamic_allocator.DynamicAllocator``, ``analytics/*allocator*``) — secondary /
experimental / Tier-C background, НЕ в money-path. См. docs/DECISIONS.md.

Читает снимок адаптеров (``data/adapter_orchestrator_status.json``), применяет
одну из моделей аллокации (``allocation_models``) и кап'ы по тирам, после чего
возвращает целевое распределение в виде :class:`AllocationResult`.

ВАЖНО: модуль строго read-only / dry-run. Он НЕ исполняет сделки, НЕ обращается
к ``execution/`` и не двигает реальные деньги — только формирует рекомендацию.
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from spa_core.allocator import allocation_models as models
from spa_core.strategies.strategy_selector import StrategySelector
from spa_core.utils.errors import AllocationError
from spa_core.utils.atomic import atomic_save

# FIX-P1 (single source of limits): import RiskConfig so allocator limits
# are always in sync with policy.py — no more hardcoded duplicates that drift.
try:
    from spa_core.risk.policy import RiskConfig as _RiskConfig
    _POLICY_CONFIG = _RiskConfig()
except Exception:  # pragma: no cover — import guard for test isolation
    _POLICY_CONFIG = None  # type: ignore[assignment]

log = logging.getLogger("spa.allocator")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATUS_PATH = _REPO_ROOT / "data" / "adapter_orchestrator_status.json"
_RISK_SCORES_PATH = _REPO_ROOT / "data" / "risk_scores.json"
_SHADOW_COMPARISON_PATH = _REPO_ROOT / "data" / "strategy_shadow_comparison.json"
_DEFAULT_OUT = _REPO_ROOT / "data" / "target_allocation.json"
_REGISTRY_PATH = _REPO_ROOT / "data" / "adapter_registry.json"
# ADR-061 (D1/D2): the ONLY file that distinguishes an OBSERVED APY from a
# hardcoded literal — ``adapters[*].live_apy`` is explicitly ``null`` when the
# producer could not observe the pool. Every other surface (registry
# ``fallback_apy``, adapter ``DEFAULT_APY_PCT``) is a literal, never evidence.
_ADAPTER_STATUS_PATH = _REPO_ROOT / "data" / "adapter_status.json"
_EPS = 1e-12

# ADR-061: below this many evidenced protocols the evidence gate is NOT applied
# (the evidence source is missing/unreadable). Ranking then falls back to the
# legacy universe with a loud note instead of silently emptying the book — an
# all-cash collapse triggered by an unreadable file would itself be a money-path
# incident. min_protocols is 3, so fewer than 3 could not be allocated anyway.
_EVIDENCE_MIN_COVERAGE = 3

# ADR-169: ВТОРОЕ условие того же отказа — обвал покрытия ОТНОСИТЕЛЬНО того,
# сколько протоколов производители вообще перечислили.
#
# Абсолютный порог выше срабатывает только когда ослепли ВСЕ, кроме двух: при
# 18 наблюдаемых протоколах он молчит вплоть до 16 ослепших. А ослепнуть разом
# больше чем наполовину протоколы не могут независимо друг от друга — у них
# разные сети, разные пулы, разные источники. Одновременная потеря половины
# наблюдений почти всегда означает поломку НАШЕГО производителя, и тогда
# «протокол не наблюдается» — неверное утверждение о мире: эвакуировать книгу
# из здоровых протоколов по нашей же поломке нельзя.
#
# Замер 2026-08-29: перечислено 34 адаптера, наблюдено 23 (68 %). До порога
# в половину — запас; поломка, гасящая половину наблюдений, его пробивает.
_EVIDENCE_MIN_COVERAGE_FRACTION = 0.5

# How long an observation stays evidence (ADR-060 §3, paper column). An observation
# is not invalidated by the next fetch failing — only by AGE. Before this window
# existed the rule was binary, so one failed HTTP request blanked live_apy for all
# 34 adapters and the gate honestly concluded "nothing is observable" — i.e. a
# network hiccup would have evacuated the book to cash. Measured 2026-08-04 15:14Z.
_EVIDENCE_MAX_AGE_H = 36.0

# MP-REGISTRY: fallback TVL assumption for registry-only adapters (not in orchestrator).
# These are all established protocols with TVL >> $5M TVL floor; $50M is conservative.
# ADR-053 (allocator side): this literal is ALWAYS labeled tvl_source="static" and
# never counts as *verifying* the $5M floor — pools ranked on it are listed in
# feed_coverage["tvl_floor_unverified"]; the RiskPolicy gate is the enforcement point.
_REGISTRY_FALLBACK_TVL_USD = 50_000_000.0

# Модель по умолчанию: risk-aware (SPA-V406). Раньше было "equal_weight".
# WS1.2: the new constrained ``optimized_yield`` optimizer is SELECTABLE + tested
# but kept BEHIND a flag for A/B — the heuristic remains the default until the
# owner promotes the optimizer (a money-path allocation-surface change). To make
# the optimizer the default: set SPA_ALLOCATOR_MODEL=optimized_yield (env) or pass
# allocation_model="optimized_yield". See OBJECTIVE dial below (owner-tunable).
DEFAULT_MODEL = "risk_adjusted"

_MODEL_DISPATCH = {
    "equal_weight": models.equal_weight,
    "equal": models.equal_weight,
    "best_apy": models.best_apy_weight,
    "best_apy_weight": models.best_apy_weight,
    "risk_parity": models.risk_parity_weight,
    "risk_parity_weight": models.risk_parity_weight,
}

# risk_adjusted обрабатывается отдельно (нужен второй аргумент — risk_scores),
# поэтому не входит в _MODEL_DISPATCH с сигнатурой fn(adapters).
_RISK_MODEL_ALIASES = {"risk_adjusted", "risk", "risk_adjusted_weight"}

# WS1.2: the constrained yield optimizer is handled on its own path (it needs the
# tier caps + budget constraints, and it produces cap-respecting weights directly
# — so the allocator MUST NOT run the T1-first _fill_remainder over its output).
_OPTIMIZER_MODEL_ALIASES = {"optimized_yield", "optimizer", "optimized"}

# Алиасы идентификаторов: адаптерный protocol → slug в data/risk_scores.json.
# Нормализация в allocation_models снимает регистр/разделители, но не различия
# в самом имени: адаптер "morpho_blue" соответствует slug "morpho".
_PROTOCOL_ALIASES = {
    "morpho_blue": "morpho",
}

# WS1.1: APY sanity band for a LIVE point-in-time reading (decimal). A live APY
# outside this band is treated as a malformed/anomalous feed and is NOT used to
# rank — the adapter fails CLOSED to its labeled stale fallback (never a
# fabricated number, never a live-feed spike silently winning). The lower bound
# is >0 (a 0% / negative live reading is not actionable yield). The upper bound
# mirrors the DeFiLlama feed's own APY_SANITY_MAX (200% == 2.0 decimal).
_LIVE_APY_MIN_DECIMAL = 0.0   # exclusive: apy must be > 0
_LIVE_APY_MAX_DECIMAL = 2.0   # 200% — anything above is an anomaly, fail-closed


# Process-level cache for the default live-APY fetch. allocate() may be called
# several times per process (cycle + analytics); without this each call would
# re-poll every adapter (~30 network round-trips). TTL keeps it point-in-time
# fresh within a cycle while collapsing duplicate fetches. Injected providers
# (tests) bypass this entirely.
_LIVE_APY_CACHE_TTL = 300.0  # seconds (mirrors DeFiLlama feed TTL)
_live_apy_cache: dict[str, float] | None = None
_live_apy_cache_ts: float = 0.0


def _default_live_apy_provider() -> dict[str, float]:
    """Live point-in-time APY (decimal) per registry adapter, via DeFiLlama.

    WS1.1 money-path fix. Instantiates every adapter class in
    ``ADAPTER_REGISTRY`` and reads its CANONICAL ``get_yield_info().apy`` (always
    a decimal fraction, or ``None`` when the live feed is unavailable — see
    base_adapter P3-5). This is the SAME live feed the orchestrator uses, but
    extended to ALL registered adapters (not just the ~7 the orchestrator polls),
    so the allocator can rank on live APY instead of the stale registry literal.

    Strictly read-only. Never raises: any per-adapter error → that adapter is
    simply absent from the result (→ caller falls to its labeled stale
    fallback, fail-CLOSED). A non-finite / out-of-band / non-positive live
    reading is EXCLUDED here so it can never silently win over the literal.
    """
    global _live_apy_cache, _live_apy_cache_ts
    import os as _os
    import time as _time

    # Offline / deterministic guard: under pytest (or when DeFiLlama is disabled)
    # the default provider performs NO network I/O — it returns {} so the
    # allocator falls to its labeled stale fallbacks. This keeps the whole test
    # suite offline + bit-reproducible; tests that exercise the LIVE money-path
    # inject an explicit ``live_apy_provider`` instead (never the real network).
    if _os.environ.get("PYTEST_CURRENT_TEST"):
        return {}
    try:
        # ``spa_core.adapters.config`` — НАСТОЯЩИЙ дом флага (тот же модуль читают
        # сами фиды `defillama_feed` / `sky_susds_feed`). Раньше здесь стояло
        # ``from . import config``, а в пакете ``spa_core.allocator`` модуля
        # ``config`` нет ⇒ ImportError глотался except'ом ниже и выключатель
        # DEFILLAMA_ENABLED=false для этого пути НЕ РАБОТАЛ (при выключенном
        # фиде аллокатор всё равно шёл в сеть). Импорт ленивый — цикла нет.
        from spa_core.adapters import config as _cfg
        if not getattr(_cfg, "DEFILLAMA_ENABLED", True):
            return {}
    except Exception:  # noqa: BLE001
        pass

    now = _time.monotonic()
    if _live_apy_cache is not None and (now - _live_apy_cache_ts) < _LIVE_APY_CACHE_TTL:
        return dict(_live_apy_cache)

    out: dict[str, float] = {}
    try:
        from spa_core.adapters import ADAPTER_REGISTRY  # lazy — avoid import cost on tests
    except Exception as exc:  # pragma: no cover — import guard
        log.warning("WS1.1 live provider: ADAPTER_REGISTRY import failed (%s)", exc)
        return out
    for entry in ADAPTER_REGISTRY:
        try:
            key, _tier, cls = entry[0], entry[1], entry[2]
        except Exception:  # noqa: BLE001 — malformed registry row
            continue
        # Advisory / research-only adapters are NEVER live-allocatable — they exist for
        # monitoring/research only (invariant: IS_ADVISORY must not reach the money path).
        # The registry was ranked by tier caps but NEVER filtered by advisory status, so an
        # advisory T3 (e.g. susde, extra_finance) could leak into the live book. Exclude here.
        if getattr(cls, "IS_ADVISORY", False) or getattr(cls, "RESEARCH_ONLY", False):
            continue
        try:
            info = cls().get_yield_info()
            apy = getattr(info, "apy", None)
        except Exception as exc:  # noqa: BLE001 — one bad adapter never breaks the feed
            log.debug("WS1.1 live provider: %s get_yield_info failed (%s)", key, exc)
            continue
        # decimal apy; fail-CLOSED on non-numeric/non-finite/out-of-band.
        if (
            isinstance(apy, (int, float))
            and not isinstance(apy, bool)
            and math.isfinite(apy)
            and _LIVE_APY_MIN_DECIMAL < float(apy) <= _LIVE_APY_MAX_DECIMAL
        ):
            out[str(key)] = float(apy)
    _live_apy_cache = dict(out)
    _live_apy_cache_ts = now
    return out


# ─── ADR-061: evidence of an OBSERVED APY (D1/D2) ────────────────────────────


def _required_coverage(attempted: int) -> int:
    """Сколько наблюдений нужно, чтобы гейт доказательств вообще применялся.

    БОЛЬШЕЕ из абсолютного минимума (ADR-061) и половины перечисленного
    (ADR-169). Знаменатель не измерен ⇒ правило доли молчит, остаётся абсолют:
    незнание не должно ужесточать money-path сильнее, чем знание.

    Отдельная функция, а не выражение внутри метода, намеренно: иначе тест
    вынужден пересчитывать порог сам и проверяет собственную копию правила.
    """
    if attempted <= 0:
        return _EVIDENCE_MIN_COVERAGE
    by_fraction = math.ceil(_EVIDENCE_MIN_COVERAGE_FRACTION * attempted)
    return max(_EVIDENCE_MIN_COVERAGE, by_fraction)


def _observation_attempts(
    orchestrator_path: Path,
    adapter_status_path: Path | None = None,
) -> int:
    """Сколько протоколов производители ВООБЩЕ перечислили (ADR-169).

    Знаменатель покрытия. Считаются записи, а не наблюдения: адаптер, который
    производитель перечислил и не смог опросить, — это попытка, и именно она
    отличает «мир затих» от «наш производитель сломался».

    Никогда не бросает: нечитаемый источник вносит ноль, и правило доли просто
    не применяется (остаётся абсолютный порог).
    """
    names: set[str] = set()
    for path in (orchestrator_path, adapter_status_path):
        if path is None:
            continue
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — знаменатель best-effort, как и числитель
            continue
        if not isinstance(doc, dict):
            continue
        block = doc.get("adapters", doc)
        if isinstance(block, dict):
            names.update(str(k) for k in block.keys())
        elif isinstance(block, list):
            for entry in block:
                if isinstance(entry, dict):
                    nm = entry.get("name") or entry.get("protocol") or entry.get("adapter")
                    if nm:
                        names.add(str(nm))
    # Ключи-метаданные верхнего уровня — не протоколы.
    return len(names - {"generated_at", "schema_version", "source", "execution_mode",
                        "run_ts", "duration_sec", "adapters"})


def _load_evidenced_apy(
    orchestrator_path: Path,
    adapter_status_path: Path | None = None,
    now: "datetime | None" = None,
) -> dict[str, tuple[float, str]]:
    """Return ``{protocol: (apy_decimal, source)}`` for OBSERVED APYs only.

    ADR-061. Two sources, both of which carry an explicit "this was observed"
    signal, so a hardcoded literal can never masquerade as a live reading:

    1. ``adapter_orchestrator_status.json`` — entries with ``live_data == true``
       (the orchestrator polled the adapter and got a value).
    2. ``adapter_status.json`` → ``adapters[*].live_apy`` — non-null means the
       producer observed the pool; ``null`` means it did not (and its ``apy``
       field then merely echoes the literal ``fallback_apy``).

    Deliberately NOT evidence: the registry ``fallback_apy`` literal, and the
    per-adapter ``get_yield_info()`` call — 12 of 35 adapters read
    ``adapter_status.json`` by an obsolete schema (top level instead of
    ``adapters``) and silently return their hardcoded ``DEFAULT_APY_PCT``
    (D1). Until those are fixed, an adapter call cannot prove observation.

    On conflict the FRESHER producer wins (deterministic, by ``generated_at``);
    both values are logged so a divergence stays visible (D6). Never raises:
    any unreadable/invalid input contributes nothing.
    """
    out: dict[str, tuple[float, str]] = {}

    def _band(v: object) -> float | None:
        """Percent → decimal, fail-CLOSED outside the live-APY sanity band."""
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        dec = float(v) / 100.0
        if not math.isfinite(dec):
            return None
        if not (_LIVE_APY_MIN_DECIMAL < dec <= _LIVE_APY_MAX_DECIMAL):
            return None
        return dec

    def _read(path: Path) -> dict[str, object]:
        """JSON *object* or ``{}``. A non-object document is an unreadable input.

        ``json.loads`` returns ``Any``, so the old ``-> dict`` annotation checked
        nothing and a VALID JSON document that simply is not an object (``[]``,
        ``"text"``, ``5``) flowed straight through into ``.get`` / ``.items`` —
        ``AttributeError`` out of the money-path allocator, contradicting this
        function's "never raises" contract (the ``try`` only ever covered reading
        and parsing, never the shape of the result). Treated as unreadable
        (fail-CLOSED, invariant 2); the type actually seen is quoted verbatim so
        the refusal stays distinguishable from a genuinely quiet world.
        """
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — evidence is best-effort
            log.warning("ADR-061: evidence source unreadable %s (%s)", path, exc)
            return {}
        if not isinstance(doc, dict):
            log.warning(
                "ADR-061: evidence source %s is valid JSON but not an object "
                "(%s) — no evidence taken from it", path, type(doc).__name__,
            )
            return {}
        return doc

    def _wrong_shape(container: object, expected: str, path: Path) -> None:
        """Log ``adapters`` of an unusable type. ``None``/empty is not a defect."""
        if container:  # ``None`` / ``{}`` / ``[]`` is simply "nothing reported"
            log.warning(
                "ADR-061: evidence source %s has 'adapters' of type %s, expected "
                "%s — no evidence taken from it",
                path, type(container).__name__, expected,
            )

    def _as_list(container: object, path: Path) -> list:
        """The orchestrator's ``adapters`` list, or an empty one.

        Same hole one level down: a well-formed object may still carry an
        ``adapters`` of the wrong type — ``5`` raised ``TypeError: 'int' object
        is not iterable``. A mapping here never produced evidence anyway
        (iterating a dict yields its keys, which are not dicts), so refusing it
        outright changes no outcome, it only makes the reason visible.
        """
        if isinstance(container, list):
            return container
        _wrong_shape(container, "list", path)
        return []

    def _as_map(container: object, path: Path) -> dict:
        """``adapter_status.json``'s ``adapters`` mapping, or an empty one.

        ``adapters: [1, 2]`` raised ``AttributeError: 'list' object has no
        attribute 'items'``.
        """
        if isinstance(container, dict):
            return container
        _wrong_shape(container, "mapping", path)
        return {}

    orch = _read(orchestrator_path)
    orch_ts = str(orch.get("generated_at") or "")
    for a in _as_list(orch.get("adapters"), orchestrator_path):
        if not isinstance(a, dict) or not a.get("live_data"):
            continue
        if a.get("status") not in ("ok", "partial", None):
            continue
        dec = _band(a.get("apy_pct"))
        if dec is not None and a.get("protocol"):
            out[str(a["protocol"])] = (dec, "orchestrator_live")

    if adapter_status_path is None:
        return out

    st = _read(adapter_status_path)
    st_ts = str(st.get("generated_at") or "")

    def _parsed(ts: str) -> "datetime | None":
        """ISO-8601 → aware datetime. Never raises; ``None`` when unparseable."""
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError):
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def _within_window(as_of: object, fallback_ts: str) -> bool:
        """Is an observation young enough to still count as evidence?

        Age is measured from when the value was OBSERVED (``live_apy_as_of``),
        not from when the file was written — a carried-forward reading must age
        out on its own clock. An unparseable timestamp is treated as too old:
        unknown age is not evidence (fail-CLOSED).
        """
        dt = _parsed(str(as_of)) if as_of else _parsed(fallback_ts)
        if dt is None:
            return False
        # ``now`` is an INPUT, not ambient state (2026-08-04). When a freshness
        # window reads the wall clock directly, every test fixture with a literal
        # date becomes a time bomb: it passes today and fails in two days for a
        # reason that has nothing to do with the behaviour under test. Three test
        # files broke exactly that way the day this window was introduced.
        # Injecting the clock makes such a test pin BOTH sides and stay valid
        # forever; the default keeps production behaviour unchanged.
        ref = now or datetime.now(timezone.utc)
        age_h = (ref - dt).total_seconds() / 3600.0
        return age_h <= _EVIDENCE_MAX_AGE_H

    # Compare real instants, not strings: "…Z" vs "…+00:00" sort in the WRONG
    # order lexicographically ("Z" > "+"), which would silently pick the stale
    # producer on a money-path tie-break. Unparseable timestamps ⇒ keep the
    # incumbent (fail-CLOSED: do not switch sources on an unknown).
    _st_dt, _orch_dt = _parsed(st_ts), _parsed(orch_ts)
    st_newer = bool(_st_dt and _orch_dt and _st_dt > _orch_dt)
    for name, entry in _as_map(st.get("adapters"), adapter_status_path).items():
        if not isinstance(entry, dict):
            continue
        dec = _band(entry.get("live_apy"))  # null ⇒ NOT observed ⇒ no evidence
        if dec is None:
            continue
        # A carried-forward reading stays evidence only inside the age window.
        if not _within_window(entry.get("live_apy_as_of"), st_ts):
            continue
        prev = out.get(str(name))
        if prev is not None:
            if abs(prev[0] - dec) > 1e-9:
                log.info(
                    "ADR-061 (D6) feed divergence %s: orchestrator=%.4f%% "
                    "adapter_status=%.4f%% — using %s (fresher)",
                    name, prev[0] * 100.0, dec * 100.0,
                    "adapter_status" if st_newer else "orchestrator",
                )
            if not st_newer:
                continue
        out[str(name)] = (dec, "adapter_status_live")

    return out


def _load_evidenced_tvl(
    adapter_status_path: Path | None = None,
    now: "datetime | None" = None,
) -> dict[str, tuple[float, str]]:
    """Return ``{protocol: (tvl_usd, pool_id)}`` for OBSERVED TVL only.

    The TVL twin of :func:`_load_evidenced_apy`, and it exists for the same
    reason the APY one does: without it the $5M floor is decided by a literal.

    Evidence here is deliberately stricter than for APY. An APY literal that is
    wrong mis-RANKS a pool; a TVL literal that is wrong lets a pool that should
    be refused pass a gate. ``moonwell_base`` is the worked example — the adapter
    carries ``TVL_USD = 500_000_000`` against $2.6M observed, a 190x
    overstatement, and the pool clears a $5M floor it actually fails.

    So only ``tvl_source == "live"`` counts, and the producer stamps that only on
    a PINNED pool-UUID match: a fuzzy "best TVL wins" hint match is not a stable
    identity (Base alone has four STEAKUSDC vaults), and a gate must not rest on
    an identity that can drift between runs. The returned ``pool_id`` makes the
    number reproducible — an auditor re-fetches that UUID and gets it back.

    Same age window as the APY evidence, for the same reason: an observation is
    evidence of the moment it was made, not forever. Never raises; anything
    unreadable simply contributes nothing, leaving the caller on its literal —
    which is labelled "static" and cannot clear the floor.
    """
    out: dict[str, tuple[float, str]] = {}
    if adapter_status_path is None:
        return out
    try:
        doc = json.loads(Path(adapter_status_path).read_text(encoding="utf-8"))
    except Exception:
        return out
    if not isinstance(doc, dict):
        return out

    ref = now or datetime.now(timezone.utc)
    generated_at = doc.get("generated_at")
    rows = doc.get("adapters")
    if not isinstance(rows, dict):
        return out

    for name, row in rows.items():
        if not isinstance(row, dict):
            continue
        if row.get("tvl_source") != "live":
            continue
        tvl = row.get("tvl_usd")
        if not isinstance(tvl, (int, float)) or isinstance(tvl, bool):
            continue
        tvl = float(tvl)
        if not math.isfinite(tvl) or tvl <= 0:
            continue
        # Age it off the same clock the APY evidence uses. ``live_apy_as_of``
        # is the observation time of the run that also produced this TVL; when
        # it is absent fall back to the document stamp, and when NEITHER parses,
        # refuse (fail-CLOSED) rather than treat an undateable number as fresh.
        stamp = row.get("live_apy_as_of") or generated_at
        try:
            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if (ref - dt).total_seconds() / 3600.0 > _EVIDENCE_MAX_AGE_H:
            continue
        pool_id = str(row.get("tvl_pool_id") or "") or "unknown"
        out[str(name)] = (tvl, pool_id)

    return out


def _adapter_class_gate(protocol: str) -> tuple[bool, str | None]:
    """ADR-061 (D3/D4): may ``protocol`` receive capital at all?

    Returns ``(allowed, reason_if_blocked)``. Fail-CLOSED — anything that cannot
    be evaluated cleanly blocks funding rather than allowing it.

    * ``IS_ADVISORY`` / ``RESEARCH_ONLY`` ⇒ never funded (invariant 9). The live
      provider already excluded these; the registry-merge path did NOT, which is
      how two advisory pools came to hold 15 % of the book (D3).
    * ``is_gsm_compliant() == False`` ⇒ not funded. This is the adapter's own
      ACTIVATION invariant — for ``spark_susds`` it is invariant 10 (Sky/sUSDS =
      0 % until the GSM Pause Delay ≥ 48 h is confirmed on-chain). Nothing
      consulted it (D4).

      ADR-137 (owner, 2026-08-25, option A): ``fluid_fusdc`` used to declare the
      same gate, and this docstring used to call that deliberate. It was not — 48 h
      is Maker's ``DSPause`` number, and Fluid (Instadapp) has its own governance
      that we have never read. The gate could therefore answer only "unconfirmed",
      so a $150.3M pool at 4.82 % was closed to capital by an alien rule rather
      than by risk — while its sibling ``fluid_usdc``, the same protocol, passed
      freely. The gate is REMOVED from the adapter (not stubbed to ``True``: a
      gate that cannot refuse is the literal ``True`` wearing a risk gate's name),
      and ``hasattr`` below therefore skips Fluid. Admission is the common key —
      live APY and live TVL.

    DELIBERATELY NOT gated on the generic ``is_eligible()``, although the card
    proposed it: for most adapters ``is_eligible`` is ``gsm ∧ MIN_APY ≤ apy ≤
    MAX_APY``, and those bands are per-adapter feed-sanity values (e.g. spark
    4–9 %, fluid 3–10 %), NOT RiskPolicy's 1–30 %. Using it to gate funding would
    silently install an APY floor that no ADR owns — a policy threshold change by
    the back door. A first attempt did gate on it and
    ``test_live_apy_drives_ranking_not_the_stale_literal`` correctly caught it.

    Adapters with no registry entry and no gate are allowed — absence of a class
    is not, by itself, a disqualification (it is handled by the evidence gate).
    """
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
    except Exception as exc:  # pragma: no cover — import guard
        log.warning("ADR-061: ADAPTER_REGISTRY import failed (%s) — gate skipped", exc)
        return True, None

    cls = None
    for entry in ADAPTER_REGISTRY:
        try:
            if entry[0] == protocol:
                cls = entry[2]
                break
        except Exception:  # noqa: BLE001 — malformed registry row
            continue
    if cls is None:
        return True, None

    if getattr(cls, "IS_ADVISORY", False) or getattr(cls, "RESEARCH_ONLY", False):
        return False, "advisory"

    if hasattr(cls, "is_gsm_compliant"):
        try:
            if not cls().is_gsm_compliant():
                return False, "gsm_not_confirmed"
        except Exception as exc:  # noqa: BLE001 — fail-CLOSED on an unusable gate
            log.warning(
                "ADR-061: %s.is_gsm_compliant() raised (%s) — blocked", protocol, exc
            )
            return False, "gsm_gate_error"

    return True, None


@dataclass
class AllocationResult:
    """Результат расчёта целевого распределения."""

    target_weights: dict[str, float]
    target_usd: dict[str, float]
    expected_apy_pct: float
    model_used: str
    timestamp: str
    capital_usd: float = 0.0
    allocated_pct: float = 0.0
    unallocated_pct: float = 0.0
    unallocated_usd: float = 0.0
    # SPA-V405: explicit deployment breakdown after T1-anchor remainder fill.
    cash_pct: float = 0.0
    t1_pct: float = 0.0
    t2_pct: float = 0.0
    total_deployed_pct: float = 0.0
    # SPA-V406: risk-aware аллокация на основе data/risk_scores.json.
    risk_model_applied: bool = False
    # protocol → {risk_grade, risk_multiplier, pre_risk_weight, post_risk_weight}
    risk_breakdown: dict[str, dict] = field(default_factory=dict)
    # SPA-V408: shadow→allocator feedback loop. Когда лучшая shadow-стратегия
    # (по Sortino, confidence ≥ medium) использована как база весов.
    strategy_loop_active: bool = False
    selected_strategy_id: str | None = None
    strategy_confidence: str | None = None
    # MP-011: соблюдение RiskPolicy на стороне аллокатора (TVL-floor + T2-total).
    tvl_filtered_protocols: list[str] = field(default_factory=list)
    t2_cap_enforced: bool = False
    # MP-209: capacity limits enforcement (позиция ≤ 1% TVL пула, ADR-009).
    capacity_capped: bool = False
    capacity_check: dict = field(default_factory=dict)
    # WS1.1 (money-path data-integrity): per-adapter provenance of the APY that
    # drove ranking/allocation. ``apy_sources`` maps protocol → "live" |
    # "fallback_stale"; ``feed_coverage`` summarises live-vs-fallback counts so a
    # reviewer SEES which adapters ranked on live DeFiLlama data vs the stale
    # registry literal. ``apy_used`` records the (pct) value actually ranked on.
    apy_sources: dict[str, str] = field(default_factory=dict)
    apy_used: dict[str, float] = field(default_factory=dict)
    feed_coverage: dict = field(default_factory=dict)
    # ADR-061 (D1–D4): True when funding was restricted to OBSERVED APYs.
    # ``blocked_protocols`` maps protocol → "advisory" | "gsm_not_confirmed" |
    # "gsm_gate_error" | "unevidenced" — the audit trail of what could NOT
    # receive capital this run, and why.
    evidence_gate_applied: bool = False
    blocked_protocols: dict[str, str] = field(default_factory=dict)
    # ADR-072-остаток (карточка «трим происходит в АЛЛОКАТОРЕ»): сколько веса
    # срезали ЗАЩИТНЫЕ тримы внутри аллокатора (доли, по шагам). Явный сигнал
    # для перезаполнения/атрибуции кэша — вместо вычитания сумм на глаз.
    protective_trims: dict[str, float] = field(default_factory=dict)
    #: ADR-160: то же срезанное, но ПОИМЁННО {протокол: доля}. Нужно перераздаче:
    #: по решению владельца (вариант 3) деньги НЕ возвращаются в пулы, чей потолок
    #: их только что и срезал — это была бы инерция, а ADR-055 требует, чтобы
    #: концентрация следовала за доходностью и риском.
    protective_trims_by_protocol: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class StrategyAllocator:
    """Advisory-аллокатор целевых весов портфеля."""

    CAPITAL = 100_000  # USD paper trading

    # FIX-P1 (single source of limits): all concentration/TVL limits are read
    # from RiskConfig (policy.py) at class definition time so the allocator and
    # the risk gate are always in sync.  _POLICY_CONFIG is None only when the
    # import failed (e.g. in isolated unit tests); in that case the hardcoded
    # fallback values below keep backwards-compatibility.
    #
    # policy.py source of truth:
    #   max_concentration_t1  → T1_CAP
    #   max_concentration_t2  → T2_CAP
    #   min_tvl_usd           → TVL_FLOOR_USD
    #   max_total_t2_alloc    → T2_TOTAL_CAP  (ADR-019: 50%)
    T1_CAP: float = (
        _POLICY_CONFIG.max_concentration_t1 if _POLICY_CONFIG is not None else 0.40
    )
    T2_CAP: float = (
        _POLICY_CONFIG.max_concentration_t2 if _POLICY_CONFIG is not None else 0.20
    )
    TVL_FLOOR_USD: float = (
        _POLICY_CONFIG.min_tvl_usd if _POLICY_CONFIG is not None else 5_000_000.0
    )
    T2_TOTAL_CAP: float = (
        _POLICY_CONFIG.max_total_t2_allocation if _POLICY_CONFIG is not None else 0.50
    )
    # ADR-020: T3 (highest-risk: sUSDe, extra_finance_base, …) total cap 15%. Read from the same
    # policy config so it can never drift. The WS1.2 optimizer collapsed T3→T2 (allocator only ever
    # emitted "T1"/"T2" tier strings), so this cap was silently unenforced — the optimized_yield book
    # could pour 30% into T3. _enforce_t3_total_cap (below) re-applies it against the CANONICAL tier_map.
    T3_TOTAL_CAP: float = (
        getattr(_POLICY_CONFIG, "max_total_t3_allocation", 0.15) if _POLICY_CONFIG is not None else 0.15
    )
    # A4 (de-hardcode ALLOC-002): the diversity floor (≤ N funded protocols) is
    # read from RiskConfig (single source of truth) instead of a hardcoded `8`
    # inside allocate(). Owner-gated like every other cap; the WS1.2 optimizer
    # receives THIS value so the limit can never drift between policy and model.
    MAX_PROTOCOLS: int = (
        _POLICY_CONFIG.max_protocols if _POLICY_CONFIG is not None else 8
    )
    # ── ADR-136: сетевые потолки. У аллокатора на входе не было поля «сеть»,
    #    хотя сеть всех кандидатов определяется из того же файла реестра,
    #    который аллокатор уже читает. Замер 2026-08-18: предложение модели
    #    optimized_yield дало 95 % капитала в Ethereum, и гейт отверг раскладку
    #    ЦЕЛИКОМ — то есть в таком цикле сделок не было вовсе.
    #    Значения — из той же политики, ни одного нового числа.
    SINGLE_CHAIN_CAP: float = (
        _POLICY_CONFIG.max_single_chain_allocation if _POLICY_CONFIG is not None else 0.90
    )
    L2_TOTAL_CAP: float = (
        _POLICY_CONFIG.max_l2_total_allocation if _POLICY_CONFIG is not None else 0.50
    )
    BASE_CHAIN_CAP: float = (
        getattr(_POLICY_CONFIG, "BASE_CHAIN_CAP", 0.20) if _POLICY_CONFIG is not None else 0.20
    )
    #: Тот же набор L2, что у входного гейта политики (блок 10).
    L2_CHAINS: frozenset = frozenset({"arbitrum", "base"})

    # Assert: fallback значения должны совпадать с policy (нет silent drift)
    if _POLICY_CONFIG is not None:
        _T1_CAP_ACTUAL = _POLICY_CONFIG.max_concentration_t1
        _T2_CAP_ACTUAL = _POLICY_CONFIG.max_concentration_t2
        assert abs(T1_CAP - _T1_CAP_ACTUAL) < 1e-6, (
            f"T1_CAP fallback ({T1_CAP}) != policy ({_T1_CAP_ACTUAL}) — update fallback!"
        )
        assert abs(T2_CAP - _T2_CAP_ACTUAL) < 1e-6, (
            f"T2_CAP fallback ({T2_CAP}) != policy ({_T2_CAP_ACTUAL}) — update fallback!"
        )

    def __init__(
        self,
        status_path: str | os.PathLike | None = None,
        risk_scores_path: str | os.PathLike | None = None,
        allocation_model: str | None = None,
        strategy_loop_enabled: bool = True,
        comparison_path: str | os.PathLike | None = None,
        strategies_dir: str | os.PathLike | None = None,
        registry_path: str | os.PathLike | None = None,
        # WS1.1-контракт (см. ``_get_live_apy_map``): None → дефолтный фид,
        # mapping → готовая карта, zero-arg callable → карта по вызову,
        # ``False`` → live-подстановка выключена (легаси-путь на литералах).
        # Любое иное значение ⇒ fail-CLOSED пустая карта.
        live_apy_provider: (
            dict[str, float] | Callable[[], dict[str, float]] | bool | None
        ) = None,
        objective: str | float | None = None,
        # ADR-061: source of OBSERVED APY (``adapters[*].live_apy``). None → the
        # project default; tests point it at a fixture or inject an explicit
        # ``live_apy_provider`` (which then acts as the evidence map).
        adapter_status_path: str | os.PathLike | None = None,
    ):
        self.status_path = Path(status_path) if status_path else _STATUS_PATH
        self.risk_scores_path = (
            Path(risk_scores_path) if risk_scores_path else _RISK_SCORES_PATH
        )
        # Model selection: explicit arg > SPA_ALLOCATOR_MODEL env (owner-tunable money-path dial,
        # set in the daily-cycle agent) > DEFAULT_MODEL. Wiring the env here makes the documented
        # mechanism actually functional (it was referenced in the header but never read), so the live
        # cycle can be flipped to optimized_yield without changing the code default that tests rely on.
        self.allocation_model = (
            allocation_model or os.environ.get("SPA_ALLOCATOR_MODEL") or DEFAULT_MODEL
        )
        # WS1.2: OWNER-TUNABLE objective dial for the optimized_yield model —
        # "max_yield" | "balanced" (default) | "min_variance", or a raw float in
        # [0,1] (1=pure yield … 0=max variance penalty). FLAGGED for the owner:
        # the default is the balanced setting. Env override SPA_ALLOCATOR_OBJECTIVE.
        self.objective = (
            objective
            if objective is not None
            else os.environ.get("SPA_ALLOCATOR_OBJECTIVE", models.DEFAULT_OBJECTIVE)
        )
        # MP-REGISTRY: optional registry path; None → use project default.
        self._registry_path = Path(registry_path) if registry_path else _REGISTRY_PATH
        # SPA-V408: shadow→allocator feedback loop.
        self.strategy_loop_enabled = strategy_loop_enabled
        self.comparison_path = (
            Path(comparison_path) if comparison_path else _SHADOW_COMPARISON_PATH
        )
        self.strategies_dir = Path(strategies_dir) if strategies_dir else None
        # WS1.1: injectable live-APY provider → {protocol: live_apy_decimal}.
        # Default = real DeFiLlama feed via the adapter registry. Tests inject a
        # deterministic provider (a dict or a zero-arg callable returning one) so
        # the suite is offline + bit-reproducible. ``False`` disables live lookup
        # entirely (forces the legacy stale-literal path — used to PIN the bug).
        self._live_apy_provider = live_apy_provider
        # WS1.1: per-protocol provenance, populated during _load_adapters and
        # surfaced on AllocationResult. protocol → "live" | "fallback_stale".
        self._apy_sources: dict[str, str] = {}
        self._apy_used: dict[str, float] = {}  # protocol → apy_pct actually ranked on
        self._as_of: dict[str, str] = {}       # protocol → ISO ts of the value used
        # ADR-053 (allocator side): per-protocol TVL provenance. "live" ONLY when
        # the orchestrator record explicitly declares tvl_source=="live" (the
        # adapter fetched TVL from the live feed); everything else — registry
        # merge ($50M literal / fallback_tvl_usd) and snapshot rows without the
        # declaration (committed-constant TVL) — is "static". Fail-closed: an
        # undeclared numeric TVL is never presented as observed.
        self._tvl_sources: dict[str, str] = {}
        # MP-011: TVL magnitude per protocol — the number ``_filter_by_tvl``
        # applies the $5M floor to. Recorded (not decided on) so every reader of
        # "may this pool take fresh capital" answers it from ONE source.
        self._tvl_used: dict[str, float] = {}
        # Pools whose TVL-floor pass rests on a static (unverified) TVL — they
        # are ranked, but the floor is NOT evidence-verified for them.
        self._tvl_floor_unverified: list[str] = []
        # ADR-061: evidence gate state, surfaced on AllocationResult.
        self._adapter_status_path = (
            Path(adapter_status_path) if adapter_status_path else _ADAPTER_STATUS_PATH
        )
        self._evidence_gate_applied: bool = False
        self._blocked: dict[str, str] = {}     # protocol → reason it cannot be funded

    # ── WS1.1: live point-in-time APY lookup ──────────────────────────────
    def _get_live_apy_map(self) -> dict[str, float]:
        """Return {protocol: live_apy_decimal} from the injected/default provider.

        Fail-CLOSED: any error (or a provider that returns a non-mapping) → ``{}``
        (every adapter then ranks on its labeled stale fallback, never a
        fabricated number). ``self._live_apy_provider is False`` → live lookup
        disabled entirely (legacy literal path).
        """
        if self._live_apy_provider is False:
            return {}
        provider = self._live_apy_provider
        try:
            if provider is None:
                raw = _default_live_apy_provider()
            elif callable(provider):
                raw = provider()
            elif isinstance(provider, dict):
                raw = provider
            else:
                return {}
            if not isinstance(raw, dict):
                return {}
            out: dict[str, float] = {}
            for k, v in raw.items():
                # Provider contract: decimal APY. Re-validate fail-CLOSED so a
                # test/real provider can never inject NaN/Inf/out-of-band/<=0.
                if (
                    isinstance(v, (int, float))
                    and not isinstance(v, bool)
                    and math.isfinite(v)
                    and _LIVE_APY_MIN_DECIMAL < float(v) <= _LIVE_APY_MAX_DECIMAL
                ):
                    out[str(k)] = float(v)
            return out
        except Exception as exc:  # noqa: BLE001 — fail-closed, never break allocation
            log.warning("WS1.1 live_apy_provider failed (%s) — stale-literal fallback", exc)
            return {}

    # ── выбор лучшей shadow-стратегии (SPA-V408) ──────────────────────────
    def _select_shadow_strategy(self) -> dict | None:
        """Пытается выбрать лучшую shadow-стратегию через StrategySelector.

        Строго read-only: читает только ``strategy_shadow_comparison.json`` и
        ``data/strategies/{name}.json``. Любая ошибка → ``None`` (аллокатор тогда
        деградирует на сконфигурированную модель). Возвращает dict выбора
        (см. :meth:`StrategySelector.select_best`) или ``None``.
        """
        try:
            kwargs = {"comparison_path": self.comparison_path}
            if self.strategies_dir is not None:
                kwargs["strategies_dir"] = self.strategies_dir
            selector = StrategySelector(**kwargs)
            return selector.select_best()
        except Exception as e:  # никогда не валим аллокацию из-за селектора
            log.warning("StrategySelector failed (%s) — fallback на модель", e)
            return None

    # ── загрузка risk-оценок (SPA-V406) ───────────────────────────────────
    def _load_risk_scores(self) -> tuple[dict[str, str], bool]:
        """Читает ``data/risk_scores.json`` (вывод risk scoring engine).

        Возвращает ``(mapping, loaded)`` где ``mapping`` — ``slug → grade``
        (плюс адаптерные алиасы из :data:`_PROTOCOL_ALIASES`), а ``loaded``
        — успешно ли загружены оценки. Любая ошибка (файл отсутствует, битый
        JSON, неожиданная схема) → ``({}, False)`` без исключения: аллокатор
        тогда деградирует на equal_weight. Модуль остаётся read-only и НЕ
        импортирует код scoring engine — читается только его JSON-снимок.
        """
        if not self.risk_scores_path.exists():
            log.info("risk_scores.json не найден (%s) — risk-модель не применяется",
                     self.risk_scores_path)
            return {}, False
        try:
            raw = json.loads(self.risk_scores_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as e:
            log.warning("risk_scores.json повреждён (%s) — fallback equal_weight: %s",
                        self.risk_scores_path, e)
            return {}, False

        mapping: dict[str, str] = {}
        if isinstance(raw, dict):
            for s in raw.get("scores", []):
                if not isinstance(s, dict):
                    continue
                slug = s.get("slug") or s.get("protocol")
                grade = s.get("grade")
                if slug and grade:
                    mapping[str(slug)] = str(grade).strip().upper()

        if not mapping:
            log.warning("risk_scores.json без валидных оценок — fallback equal_weight")
            return {}, False

        # Адаптерные алиасы: morpho_blue → grade(morpho) и т.п.
        for adapter_name, slug in _PROTOCOL_ALIASES.items():
            if slug in mapping:
                mapping.setdefault(adapter_name, mapping[slug])

        return mapping, True

    # ── загрузка адаптеров ────────────────────────────────────────────────
    def _load_adapters(self) -> list[dict]:
        """Читает снимок оркестратора и возвращает только живые адаптеры.

        Берутся записи со ``status == 'ok'`` (или без поля status). Каждая
        приводится к контракту моделей: protocol / apy_pct / tvl_usd / tier.

        MP-REGISTRY: после загрузки оркестраторного снимка дополнительно
        мёрджит активные адаптеры из ``data/adapter_registry.json``, которых
        нет в снимке. Используется ``fallback_apy`` (decimal → pct × 100) и
        консервативный TVL по умолчанию ($50M). Это устраняет 0%-аллокацию
        адаптеров (morpho_steakhouse, aave_arbitrum, spark_susds и т.д.),
        которые зарегистрированы, но ещё не охвачены оркестратором.
        """
        adapters: list[dict] = []
        seen_protocols: set[str] = set()

        # WS1.1: reset per-call provenance, then fetch the live point-in-time APY
        # map ONCE (decimal per protocol). live[name] WINS over the stale literal.
        self._apy_sources = {}
        self._apy_used = {}
        self._as_of = {}
        self._tvl_sources = {}
        self._tvl_used = {}
        self._tvl_floor_unverified = []
        self._blocked = {}
        live_apy = self._get_live_apy_map()
        now_iso = datetime.now(timezone.utc).isoformat()

        # ── ADR-061: build the EVIDENCE map (observed APY only) ─────────────
        # Contract: an explicitly injected ``live_apy_provider`` IS the evidence
        # map (tests stay offline + deterministic and keep full control). With
        # the default (None) provider evidence is read from the two files that
        # carry an explicit observation flag. Under pytest the default performs
        # no file read for the same reason the live provider performs no network
        # I/O — a test must never rank on the live repo's data/.
        evidence: dict[str, float] = {}
        evidence_src: dict[str, str] = {}
        if self._live_apy_provider is None:
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                for _p, (_v, _s) in _load_evidenced_apy(
                    self.status_path, self._adapter_status_path
                ).items():
                    evidence[_p], evidence_src[_p] = _v, _s
        else:
            for _p, _v in live_apy.items():
                evidence[_p], evidence_src[_p] = _v, "injected"

        # ── TVL evidence (same discipline, stricter consequence) ────────────
        # A wrong APY literal mis-ranks; a wrong TVL literal lets a pool pass a
        # gate it should fail. Guarded by the same PYTEST guard as the APY map:
        # a test must never read the live repo's data/.
        tvl_evidence: dict[str, tuple[float, str]] = {}
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            tvl_evidence = _load_evidenced_tvl(self._adapter_status_path)
        # Fail-safe: too little evidence means the SOURCE is broken, not that the
        # world is unfundable. Ranking then keeps the legacy universe (loudly
        # noted) instead of collapsing the book to all-cash on an unreadable file.
        # ADR-169: порог — БОЛЬШЕЕ из абсолютного (3) и половины перечисленных.
        # В режиме инъекции провайдер САМ является доказательством: производителя,
        # который мог бы сломаться, там нет, поэтому знаменатель — то, что он дал.
        if self._live_apy_provider is not None:
            attempts = len(live_apy)
        elif os.environ.get("PYTEST_CURRENT_TEST"):
            # Тот же заслон, что стоит на загрузке доказательств двумя блоками
            # выше, и по той же причине: тест не читает живой  репозитория.
            # Без него знаменатель брался с ХОСТА, и вердикт теста начинал
            # зависеть от того, сколько адаптеров лежит в дереве разработчика —
            # на CI и на Маке это разные числа. Числитель под pytest пуст по
            # построению, поэтому знаменатель здесь не «ноль адаптеров», а
            # НЕ ИЗМЕРЕН: правило доли молчит, остаётся абсолютный порог.
            attempts = 0
        else:
            attempts = _observation_attempts(
                self.status_path, self._adapter_status_path
            )
        required = _required_coverage(attempts)
        self._evidence_coverage = {
            "evidenced": len(evidence),
            "attempted": attempts,
            "required": required,
            "gate_applied": len(evidence) >= required,
        }
        self._evidence_gate_applied = len(evidence) >= required
        if not self._evidence_gate_applied:
            log.warning(
                "ADR-061/169: only %d evidenced APYs of %d attempted (< %d required) "
                "— evidence gate NOT applied, ranking on the legacy universe. "
                "Покрытие обвалилось: это симптом поломки производителя, а не "
                "сигнал уходить из здоровых протоколов",
                len(evidence), attempts, required,
            )

        def _fundable(protocol: str) -> bool:
            """ADR-061 gate: class flags (D3/D4) + evidence (D1/D2). Fail-CLOSED."""
            allowed, reason = _adapter_class_gate(protocol)
            if not allowed:
                self._blocked[protocol] = reason or "blocked"
                return False
            if self._evidence_gate_applied and protocol not in evidence:
                # Rule (.claude/rules/risk-engine.md): a stale/unobserved feed
                # means the protocol is NOT taken into a fresh allocation.
                self._blocked[protocol] = "unevidenced"
                return False
            return True

        if self.status_path.exists():
            with open(self.status_path, encoding="utf-8") as fh:
                raw = json.load(fh)
            for a in raw.get("adapters", []):
                status = a.get("status", "ok")
                if status not in ("ok", "partial"):
                    continue
                protocol = str(a["protocol"])
                seen_protocols.add(protocol)
                # ADR-061 (D3/D4 + evidence): an advisory / not-eligible /
                # unobserved protocol is never funded — from EITHER load path.
                if not _fundable(protocol):
                    continue
                # Orchestrator-snapshot adapters already came from the live
                # get_yield_info() feed → their apy_pct is live by construction.
                # ADR-061: rank on the EVIDENCED value when we have one (it is
                # the observation that won the freshness tie-break), else on the
                # snapshot value. The pre-ADR-061 path preferred ``live_apy``,
                # which for 12 adapters is a hardcoded literal (D1).
                snap_apy = float(a.get("apy_pct", 0.0))
                if protocol in evidence:
                    apy_pct = round(evidence[protocol] * 100.0, 4)
                elif protocol in live_apy:
                    apy_pct = round(live_apy[protocol] * 100.0, 4)
                else:
                    apy_pct = snap_apy
                # ADR-053 (allocator side): TVL provenance. "live" only when the
                # orchestrator record DECLARES it (adapter fetched TVL from the
                # feed). A numeric TVL without the declaration is a committed
                # constant → "static" — it may rank, but must never be presented
                # as verifying the $5M floor (see _filter_by_tvl).
                tvl_source = "live" if a.get("tvl_source") == "live" else "static"
                tvl_usd = float(a.get("tvl_usd", 0.0))
                # A pinned observation outranks the orchestrator's literal: the
                # orchestrator reports whatever the adapter handed it, and 11
                # adapters hand over a hardcoded TVL_USD constant.
                #
                # ADR-126 (owner decision 2026-08-23, option 1): the observation
                # must REPLACE the number, not just the label. Until this line
                # the branch bound the measured value to a local that nothing
                # read, so the row went out stamped ``tvl_source="live"`` while
                # carrying the very literal the observation was fetched to
                # replace — the one thing `.claude/rules/risk-engine.md` forbids
                # by name ("Never stamp `live` on a constant"). The registry
                # merge below always did this correctly; only this path did not.
                if tvl_source != "live" and protocol in tvl_evidence:
                    tvl_usd, _pool = tvl_evidence[protocol]
                    tvl_usd = float(tvl_usd)
                    tvl_source = "live"
                    log.info(
                        "ADR-053: %s TVL from pinned observation $%.0fM (pool %s) — "
                        "replaces the adapter literal",
                        protocol, tvl_usd / 1_000_000, _pool[:8],
                    )
                _row = {
                    "protocol": protocol,
                    "apy_pct": apy_pct,
                    "tvl_usd": tvl_usd,
                    "tier": a.get("tier", "T2"),
                    "apy_source": "live",
                    "tvl_source": tvl_source,
                    "as_of": a.get("last_updated", now_iso),
                }
                # WS1.2: pass through an explicit per-pool APY volatility if the
                # feed carries one — the optimizer's variance dial reads it (else
                # it derives a grade proxy). Optional; absent on most snapshots.
                for _vk in ("apy_vol", "volatility", "vol"):
                    if _vk in a and a[_vk] is not None:
                        _row[_vk] = a[_vk]
                        break
                adapters.append(_row)
                self._apy_sources[protocol] = "live"
                self._apy_used[protocol] = apy_pct
                self._as_of[protocol] = a.get("last_updated", now_iso)
                self._tvl_sources[protocol] = tvl_source
                self._tvl_used[protocol] = _row["tvl_usd"]

        # MP-REGISTRY: merge active adapters from adapter_registry.json that are
        # absent from the orchestrator snapshot.
        #
        # WS1.1 MONEY-PATH FIX: when a LIVE DeFiLlama reading exists for this
        # adapter, it WINS over the hardcoded ``fallback_apy`` literal (the desk
        # ranks on live APY, e.g. aave 6.9% live, not the 3.5% stale literal).
        # The literal becomes a LABELED, staleness-stamped LAST RESORT only —
        # used (and flagged ``apy_source="fallback_stale"``) solely when the live
        # feed has no usable value for that adapter. A live reading is never
        # fabricated and a stale literal is never silently presented as live.
        if self._registry_path.exists():
            try:
                reg = json.loads(self._registry_path.read_text(encoding="utf-8"))
                for name, entry in reg.get("adapters", {}).items():
                    if name in seen_protocols:
                        continue  # already handled (orchestrator snapshot, live)
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("research_only"):
                        continue
                    if entry.get("status") not in ("active",):
                        continue
                    # ADR-061 (D3): the live path already excluded advisory
                    # adapters — THIS path did not, which is how two advisory
                    # pools came to hold 15 % of the book. Same gate, both paths.
                    if not _fundable(name):
                        continue
                    # Registry stores tier as integer (1/2/3); treat tier≥3 as T2.
                    tier_int = entry.get("tier", 2)
                    tier_str = "T1" if tier_int == 1 else "T2"
                    tvl = float(entry.get("fallback_tvl_usd", _REGISTRY_FALLBACK_TVL_USD))

                    if name in evidence:
                        # ADR-061: an OBSERVED reading — the only thing that may
                        # rank a protocol for funding.
                        apy_pct = round(evidence[name] * 100.0, 4)
                        apy_source = "live"
                        as_of = now_iso
                    elif name in live_apy and not self._evidence_gate_applied:
                        # Legacy path, reachable only while the evidence source
                        # is unusable (see _EVIDENCE_MIN_COVERAGE).
                        apy_pct = round(live_apy[name] * 100.0, 4)
                        apy_source = "live"
                        as_of = now_iso
                    else:
                        # Fail-CLOSED: no usable live value → labeled stale literal.
                        fallback_apy = entry.get("fallback_apy")
                        if not isinstance(fallback_apy, (int, float)) or isinstance(
                            fallback_apy, bool
                        ) or not math.isfinite(fallback_apy) or fallback_apy <= 0:
                            # No live AND no usable literal → exclude entirely
                            # (never a fabricated number).
                            continue
                        apy_pct = round(float(fallback_apy) * 100.0, 4)
                        apy_source = "fallback_stale"
                        as_of = entry.get("updated") or reg.get("updated") or "unknown"

                    # ADR-053 (allocator side): registry TVL is a literal
                    # (fallback_tvl_usd or the $50M default) — never an
                    # observation. It is upgraded to "live" ONLY by a pinned
                    # pool-UUID reading, which is reproducible by re-fetching it.
                    reg_tvl_source = "static"
                    if name in tvl_evidence:
                        tvl, _pool = tvl_evidence[name]
                        reg_tvl_source = "live"
                        log.info(
                            "ADR-053: %s TVL from pinned observation $%.0fM (pool %s) — "
                            "replaces the registry literal",
                            name, tvl / 1_000_000, _pool[:8],
                        )

                    adapters.append(
                        {
                            "protocol": name,
                            "apy_pct": apy_pct,
                            "tvl_usd": tvl,
                            "tier": tier_str,
                            "apy_source": apy_source,
                            "tvl_source": reg_tvl_source,
                            "as_of": as_of,
                        }
                    )
                    self._apy_sources[name] = apy_source
                    self._apy_used[name] = apy_pct
                    self._as_of[name] = as_of
                    self._tvl_sources[name] = reg_tvl_source
                    self._tvl_used[name] = tvl
                    log.info(
                        "WS1.1: adapter %s apy=%.2f%% source=%s tier=%s tvl=$%.0fM",
                        name, apy_pct, apy_source, tier_str, tvl / 1_000_000,
                    )
            except Exception as _reg_exc:
                log.warning("MP-REGISTRY: registry merge failed (%s) — using orchestrator only", _reg_exc)

        return adapters

    # ── WS1.1: feed coverage metric ───────────────────────────────────────
    def _build_feed_coverage(self) -> dict:
        """Summarise live-vs-fallback APY provenance across loaded adapters.

        Reads the per-protocol ``self._apy_sources`` populated by
        ``_load_adapters``. Returns a dict a reviewer can audit at a glance:
        live/fallback counts, the lists, and a ``ranked_on`` provenance map.
        """
        live = sorted(p for p, s in self._apy_sources.items() if s == "live")
        stale = sorted(p for p, s in self._apy_sources.items() if s == "fallback_stale")
        total = len(self._apy_sources)
        return {
            "total": total,
            "live": len(live),
            "fallback_stale": len(stale),
            "live_pct": round(100.0 * len(live) / total, 1) if total else 0.0,
            "live_adapters": live,
            "fallback_stale_adapters": stale,
            "apy_sources": dict(self._apy_sources),
            "apy_used_pct": {p: round(v, 4) for p, v in self._apy_used.items()},
            "as_of": dict(self._as_of),
            # ADR-053 (allocator side): TVL provenance — "live" only when the
            # orchestrator record declared its TVL as feed-observed; registry
            # literals and undeclared snapshot TVLs are "static".
            # ``tvl_floor_unverified`` — pools whose $5M-floor pass rests on a
            # static TVL (ranked, but the floor is NOT evidence-verified).
            "tvl_sources": dict(self._tvl_sources),
            "tvl_live": sum(1 for s in self._tvl_sources.values() if s == "live"),
            "tvl_static": sum(1 for s in self._tvl_sources.values() if s == "static"),
            "tvl_static_adapters": sorted(
                p for p, s in self._tvl_sources.items() if s == "static"
            ),
            "tvl_floor_unverified": list(self._tvl_floor_unverified),
            # MP-011 (карточка 07.08): РАЗМЕР TVL, ровно тот, на котором сам
            # аллокатор применяет порог $5M (``_filter_by_tvl``). Провенанс
            # отвечает «наблюдали ли», порог — «сколько»; атрибуция кэша знала
            # только первое и записывала пул ниже порога в «пригодную комнату».
            # Только запись отчёта: ни одно решение аллокатора это поле не читает.
            "tvl_usd": dict(self._tvl_used),
            # ADR-061: was funding restricted to OBSERVED APYs this run, and who
            # was blocked (advisory / not_eligible / unevidenced) and why.
            "evidence_gate_applied": self._evidence_gate_applied,
            # ADR-169: ПОЧЕМУ гейт применён или нет — числами, а не одним флагом.
            # Флаг отвечает «применён ли», но не отличает «мир затих» от «наш
            # производитель сломался»; отличают это наблюдено/перечислено.
            # Поле пишется в артефакт намеренно: ADR-169 обещает, что состояние
            # покрытия доходит до дневного отчёта, а атрибут в памяти объекта
            # туда дойти не может.
            "evidence_coverage": dict(getattr(self, "_evidence_coverage", {}) or {}),
            "blocked": dict(self._blocked),
        }

    # ── кап'ы по тирам (water-filling) ────────────────────────────────────
    def _cap_for(self, tier: str) -> float:
        return self.T1_CAP if str(tier).upper() == "T1" else self.T2_CAP

    def _apply_caps(
        self, weights: dict[str, float], tier_map: dict[str, str]
    ) -> tuple[dict[str, float], bool]:
        """Итеративно ограничивает веса cap'ами тира с перераспределением.

        Возвращает ``(capped_weights, was_capped)``. Сумма результата ≤ 1.0:
        если все протоколы упёрлись в свои cap'ы, остаток остаётся
        нераспределённым (кэш-буфер), а не нарушает лимиты.
        """
        caps = {p: self._cap_for(tier_map.get(p, "T2")) for p in weights}
        w = dict(weights)
        was_capped = False

        for _ in range(100):
            over = [p for p in w if w[p] > caps[p] + _EPS]
            if not over:
                break
            was_capped = True
            excess = 0.0
            for p in over:
                excess += w[p] - caps[p]
                w[p] = caps[p]
            uncapped = [p for p in w if w[p] < caps[p] - _EPS]
            if not uncapped:
                # некуда раскидывать — остаток уходит в кэш
                break
            base = sum(w[p] for p in uncapped)
            if base <= _EPS:
                share = excess / len(uncapped)
                for p in uncapped:
                    w[p] = min(w[p] + share, caps[p])
            else:
                for p in uncapped:
                    w[p] = min(w[p] + excess * (w[p] / base), caps[p])
        return w, was_capped

    # ── MP-011: TVL-floor фильтр ──────────────────────────────────────────
    def _filter_by_tvl(
        self, adapters: list[dict]
    ) -> tuple[list[dict], list[str]]:
        """Исключает адаптеры с TVL ниже :data:`TVL_FLOOR_USD`.

        RiskPolicy (``min_tvl_usd``) отклоняет любую позицию в пуле с TVL
        < $5M, поэтому такие адаптеры нельзя даже рассматривать при расчёте
        весов. Возвращает ``(прошедшие, имена отклонённых)``.

        ADR-053 (allocator side): пул со СТАТИЧЕСКИМ TVL (``tvl_source !=
        "live"`` — реестровый литерал/$50M-дефолт или снимок без live-декларации)
        технически проходит числовой floor, но это НЕ верификация — литерал не
        является наблюдением ликвидности. Такие проходы собираются в
        ``self._tvl_floor_unverified`` (→ feed_coverage) и логируются WARNING.
        Пул при этом ОСТАЁТСЯ в ранжировании: исключение static-TVL пулов
        обнулило бы цели 4/5 текущих held-позиций (registry-merge путь) →
        принудительная распродажа книги — это owner-решение (карточка в
        трекере), а enforcement-точка — RiskPolicy-гейт (ADR-053 freeze).
        """
        ok: list[dict] = []
        rejected: list[str] = []
        static_passed: list[str] = []
        for a in adapters:
            raw_tvl = a.get("tvl_usd")
            if raw_tvl is None:
                raw_tvl = a.get("tvl")
            try:
                tvl = float(raw_tvl) if raw_tvl is not None else 0.0
            except (TypeError, ValueError):
                tvl = float("nan")
            # FAIL-CLOSED (property-test PROP-TVL-NONFINITE): a non-finite TVL
            # (NaN/Inf from a malformed feed) cannot be verified against the
            # floor — `inf >= floor` would wrongly PASS the pool and then the
            # MP-209 capacity cap divides by that TVL → a NaN target weight
            # flows straight into target_usd / the rebalancer (a money-path
            # corruption). Reject any non-finite TVL exactly like the RiskPolicy
            # finiteness gate. Behaviour is unchanged for every finite TVL.
            if math.isfinite(tvl) and tvl >= self.TVL_FLOOR_USD:
                ok.append(a)
                if a.get("tvl_source") != "live":
                    static_passed.append(str(a.get("protocol", "?")))
            else:
                rejected.append(a.get("protocol", "?"))
        self._tvl_floor_unverified = sorted(static_passed)
        if static_passed:
            log.warning(
                "ADR-053: TVL-floor pass on STATIC (unverified) TVL for %s — "
                "литерал не верифицирует floor; ранжирование сохранено, "
                "enforcement — RiskPolicy-гейт",
                self._tvl_floor_unverified,
            )
        if rejected:
            log.warning(
                "MP-011: TVL-floor ($%s) отфильтровал адаптеры: %s",
                f"{self.TVL_FLOOR_USD:,.0f}", rejected,
            )
        if not ok and adapters:
            # Fallback: все адаптеры ниже floor — не возвращаем пустую вселенную
            # (иначе аллокатор молча уйдёт в 100% кэш). RiskPolicy-гейт всё равно
            # отклонит такие позиции — но это будет видно в risk_policy_blocks.json.
            # FAIL-CLOSED (property-test PROP-TVL-NONFINITE): даже в fallback'е
            # НЕ возвращаем адаптеры с non-finite TVL — иначе MP-209 capacity-cap
            # делит на inf/NaN и пишет NaN-вес в target_usd. Финитные-но-низкие
            # TVL остаются (gate их заблокирует, видно в risk_policy_blocks).
            def _finite_tvl(a: dict) -> bool:
                raw = a.get("tvl_usd")
                if raw is None:
                    raw = a.get("tvl")
                try:
                    return math.isfinite(float(raw)) if raw is not None else True
                except (TypeError, ValueError):
                    return False

            finite_fallback = [a for a in adapters if _finite_tvl(a)]
            log.warning(
                "MP-011: ВСЕ адаптеры ниже TVL-floor — fallback на исходный список"
            )
            return finite_fallback, rejected
        return ok, rejected

    # ── MP-011: совокупный T2-кап ─────────────────────────────────────────
    def _enforce_t2_total_cap(
        self, weights: dict[str, float], tier_map: dict[str, str]
    ) -> tuple[dict[str, float], bool]:
        """Ограничивает суммарный вес T2 значением :data:`T2_TOTAL_CAP`.

        Если совокупный T2 > 50% (ADR-019) — T2-веса срезаются пропорционально, а
        освобождённый вес перераспределяется в headroom T1-адаптеров
        (не превышая :data:`T1_CAP` на протокол). Если T1-ёмкости не хватает,
        остаток честно остаётся кэшем. Возвращает ``(weights, enforced)``.
        """

        def _is_t2(p: str) -> bool:
            return str(tier_map.get(p, "T2")).upper() != "T1"

        t2_total = sum(wt for p, wt in weights.items() if _is_t2(p))
        if t2_total <= self.T2_TOTAL_CAP + _EPS:
            return dict(weights), False

        scale = self.T2_TOTAL_CAP / t2_total
        w = dict(weights)
        freed = 0.0
        for p, wt in w.items():
            if _is_t2(p):
                new_wt = wt * scale
                freed += wt - new_wt
                w[p] = new_wt

        # Water-fill освобождённого веса в T1 с учётом per-protocol cap.
        t1 = [p for p in w if not _is_t2(p)]
        for _ in range(100):
            if freed <= _EPS:
                break
            room = {p: self.T1_CAP - w[p] for p in t1 if self.T1_CAP - w[p] > _EPS}
            if not room:
                break  # T1 упёрся в cap'ы — остаток уходит в кэш
            base = sum(w[p] for p in room)
            if base <= _EPS:
                share = freed / len(room)
                added = sum(
                    min(share, room[p]) for p in room
                )
                for p in room:
                    w[p] += min(share, room[p])
            else:
                added = 0.0
                for p, headroom in room.items():
                    add = min(freed * (w[p] / base), headroom)
                    w[p] += add
                    added += add
            freed = max(0.0, freed - added)

        log.info(
            "MP-011: T2-total cap применён: %.1f%% → %.1f%%",
            t2_total * 100, self.T2_TOTAL_CAP * 100,
        )
        return w, True

    def _enforce_t3_total_cap(
        self, weights: dict[str, float]
    ) -> tuple[dict[str, float], bool]:
        """Cap total T3 exposure at :data:`T3_TOTAL_CAP` (ADR-020, 15%).

        T3 = the highest-risk tier (sUSDe, extra_finance_base, …). Classified via the CANONICAL
        ``tier_map.tier_of`` — NOT the allocator's collapsed "T1"/"T2" tier strings, which never
        emitted "T3" and so let the optimizer's T3 exposure go unenforced. If Σ T3 > 15%, T3 weights
        are scaled down proportionally; the freed weight honestly stays cash (it is NOT water-filled
        into a riskier tier). Idempotent, fail-safe (a tier lookup that fails treats the pool as
        non-T3 → never forces a trim it can't justify). Returns ``(weights, enforced)``.
        """
        try:
            from spa_core.adapters.tier_map import tier_of
        except Exception:  # noqa: BLE001 — no resolver → nothing to enforce (fail-open, logged upstream)
            return dict(weights), False

        def _is_t3(p: str) -> bool:
            try:
                return str(tier_of(p) or "").upper() == "T3"
            except Exception:  # noqa: BLE001
                return False

        t3_total = sum(wt for p, wt in weights.items() if _is_t3(p))
        if t3_total <= self.T3_TOTAL_CAP + _EPS:
            return dict(weights), False

        scale = self.T3_TOTAL_CAP / t3_total
        w = dict(weights)
        for p, wt in list(w.items()):
            if _is_t3(p):
                w[p] = wt * scale
        log.warning(
            "ADR-020: T3-total cap applied: %.1f%% → %.1f%% (freed weight → cash)",
            t3_total * 100, self.T3_TOTAL_CAP * 100,
        )
        return w, True

    def _select_best_n(
        self,
        weights: dict[str, float],
        apy_map: dict[str, float] | None = None,
        tier_map: dict[str, str] | None = None,
    ) -> tuple[dict[str, float], set[str], list[str]]:
        """Оставить ЛУЧШИЕ ``MAX_PROTOCOLS`` и отсечь худших (ADR-138).

        **Что было.** Аллокатор раздавал деньги по ВСЕМ проходным протоколам, а
        готовую раскладку уже потом ловило правило «не больше 8 позиций»
        (ALLOC-002) — и вместо того, чтобы отсечь худших, система выбрасывала
        раскладку целиком и брала аварийную книгу, которая к тому же идёт мимо
        проверок свежести. Замер на модели по умолчанию (``risk_adjusted``):
        12 кандидатов → 12 профинансировано, 27 → 27, гейт отвергал обе
        (`max_protocols`). Порог ``max_protocols`` до сих пор доходил ТОЛЬКО до
        ``optimized_yield``; остальные модели о нём не знали.

        Поэтому «больше кандидатов» буквально означало «хуже книга»: сегодня
        проходных ровно 8, и первый же девятый протокол, подтвердивший доходность
        и размер пула, ронял книгу в фолбэк.

        **Порядок важен.** Отбор идёт СТРОГО ПОСЛЕ проверок доказанности
        доходности и живого размера пула — условие владельца дословно. Замер
        08.08 показал цену обратного порядка: отбор ДО проверок дал кэш 15.8 % и
        доходность 4.73 против 10 % / 6.03.

        **Чем судим.** Предпочтением самой модели: вес, который она назначила
        (по убыванию), затем APY, затем имя — детерминированно и без нового
        объектива. Своя мера ранжирования была бы порогом политики с чёрного
        хода: у моделей уже есть своя, и ADR на другую никто не писал. Для
        ``equal_weight`` веса равны, и решает APY — то есть «лучшие 8» там
        буквально «восемь самых доходных».

        Отсечённые НАЗЫВАЮТСЯ (инв. #17). Их вес не перекладывается вручную —
        он возвращается в бюджет, и дальше по конвейеру ``_fill_remainder``
        разливает его по ОСТАВШИМСЯ в пределах их cap'ов.

        Идемпотентно. Возвращает ``(weights, dropped, notes)``.
        """
        limit = int(self.MAX_PROTOCOLS)
        funded = {p: w for p, w in weights.items() if w > _EPS}
        if limit <= 0 or len(funded) <= limit:
            return dict(weights), set(), []

        apy_map = apy_map or {}
        ranked = sorted(
            funded.items(),
            key=lambda kv: (-kv[1], -float(apy_map.get(kv[0], 0.0) or 0.0), kv[0]),
        )
        keep = {p for p, _ in ranked[:limit]}
        dropped = [p for p, _ in ranked[limit:]]

        # УДАЛЯЕМ из расчёта, а не обнуляем. Обнулённый протокол остаётся в
        # словаре, и следующие шаги честно считают его «есть ёмкость, вес ноль»:
        # `_apply_caps` разливает на него излишек, `_fill_remainder` — остаток.
        # Замер с обнулением: 12 кандидатов → 11 профинансировано, предел 8 —
        # то есть отсечение не срабатывало вовсе.
        out = dict(weights)
        freed = 0.0
        for p in dropped:
            freed += out.pop(p, 0.0)

        note = (
            f"ALLOC-002 (ADR-138): проходных {len(funded)} при пределе {limit} — "
            f"отсечены худшие {len(dropped)} ({', '.join(dropped)}), "
            f"освобождено {freed * 100:.2f}% в бюджет оставшихся. "
            "Раньше такая книга целиком уходила в аварийный фолбэк."
        )
        log.warning("%s", note)
        return out, set(dropped), [note]

    def _enforce_chain_caps(
        self, weights: dict[str, float]
    ) -> tuple[dict[str, float], list[str]]:
        """Срезать раскладку до СЕТЕВЫХ потолков политики (ADR-136).

        Три потолка, все из ``RiskConfig``, ни одного нового числа:
        одна сеть ≤ :data:`SINGLE_CHAIN_CAP`, все L2 вместе ≤ :data:`L2_TOTAL_CAP`,
        Base ≤ :data:`BASE_CHAIN_CAP` (ADR-025).

        Сеть резолвится ТЕМ ЖЕ ``_resolve_chain_map``, которым её резолвит гейт —
        импортом, а не копией: копия разъехалась бы с гейтом ровно так же, как
        разъезжались пороги.

        **Неразрешённая сеть — ХУДШИЙ случай, а не «прочее».** Условие владельца
        к варианту A звучит «протокол, у которого сеть не определяется, — не
        берётся в раскладку (отказ, а не догадка)», и у подборщика исполнено
        буквально. Здесь — ступень, чья раскладка ИДЁТ В ЦИКЛ, и обнулять на ней
        реальный протокол из-за пробела в реестре значит воспроизводить ровно ту
        аварию, которую ADR-136 и чинит: цикл без сделок. Поэтому неразрешённые
        считаются **одной и той же неизвестной сетью** — самое концентрированное
        из возможных предположений. Недосчитать потолок это не может (оценка
        только строже правды), капитал при этом не простаивает, а имена
        называются в ``notes``. Отличие от буквы решения владельца названо в
        ADR-136 §3 — если он предпочтёт жёсткий отказ и здесь, это одна строка.

        Излишек НИКОГДА не перекладывается в другой протокол: он честно остаётся
        кэшем (тот же принцип, что у :meth:`_enforce_t3_total_cap`).
        Идемпотентно. Возвращает ``(weights, notes)``; ``notes`` называют каждый
        срез — молчаливый простой капитала запрещён (ADR-055).
        """
        w = dict(weights)
        notes: list[str] = []
        funded = [p for p, val in w.items() if val > _EPS]
        if not funded:
            return w, notes

        try:
            from spa_core.risk.policy_enforcer import _resolve_chain_map
            chain_map, unresolved = _resolve_chain_map(funded)
        except Exception as exc:  # noqa: BLE001
            # Карту построить не удалось ⇒ сеть НЕ ИЗМЕРЕНА ни у одного
            # протокола. Тихо пропустить проверку значило бы выдать «потолки
            # соблюдены» вместо «не проверено» (инв. #17), поэтому все идут в
            # ту же корзину худшего случая — то есть книга целиком судится как
            # одна сеть и режется до 90 %.
            log.warning("ADR-136: карта сетей не построена (%s) — fail-CLOSED", exc)
            chain_map, unresolved = {}, list(funded)

        # Худший случай: все неопознанные — одна и та же сеть. Оценка может быть
        # только СТРОЖЕ правды, поэтому потолок недосчитан быть не может.
        _UNKNOWN = "<неизвестная сеть>"
        if unresolved:
            for p in unresolved:
                chain_map[p] = _UNKNOWN
            notes.append(
                "сеть не определена у " + ", ".join(sorted(unresolved))
                + f" — считаются ОДНОЙ сетью «{_UNKNOWN}» (худший случай, "
                "потолок недосчитан быть не может)"
            )

        def _scale(members: list[str], cap: float, label: str) -> None:
            total = sum(w.get(p, 0.0) for p in members)
            if total <= cap + _EPS or total <= _EPS:
                return
            scale = cap / total
            for p in members:
                w[p] = w[p] * scale
            notes.append(
                f"{label}: {total * 100:.2f}% → {cap * 100:.2f}% (излишек честно остался кэшем)"
            )

        chains = sorted({chain_map.get(p, "") for p in funded if chain_map.get(p)})
        for ch in chains:
            _scale([p for p in funded if chain_map.get(p) == ch],
                   self.SINGLE_CHAIN_CAP, f"сеть {ch}")
        _scale([p for p in funded if chain_map.get(p) in self.L2_CHAINS],
               self.L2_TOTAL_CAP, "L2 суммарно")
        _scale([p for p in funded if chain_map.get(p) == "base"],
               self.BASE_CHAIN_CAP, "сеть base")

        if notes:
            log.warning("ADR-136: сетевые потолки применены: %s", "; ".join(notes))
        return w, notes

    # ── заполнение остатка T1-якорем (SPA-V405) ───────────────────────────
    def _fill_remainder(
        self,
        weights: dict[str, float],
        tier_map: dict[str, str],
        apy_map: dict[str, float],
        exclude: set[str] | None = None,
    ) -> tuple[dict[str, float], bool]:
        """Заполняет нераспределённый остаток в headroom доступных адаптеров.

        Структурный 20% cash-drag возникает, когда 4 T2-адаптера (cap 20% каждый)
        могут разместить максимум 80%, а T1-якоря нет. Этот шаг направляет
        остаток капитала в свободную ёмкость (cap − текущий вес) — СНАЧАЛА в
        T1-адаптеры (cap 40%, приоритет якоря), ПОТОМ в T2 — в порядке убывания
        APY. Веса никогда не превышают cap'ы тира.

        ``exclude`` — протоколы, исключённые риск-моделью (grade D): им НЕЛЬЗЯ
        возвращать капитал через headroom-fill, иначе D-исключение нарушится.

        Если ни у одного адаптера нет headroom (всё уперлось в cap'ы) — остаток
        честно остаётся кэшем. Возвращает ``(weights, filled)``.
        """
        excluded = exclude or set()
        w = dict(weights)
        # Полная вселенная адаптеров — включая те, которым модель дала 0
        # (например best_apy выбирает только top-N). Их headroom тоже доступен,
        # КРОМЕ исключённых риском (grade D) — они остаются с весом 0.
        universe = [p for p in tier_map.keys() if p not in excluded]
        caps = {p: self._cap_for(tier_map.get(p, "T2")) for p in universe}

        remainder = max(0.0, 1.0 - sum(w.values()))
        if remainder <= 1e-9:
            return w, False

        filled = False
        # T1 (якорь) первым, затем T2; внутри тира — по убыванию APY.
        for tier_filter in ("T1", "T2"):
            if remainder <= 1e-9:
                break
            candidates = sorted(
                (
                    p
                    for p in universe
                    if str(tier_map.get(p, "T2")).upper() == tier_filter
                ),
                key=lambda p: apy_map.get(p, 0.0),
                reverse=True,
            )
            for p in candidates:
                if remainder <= 1e-9:
                    break
                headroom = caps[p] - w.get(p, 0.0)
                if headroom <= 1e-9:
                    continue
                add = min(headroom, remainder)
                w[p] = w.get(p, 0.0) + add
                remainder -= add
                filled = True
        return w, filled

    # ── основной расчёт ───────────────────────────────────────────────────
    def allocate(self, model: str | None = None) -> AllocationResult:
        model = model or self.allocation_model
        is_risk_model = model in _RISK_MODEL_ALIASES
        is_optimizer = model in _OPTIMIZER_MODEL_ALIASES
        if not is_risk_model and not is_optimizer and model not in _MODEL_DISPATCH:
            raise AllocationError(
                f"Неизвестная модель аллокации: {model!r}. "
                f"Доступны: "
                f"{sorted(set(_MODEL_DISPATCH) | _RISK_MODEL_ALIASES | _OPTIMIZER_MODEL_ALIASES)}",
                code="UNKNOWN_ALLOCATION_MODEL",
            )

        adapters = self._load_adapters()
        ts = datetime.now(timezone.utc).isoformat()
        notes: list[str] = []

        # MP-011: TVL-floor ДО расчёта весов — пулы ниже $5M RiskPolicy всё
        # равно отклонит, поэтому им нельзя получить вес вообще.
        adapters, tvl_rejected = self._filter_by_tvl(adapters)
        survivors = {a["protocol"] for a in adapters}
        tvl_filtered = [p for p in tvl_rejected if p not in survivors]
        if tvl_filtered:
            notes.append(
                f"MP-011: TVL-floor ${self.TVL_FLOOR_USD:,.0f} исключил: "
                + str(sorted(tvl_filtered))
            )
        elif tvl_rejected:
            notes.append(
                "MP-011 WARNING: все адаптеры ниже TVL-floor — fallback на "
                "исходный список (RiskPolicy-гейт заблокирует такие позиции)."
            )

        if not adapters:
            notes.append("Нет активных адаптеров — пустое распределение.")
            return AllocationResult(
                target_weights={},
                target_usd={},
                expected_apy_pct=0.0,
                model_used=model,
                timestamp=ts,
                capital_usd=float(self.CAPITAL),
                allocated_pct=0.0,
                unallocated_pct=1.0,
                unallocated_usd=float(self.CAPITAL),
                cash_pct=1.0,
                t1_pct=0.0,
                t2_pct=0.0,
                total_deployed_pct=0.0,
                risk_model_applied=False,
                risk_breakdown={},
                strategy_loop_active=False,
                selected_strategy_id=None,
                strategy_confidence=None,
                tvl_filtered_protocols=tvl_filtered,
                t2_cap_enforced=False,
                apy_sources=dict(self._apy_sources),
                apy_used=dict(self._apy_used),
                feed_coverage=self._build_feed_coverage(),
                evidence_gate_applied=self._evidence_gate_applied,
                blocked_protocols=dict(self._blocked),
                notes=notes,
            )

        tier_map = {a["protocol"]: a["tier"] for a in adapters}
        apy_map = {a["protocol"]: a["apy_pct"] for a in adapters}
        # WS1.1: coverage note so the live-vs-stale split is visible in cycle logs.
        _cov = self._build_feed_coverage()
        notes.append(
            "WS1.1 feed_coverage: {live}/{total} adapters on LIVE APY, "
            "{stale} on labeled stale fallback.".format(
                live=_cov["live"], total=_cov["total"], stale=_cov["fallback_stale"]
            )
        )
        # ADR-053 (allocator side): a static TVL passing the numeric floor is a
        # ranking assumption, NOT verification — say so where a reviewer looks.
        if self._tvl_floor_unverified:
            notes.append(
                "ADR-053: TVL-floor у {n} пулов держится на СТАТИЧЕСКОМ "
                "(неверифицированном) TVL: {pools}. Это допущение ранжирования, "
                "не наблюдение ликвидности; enforcement — RiskPolicy-гейт. "
                "Исключение таких пулов из ранжирования обнулило бы цели "
                "held-позиций (forced sell) — owner-gated.".format(
                    n=len(self._tvl_floor_unverified),
                    pools=self._tvl_floor_unverified,
                )
            )
        # ADR-061: capital that could NOT be deployed must say why — a blocked
        # protocol is a deliberate, logged refusal, never a silent omission.
        if self._evidence_gate_applied:
            _by_reason: dict[str, list[str]] = {}
            for _p, _r in sorted(self._blocked.items()):
                _by_reason.setdefault(_r, []).append(_p)
            notes.append(
                "ADR-061 evidence gate ON: финансируются только протоколы с "
                "НАБЛЮДЁННЫМ APY. Не допущены: "
                + ("; ".join(f"{r} → {ps}" for r, ps in sorted(_by_reason.items()))
                   or "нет")
            )
        else:
            notes.append(
                "ADR-061 WARNING: evidence gate НЕ применён (источник наблюдений "
                "недоступен) — ранжирование на легаси-вселенной, числа могут быть "
                "литералами. Требуется проверка data/adapter_status.json."
            )

        risk_model_applied = False
        risk_breakdown: dict[str, dict] = {}
        excluded: set[str] = set()

        strategy_loop_active = False
        selected_strategy_id: str | None = None
        strategy_confidence: str | None = None
        raw_weights: dict[str, float] | None = None

        # ── SPA-V408: shadow→allocator feedback loop ──────────────────────
        # Если включено — пробуем взять веса лучшей shadow-стратегии (по Sortino,
        # confidence ≥ medium) как БАЗУ. Cap'ы по тирам и risk-grade исключения
        # применяются ПОВЕРХ — стратегия не может обойти лимиты или вернуть
        # капитал в grade-D протокол.
        if self.strategy_loop_enabled:
            best = self._select_shadow_strategy()
            if best and best.get("confidence") in ("medium", "high"):
                sw = best.get("allocation_weights") or {}
                # Только веса по живым адаптерам — стратегия могла держать пул,
                # которого нет в текущем снимке оркестратора.
                sw = {
                    p: float(w)
                    for p, w in sw.items()
                    if p in tier_map and (float(w) if w is not None else 0.0) > 0
                }
                if sw:
                    raw_weights = sw
                    strategy_loop_active = True
                    selected_strategy_id = best.get("strategy_id")
                    strategy_confidence = best.get("confidence")
                    notes.append(
                        f"SPA-V408: shadow-стратегия '{selected_strategy_id}' "
                        f"использована как база весов (confidence="
                        f"{strategy_confidence}, Sortino={best.get('sortino')}, "
                        f"N={best.get('days_running')}д)."
                    )
                    log.info(
                        "strategy_loop_active: %s (confidence=%s)",
                        selected_strategy_id, strategy_confidence,
                    )
                    # Risk-grade исключения (grade D) применяем ПОВЕРХ весов
                    # стратегии — это жёсткий safety-гейт, не зависящий от модели.
                    risk_scores, loaded = self._load_risk_scores()
                    if loaded:
                        bd = models.risk_adjusted_breakdown(adapters, risk_scores)
                        excluded = set(bd["excluded"])
                        risk_breakdown = bd["per_protocol"]
                        risk_model_applied = True
                        if excluded:
                            notes.append(
                                "excluded_by_risk (поверх shadow-весов): "
                                + str(sorted(excluded))
                            )
                            log.info("excluded_by_risk: %s", sorted(excluded))

        # WS1.2: tracks whether the constrained optimizer produced these weights
        # (cap-respecting by construction) → the T1-first _fill_remainder is then
        # SKIPPED so it can't re-introduce the low-yield T1 water-fill drag.
        optimizer_applied = False

        # ── fallback: сконфигурированная модель (текущее поведение) ───────
        if not strategy_loop_active:
            if is_optimizer:
                # WS1.2 constrained yield optimizer (greedy knapsack under caps).
                # Caps are read from THIS allocator (RiskConfig source of truth) and
                # passed in — the model never hardcodes/mutates a cap.
                risk_scores, loaded = self._load_risk_scores()
                tier_caps = {
                    a["protocol"]: self._cap_for(a["tier"]) for a in adapters
                }
                bd = models.optimized_yield_breakdown(
                    adapters,
                    risk_scores if loaded else {},
                    tier_caps=tier_caps,
                    t2_total_cap=self.T2_TOTAL_CAP,
                    cash_floor=(_POLICY_CONFIG.min_cash_pct if _POLICY_CONFIG else 0.05),
                    max_protocols=self.MAX_PROTOCOLS,  # ALLOC-002 (A4: from RiskConfig)
                    objective=self.objective,
                )
                raw_weights = bd["weights"]
                risk_breakdown = bd["per_protocol"]
                excluded = set(bd["excluded"])
                risk_model_applied = loaded
                optimizer_applied = True
                notes.append(
                    "WS1.2 optimized_yield: greedy knapsack under RiskPolicy caps "
                    f"(objective={bd['objective']!r}, alpha={bd['alpha']}, "
                    f"funded={len(bd['funded'])}, exp_riskadj_score="
                    f"{bd['expected_riskadj_score']})."
                )
                if not loaded:
                    notes.append(
                        "WS1.2: risk_scores.json отсутствует/повреждён — оптимизатор "
                        "трактует все протоколы консервативно как grade B."
                    )
                if excluded:
                    notes.append("excluded_by_risk: " + str(sorted(excluded)))
                    log.info("WS1.2 excluded_by_risk: %s", sorted(excluded))
            elif is_risk_model:
                risk_scores, loaded = self._load_risk_scores()
                if not loaded:
                    # Защитный fallback: нет/битый risk_scores.json → equal_weight.
                    notes.append(
                        "risk_scores.json отсутствует или повреждён — риск-модель НЕ "
                        "применена, fallback на equal_weight."
                    )
                    raw_weights = models.equal_weight(adapters)
                else:
                    bd = models.risk_adjusted_breakdown(adapters, risk_scores)
                    raw_weights = bd["weights"]
                    risk_breakdown = bd["per_protocol"]
                    excluded = set(bd["excluded"])
                    risk_model_applied = True
                    if bd["excluded"]:
                        notes.append("excluded_by_risk: " + str(sorted(bd["excluded"])))
                        log.info("excluded_by_risk: %s", sorted(bd["excluded"]))
                    if bd["fallback_equal_weight"]:
                        notes.append(
                            "WARNING: все протоколы исключены риск-моделью "
                            "(grade D или нулевой APY) — fallback на equal_weight."
                        )
            else:
                raw_weights = _MODEL_DISPATCH[model](adapters)

        # Исключённые риском (grade D) убираем из расчёта целиком: иначе
        # _apply_caps перераспределит на них excess, а _fill_remainder — остаток.
        weights_for_alloc = {p: w for p, w in raw_weights.items() if p not in excluded}

        # ADR-138 (решение владельца 25.08, вариант A): ОСОЗНАННЫЙ отбор лучших N
        # СТРОГО ПОСЛЕ проверок доходности и живого размера пула. Всё, что дошло
        # сюда, эти проверки уже прошло (`_load_adapters` → TVL-floor → evidence
        # gate → исключения риск-модели), поэтому отбор судит равных.
        weights_for_alloc, dropped_by_count, kept_notes = self._select_best_n(
            weights_for_alloc, apy_map, tier_map
        )
        notes.extend(kept_notes)
        # Отсечённые по счёту НЕ должны вернуться через водоналив остатка:
        # `_fill_remainder` разливает по свободной ёмкости ВСЕХ известных ему
        # протоколов, включая обнулённых, и без этого списка книга снова
        # набирала одиннадцать позиций при пределе восемь (замер).
        _no_refill = set(excluded) | dropped_by_count

        capped, was_capped = self._apply_caps(weights_for_alloc, tier_map)
        if was_capped:
            notes.append("Веса ограничены cap'ами по тирам (T1≤40%, T2≤20%).")

        # SPA-V405: устранение структурного cash-drag — остаток после cap'ов
        # направляется в свободную ёмкость T1-якоря (затем T2), а не в кэш.
        # Исключённые риском (grade D) протоколы НЕ получают этот остаток.
        #
        # WS1.2: the constrained optimizer ALREADY poured the deployable budget
        # into the highest risk-adjusted-yield headroom (cap-respecting), so the
        # T1-first water-fill here would only RE-INTRODUCE the low-yield T1 drag
        # this optimizer exists to remove. Skip it — the optimizer's remainder is
        # genuine, cap-bound cash, not a fillable T1 anchor.
        if optimizer_applied:
            filled = False
        else:
            capped, filled = self._fill_remainder(
                capped, tier_map, apy_map, exclude=_no_refill
            )

        # MP-011: совокупный T2-кап ПОСЛЕ всех перераспределений (caps +
        # remainder-fill могут поднять суммарный T2 выше 35%) — финальный
        # инвариант перед возвратом: sum(T2) ≤ 35%.
        _sum_before_t2 = sum(capped.values())
        # ADR-160: срез ПЕРЕД каждым защитным шагом. Сумма отвечает «сколько срезали»,
        # но перераздача по варианту 3 владельца обязана знать «У КОГО» — вернуть деньги
        # туда, откуда их только что срезал потолок, значит отменить решение защиты.
        _by_proto_before_t2 = dict(capped)
        capped, t2_cap_enforced = self._enforce_t2_total_cap(capped, tier_map)
        if t2_cap_enforced:
            notes.append(
                f"MP-011: суммарный T2 срезан до {self.T2_TOTAL_CAP * 100:.0f}% "
                "(излишек перераспределён в headroom T1 либо остался кэшем)."
            )

        # ADR-020: T3-total cap (15%) — final invariant. The WS1.2 optimizer collapsed T3→T2 and
        # never enforced this, so optimized_yield could pour 30% into T3 (susde + extra_finance).
        # Re-applied here against the CANONICAL tier_map; the trimmed weight stays cash (never moved
        # to a riskier tier). Makes the go-live book compliant with the T3 cap the policy layer asserts.
        _sum_before_t3 = sum(capped.values())
        _by_proto_before_t3 = dict(capped)
        capped, t3_cap_enforced = self._enforce_t3_total_cap(capped)
        if t3_cap_enforced:
            notes.append(
                f"ADR-020: суммарный T3 срезан до {self.T3_TOTAL_CAP * 100:.0f}% "
                "(излишек честно остался кэшем — не перемещён в более рисковый тир)."
            )

        # ADR-136: сетевые потолки — последний защитный шаг перед учётом тримов.
        # До него аллокатор о сетях не знал вовсе: замер 2026-08-18 дал 95 % в
        # Ethereum и гейт отверг раскладку ЦЕЛИКОМ, то есть цикл остался без
        # сделок. Срезанное остаётся кэшем и попадает в protective_trims ниже,
        # чтобы перезаполнитель и атрибуция кэша видели ЧИСЛО, а не догадку.
        _sum_before_chain = sum(capped.values())
        _by_proto_before_chain = dict(capped)
        capped, chain_notes = self._enforce_chain_caps(capped)
        for _n in chain_notes:
            notes.append(f"ADR-136 (сетевые потолки): {_n}")

        # ADR-072-остаток: явный сигнал «сколько срезали защиты». Дельта каждого
        # защитного шага измерена по факту (сумма до − сумма после), а не выведена
        # из флагов: перезаполнителю и атрибуции кэша нужно ЧИСЛО, не догадка.
        protective_trims: dict[str, float] = {}
        _t2_cut = max(0.0, _sum_before_t2 - _sum_before_t3)
        _t3_cut = max(0.0, _sum_before_t3 - _sum_before_chain)
        _chain_cut = max(0.0, _sum_before_chain - sum(capped.values()))
        if _chain_cut > 1e-9:
            protective_trims["chain_caps"] = round(_chain_cut, 8)
        if _t2_cut > 1e-9:
            protective_trims["t2_total_cap"] = round(_t2_cut, 8)
        if _t3_cut > 1e-9:
            protective_trims["t3_total_cap"] = round(_t3_cut, 8)
        # ADR-160: та же дельта, но ПОИМЁННО. Считается тем же способом — разностью
        # факта до и после шага, а не выводится из флагов: перераздача должна опираться
        # на число, а не на догадку, кого именно урезали.
        protective_trims_by_protocol: dict[str, float] = {}
        for _before in (_by_proto_before_t2, _by_proto_before_t3, _by_proto_before_chain):
            for _proto, _w in _before.items():
                _cut = float(_w) - float(capped.get(_proto, 0.0))
                if _cut > 1e-9:
                    protective_trims_by_protocol[_proto] = round(
                        protective_trims_by_protocol.get(_proto, 0.0) + _cut, 8)

        if protective_trims:
            _total_cut = sum(protective_trims.values())
            notes.append(
                "Защитные тримы аллокатора срезали в кэш "
                f"{_total_cut * 100:.2f}% ("
                + ", ".join(f"{k}: {v * 100:.2f}%" for k, v in protective_trims.items())
                + ") — сигнал для перезаполнения (ADR-072)."
            )

        # Возвращаем исключённые риском протоколы в вывод с нулевым весом —
        # для прозрачности (видно, что они учтены и сознательно занулены).
        for p in excluded:
            capped.setdefault(p, 0.0)
        # ADR-138: отсечённые по счёту — тоже видны нулём. Молча исчезнувший из
        # вывода протокол неотличим от «его не рассматривали» (инв. #17), а его
        # рассмотрели и сознательно предпочли лучших.
        for p in dropped_by_count:
            capped.setdefault(p, 0.0)
        if filled:
            notes.append(
                "Остаток после cap'ов размещён в headroom T1-якоря/T2 "
                "(устранение cash-drag, SPA-V405)."
            )

        allocated = sum(capped.values())
        unallocated = max(0.0, 1.0 - allocated)
        if unallocated > 1e-6:
            notes.append(
                f"Нераспределённый кэш-буфер: {unallocated * 100:.2f}% "
                "(остаток после применения cap'ов и заполнения T1-якорем)."
            )

        # Разбивка размещения по тирам (T3 трактуем как T2, как и cap'ы).
        t1_pct = sum(
            w for p, w in capped.items() if str(tier_map.get(p, "T2")).upper() == "T1"
        )
        t2_pct = sum(
            w for p, w in capped.items() if str(tier_map.get(p, "T2")).upper() != "T1"
        )

        target_usd = {p: round(w * self.CAPITAL, 2) for p, w in capped.items()}

        # MP-209: capacity limits enforcement — обрезаем позиции превышающие
        # 1% TVL пула. Warn-only режим (ADR-009): срезание происходит в аллокаторе,
        # нарушения логируются, но цикл не блокируется.
        # Если TVL map пустой → пропускаем (fail-safe).
        capacity_capped = False
        capacity_check_result: dict = {}
        try:
            from spa_core.risk.capacity_limits import (  # lazy import, без цикл. зависимостей
                apply_capacity_caps,
                build_tvl_map,
                check_all_capacities,
            )
            # Строим tvl_map из текущего снимка адаптеров
            status_dict: dict = {}
            if self.status_path.exists():
                import json as _json
                with open(self.status_path, encoding="utf-8") as _fh:
                    status_dict = _json.load(_fh)
            tvl_map_cap = build_tvl_map(status_dict)

            if tvl_map_cap:
                # Проверяем до обрезания — для логирования нарушений
                capacity_check_result = check_all_capacities(target_usd, tvl_map_cap)
                if capacity_check_result.get("violations"):
                    log.warning(
                        "MP-209: capacity violations (warn-only, ADR-009): %s",
                        capacity_check_result["violations"],
                    )
                    notes.append(
                        "MP-209 CAPACITY_WARN: позиции обрезаны по лимиту 1%% TVL: "
                        + str(capacity_check_result["violations"])
                    )

                # Применяем cap'ы
                target_usd_capped = apply_capacity_caps(target_usd, tvl_map_cap)
                if target_usd_capped != target_usd:
                    capacity_capped = True
                    target_usd = {p: round(v, 2) for p, v in target_usd_capped.items()}
                    # Пересчитываем веса из обрезанных USD-сумм
                    capped = {p: target_usd[p] / self.CAPITAL for p in target_usd}
            else:
                log.info("MP-209: tvl_map пустой — capacity check пропущен")
        except Exception as _cap_exc:
            # Capacity check не должен валить аллокацию (fail-safe)
            log.warning("MP-209: capacity_cap ошибка (%s) — пропущен", _cap_exc)

        # APY портфеля: веса как доли капитала; нераспределённый кэш = 0% APY.
        # FAIL-CLOSED (property-test PROP-NAN): non-finite per-protocol APY
        # (NaN/Inf from a malformed feed) must NOT propagate into the portfolio
        # APY metric — a single NaN poisons expected_apy_pct → equity-curve /
        # reporting / dashboard consumers silently ingest NaN. Sanitize any
        # non-finite APY to 0.0 in THIS sum only (weights/caps are already safe;
        # behaviour is unchanged for every finite input).
        def _finite_apy(p: str) -> float:
            v = apy_map.get(p, 0.0)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                return 0.0
            return float(v)

        expected_apy = sum(capped[p] * _finite_apy(p) for p in capped)

        # Пересчитываем метрики после capacity cap (если был)
        allocated = sum(capped.values())
        unallocated = max(0.0, 1.0 - allocated)
        t1_pct = sum(
            w for p, w in capped.items() if str(tier_map.get(p, "T2")).upper() == "T1"
        )
        t2_pct = sum(
            w for p, w in capped.items() if str(tier_map.get(p, "T2")).upper() != "T1"
        )

        return AllocationResult(
            target_weights={p: round(w, 6) for p, w in capped.items()},
            target_usd=target_usd,
            expected_apy_pct=round(expected_apy, 4),
            model_used=model,
            timestamp=ts,
            capital_usd=float(self.CAPITAL),
            allocated_pct=round(allocated, 6),
            unallocated_pct=round(unallocated, 6),
            unallocated_usd=round(unallocated * self.CAPITAL, 2),
            cash_pct=round(unallocated, 6),
            t1_pct=round(t1_pct, 6),
            t2_pct=round(t2_pct, 6),
            total_deployed_pct=round(allocated, 6),
            risk_model_applied=risk_model_applied,
            protective_trims=protective_trims,
            protective_trims_by_protocol=protective_trims_by_protocol,
            risk_breakdown=risk_breakdown,
            strategy_loop_active=strategy_loop_active,
            selected_strategy_id=selected_strategy_id,
            strategy_confidence=strategy_confidence,
            tvl_filtered_protocols=tvl_filtered,
            t2_cap_enforced=t2_cap_enforced,
            capacity_capped=capacity_capped,
            capacity_check=capacity_check_result,
            apy_sources=dict(self._apy_sources),
            apy_used=dict(self._apy_used),
            feed_coverage=_cov,
            evidence_gate_applied=self._evidence_gate_applied,
            blocked_protocols=dict(self._blocked),
            notes=notes,
        )

    # ── сохранение ────────────────────────────────────────────────────────
    def save(
        self, result: AllocationResult, path: str | os.PathLike = _DEFAULT_OUT
    ) -> Path:
        """Атомарно пишет результат в JSON (tmp + os.replace)."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = result.to_dict()
        atomic_save(payload, str(out))
        return out


def main() -> None:
    """CLI: рассчитать и сохранить распределение по выбранной модели."""
    import argparse

    parser = argparse.ArgumentParser(description="SPA Strategy Allocator (advisory)")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        choices=sorted(
            set(_MODEL_DISPATCH) | _RISK_MODEL_ALIASES | _OPTIMIZER_MODEL_ALIASES
        ),
        help="Модель аллокации (по умолчанию risk_adjusted; "
        "optimized_yield = WS1.2 constrained optimizer)",
    )
    parser.add_argument(
        "--objective",
        default=None,
        help="WS1.2 optimizer objective dial: max_yield|balanced|min_variance "
        "or a float in [0,1] (owner-tunable; default balanced)",
    )
    parser.add_argument("--out", default=str(_DEFAULT_OUT), help="Путь вывода")
    args = parser.parse_args()

    allocator = StrategyAllocator(objective=args.objective)
    result = allocator.allocate(model=args.model)
    allocator.save(result, args.out)
    print(f"Модель: {result.model_used}")
    print(f"Риск-модель применена: {result.risk_model_applied}")
    print(f"Веса: {result.target_weights}")
    print(f"USD: {result.target_usd}")
    print(f"Ожидаемый APY: {result.expected_apy_pct}%")
    print(f"Нераспределено: {result.unallocated_pct * 100:.2f}%")
    print(f"Сохранено в {args.out}")


if __name__ == "__main__":
    main()
