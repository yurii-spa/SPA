"""
MP-1117 ProtocolDeFiEpochRewardTimingAnalyzer
Advisory/read-only analytics module.

Analyzes optimal entry/exit timing relative to protocol reward epochs.
Entering just before epoch end gives minimal rewards; entering at epoch
start maximizes duration. Detects epoch timing arbitrage opportunities.

Inputs:
  epoch_duration_hours    (int)   e.g. 168 for weekly
  hours_elapsed_in_epoch  (float) how far into current epoch
  reward_per_epoch_usd    (float) total rewards distributed this epoch
  total_staked_usd        (float) total TVL eligible for rewards
  my_stake_usd            (float) my staked amount
  entry_cost_usd          (float) gas cost to enter
  exit_cost_usd           (float) gas cost to exit
  protocol_name           (str)   protocol identifier

Outputs:
  epoch_progress_pct         (float) elapsed / duration * 100
  hours_remaining_in_epoch   (float) duration - elapsed
  my_share_pct               (float) my_stake / (total + my_stake) * 100
  expected_epoch_reward_usd  (float) my_share * reward_per_epoch
  annualized_reward_apy_pct  (float) annual reward / my_stake * 100
  entry_timing_score         (int)   0-100, 100=best (early in epoch)
  timing_label               (str)   PERFECT_ENTRY / GOOD_ENTRY / NEUTRAL_TIMING
                                     / LATE_ENTRY / EPOCH_ALMOST_DONE

Data log: data/epoch_reward_timing_log.json (ring-buffer, max 100 entries)
Pure stdlib. No external dependencies.
Atomic writes: tmp + os.replace.
"""

import json
import os
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_CAP = 100
_HOURS_PER_YEAR = 365.0 * 24.0  # 8760

# Timing label thresholds (inclusive upper bound)
# epoch_progress_pct <= 10  → PERFECT_ENTRY
# epoch_progress_pct <= 30  → GOOD_ENTRY
# epoch_progress_pct <= 60  → NEUTRAL_TIMING
# epoch_progress_pct <= 85  → LATE_ENTRY
# epoch_progress_pct >  85  → EPOCH_ALMOST_DONE
_TIMING_THRESHOLDS = [
    (10.0,  "PERFECT_ENTRY"),
    (30.0,  "GOOD_ENTRY"),
    (60.0,  "NEUTRAL_TIMING"),
    (85.0,  "LATE_ENTRY"),
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _timing_label(epoch_progress_pct: float) -> str:
    """Return timing label for the given epoch progress percentage."""
    for threshold, label in _TIMING_THRESHOLDS:
        if epoch_progress_pct <= threshold:
            return label
    return "EPOCH_ALMOST_DONE"


def _entry_timing_score(epoch_progress_pct: float) -> int:
    """
    Return entry timing score 0-100.
    100 = best timing (very early in epoch).
    0   = worst timing (end of epoch).
    Linear: score = max(0, int(100 - epoch_progress_pct)).
    """
    return max(0, int(100 - epoch_progress_pct))


def _atomic_write(path: str, data) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    dir_part = os.path.dirname(path)
    if dir_part:
        os.makedirs(dir_part, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(
    epoch_duration_hours: int,
    hours_elapsed_in_epoch: float,
    reward_per_epoch_usd: float,
    total_staked_usd: float,
    my_stake_usd: float,
    entry_cost_usd: float,
    exit_cost_usd: float,
    protocol_name: str,
) -> dict:
    """
    Analyze epoch reward timing for a DeFi protocol.

    Parameters
    ----------
    epoch_duration_hours : int
        Total duration of one reward epoch in hours (e.g. 168 = weekly).
        Clamped to minimum 1.
    hours_elapsed_in_epoch : float
        Hours elapsed so far in the current epoch.
        Clamped to [0, epoch_duration_hours].
    reward_per_epoch_usd : float
        Total USD rewards distributed in this epoch.
    total_staked_usd : float
        Total TVL eligible for rewards (before adding my_stake_usd).
    my_stake_usd : float
        My staked amount in USD.
    entry_cost_usd : float
        Gas cost in USD to enter the position.
    exit_cost_usd : float
        Gas cost in USD to exit the position.
    protocol_name : str
        Name of the protocol.

    Returns
    -------
    dict with keys:
        protocol_name, epoch_duration_hours, hours_elapsed_in_epoch,
        epoch_progress_pct, hours_remaining_in_epoch, my_share_pct,
        expected_epoch_reward_usd, annualized_reward_apy_pct,
        entry_timing_score, timing_label, total_cost_usd, net_reward_usd,
        epochs_per_year, timestamp.
    """
    dur = float(max(1, int(epoch_duration_hours)))
    elapsed = float(hours_elapsed_in_epoch)
    elapsed = max(0.0, min(elapsed, dur))

    epoch_progress_pct = elapsed / dur * 100.0
    hours_remaining_in_epoch = dur - elapsed

    total = float(total_staked_usd)
    my_stake = float(my_stake_usd)
    pool = total + my_stake

    if pool > 0.0:
        my_share_pct = my_stake / pool * 100.0
    else:
        my_share_pct = 0.0

    reward = float(reward_per_epoch_usd)
    expected_epoch_reward_usd = my_share_pct / 100.0 * reward

    epochs_per_year = _HOURS_PER_YEAR / dur
    if my_stake > 0.0:
        annual_reward_usd = expected_epoch_reward_usd * epochs_per_year
        annualized_reward_apy_pct = annual_reward_usd / my_stake * 100.0
    else:
        annualized_reward_apy_pct = 0.0

    label = _timing_label(epoch_progress_pct)
    score = _entry_timing_score(epoch_progress_pct)

    total_cost_usd = float(entry_cost_usd) + float(exit_cost_usd)
    net_reward_usd = expected_epoch_reward_usd - total_cost_usd

    return {
        "protocol_name": str(protocol_name),
        "epoch_duration_hours": int(epoch_duration_hours),
        "hours_elapsed_in_epoch": elapsed,
        "epoch_progress_pct": epoch_progress_pct,
        "hours_remaining_in_epoch": hours_remaining_in_epoch,
        "my_share_pct": my_share_pct,
        "expected_epoch_reward_usd": expected_epoch_reward_usd,
        "annualized_reward_apy_pct": annualized_reward_apy_pct,
        "entry_timing_score": score,
        "timing_label": label,
        "total_cost_usd": total_cost_usd,
        "net_reward_usd": net_reward_usd,
        "epochs_per_year": epochs_per_year,
        "timestamp": time.time(),
    }


def log_result(
    result: dict,
    log_path: str = "data/epoch_reward_timing_log.json",
) -> None:
    """
    Append a summary entry to the ring-buffer log.
    Ring-buffer capped at _LOG_CAP (100) entries.
    Atomic write: tmp + os.replace.
    """
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
        if not isinstance(entries, list):
            entries = []
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entry = {
        "timestamp": result.get("timestamp", time.time()),
        "protocol_name": result.get("protocol_name"),
        "epoch_duration_hours": result.get("epoch_duration_hours"),
        "epoch_progress_pct": result.get("epoch_progress_pct"),
        "timing_label": result.get("timing_label"),
        "entry_timing_score": result.get("entry_timing_score"),
        "my_share_pct": result.get("my_share_pct"),
        "expected_epoch_reward_usd": result.get("expected_epoch_reward_usd"),
        "annualized_reward_apy_pct": result.get("annualized_reward_apy_pct"),
        "net_reward_usd": result.get("net_reward_usd"),
    }

    entries.append(entry)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]

    _atomic_write(log_path, entries)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-1117 ProtocolDeFiEpochRewardTimingAnalyzer"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Compute and print result; do NOT write to log (default behaviour)"
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Compute result AND write to log"
    )
    parser.add_argument(
        "--data-dir", default="data",
        help="Directory for JSON state files (default: data)"
    )
    args = parser.parse_args()

    # Demo: weekly epoch (168 h), 25% elapsed → GOOD_ENTRY
    demo = analyze(
        epoch_duration_hours=168,
        hours_elapsed_in_epoch=42.0,
        reward_per_epoch_usd=10_000.0,
        total_staked_usd=5_000_000.0,
        my_stake_usd=100_000.0,
        entry_cost_usd=15.0,
        exit_cost_usd=12.0,
        protocol_name="Aave V3",
    )

    import json as _json
    print(_json.dumps(
        {k: v for k, v in demo.items() if k != "timestamp"},
        indent=2,
    ))

    if args.run:
        log_path = os.path.join(args.data_dir, "epoch_reward_timing_log.json")
        log_result(demo, log_path)
        print(f"[MP-1117] Result logged → {log_path}")


if __name__ == "__main__":
    _cli()
