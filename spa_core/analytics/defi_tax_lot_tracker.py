"""
MP-831: DeFiTaxLotTracker
Tracks cost-basis tax lots for DeFi positions using FIFO and LIFO methods.
Computes realized and unrealized gains/losses for advisory reporting.
Advisory/read-only, stdlib only.
"""

import json
import os
import time
from datetime import date, datetime
from pathlib import Path

DATA_FILE = Path("data/tax_lot_log.json")
MAX_ENTRIES = 100


def _parse_date(s: str) -> date:
    """Parse ISO date string to date object."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def _process_disposal(lots: list, disposal: dict, short_term_days: int, today: date) -> dict:
    """
    Process a disposal (sale) of lots using FIFO or LIFO method.

    lots: list of lot dicts (original, not mutated)
    disposal: {quantity, proceeds_usd, method}
    short_term_days: threshold for short vs long term
    today: reference date for days_held computation

    Returns disposal_result dict.
    """
    method = disposal.get("method", "FIFO").upper()
    qty_to_sell = float(disposal.get("quantity", 0.0))
    proceeds = float(disposal.get("proceeds_usd", 0.0))

    if qty_to_sell <= 0:
        return None

    # Sort lots according to method
    if method == "FIFO":
        sorted_lots = sorted(lots, key=lambda x: _parse_date(x["acquired_date"]))
    elif method == "LIFO":
        sorted_lots = sorted(lots, key=lambda x: _parse_date(x["acquired_date"]), reverse=True)
    else:
        sorted_lots = sorted(lots, key=lambda x: _parse_date(x["acquired_date"]))

    # Filter out zero-quantity lots
    sorted_lots = [lot for lot in sorted_lots if float(lot.get("quantity", 0.0)) > 0]

    # Compute total available
    total_available = sum(float(lot.get("quantity", 0.0)) for lot in sorted_lots)

    # Cap at total available
    if qty_to_sell > total_available:
        qty_to_sell = total_available

    remaining_to_sell = qty_to_sell
    total_cost_basis_sold = 0.0
    short_term_gain = 0.0
    long_term_gain = 0.0
    lots_used = []

    for lot in sorted_lots:
        if remaining_to_sell <= 0:
            break

        lot_qty = float(lot.get("quantity", 0.0))
        lot_cost_basis = float(lot.get("cost_basis_usd", 0.0))
        acquired = _parse_date(lot["acquired_date"])
        days_held = (today - acquired).days
        is_short_term = days_held < short_term_days

        # How much from this lot
        qty_from_lot = min(remaining_to_sell, lot_qty)
        fraction = qty_from_lot / lot_qty if lot_qty > 0 else 0.0

        cost_basis_fraction = lot_cost_basis * fraction

        # Proceeds allocated proportionally to quantity sold
        proceeds_fraction = proceeds * (qty_from_lot / qty_to_sell) if qty_to_sell > 0 else 0.0

        realized = proceeds_fraction - cost_basis_fraction

        if is_short_term:
            short_term_gain += realized
        else:
            long_term_gain += realized

        total_cost_basis_sold += cost_basis_fraction
        lots_used.append(lot["lot_id"])
        remaining_to_sell -= qty_from_lot

    realized_gain = short_term_gain + long_term_gain

    return {
        "method": method,
        "quantity_sold": qty_to_sell,
        "proceeds_usd": proceeds,
        "cost_basis_sold_usd": total_cost_basis_sold,
        "realized_gain_usd": realized_gain,
        "short_term_gain_usd": short_term_gain,
        "long_term_gain_usd": long_term_gain,
        "lots_used": lots_used,
    }


def analyze(positions: list, config: dict = None) -> dict:
    """
    Analyze tax lots for a list of DeFi positions.

    positions: list of {
        "protocol": str,
        "lots": list of {
            "lot_id": str,
            "acquired_date": str,   # ISO date e.g. "2024-01-15"
            "cost_basis_usd": float,
            "quantity": float,
            "current_price_usd": float  # current price per unit
        },
        "disposal": dict | None
    }
    config: {
        "short_term_days": int  # default 365
    }

    Returns: {
        "positions": list of position results,
        "portfolio_summary": {...},
        "timestamp": float
    }
    """
    if config is None:
        config = {}
    short_term_days = int(config.get("short_term_days", 365))
    today = date.today()

    results = []

    total_cost_basis = 0.0
    total_current_value = 0.0
    total_unrealized_gain = 0.0
    total_realized_gain = 0.0
    total_short_term_gain = 0.0
    total_long_term_gain = 0.0

    for pos in positions:
        protocol = pos.get("protocol", "")
        lots = pos.get("lots", [])
        disposal = pos.get("disposal", None)

        # Compute per-lot values
        pos_cost_basis = 0.0
        pos_current_value = 0.0

        for lot in lots:
            qty = float(lot.get("quantity", 0.0))
            cost = float(lot.get("cost_basis_usd", 0.0))
            price = float(lot.get("current_price_usd", 0.0))
            pos_cost_basis += cost
            pos_current_value += qty * price

        unrealized_gain = pos_current_value - pos_cost_basis
        unrealized_gain_pct = 0.0
        if pos_cost_basis != 0:
            unrealized_gain_pct = (unrealized_gain / pos_cost_basis) * 100.0

        # Process disposal if present
        disposal_result = None
        if disposal is not None:
            disposal_result = _process_disposal(lots, disposal, short_term_days, today)

        pos_result = {
            "protocol": protocol,
            "total_cost_basis_usd": pos_cost_basis,
            "total_current_value_usd": pos_current_value,
            "unrealized_gain_usd": unrealized_gain,
            "unrealized_gain_pct": unrealized_gain_pct,
            "lot_count": len(lots),
            "disposal_result": disposal_result,
        }
        results.append(pos_result)

        # Accumulate portfolio totals
        total_cost_basis += pos_cost_basis
        total_current_value += pos_current_value
        total_unrealized_gain += unrealized_gain
        if disposal_result is not None:
            total_realized_gain += disposal_result["realized_gain_usd"]
            total_short_term_gain += disposal_result["short_term_gain_usd"]
            total_long_term_gain += disposal_result["long_term_gain_usd"]

    return {
        "positions": results,
        "portfolio_summary": {
            "total_cost_basis_usd": total_cost_basis,
            "total_current_value_usd": total_current_value,
            "total_unrealized_gain_usd": total_unrealized_gain,
            "total_realized_gain_usd": total_realized_gain,
            "total_short_term_gain_usd": total_short_term_gain,
            "total_long_term_gain_usd": total_long_term_gain,
        },
        "timestamp": time.time(),
    }


def save_log(result: dict, data_file: Path = DATA_FILE) -> None:
    """Atomically append result to ring-buffer JSON (max MAX_ENTRIES)."""
    data_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(data_file.read_text())
        if not isinstance(existing, list):
            existing = []
    except Exception:
        existing = []
    existing.append(result)
    existing = existing[-MAX_ENTRIES:]
    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2))
    os.replace(tmp, data_file)


def load_log(data_file: Path = DATA_FILE) -> list:
    """Return saved log; [] on any read/parse error."""
    try:
        return json.loads(data_file.read_text())
    except Exception:
        return []


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MP-831 DeFiTaxLotTracker")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print; no write (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute and atomically write to data file")
    parser.add_argument("--data-dir", default="data", help="data directory")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_file = data_dir / "tax_lot_log.json"

    # Try to load current positions
    positions_file = data_dir / "current_positions.json"
    positions = []
    try:
        raw = json.loads(positions_file.read_text())
        if isinstance(raw, list):
            positions = raw
    except Exception:
        pass

    result = analyze(positions)

    print("[MP-831] DeFiTaxLotTracker")
    print(f"  positions analyzed : {len(result['positions'])}")
    summary = result["portfolio_summary"]
    print(f"  total_cost_basis   : ${summary['total_cost_basis_usd']:,.2f}")
    print(f"  total_current_val  : ${summary['total_current_value_usd']:,.2f}")
    print(f"  unrealized_gain    : ${summary['total_unrealized_gain_usd']:,.2f}")
    print(f"  realized_gain      : ${summary['total_realized_gain_usd']:,.2f}")
    print(f"  short_term_gain    : ${summary['total_short_term_gain_usd']:,.2f}")
    print(f"  long_term_gain     : ${summary['total_long_term_gain_usd']:,.2f}")

    if args.run:
        save_log(result, data_file)
        print(f"\n  [written] → {data_file}")


if __name__ == "__main__":
    _main()
