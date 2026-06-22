"""
spa_core/analytics/source_integration_helper.py

Mini-utility for wiring new DeFiLlama sources into the SPA data pipeline.

Read-only / advisory module — never modifies allocator, risk, or execution
domains. Only writes to data/backtest/source_pipeline.json (atomic).

Stdlib only. No external dependencies.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Default paths (relative to repo root; override in tests)
# ---------------------------------------------------------------------------
_DEFAULT_PIPELINE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "data", "backtest", "source_pipeline.json",
)

# UUID v4 pattern (flexible: allows any hex in 8-4-4-4-12 segments)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class SourceIntegrationHelper:
    """Utility for integrating new DeFiLlama sources into SPA adapters.

    All write operations are atomic (tmp + os.replace).
    This class is read-only / advisory: it never touches the allocator,
    risk policy, or execution domain.
    """

    def __init__(self, pipeline_path: Optional[str] = None) -> None:
        self._pipeline_path = os.path.abspath(
            pipeline_path if pipeline_path is not None else _DEFAULT_PIPELINE_PATH
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_pool_id(self, pool_id: str) -> Dict[str, Any]:
        """Validates that pool_id looks like a DeFiLlama UUID.

        DeFiLlama pool IDs follow UUID v4 format:
            xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        (8-4-4-4-12 hex segments, separated by hyphens, total 36 chars)

        Returns:
            {"valid": bool, "reason": str}
        """
        if not isinstance(pool_id, str):
            return {"valid": False, "reason": "pool_id must be a string"}

        pool_id = pool_id.strip()

        if len(pool_id) < 36:
            return {
                "valid": False,
                "reason": f"Too short: {len(pool_id)} chars (expected 36 for UUID format)",
            }

        if not _UUID_RE.match(pool_id):
            return {
                "valid": False,
                "reason": (
                    "Does not match UUID format "
                    "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (hex, hyphens)"
                ),
            }

        return {"valid": True, "reason": "Valid UUID format"}

    def generate_adapter_snippet(
        self,
        source_name: str,
        pool_id: str,
        fallback_apy: float = 0.0,
    ) -> str:
        """Generates a Python code snippet for a DeFiLlama-backed adapter.

        The snippet is ready to paste into a new adapter file under
        spa_core/adapters/. It follows SPA conventions:
          - stdlib only (urllib.request, json)
          - never raises — returns fallback on error
          - docstring includes pool_id for traceability

        Args:
            source_name:  Human name for the source (e.g. 'gmx_v2_btc').
            pool_id:      DeFiLlama pool UUID confirmed via find_defillama_sources.py.
            fallback_apy: APY value to return when the live fetch fails.

        Returns:
            Multi-line Python string (non-empty).
        """
        sanitized_name = re.sub(r"[^a-zA-Z0-9_]", "_", source_name)

        snippet = f'''\
# ---------------------------------------------------------------------------
# {sanitized_name} — DeFiLlama adapter snippet
# Pool ID confirmed via scripts/find_defillama_sources.py
# Pool ID: {pool_id}
# Source name: {source_name}
# ---------------------------------------------------------------------------

import json
import urllib.request
from spa_core.utils.atomic import atomic_save

DEFILLAMA_POOL_ID_{sanitized_name.upper()} = "{pool_id}"
FALLBACK_APY_{sanitized_name.upper()} = {fallback_apy!r}


def fetch_{sanitized_name}_apy(timeout: int = 10) -> dict:
    """Fetches live APY for {source_name} from DeFiLlama.

    Pool: {pool_id}

    Returns:
        {{
            "apy":     float | None,
            "tvl_usd": float | None,
            "source":  str,
        }}
    On any error returns fallback APY without raising.
    """
    url = f"https://yields.llama.fi/chart/{{DEFILLAMA_POOL_ID_{sanitized_name.upper()}}}"
    try:
        raw = urllib.request.urlopen(url, timeout=timeout).read()
        data = json.loads(raw)
        rows = data.get("data", [])
        if not rows:
            raise ValueError("Empty data series from DeFiLlama")
        latest = rows[-1]
        return {{
            "apy":     float(latest.get("apy") or 0),
            "tvl_usd": float(latest.get("tvlUsd") or 0),
            "source":  f"defillama:{{DEFILLAMA_POOL_ID_{sanitized_name.upper()}}}",
        }}
    except Exception:
        return {{
            "apy":     FALLBACK_APY_{sanitized_name.upper()},
            "tvl_usd": None,
            "source":  "defillama:error",
        }}
'''
        return snippet

    def update_source_pipeline(
        self,
        source_id: str,
        pool_id: str,
        status: str = "PENDING",
    ) -> bool:
        """Updates data/backtest/source_pipeline.json with a source entry.

        Creates the file and parent directories if they don't exist.
        Write is atomic (tmp + os.replace).

        Args:
            source_id:  Unique source identifier (e.g. 'gmx_v2_btc').
            pool_id:    DeFiLlama pool UUID.
            status:     One of PENDING / TESTING / INTEGRATED / CLEAN.

        Returns:
            True on success, False on write failure.
        """
        # Load existing data
        pipeline = self._load_pipeline()

        # Update / insert entry
        now = datetime.now(timezone.utc).isoformat()
        if source_id in pipeline.get("sources", {}):
            pipeline["sources"][source_id].update(
                {
                    "pool_id": pool_id,
                    "status": status,
                    "updated_at": now,
                }
            )
        else:
            pipeline.setdefault("sources", {})[source_id] = {
                "pool_id": pool_id,
                "status": status,
                "created_at": now,
                "updated_at": now,
            }

        pipeline["last_updated"] = now

        return self._save_pipeline(pipeline)

    def integration_checklist(self, source_id: str) -> List[str]:
        """Returns the 5-step integration checklist for adding a new source.

        Args:
            source_id:  Name of the source (used in step text).

        Returns:
            List of exactly 5 checklist strings.
        """
        return [
            (
                f"[ ] Step 1 — DISCOVER: Run "
                f"`python3 scripts/find_defillama_sources.py --protocol {source_id}` "
                f"and record the Pool ID."
            ),
            (
                "[ ] Step 2 — VERIFY: Confirm the pool has live history via "
                "`https://yields.llama.fi/chart/<POOL_ID>` (expect ≥ 30 data points)."
            ),
            (
                f"[ ] Step 3 — IMPLEMENT: Add `DEFILLAMA_POOL_ID` constant and "
                f"`fetch_{source_id}_apy()` function to the adapter file under "
                f"`spa_core/adapters/`. Stdlib only, no external deps."
            ),
            (
                "[ ] Step 4 — REGISTER: Add the adapter to `ADAPTER_REGISTRY` in "
                "`spa_core/adapters/__init__.py` and run a dry-run cycle: "
                "`python3 -m spa_core.paper_trading.cycle_runner --verbose`."
            ),
            (
                f"[ ] Step 5 — TRACK: Call `update_source_pipeline('{source_id}', "
                f"'<POOL_ID>', status='INTEGRATED')` and push all changed files via "
                f"`push_to_github.py`. Update KANBAN.json to DATA_READY."
            ),
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_pipeline(self) -> dict:
        """Loads pipeline JSON from disk; returns empty structure on any error."""
        try:
            with open(self._pipeline_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"sources": {}, "last_updated": None}

    def _save_pipeline(self, data: dict) -> bool:
        """Atomically saves pipeline JSON. Returns True on success."""
        try:
            dir_path = os.path.dirname(self._pipeline_path)
            os.makedirs(dir_path, exist_ok=True)

            atomic_save(data, self._pipeline_path)
            return True
        except Exception:
            return False
