# SPA Public API Reference

**Version:** 10.0.0  
**Module:** `spa_core`  
**Source:** `spa_core/__init__.py`

All symbols listed here are importable directly from `spa_core` and are stable across patch versions.

---

## Version

### `VERSION: str`
Current SPA version string, e.g. `"10.0.0"`.

### `__version__: str`
PEP 8 alias for `VERSION`. Identical value.

```python
from spa_core import VERSION, __version__
assert VERSION == __version__  # always True
```

---

## Base Classes

### `BaseAnalytics`
Abstract base for all read-only analytics modules.

| Method | Signature | Description |
|--------|-----------|-------------|
| `save` | `(data=None, path=None) -> str` | Atomic write to `OUTPUT_PATH` (tmp+replace). |
| `load` | `(path=None) -> Any` | Load JSON from `OUTPUT_PATH`. |
| `to_dict` | `() -> dict` | Abstract — subclass must implement. |
| `_path` | `(relative) -> str` | Resolve path relative to base_dir. |
| `_ensure_dir` | `(path) -> None` | mkdir -p for output directory. |

```python
from spa_core import BaseAnalytics

class MyModule(BaseAnalytics):
    OUTPUT_PATH = "data/my_output.json"

    def to_dict(self) -> dict:
        return {"value": 42}
```

### `BaseAdapter`
Abstract base for all read-only protocol adapters.

| Method | Signature | Description |
|--------|-----------|-------------|
| `current_apy` | `() -> float` | Abstract — return APY as decimal (e.g. 0.035 = 3.5%). |
| `safe_apy` | `() -> float` | `current_apy()` clamped to `[0.0, 1.0]`; returns 0.0 on error. |
| `is_research_only` | `() -> bool` | True if `RESEARCH_ONLY = True` on the class. |
| `source_metadata` | `() -> dict` | Returns dict with name, tier, research_only flag. |
| `_cache_expired` | `() -> bool` | True if cache TTL has elapsed. |

```python
from spa_core import BaseAdapter

class MyAdapter(BaseAdapter):
    TIER = "T1"
    CACHE_TTL = 300

    def current_apy(self) -> float:
        return 0.035  # 3.5%
```

### `BaseReport`
Abstract base for report generators (extends BaseAnalytics with markdown).

| Method | Signature | Description |
|--------|-----------|-------------|
| `to_markdown` | `() -> str` | Abstract — return markdown string. |
| `save_markdown` | `(path=None) -> str` | Atomic write of `to_markdown()` to `.md` file. |
| `to_dict` | `() -> dict` | Abstract — return dict representation. |
| `save` | `(data=None, path=None) -> str` | Atomic JSON save. |
| `load` | `(path=None) -> Any` | Load JSON. |

---

## Error Hierarchy

All SPA exceptions inherit from `SPAError`.

```
SPAError (E001)
├── GateError (G001)       — validation gate failed
├── SourceError (S001)     — data source unavailable / stale
├── ConfigError (C001)     — bad configuration / missing key
├── RegistryError (R001)   — adapter or strategy not registered
├── AdapterError (A001)    — adapter fetch / parse failure
├── AllocationError (L001) — portfolio allocation constraint violated
└── LiveTradingForbiddenError (X001) — live trading blocked by safeguard
```

### `SPAError`
Base class for all SPA exceptions. Code: `E001`.

```python
from spa_core import SPAError
try:
    raise SPAError("something failed")
except SPAError as e:
    print(e)  # "something failed"
```

### `GateError`
Raised when a validation gate (backtest, pre-paper, go-live) blocks progression.

```python
from spa_core import GateError
raise GateError("pre_paper_gate: expanded universe verification STRICT_BLOCKED")
```

### `SourceError`
Raised when a data source (DeFiLlama, on-chain RPC) is unavailable or stale.

```python
from spa_core import SourceError
raise SourceError("DeFiLlama API returned non-200 status")
```

### `ConfigError`
Raised when required configuration is missing or malformed.

```python
from spa_core import ConfigError
raise ConfigError("DEFILLAMA_API_URL must not be empty")
```

### `RegistryError`
Raised when an adapter or strategy key is not found in the registry.

```python
from spa_core import RegistryError
raise RegistryError("adapter 'unknown_protocol' not in ADAPTER_REGISTRY")
```

### `AdapterError`
Raised when an adapter fails to fetch or parse protocol data.

```python
from spa_core import AdapterError
raise AdapterError("aave_v3: TVL fetch timed out after 8s")
```

### `AllocationError`
Raised when a portfolio allocation violates a RiskPolicy constraint.

```python
from spa_core import AllocationError
raise AllocationError("T2 total cap exceeded: 52% > 50% limit")
```

### `LiveTradingForbiddenError`
Raised when code attempts a live-trade action during the paper-trading period.

```python
from spa_core import LiveTradingForbiddenError
raise LiveTradingForbiddenError("live execution blocked — paper period active")
```

---

## Atomic I/O

### `atomic_save(data, path) -> None`
Write `data` (dict or list) to `path` atomically using `tmp + os.replace`.  
Never leaves a partial file on disk.

```python
from spa_core import atomic_save
atomic_save({"value": 42}, "data/my_state.json")
```

### `atomic_load(path) -> dict | list | None`
Read JSON from `path` defensively. Returns `None` on missing or malformed file.

```python
from spa_core import atomic_load
d = atomic_load("data/my_state.json")
if d is not None:
    print(d["value"])
```

---

## KANBAN Helpers

### `increment_done(n=1) -> int`
Increment `done_count` in `KANBAN.json` by `n`. Returns new count.  
Reads and writes atomically — safe against the concurrent hourly cycle.

```python
from spa_core import increment_done
new_count = increment_done()
```

---

## Adapter Registry

### `ADAPTER_REGISTRY: dict[str, type]`
Maps adapter name → adapter class for all registered protocols.

```python
from spa_core import ADAPTER_REGISTRY
for name, cls in ADAPTER_REGISTRY.items():
    a = cls()
    print(f"{name}: APY={a.safe_apy():.2%}")
```

Registry is defined in `spa_core/adapters/__init__.py` and includes adapters for:
Aave V3, Compound V3, Morpho Steakhouse, Morpho Blue, Yearn V3, Euler V2, Maple, and others.

---

## Safety

### `LiveTradingGate`
Context manager / checker that blocks live trading during the paper period.

```python
from spa_core import LiveTradingGate

gate = LiveTradingGate()
if gate.is_live_allowed():
    # proceed with live execution
    pass
```

### `live_trading_forbidden() -> None`
Raises `LiveTradingForbiddenError` unconditionally.  
Decorate or call at the top of any live-execution function to enforce the paper-period safeguard.

```python
from spa_core import live_trading_forbidden

def execute_trade(order):
    live_trading_forbidden()  # raises during paper period
    # ... live execution code (unreachable in paper mode)
```

---

## Optional / Legacy Exports

The following are also re-exported from `spa_core` for backwards compatibility.  
They may be `None` if the underlying module is not present.

| Symbol | Source | Description |
|--------|--------|-------------|
| `BacktestGate` | `spa_core.backtesting` | Historical backtest gate |
| `PITEngine` | `spa_core.backtesting.pit_engine` | Point-in-time data engine |
| `RS001LiveAPYEngine` | `spa_core.analytics.rs001_live_apy_engine` | Research strategy RS-001 |
| `RS002LiveAPYEngine` | `spa_core.analytics.rs002_live_apy_engine` | Research strategy RS-002 |

---

## Complete `__all__`

```python
from spa_core import __all__
# ['VERSION', '__version__', 'BaseAnalytics', 'BaseAdapter', 'BaseReport',
#  'SPAError', 'GateError', 'SourceError', 'ConfigError', 'RegistryError',
#  'AdapterError', 'AllocationError', 'LiveTradingForbiddenError',
#  'atomic_save', 'atomic_load', 'increment_done', 'ADAPTER_REGISTRY',
#  'LiveTradingGate', 'live_trading_forbidden',
#  'BacktestGate', 'PITEngine', 'RS001LiveAPYEngine', 'RS002LiveAPYEngine']
```

---

*Generated by MP-1484 (v11.00) — 2026-06-20*
