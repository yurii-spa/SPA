"""Adapter Status Generator — spa_core/monitoring (MP-1195).

Reads ``data/adapter_registry.json`` as the canonical source of truth for
adapter metadata (tier, fallback_apy, chain, per_protocol_cap) and attempts
to enrich APY values with live data from DeFiLlama (5 s timeout, graceful
fallback on any network error).

Output: schema_version 2 where ``adapters`` is a **dict** keyed by snake_case
protocol name.  This satisfies:

* GoLive checker (MP-384) — checks ``doc["adapters"]["compound_v3"]`` etc.
* cycle_runner MP-413 fallback APY merge (iterates ``adapters`` dict).
* Adapter modules that read individual top-level shadow keys:
    - ``morpho_steakhouse_adapter.py`` → ``doc["morpho_steakhouse"]["apy"]``
    - ``aave_arbitrum_adapter.py``     → ``doc["aave_arbitrum"]["apy"]``

APY unit convention (v2): all ``apy`` / ``live_apy`` / ``fallback_apy``
fields are **percentages** (e.g. 5.2 means 5.2 %, not 0.052).

CLI:
    python3 -m spa_core.monitoring.adapter_status_generator          # dry-run
    python3 -m spa_core.monitoring.adapter_status_generator --run    # write

Always exits 0 — advisory module, fail-safe.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_FILE = _REPO_ROOT / "data" / "adapter_registry.json"
_STATUS_FILE = _REPO_ROOT / "data" / "adapter_status.json"

SCHEMA_VERSION = 2
DEFILLAMA_URL = "https://yields.llama.fi/pools"
DEFILLAMA_TIMEOUT = 5  # seconds

# ── DeFiLlama project / symbol / chain lookup hints ─────────────────────────
# Each value is (project_substring, symbol_substring, chain) — all
# case-insensitive substring matches against the DeFiLlama pools response.
_DEFILLAMA_HINTS: dict[str, tuple[str, str, str]] = {
    "aave_v3":           ("aave-v3",     "USDC",   "Ethereum"),
    "compound_v3":       ("compound-v3", "USDC",   "Ethereum"),
    "aave_arbitrum":     ("aave-v3",     "USDC",   "Arbitrum"),
    # DeFiLlama calls this chain "OP Mainnet", never "Optimism" — the hint below
    # matched nothing for as long as it said otherwise, and the adapter reported
    # live_apy: null with no error anywhere. The label is documented in
    # .claude/rules/adapters.md; the code had simply never been corrected.
    "aave_v3_optimism":  ("aave-v3",     "USDC",   "OP Mainnet"),
    "aave_v3_polygon":   ("aave-v3",     "USDC",   "Polygon"),
    "morpho_blue":       ("morpho",      "USDC",   "Ethereum"),
    "morpho_steakhouse": ("morpho",      "USDC",   "Ethereum"),
    "spark_susds":       ("spark",       "USDS",   "Ethereum"),
    "yearn_v3":          ("yearn",       "USDC",   "Ethereum"),
    "euler_v2":          ("euler",       "USDC",   "Ethereum"),
    "maple":             ("maple",       "USDC",   "Ethereum"),
    "fluid_fusdc":       ("fluid",       "USDC",   "Ethereum"),
    "aave_v3_base":      ("aave-v3",     "USDC",   "Base"),
    "moonwell_base":     ("moonwell",    "USDC",   "Base"),
    "morpho_blue_base":  ("morpho",      "USDC",   "Base"),
}

# Direct DeFiLlama pool UUID match — overrides project/symbol matching
# Pinned DeFiLlama pool UUIDs. A pin is what makes an observation *auditable*:
# without it a protocol key is resolved by fuzzy project/chain/symbol hints and
# "best TVL wins", which is not a stable identity. Base alone carries four
# STEAKUSDC vaults ($587M @ 4.32%, $172M @ 3.22%, $30M, $0.3M) — a silent switch
# between them changes the APY that ranks capital, with nothing in the record to
# show the pool changed. Only a pinned match may stamp ``tvl_source: "live"``,
# because the $5M TVL floor is a policy gate and a gate must not rest on a match
# that can drift.
#
# The former single entry was an Ethereum contract ADDRESS, not a DeFiLlama pool
# UUID, so it never matched ``by_id`` and morpho_steakhouse silently resolved by
# hint anyway. Every UUID below was read off the live feed on 2026-08-05 and is
# recorded with the chain/project/symbol/TVL it identified.
_POOL_ID_LOOKUP: dict[str, str] = {
    # Ethereum / morpho-blue / STEAKUSDC — $106.5M @ 3.51%
    "morpho_steakhouse": "931ea9be-5f4d-428e-beaf-205fc5b4e2b5",
    # Base / morpho-blue / STEAKUSDC — $587.3M @ 4.32%; largest USDC vault on
    # Morpho Base. NOTE: same curator (Steakhouse) as morpho_steakhouse above on
    # a different chain — distinct pools, but correlated curator risk that the
    # per-protocol cap does NOT see. Tracked in agent-morpho-curator-concentration.
    "morpho_blue_base":  "ba68527f-8ec2-4c55-827a-8f4673ae047c",
    # Ethereum / maple / USDC — $2.65B @ 4.96%
    "maple":             "43641cf5-a92e-416b-bce9-27113d3c0db6",
    # Ethereum / fluid-lending / USDC — $150.3M @ 4.82%. Deliberately NOT
    # fluid-lite ($41M @ 7.24%): a different, smaller product. The higher number
    # is not the one this adapter models.
    "fluid_fusdc":       "4438dabc-7f0c-430b-8136-2722711ae663",
    # Base / moonwell-lending / USDC — $2.6M @ 4.12%. Pinned precisely BECAUSE it
    # is small: the adapter carries TVL_USD = 500_000_000, a 190x overstatement
    # that let a sub-floor pool clear the $5M floor unnoticed.
    "moonwell_base":     "69cf831d-624a-4f23-b5e3-c0f63ad1fa01",
    # ── wired 2026-08-05: protocols that had NO producer at all ──────────────
    # 19 of 34 adapters had neither a hint nor a pin — they were never wired,
    # not broken. Only the unambiguous ones are pinned here; see
    # agent-feeds-without-a-producer for the ones deliberately left unwired and
    # why (a wrong pool is worse than an honest null).
    #
    # Ethereum / sky-lending / SUSDS — $4.75B @ 3.52%
    "sky_susds":         "d8c4eff5-c8a9-46fc-a888-057c4c668e72",
    # Ethereum / ondo-yield-assets / USDY — $1.11B @ 3.55%
    "ondo_usdy":         "ac61ee82-2fe4-4f9b-a9cd-7fb33f598859",
    # Ethereum / ethena-usde / SUSDE — $1.56B @ 3.94%. Observation only; susde
    # stays blocked by its advisory class gate (invariant 9) regardless.
    "susde":             "66985a81-9c51-46ca-9977-42b4fe7bc6df",
    # Ethereum / frax / SFRAX — $65.1M @ 1.25%. NOTE: the ``frax`` key resolves
    # to this same pool, so it is deliberately NOT pinned — two protocol keys
    # sharing one pool is hidden concentration, and the per-protocol cap cannot
    # see it. Enforced by test_no_two_keys_share_a_pool.
    "sfrax":             "55de30c3-bf9f-4d4e-9e0b-536a8ef5ab35",
    # ── wired 2026-08-05 (second pass, agent-blocked-protocols-need-live-feeds) ─
    # The first pass concluded "sdai: only a $44k sparklend dust pool exists".
    # That was a search miss, not an absence: after the Maker→Sky rebrand the
    # real DSR vault is listed under project "sky-lending". Verified by
    # underlyingTokens == DAI (0x6B17...1d0F).
    # Ethereum / sky-lending / SDAI — $210.0M @ 1.25%
    "sdai":              "c8a24fee-ec00-4f38-86c0-9f6daebc4225",
    # Same class of miss for scrvusd: the first pass matched the REUSD-SCRVUSD
    # curve-dex LP and rightly refused it. The Curve Savings vault itself is
    # listed under project "crvusd" (single exposure, underlying crvUSD
    # 0xf939...1b4E). Ethereum / crvusd / SCRVUSD — $18.7M @ 1.10%
    "scrvusd":           "5fd328af-4203-471b-bd16-1705c726d926",
    # Base / extra-finance-xlend / USDC — $0.34M @ 1.51%. Pinned precisely
    # BECAUSE it is tiny: the adapter carries TVL_USDC_LENDING = 15_000_000
    # ("> $5M — RiskPolicy floor ok"), a ~43x overstatement of the observed
    # pool. The observation is the fact; the live TVL honestly fails the $5M
    # floor and the T3/advisory class gate (invariant 9) stays shut regardless.
    "extra_finance_base": "bc6b7193-da3c-43e3-8c7b-4c9508eec893",
    # ── NOT wired, with evidence (2026-08-05 live /pools scan) ───────────────
    # frax  — the adapter models the FraxLend v2 USDC/FRAX pair
    #         (0x3835a58CA93Cdb5f912519ad366826aC9a752510). No such pool is in
    #         the feed: fraxlend/Ethereum pools are FRXUSD-era pairs with other
    #         collateral; the only USDC pool is "sfrxETH collateral" at $31.7k
    #         (dust, different pair). Pinning the SFRAX pool instead is
    #         forbidden (see sfrax note above).
    # stusd — Angle staked USDA: project "angle" has zero pools; no STUSD
    #         symbol anywhere. Every USDA hit in the feed is a different asset
    #         (usd-ai, gauntlet GTUSDA, Tether USDAT, Cardano USDA).
    # wusdm — Mountain Protocol wrapped USDM: no mountain-protocol project, no
    #         WUSDM pool; USDM hits are unrelated tokens on Cardano/MegaETH/
    #         Celo. No honest source → stays unobserved (None, never a mock).
}

# TVL estimates (USD) used when DeFiLlama is unavailable
_TVL_ESTIMATES: dict[str, float] = {
    "aave_v3":            12_000_000_000.0,
    "compound_v3":         3_000_000_000.0,
    "morpho_steakhouse":     800_000_000.0,
    "aave_arbitrum":       1_200_000_000.0,
    "aave_v3_optimism":      400_000_000.0,
    "aave_v3_polygon":       600_000_000.0,
    "morpho_blue":         2_000_000_000.0,
    "spark_susds":           500_000_000.0,
    "yearn_v3":              300_000_000.0,
    "euler_v2":              150_000_000.0,
    "maple":                 200_000_000.0,
    "fluid_fusdc":           100_000_000.0,
    "sfrax":                 800_000_000.0,
    "wusdm":                 400_000_000.0,
    "scrvusd":               300_000_000.0,
    "stusd":                 200_000_000.0,
    "sdai":                1_200_000_000.0,
    "frax":                  100_000_000.0,
    "aave_v3_base":          250_000_000.0,
    "morpho_blue_base":      300_000_000.0,
    "moonwell_base":         150_000_000.0,
    "pendle":                500_000_000.0,
    "pendle_pt":             500_000_000.0,
    "susde":                 800_000_000.0,
    "extra_finance_base":     50_000_000.0,
    "fluid_usdc":            100_000_000.0,
    "notional_v3":            50_000_000.0,
}


# ── DeFiLlama helpers ────────────────────────────────────────────────────────

def _fetch_defillama(timeout: int = DEFILLAMA_TIMEOUT) -> Optional[list]:
    """Fetch all pools from DeFiLlama /pools.

    Returns a list of pool dicts on success, ``None`` on any error.
    """
    # CI/offline guard: never make an external network call under SPA_ENV=ci. The
    # DeFiLlama /pools body is large and resp.read() can stall past the connect
    # timeout, wedging CI test runs for 30min+ (any test that reaches generate()
    # transitively — cycles, chaos, status — would hang). Returns None → the
    # generator's existing NON-LIVE fallback (APY honestly marked non-live, never
    # fabricated). Production (SPA_ENV != ci) is unaffected.
    if os.environ.get("SPA_ENV") == "ci":
        return None
    try:
        req = urllib.request.Request(
            DEFILLAMA_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "SPA-AdapterStatusGenerator/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        pools = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(pools, list):
            log.debug("DeFiLlama: fetched %d pools", len(pools))
            return pools
        log.warning("DeFiLlama: unexpected response shape")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("DeFiLlama fetch failed (network): %s", exc)
        return None
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("DeFiLlama fetch failed (parse): %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — strict fail-safe
        log.warning("DeFiLlama fetch failed (unexpected): %s", exc)
        return None


def _build_pool_indexes(
    pools: list,
) -> tuple[dict[str, dict], dict[tuple[str, str, str], list[dict]]]:
    """Return (by_pool_id, by_project_chain_symbol) indexes for fast lookup."""
    by_id: dict[str, dict] = {}
    by_pcs: dict[tuple[str, str, str], list[dict]] = {}
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        pid = str(pool.get("pool", "")).lower()
        if pid:
            by_id[pid] = pool
        proj = str(pool.get("project", "")).lower()
        chain = str(pool.get("chain", "")).lower()
        sym = str(pool.get("symbol", "")).upper()
        by_pcs.setdefault((proj, chain, sym), []).append(pool)
    return by_id, by_pcs


def _valid_apy(pool: dict) -> Optional[float]:
    """Extract APY (%) from a pool dict; return ``None`` if out of sanity range."""
    apy = pool.get("apy")
    if isinstance(apy, (int, float)) and not isinstance(apy, bool):
        if 0.0 < float(apy) < 200.0:
            return round(float(apy), 4)
    return None


# ── Pendle PT: закрепляем РЫНОК, а не выпуск ────────────────────────────────
#
# PT — датированный инструмент. Закрепить его по UUID нельзя: выпуск гасится, пул
# исчезает, и фид выглядит рабочим ровно до дня погашения (замер 2026-08-05:
# PT-sUSDe-13AUG2026 — до конца жизни 8 дней). Поэтому закрепляется рынок
# (проект/сеть/базовый актив), а выпуск выбирается КАЖДЫЙ прогон.
#
# Различить PT от LP по symbol невозможно — он у них одинаковый, и TVL тоже:
# на Ethereum обе записи SUSDE несут $8.24M, но APY 4.26 % против 12.39 %.
# Различает ТОЛЬКО poolMeta: "For buying PT-..." против "For LP | Maturity ...".
# Правило «побеждает крупнейший TVL» выбирало бы между ними монеткой, а разница
# втрое — это не шум, это другой инструмент с другим риском.
_PT_BUY_PREFIX = "for buying pt-"

# adapter_key → (project, chain, базовый актив в symbol)
_PENDLE_PT_MARKETS: dict[str, tuple[str, str, str]] = {
    "pendle_pt_susde": ("pendle", "ethereum", "SUSDE"),
}

# Сколько дней до погашения выпуск ещё считается пригодным. Ближе к сроку PT
# теряет смысл как позиция: капитал в него зайти не успеет, а доходность
# вырождается. Порог намеренно консервативный.
_PT_MIN_DAYS_TO_MATURITY = 7


def _pt_maturity(pool: dict) -> "date | None":
    """Дата погашения из poolMeta вида 'For buying PT-sUSDe-13AUG2026'.

    Не парсится ⇒ ``None`` ⇒ выпуск не берётся. Датированный инструмент без
    читаемой даты — это инструмент с неизвестным сроком, а неизвестный срок не
    доказательство пригодности (fail-CLOSED).
    """
    from datetime import datetime as _dt

    meta = str(pool.get("poolMeta") or "")
    if not meta.lower().startswith(_PT_BUY_PREFIX):
        return None
    # "13AUG2026" — месяц приходит капсом, а %b ждёт "Aug": приводим ЗНАЧЕНИЕ,
    # не формат. (Первая версия делала fmt.upper() и превращала %d%b%Y в %D%B%Y —
    # парсер молча возвращал None на совершенно корректной дате.)
    tail = meta.rsplit("-", 1)[-1].strip().title()
    for fmt in ("%d%b%Y", "%d%B%Y"):
        try:
            return _dt.strptime(tail, fmt).date()
        except ValueError:
            continue
    return None


def _lookup_pendle_pt(
    adapter_key: str,
    pools: list,
    today=None,
) -> Optional[dict]:
    """Текущий выпуск PT для закреплённого рынка, или ``None``.

    Детерминировано: среди пулов рынка берутся только записи "For buying PT-"
    (не LP), с читаемой датой, до погашения которых осталось не меньше
    ``_PT_MIN_DAYS_TO_MATURITY`` дней; из них выбирается БЛИЖАЙШИЙ по сроку —
    то есть текущий торгуемый выпуск, а не самый дальний.

    Выбор воспроизводим: по этим правилам аудитор получит тот же пул. Именно это
    делает результат наблюдением, а не совпадением.
    """
    from datetime import date as _date

    market = _PENDLE_PT_MARKETS.get(adapter_key)
    if not market:
        return None
    proj, chain, asset = market
    ref = today or _date.today()

    best = None
    best_maturity = None
    for pool in pools or []:
        if not isinstance(pool, dict):
            continue
        if proj not in str(pool.get("project", "")).lower():
            continue
        if chain not in str(pool.get("chain", "")).lower():
            continue
        if asset not in str(pool.get("symbol", "")).upper():
            continue
        maturity = _pt_maturity(pool)
        if maturity is None:
            continue                      # LP-запись или нечитаемая дата
        if (maturity - ref).days < _PT_MIN_DAYS_TO_MATURITY:
            continue                      # погашен или гасится вот-вот
        if _valid_apy(pool) is None:
            continue
        if best_maturity is None or maturity < best_maturity:
            best, best_maturity = pool, maturity

    if best is not None:
        log.info("Pendle PT %s: выпуск с погашением %s (пул %s)",
                 adapter_key, best_maturity, str(best.get("pool"))[:8])
    return best


def _lookup_live_pool(
    adapter_key: str,
    by_id: dict[str, dict],
    by_pcs: dict[tuple[str, str, str], list[dict]],
) -> Optional[dict]:
    """Return the DeFiLlama POOL matched for *adapter_key*, not just its APY.

    The matcher already identifies the right pool for 14 adapters; returning only
    the APY threw away the TVL sitting in the same record. The consequence was
    material: with no observed TVL, every adapter fell back to a hardcoded
    ``_TVL_ESTIMATES`` literal, ADR-053 refused to let a literal clear the $5M
    floor, and unheld pools were frozen at their held size — i.e. **no new
    position could be opened at all**, and 10 % of capital sat in cash with a
    qualified candidate available. One matched pool now yields both numbers, and
    both are provably observed.

    Strategy:
    1. Exact pool UUID match (``_POOL_ID_LOOKUP``).
    2. Best-TVL pool matching project / chain / symbol hints
       (``_DEFILLAMA_HINTS``), using substring matching on each dimension.
    """
    # 0. Pendle PT — рынок закреплён, выпуск выбирается по сроку.
    if adapter_key in _PENDLE_PT_MARKETS:
        pt = _lookup_pendle_pt(adapter_key, list(by_id.values()))
        if pt is not None:
            return pt, "pinned"
        return None

    # 1. Exact pool UUID
    raw_id = _POOL_ID_LOOKUP.get(adapter_key, "")
    if raw_id:
        pool = by_id.get(raw_id.lower())
        if pool:
            if _valid_apy(pool) is not None:
                log.debug("DeFiLlama pool-id hit: %s", adapter_key)
                return pool, "pinned"

    # 2. Hint-based lookup
    hints = _DEFILLAMA_HINTS.get(adapter_key)
    if not hints:
        return None
    proj_hint, sym_hint, chain_hint = hints
    proj_l = proj_hint.lower()
    chain_l = chain_hint.lower()
    sym_u = sym_hint.upper()

    candidates: list[dict] = []
    for (proj, chain, sym), pool_list in by_pcs.items():
        if proj_l not in proj and proj not in proj_l:
            continue
        if chain_l not in chain and chain not in chain_l:
            continue
        if sym_u not in sym and sym not in sym_u:
            continue
        candidates.extend(pool_list)

    best: Optional[dict] = None
    best_tvl = -1.0
    for cand in candidates:
        tvl = float(cand.get("tvlUsd", 0) or 0)
        if _valid_apy(cand) is not None and tvl > best_tvl:
            best_tvl = tvl
            best = cand

    if best is not None and _valid_apy(best) is not None:
        log.debug("DeFiLlama hint hit: %s", adapter_key)
        return best, "hint"
    return None


def _lookup_live_apy(
    adapter_key: str,
    by_id: dict[str, dict],
    by_pcs: dict[tuple[str, str, str], list[dict]],
) -> Optional[float]:
    """Live APY (%) for *adapter_key* — thin wrapper over :func:`_lookup_live_pool`."""
    match = _lookup_live_pool(adapter_key, by_id, by_pcs)
    return _valid_apy(match[0]) if match is not None else None


# ── Core document builder ────────────────────────────────────────────────────

# Which protocol keys may inherit the Sky/Maker governance pause delay.
#
# Deliberately ONE key. ``fluid_fusdc`` also carries an ``is_gsm_compliant()``
# gate, and its docstring calls the rule "analogous to Spark sUSDS" — but Fluid
# is a different protocol with its own governance, and stamping Maker's DSPause
# delay onto it would attribute another protocol's safety parameter. That is the
# same class of fabrication the evidence gate exists to stop, so Fluid stays
# unconfirmed until its OWN timelock is read (agent-fluid-timelock-source).
_GSM_INHERITS_SKY = ("spark_susds",)



# Окно годности наблюдения ставки, снятой нами самими. Ряд обновляется раз в
# сутки; двое суток без обновления означают, что производитель встал, и число
# перестаёт быть свидетельством своего момента.
_ERC4626_MAX_AGE_H = 48.0


def _merge_erc4626_rates(adapters: dict, data_dir: Path) -> None:
    """Внести ставки, которые мы измерили сами (`erc4626_rate_monitor`).

    ``stusd`` и ``wusdm`` не индексируются DeFiLlama вовсе, поэтому единственный
    путь к наблюдению — читать цену доли хранилища и копить свой ряд. Слияние
    делается ЗДЕСЬ, а не производителем, чтобы у ``adapter_status.json`` остался
    один писатель: генератор переписывает карту ``adapters`` целиком и затёр бы
    поле, записанное за его спиной.

    Fail-CLOSED на каждом шаге: нет файла, нет ставки, недатированное или
    протухшее наблюдение — поле просто не появляется, и протокол честно остаётся
    ненаблюдаемым. Ставка ставится в ``live_apy`` (единственное поле, которое
    доказывает наблюдение) с пометкой источника — литералом она не станет.
    """
    try:
        doc = json.loads((Path(data_dir) / "erc4626_rates.json").read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(doc, dict):
        return
    vaults = doc.get("vaults")
    if not isinstance(vaults, dict):
        return

    now = datetime.now(timezone.utc)
    for key, entry in vaults.items():
        if not isinstance(entry, dict):
            continue
        row = adapters.get(key)
        if not isinstance(row, dict):
            continue
        apy = entry.get("apy_pct")
        if not isinstance(apy, (int, float)) or isinstance(apy, bool):
            continue
        stamp = entry.get("share_price_as_of")
        try:
            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if (now - dt).total_seconds() / 3600.0 > _ERC4626_MAX_AGE_H:
            continue
        row["apy"] = round(float(apy), 4)
        row["live_apy"] = round(float(apy), 4)
        row["live_apy_as_of"] = stamp
        row["live_apy_fresh"] = True
        row["apy_source"] = "erc4626_self_measured"
        row["apy_witnesses"] = entry.get("witnesses")


def _merge_gsm_hours(adapters: dict, data_dir: Path) -> None:
    """Carry the observed GSM pause delay into the rows whose gate reads it.

    ``sky_monitor`` observes ``DSPause.delay()`` on-chain and owns
    ``sky_status.json``; the adapters' gate reads ``adapter_status.json``. Until
    now nothing joined the two, so the gate read a missing field, treated it as
    zero, and refused — permanently. The producer ran, exited 0, and wrote an
    honest ``null`` every time, which is why nothing ever alerted.

    The merge happens HERE rather than in the producer so that
    ``adapter_status.json`` keeps a single writer: the generator rewrites the
    whole ``adapters`` map each run and would silently clobber a field written
    behind its back.

    Fail-CLOSED throughout: an unreadable file, a missing value, a non-numeric
    value or a non-on-chain source all leave the field ABSENT, and an absent
    field is what keeps the gate shut. Nothing is defaulted.
    """
    try:
        doc = json.loads((Path(data_dir) / "sky_status.json").read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(doc, dict):
        return

    hours = doc.get("gsm_hours")
    if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours <= 0:
        return
    # Only an on-chain observation counts. "manual" is the hardcoded constant
    # the module falls back to; it must never reach a gate.
    if doc.get("source") != "onchain":
        return

    as_of = doc.get("last_checked")
    for key in _GSM_INHERITS_SKY:
        row = adapters.get(key)
        if isinstance(row, dict):
            row["gsm_hours"] = float(hours)
            # The gate ages this off: an observation is evidence of its moment,
            # not forever. Without a stamp a stale reading would hold a gate
            # open indefinitely — the "producer without a schedule" class.
            row["gsm_hours_as_of"] = as_of
            row["gsm_source"] = "onchain"
            row["gsm_witnesses"] = doc.get("witnesses") or []


def generate(
    registry_path: Path = _REGISTRY_FILE,
    output_path: Path = _STATUS_FILE,
    defillama_timeout: int = DEFILLAMA_TIMEOUT,
) -> dict[str, Any]:
    """Build the v2 adapter_status document.

    Does NOT write to disk — call :func:`write` to persist atomically.

    Args:
        registry_path:     Path to ``adapter_registry.json``.
        output_path:       Intended output path (used only for logging).
        defillama_timeout: HTTP timeout in seconds for DeFiLlama fetch.

    Returns:
        A fully formed ``dict`` ready to be serialised as JSON.
    """
    # ── 1. Read adapter registry ─────────────────────────────────────────────
    try:
        with open(registry_path, encoding="utf-8") as fh:
            registry_doc = json.load(fh)
        adapters_meta: dict[str, Any] = registry_doc.get("adapters", registry_doc)
        if not isinstance(adapters_meta, dict):
            log.error("adapter_registry.json: 'adapters' is not a dict — aborting")
            adapters_meta = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        log.error("Cannot read adapter registry %s: %s", registry_path, exc)
        adapters_meta = {}

    # ── 2. Fetch DeFiLlama (best-effort, fail-safe) ──────────────────────────
    pools = _fetch_defillama(timeout=defillama_timeout)
    by_id: dict[str, dict] = {}
    by_pcs: dict[tuple[str, str, str], list[dict]] = {}
    if pools:
        by_id, by_pcs = _build_pool_indexes(pools)

    now_ts = datetime.now(timezone.utc).isoformat()
    live_count = 0

    # Previous snapshot — the basis for carrying a last-known-good observation
    # forward when THIS fetch failed. Without it a single failed HTTP request
    # blanks live_apy for every adapter, and a downstream evidence gate reads that
    # as "nothing is observable" and evacuates the book to cash. A network hiccup
    # must not move capital; only real staleness may. Consumers decide how long an
    # observation stays valid from ``live_apy_as_of`` (its OWN timestamp, not the
    # time this file was written).
    prev_adapters: dict = {}
    try:
        # ``output_path`` IS the file about to be overwritten — the right place to
        # read the previous snapshot from (it was documented as logging-only).
        _prev = json.loads(Path(output_path).read_text(encoding="utf-8"))
        if isinstance(_prev.get("adapters"), dict):
            prev_adapters = _prev["adapters"]
    except Exception:  # noqa: BLE001 — no previous file is normal on a first run
        prev_adapters = {}

    # ── 3. Build adapters dict ───────────────────────────────────────────────
    adapters: dict[str, Any] = {}
    for key, meta in adapters_meta.items():
        if not isinstance(meta, dict):
            continue

        # fallback_apy in registry is decimal (0.052 = 5.2%); convert to %
        fallback_pct = round(float(meta.get("fallback_apy", 0.0)) * 100.0, 4)
        tier_raw = meta.get("tier", 2)
        per_cap = float(meta.get("per_protocol_cap", 0.2))
        chain = str(meta.get("chain", "ethereum"))
        is_active = str(meta.get("status", "active")).lower() in {"active"}

        # One matched pool → both APY and TVL, both provably observed.
        live_apy: Optional[float] = None
        live_pool: Optional[dict] = None
        match_kind: Optional[str] = None
        if pools:
            _match = _lookup_live_pool(key, by_id, by_pcs)
            if _match is not None:
                live_pool, match_kind = _match
                live_apy = _valid_apy(live_pool)
            if live_apy is not None:
                live_count += 1

        # Carry the last-known-good observation forward when this run has none.
        # ``live_apy_as_of`` keeps the ORIGINAL observation time, so age — and
        # therefore validity — is measured from when it was seen, not from now.
        live_as_of: Optional[str] = now_ts if live_apy is not None else None
        live_fresh = live_apy is not None
        if live_apy is None:
            _p = prev_adapters.get(key)
            if isinstance(_p, dict) and _p.get("live_apy") is not None:
                live_apy = _p.get("live_apy")
                live_as_of = _p.get("live_apy_as_of") or _p.get("last_updated")

        apy_used = live_apy if live_apy is not None else fallback_pct

        # TVL from the SAME matched pool when it carries one; else the static
        # estimate — labelled honestly. ADR-053: "live" is stamped only on an
        # observation, never on a constant, because a literal must not be able to
        # clear the $5M floor.
        # Only a PINNED match may be called observed. A hint match still supplies
        # the APY (ranking, guarded by the evidence gate), but its TVL stays
        # "static": the $5M floor is a policy gate, and a gate must not rest on an
        # identity that "best TVL wins" can silently move to a different vault.
        tvl = _TVL_ESTIMATES.get(key, 0.0)
        tvl_source = "static"
        tvl_pool_id: Optional[str] = None
        if live_pool is not None and match_kind == "pinned":
            _t = live_pool.get("tvlUsd")
            if isinstance(_t, (int, float)) and not isinstance(_t, bool) and float(_t) > 0:
                tvl = float(_t)
                tvl_source = "live"
                tvl_pool_id = str(live_pool.get("pool") or "") or None

        adapters[key] = {
            "display_name":     str(meta.get("protocol", key)),
            "apy":              round(apy_used, 4),
            "live_apy":         live_apy,
            # When the observation was actually made (NOT when this file was
            # written) + whether it came from THIS run. A consumer applies its own
            # age window to as_of; ``fresh=False`` means "carried forward".
            "live_apy_as_of":   live_as_of,
            "live_apy_fresh":   live_fresh,
            "fallback_apy":     fallback_pct,
            "tvl_usd":          tvl,
            "tvl_source":       tvl_source,
            # Which pool the observation came from — an auditor can re-fetch this
            # UUID and reproduce the number. None whenever tvl_source != "live".
            "tvl_pool_id":      tvl_pool_id,
            # How the pool was resolved: "pinned" (UUID), "hint" (fuzzy), None.
            "pool_match":       match_kind,
            "tier":             tier_raw,
            "chain":            chain,
            "per_protocol_cap": per_cap,
            "active":           is_active,
            "last_updated":     now_ts,
        }

    live_apy_enabled = bool(pools and live_count > 0)
    # An infrastructure fact, kept separate from "is this protocol observable":
    # False means the FEED did not answer this run. Consumers must treat that as
    # an incident to alert on, never as evidence that protocols became unobservable.
    feed_reachable = bool(pools)

    # ── 4. Shadow top-level entries (backward compat) ────────────────────────
    # Several adapter modules and apy_aggregator.py read specific top-level
    # keys from adapter_status.json.  We mirror the same data here so they
    # continue to work without modification.
    #
    # morpho_steakhouse_adapter.py  → doc["morpho_steakhouse"]["apy"]
    # aave_arbitrum_adapter.py      → doc["aave_arbitrum"]["apy"]
    # apy_aggregator.py sections 2-4 → doc.get("morpho_steakhouse" / "aave_arbitrum" / "pendle_pt")

    ms_entry = adapters.get("morpho_steakhouse", {})
    ms_apy = ms_entry.get("apy", 6.5)

    arb_entry = adapters.get("aave_arbitrum", {})
    arb_apy = arb_entry.get("apy", 4.1)

    pendle_entry = adapters.get("pendle_pt", adapters.get("pendle", {}))
    pendle_apy = pendle_entry.get("apy", 8.0)

    doc: dict[str, Any] = {
        "schema_version":   SCHEMA_VERSION,
        "generated_at":     now_ts,
        "generated_by":     "adapter_status_generator",
        "live_apy_enabled": live_apy_enabled,
        "feed_reachable":   feed_reachable,
        "live_fresh_count": live_count,
        "live_count":       live_count,
        # Primary adapters dict (snake_case keys) — GoLive checker reads here
        "adapters":         adapters,
        # ── Backward-compat top-level shadow entries ──────────────────────
        # These duplicate select adapter data for consumers that have NOT yet
        # been migrated to the new nested format.
        "morpho_steakhouse": {
            "apy":          ms_apy,
            "protocol_key": "morpho-blue",
            "bps_gain":     round(max(0.0, ms_apy - 3.2) * 100.0, 1),
            "tier":         "T1",
            "tvl_usd":      ms_entry.get("tvl_usd", _TVL_ESTIMATES.get("morpho_steakhouse", 0.0)),
        },
        "aave_arbitrum": {
            "apy":      arb_apy,
            "tier":     "T1",
            "network":  "arbitrum",
            "tvl_usd":  arb_entry.get("tvl_usd", _TVL_ESTIMATES.get("aave_arbitrum", 0.0)),
        },
        "pendle_pt": {
            "apy":          pendle_apy,
            "tier":         "T2",
            "chain":        "ethereum",
            "protocol_key": "pendle-pt",
        },
    }

    _merge_gsm_hours(adapters, Path(output_path).parent)
    _merge_erc4626_rates(adapters, Path(output_path).parent)

    log.info(
        "adapter_status_generator: adapters=%d  live_apy_enabled=%s  live_count=%d",
        len(adapters),
        live_apy_enabled,
        live_count,
    )
    return doc


def write(
    doc: dict[str, Any],
    output_path: Path = _STATUS_FILE,
) -> None:
    """Atomically write *doc* to *output_path* (tmp + os.replace).

    Raises on I/O errors (cleans up the temp file).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=".adapter_status_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_path, output_path)
        log.info("adapter_status_generator: wrote %s", output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def run_and_write(
    registry_path: Path = _REGISTRY_FILE,
    output_path: Path = _STATUS_FILE,
    defillama_timeout: int = DEFILLAMA_TIMEOUT,
) -> dict[str, Any]:
    """Convenience: generate + write, returning the document.

    Intended for call-sites that want fire-and-forget behaviour (the caller
    catches all exceptions).
    """
    doc = generate(
        registry_path=registry_path,
        output_path=output_path,
        defillama_timeout=defillama_timeout,
    )
    write(doc, output_path)
    return doc


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:  # noqa: D103
    parser = argparse.ArgumentParser(
        description="Generate data/adapter_status.json (schema_version 2)"
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="write data/adapter_status.json (default: dry-run, print only)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="DIR",
        help="override data directory (default: <repo>/data/)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFILLAMA_TIMEOUT,
        metavar="SEC",
        help=f"DeFiLlama fetch timeout in seconds (default: {DEFILLAMA_TIMEOUT})",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    reg_path = _REGISTRY_FILE
    out_path = _STATUS_FILE
    if args.data_dir:
        dd = Path(args.data_dir)
        reg_path = dd / "adapter_registry.json"
        out_path = dd / "adapter_status.json"

    doc = generate(
        registry_path=reg_path,
        output_path=out_path,
        defillama_timeout=args.timeout,
    )

    adapters = doc.get("adapters", {})
    live_enabled = doc.get("live_apy_enabled", False)
    live_cnt = doc.get("live_count", 0)

    print(
        f"adapters={len(adapters)}"
        f"  schema_version={doc.get('schema_version')}"
        f"  live_apy_enabled={live_enabled}"
        f"  live_count={live_cnt}"
    )
    for key in ("compound_v3", "morpho_steakhouse", "aave_arbitrum"):
        entry = adapters.get(key, {})
        print(
            f"  {key}: apy={entry.get('apy')}%"
            f"  live_apy={entry.get('live_apy')}"
            f"  fallback_apy={entry.get('fallback_apy')}%"
        )

    if args.run:
        write(doc, out_path)
        print(f"Written → {out_path}")
    else:
        print("(dry-run — pass --run to write file)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
