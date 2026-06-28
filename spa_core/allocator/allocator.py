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
_EPS = 1e-12

# MP-REGISTRY: fallback TVL assumption for registry-only adapters (not in orchestrator).
# These are all established protocols with TVL >> $5M TVL floor; $50M is conservative.
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
        from . import config as _cfg
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
    # A4 (de-hardcode ALLOC-002): the diversity floor (≤ N funded protocols) is
    # read from RiskConfig (single source of truth) instead of a hardcoded `8`
    # inside allocate(). Owner-gated like every other cap; the WS1.2 optimizer
    # receives THIS value so the limit can never drift between policy and model.
    MAX_PROTOCOLS: int = (
        _POLICY_CONFIG.max_protocols if _POLICY_CONFIG is not None else 8
    )

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
        live_apy_provider=None,
        objective: str | float | None = None,
    ):
        self.status_path = Path(status_path) if status_path else _STATUS_PATH
        self.risk_scores_path = (
            Path(risk_scores_path) if risk_scores_path else _RISK_SCORES_PATH
        )
        self.allocation_model = allocation_model or DEFAULT_MODEL
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
        live_apy = self._get_live_apy_map()
        now_iso = datetime.now(timezone.utc).isoformat()

        if self.status_path.exists():
            with open(self.status_path, encoding="utf-8") as fh:
                raw = json.load(fh)
            for a in raw.get("adapters", []):
                status = a.get("status", "ok")
                if status not in ("ok", "partial"):
                    continue
                protocol = str(a["protocol"])
                seen_protocols.add(protocol)
                # Orchestrator-snapshot adapters already came from the live
                # get_yield_info() feed → their apy_pct is live by construction.
                # Prefer the freshly-fetched live reading when present (same feed,
                # one consistent timestamp); else trust the snapshot value.
                snap_apy = float(a.get("apy_pct", 0.0))
                if protocol in live_apy:
                    apy_pct = round(live_apy[protocol] * 100.0, 4)
                else:
                    apy_pct = snap_apy
                _row = {
                    "protocol": protocol,
                    "apy_pct": apy_pct,
                    "tvl_usd": float(a.get("tvl_usd", 0.0)),
                    "tier": a.get("tier", "T2"),
                    "apy_source": "live",
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
                    # Registry stores tier as integer (1/2/3); treat tier≥3 as T2.
                    tier_int = entry.get("tier", 2)
                    tier_str = "T1" if tier_int == 1 else "T2"
                    tvl = float(entry.get("fallback_tvl_usd", _REGISTRY_FALLBACK_TVL_USD))

                    if name in live_apy:
                        # LIVE WINS. Normalised decimal → pct.
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

                    adapters.append(
                        {
                            "protocol": name,
                            "apy_pct": apy_pct,
                            "tvl_usd": tvl,
                            "tier": tier_str,
                            "apy_source": apy_source,
                            "as_of": as_of,
                        }
                    )
                    self._apy_sources[name] = apy_source
                    self._apy_used[name] = apy_pct
                    self._as_of[name] = as_of
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
        """
        ok: list[dict] = []
        rejected: list[str] = []
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
            else:
                rejected.append(a.get("protocol", "?"))
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
                capped, tier_map, apy_map, exclude=excluded
            )

        # MP-011: совокупный T2-кап ПОСЛЕ всех перераспределений (caps +
        # remainder-fill могут поднять суммарный T2 выше 35%) — финальный
        # инвариант перед возвратом: sum(T2) ≤ 35%.
        capped, t2_cap_enforced = self._enforce_t2_total_cap(capped, tier_map)
        if t2_cap_enforced:
            notes.append(
                f"MP-011: суммарный T2 срезан до {self.T2_TOTAL_CAP * 100:.0f}% "
                "(излишек перераспределён в headroom T1 либо остался кэшем)."
            )

        # Возвращаем исключённые риском протоколы в вывод с нулевым весом —
        # для прозрачности (видно, что они учтены и сознательно занулены).
        for p in excluded:
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
