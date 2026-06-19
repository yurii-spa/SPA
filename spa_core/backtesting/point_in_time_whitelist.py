"""
SPA Backtesting — Point-in-Time Whitelist
==========================================
MP-1300 (v9.16)

Prevents look-ahead bias in backtesting by tracking which protocols
were actually live/eligible on a given historical date.

Background: the CPA backtest showed that 87% of strict-portfolio time was
spent in cash because most protocols were not eligible point-in-time.
This module makes that filter explicit and testable.

stdlib only. No external dependencies. Atomic-write-safe (read-only module).
"""

from __future__ import annotations

from datetime import date


# ── Default launch-date table ──────────────────────────────────────────────────
#
# Sources: DeFi protocol launch/deployment records.
# Dates are approximate; use conservative (latest) estimates when uncertain.
# All dates: YYYY-MM-DD (ISO 8601).

_DEFAULT_LAUNCH_DATES: dict[str, str] = {
    "aave_v2_usdc":             "2020-12-17",
    "compound_v2_usdc":         "2018-09-27",
    "aave_v3_usdc":             "2022-03-16",
    "compound_v3_usdc":         "2022-08-26",
    "morpho_blue":              "2023-11-07",
    "morpho_steakhouse_usdc":   "2024-01-15",
    "yearn_v2_yvusdc":          "2020-07-17",
    "yearn_v3_yvusdc":          "2023-06-01",
    "euler_v2_usdc":            "2024-02-06",
    "sky_susds":                "2024-09-01",
    "pendle_pt_susde_mar2025":  "2024-11-01",  # specific market
    "sfrax_usdc":               "2023-03-01",
    "maple_syrupusdc":          "2024-06-01",
    "aave_v3_base":             "2023-08-09",
    "morpho_blue_base":         "2023-12-01",
}


class PointInTimeWhitelist:
    """
    Knows which adapter/protocol was eligible on a given historical date.
    Prevents look-ahead bias in backtesting.

    Protocol launch dates (approximate, based on DeFi history):
    - aave_v2_usdc: 2020-12-17
    - compound_v2_usdc: 2018-09-27
    - aave_v3_usdc: 2022-03-16
    - compound_v3_usdc: 2022-08-26
    - morpho_blue: 2023-11-07
    - morpho_steakhouse_usdc: 2024-01-15
    - yearn_v2_yvusdc: 2020-07-17
    - yearn_v3_yvusdc: 2023-06-01
    - euler_v2_usdc: 2024-02-06
    - sky_susds: 2024-09-01
    - pendle_pt_susde_mar2025: 2024-11-01 (specific market)
    - sfrax_usdc: 2023-03-01
    - maple_syrupusdc: 2024-06-01
    - aave_v3_base: 2023-08-09
    - morpho_blue_base: 2023-12-01
    """

    def __init__(self, launch_dates: dict | None = None) -> None:
        """
        Args:
            launch_dates: Optional mapping of protocol_id -> "YYYY-MM-DD" launch date.
                          If None, uses the built-in table of DeFi protocol launch dates.
                          Pass a custom dict to extend or override the defaults.
        """
        if launch_dates is not None:
            self._launch_dates: dict[str, str] = dict(launch_dates)
        else:
            self._launch_dates = dict(_DEFAULT_LAUNCH_DATES)

    # ── Core eligibility API ───────────────────────────────────────────────────

    def is_eligible(self, protocol_id: str, date_str: str) -> bool:
        """
        Returns True if the protocol was live/eligible on the given date.

        Unknown protocols (not in the launch-dates table) always return False —
        conservative assumption: if we don't know the launch date, we exclude it.

        Args:
            protocol_id: Protocol identifier string (e.g. "aave_v3_usdc").
            date_str:    ISO date string "YYYY-MM-DD".

        Returns:
            True if protocol was launched on or before date_str.
        """
        launch = self._launch_dates.get(protocol_id)
        if launch is None:
            return False  # unknown → not eligible (conservative)
        return date_str >= launch

    def eligible_protocols(self, date_str: str) -> list[str]:
        """
        Returns sorted list of all protocols eligible on the given date.

        Args:
            date_str: ISO date string "YYYY-MM-DD".

        Returns:
            Alphabetically sorted list of protocol_id strings that were
            live on date_str.
        """
        return sorted(
            pid for pid in self._launch_dates
            if self.is_eligible(pid, date_str)
        )

    def ineligible_reason(self, protocol_id: str, date_str: str) -> str:
        """
        Returns a human-readable reason why a protocol is not eligible.

        Args:
            protocol_id: Protocol identifier string.
            date_str:    ISO date string "YYYY-MM-DD".

        Returns:
            Empty string ("") if protocol IS eligible on date_str.
            Descriptive reason string if protocol is NOT eligible.
        """
        launch = self._launch_dates.get(protocol_id)
        if launch is None:
            return f"protocol '{protocol_id}' not in whitelist"
        if date_str < launch:
            return (
                f"protocol '{protocol_id}' launched {launch}, "
                f"but requested date {date_str} is before launch"
            )
        return ""  # eligible → no reason

    def coverage_stats(self, protocols: list[str], start: str, end: str) -> dict:
        """
        Computes per-protocol eligibility coverage over a date range.

        Uses arithmetic date arithmetic (O(1) per protocol) rather than
        iterating every day, making it efficient for multi-year ranges.

        Args:
            protocols: List of protocol_id strings to analyse.
            start:     Start date "YYYY-MM-DD" (inclusive).
            end:       End date "YYYY-MM-DD" (inclusive).

        Returns:
            Dict mapping protocol_id -> {eligible_days, total_days, pct}.

            Example::

                {
                  "aave_v3_usdc": {
                      "eligible_days": 500,
                      "total_days": 1466,
                      "pct": 34.1,
                  }
                }

        Note:
            If end < start, returns zero stats for all protocols.
        """
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)

        if end_d < start_d:
            return {
                p: {"eligible_days": 0, "total_days": 0, "pct": 0.0}
                for p in protocols
            }

        total_days = (end_d - start_d).days + 1
        result: dict = {}

        for proto in protocols:
            launch = self._launch_dates.get(proto)

            if launch is None:
                # Unknown protocol — ineligible for the entire range
                eligible_days = 0
            else:
                launch_d = date.fromisoformat(launch)

                if launch_d > end_d:
                    # Protocol not yet launched at end of range
                    eligible_days = 0
                elif launch_d <= start_d:
                    # Already live at the start of the range
                    eligible_days = total_days
                else:
                    # Partial: launched somewhere inside the range
                    eligible_days = (end_d - launch_d).days + 1

            pct = (
                round(eligible_days / total_days * 100, 1)
                if total_days > 0
                else 0.0
            )
            result[proto] = {
                "eligible_days": eligible_days,
                "total_days": total_days,
                "pct": pct,
            }

        return result

    # ── Introspection helpers ──────────────────────────────────────────────────

    def known_protocols(self) -> list[str]:
        """Returns sorted list of all protocols registered in the whitelist."""
        return sorted(self._launch_dates.keys())

    def launch_date(self, protocol_id: str) -> str | None:
        """
        Returns the launch date string for a protocol, or None if unknown.

        Args:
            protocol_id: Protocol identifier string.

        Returns:
            "YYYY-MM-DD" string, or None.
        """
        return self._launch_dates.get(protocol_id)

    def __len__(self) -> int:
        """Number of protocols in the whitelist."""
        return len(self._launch_dates)

    def __contains__(self, protocol_id: str) -> bool:
        """Supports `protocol_id in whitelist` syntax."""
        return protocol_id in self._launch_dates
