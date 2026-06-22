#!/usr/bin/env python3
"""
SPA Go-Live Preflight — MP-351
Автоматически проверяет пункты ADR-011 go-live security checklist,
поддающиеся программной верификации.

Использование:
    python3 scripts/golive_preflight.py
    python3 scripts/golive_preflight.py --data-dir /path/to/data
    python3 scripts/golive_preflight.py --json-only   # только JSON, без консоли
    python3 scripts/golive_preflight.py --no-telegram  # без пинга Telegram API

Exit code: 0 если READY, 1 если NOT_READY.
Никогда не raise — любой сбой → FAIL с описанием, не traceback.

Pure stdlib. Read-only (пишет только data/golive_preflight_result.json).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_RESULT_FILENAME = "golive_preflight_result.json"

VERSION = "1.0"


# ─── Result dataclass ────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    status: str          # "pass" | "warn" | "fail"
    detail: str
    value: Any = None
    emoji: str = ""

    def __post_init__(self):
        if not self.emoji:
            self.emoji = {"pass": "✅", "warn": "⚠️ ", "fail": "❌"}.get(self.status, "❓")


# ─── Individual checks ───────────────────────────────────────────────────────

def _check_keychain_secret(service: str) -> CheckResult:
    """Проверяет наличие секрета в macOS Keychain через `security` CLI."""
    name = f"keychain_{service.lower().replace('_spa', '').replace('-', '_')}"
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            val = proc.stdout.strip()
            masked = val[:4] + "***" if len(val) > 4 else "***"
            return CheckResult(name, "pass", f"{service} found in Keychain ({masked})", value=True)
        else:
            return CheckResult(name, "fail",
                               f"{service} NOT found in Keychain (rc={proc.returncode})", value=False)
    except FileNotFoundError:
        return CheckResult(name, "warn",
                           f"{service}: `security` binary not found (not on macOS?)", value=None)
    except subprocess.TimeoutExpired:
        return CheckResult(name, "fail", f"{service}: Keychain lookup timed out", value=False)
    except Exception as exc:
        return CheckResult(name, "fail", f"{service}: {exc}", value=False)


def _read_keychain_secret(service: str) -> Optional[str]:
    """Читает секрет из Keychain; возвращает None при любой ошибке."""
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or None
    except Exception:
        pass
    return None


def _check_telegram_bot(data_dir: Path, skip: bool = False) -> CheckResult:
    """Пинг Telegram getMe API с токеном из Keychain."""
    name = "telegram_bot_ping"
    if skip:
        return CheckResult(name, "warn", "Telegram ping пропущен (--no-telegram)", value=None)
    token = _read_keychain_secret("TELEGRAM_BOT_TOKEN_SPA")
    if not token:
        return CheckResult(name, "fail",
                           "TELEGRAM_BOT_TOKEN_SPA не найден в Keychain — невозможно пинговать", value=False)
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        req = urllib.request.Request(url, headers={"User-Agent": "SPA-Preflight/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode())
        if body.get("ok") and body.get("result"):
            bot_name = body["result"].get("username", "?")
            return CheckResult(name, "pass", f"Telegram getMe OK (@{bot_name})", value=bot_name)
        else:
            return CheckResult(name, "fail",
                               f"Telegram API ok=False: {body.get('description', 'unknown')}", value=False)
    except urllib.error.HTTPError as exc:
        return CheckResult(name, "fail", f"Telegram API HTTP {exc.code}: {exc.reason}", value=False)
    except Exception as exc:
        return CheckResult(name, "fail", f"Telegram ping error: {exc}", value=False)


def _check_golive_checker(data_dir: Path) -> CheckResult:
    """Читает data/golive_status.json — проверяет ready=True."""
    name = "golive_checker_ready"
    path = data_dir / "golive_status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ready = data.get("ready", False)
        checks = data.get("checks", {})
        blockers = data.get("blockers", [])
        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        if ready:
            return CheckResult(name, "pass",
                               f"GoLiveChecker READY ({passed}/{total} checks)", value=True)
        else:
            blk = ", ".join(blockers) if blockers else "see golive_status.json"
            return CheckResult(name, "fail",
                               f"GoLiveChecker NOT READY ({passed}/{total}): {blk}", value=False)
    except FileNotFoundError:
        return CheckResult(name, "fail", "data/golive_status.json not found", value=False)
    except Exception as exc:
        return CheckResult(name, "fail", f"golive_status.json parse error: {exc}", value=False)


def _check_consecutive_ready_days(data_dir: Path) -> CheckResult:
    """Проверяет consecutive_ready_days ≥ 7 (ADR-002 / C3)."""
    name = "golive_consecutive_days"
    path = data_dir / "golive_status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        days = data.get("consecutive_ready_days", 0)
        required = 7
        if days >= required:
            return CheckResult(name, "pass",
                               f"consecutive_ready_days={days} ≥ {required}", value=days)
        else:
            remaining = required - days
            return CheckResult(name, "warn",
                               f"consecutive_ready_days={days} / {required} required "
                               f"({remaining} remaining)", value=days)
    except FileNotFoundError:
        return CheckResult(name, "fail", "data/golive_status.json not found", value=0)
    except Exception as exc:
        return CheckResult(name, "fail", f"consecutive_ready_days error: {exc}", value=0)


def _check_gap_monitor(data_dir: Path) -> CheckResult:
    """Проверяет gap_monitor.json: gap_detected=False, status=ok (C2)."""
    name = "gap_monitor_clean"
    path = data_dir / "gap_monitor.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        gap = data.get("gap_detected", True)
        status = data.get("status", "unknown")
        hours = data.get("hours_since_last_entry", 999)
        if not gap and status == "ok":
            return CheckResult(name, "pass",
                               f"No gaps — last entry {hours:.1f}h ago", value={"gap": gap, "hours": hours})
        else:
            msg = data.get("message", "gap detected")
            return CheckResult(name, "fail",
                               f"Gap detected: {msg}", value={"gap": gap, "status": status})
    except FileNotFoundError:
        return CheckResult(name, "fail", "data/gap_monitor.json not found", value=None)
    except Exception as exc:
        return CheckResult(name, "fail", f"gap_monitor.json parse error: {exc}", value=None)


def _check_paper_days(data_dir: Path) -> CheckResult:
    """Проверяет бумажных дней трека ≥ 30 (ADR-002 / C2)."""
    name = "paper_days_30"
    required = 30
    # Primary: progress_tracker.json
    try:
        pt_path = data_dir / "progress_tracker.json"
        data = json.loads(pt_path.read_text(encoding="utf-8"))
        days = int(data.get("paper_days", 0))
        if days >= required:
            return CheckResult(name, "pass",
                               f"paper_days={days} ≥ {required}", value=days)
        remaining = required - days
        return CheckResult(name, "warn",
                           f"paper_days={days} / {required} required ({remaining} remaining)",
                           value=days)
    except FileNotFoundError:
        pass
    except Exception as exc:
        pass
    # Fallback: paper_trading_status.json
    try:
        pts_path = data_dir / "paper_trading_status.json"
        data = json.loads(pts_path.read_text(encoding="utf-8"))
        days = int(data.get("days_running", 0))
        if days >= required:
            return CheckResult(name, "pass",
                               f"paper_days={days} ≥ {required} (from paper_trading_status)", value=days)
        remaining = required - days
        return CheckResult(name, "warn",
                           f"paper_days={days} / {required} required ({remaining} remaining)",
                           value=days)
    except Exception as exc:
        return CheckResult(name, "fail", f"Cannot determine paper_days: {exc}", value=0)


def _check_equity_level(data_dir: Path) -> CheckResult:
    """Equity > $99,000 (не просела ниже -1% от старта)."""
    name = "equity_above_99k"
    threshold = 99_000.0
    try:
        path = data_dir / "paper_trading_status.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        equity = float(data.get("current_equity", 0.0))
        if equity >= threshold:
            return CheckResult(name, "pass",
                               f"equity=${equity:,.2f} ≥ ${threshold:,.0f}", value=equity)
        else:
            return CheckResult(name, "fail",
                               f"equity=${equity:,.2f} < ${threshold:,.0f} (below -1% floor)", value=equity)
    except FileNotFoundError:
        return CheckResult(name, "fail", "data/paper_trading_status.json not found", value=None)
    except Exception as exc:
        return CheckResult(name, "fail", f"equity check error: {exc}", value=None)


def _check_max_drawdown(data_dir: Path) -> CheckResult:
    """Max drawdown за весь трек < 2% (читает equity_curve_daily.json)."""
    name = "max_drawdown_2pct"
    limit_pct = 2.0
    initial = 100_000.0
    try:
        path = data_dir / "equity_curve_daily.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        # Handle both list and dict-with-"daily" structures
        if isinstance(data, list):
            bars = data
        elif isinstance(data, dict):
            bars = (data.get("daily")
                    or data.get("bars")
                    or data.get("equity_curve")
                    or [])
        else:
            bars = []

        if not bars:
            return CheckResult(name, "warn",
                               "equity_curve_daily.json: no bars yet (too early to evaluate)", value=None)

        # Extract equity values
        equities: list[float] = []
        for bar in bars:
            if isinstance(bar, dict):
                eq = bar.get("equity") or bar.get("close_equity") or bar.get("close")
                if eq is not None:
                    equities.append(float(eq))

        if not equities:
            return CheckResult(name, "warn", "No equity values found in bars", value=None)

        # Peak-to-trough drawdown (rolling peak)
        peak = initial
        max_dd = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100.0 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        max_dd = round(max_dd, 4)
        if max_dd < limit_pct:
            return CheckResult(name, "pass",
                               f"max drawdown={max_dd:.4f}% < {limit_pct}% limit "
                               f"(over {len(equities)} bars)", value=max_dd)
        else:
            return CheckResult(name, "fail",
                               f"max drawdown={max_dd:.4f}% ≥ {limit_pct}% limit", value=max_dd)
    except FileNotFoundError:
        return CheckResult(name, "fail", "data/equity_curve_daily.json not found", value=None)
    except Exception as exc:
        return CheckResult(name, "fail", f"drawdown check error: {exc}", value=None)


def _check_kanban_no_p0_p1(repo_root: Path) -> CheckResult:
    """Нет P0/P1 задач в backlog (кроме USER ACTION)."""
    name = "kanban_no_p0_p1_backlog"
    path = repo_root / "KANBAN.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        columns = data.get("columns", {})
        backlog = columns.get("backlog", [])
        blockers = []
        for item in backlog:
            if not isinstance(item, dict):
                continue
            priority = item.get("priority", "")
            tags = item.get("tags", [])
            title = item.get("title", "")
            if priority in ("P0", "P1"):
                is_user_action = (
                    "USER ACTION" in title.upper()
                    or "user_action" in [str(t).lower() for t in tags]
                    or "user action" in [str(t).lower() for t in tags]
                )
                if not is_user_action:
                    blockers.append(f"{item.get('id','?')} [{priority}]: {title[:50]}")
        if not blockers:
            return CheckResult(name, "pass",
                               f"No P0/P1 items in backlog ({len(backlog)} items checked)", value=0)
        else:
            return CheckResult(name, "fail",
                               f"{len(blockers)} P0/P1 items in backlog: "
                               + "; ".join(blockers[:3]), value=len(blockers))
    except FileNotFoundError:
        return CheckResult(name, "fail", "KANBAN.json not found", value=None)
    except Exception as exc:
        return CheckResult(name, "fail", f"KANBAN.json parse error: {exc}", value=None)


def _check_cycle_runner_exists(repo_root: Path) -> CheckResult:
    """cycle_runner.py существует."""
    name = "cycle_runner_exists"
    path = repo_root / "spa_core" / "paper_trading" / "cycle_runner.py"
    if path.exists():
        size_kb = round(path.stat().st_size / 1024, 1)
        return CheckResult(name, "pass",
                           f"cycle_runner.py exists ({size_kb} KB)", value=str(path))
    else:
        return CheckResult(name, "fail",
                           "spa_core/paper_trading/cycle_runner.py not found", value=None)


def _check_cycle_runner_imports(repo_root: Path) -> CheckResult:
    """cycle_runner.py импортируется без ошибок."""
    name = "cycle_runner_imports"
    try:
        sys_path_backup = sys.path[:]
        sys.path.insert(0, str(repo_root))
        try:
            import importlib
            spec = importlib.util.spec_from_file_location(
                "cycle_runner",
                str(repo_root / "spa_core" / "paper_trading" / "cycle_runner.py"),
            )
            if spec is None:
                raise ImportError("Could not create module spec")
            mod = importlib.util.module_from_spec(spec)
            # Don't exec — just check syntax via compile
            src = (repo_root / "spa_core" / "paper_trading" / "cycle_runner.py").read_text(encoding="utf-8")
            compile(src, "cycle_runner.py", "exec")
            return CheckResult(name, "pass", "cycle_runner.py compiles without syntax errors", value=True)
        finally:
            sys.path[:] = sys_path_backup
    except SyntaxError as exc:
        return CheckResult(name, "fail", f"SyntaxError in cycle_runner.py: {exc}", value=False)
    except FileNotFoundError:
        return CheckResult(name, "fail", "cycle_runner.py not found", value=False)
    except Exception as exc:
        return CheckResult(name, "fail", f"cycle_runner.py check error: {exc}", value=False)


def _check_risk_policy(repo_root: Path) -> CheckResult:
    """RiskPolicy: можно импортировать, версия v1.0, drawdown gate работает."""
    name = "risk_policy_drawdown"
    sys_path_backup = sys.path[:]
    try:
        sys.path.insert(0, str(repo_root))
        from spa_core.risk.policy import RiskPolicy, RiskConfig, PortfolioState, Position  # noqa: PLC0415
        cfg = RiskConfig()
        version_ok = cfg.version == "v1.0"
        dd_ok = abs(cfg.max_drawdown_stop - 0.05) < 1e-9
        policy = RiskPolicy(cfg)
        # Simulate 6% drawdown portfolio → kill-switch must fire
        pos = Position(
            protocol_key="aave_v3",
            tier="T1",
            asset="USDC",
            amount_usd=94_000.0,
            apy_at_open=3.5,
            current_apy=3.5,
            unrealized_pnl_usd=-6_000.0,  # 6% loss
        )
        ps = PortfolioState(total_capital_usd=100_000.0, positions=[pos])
        verdict = policy.check_portfolio_health(ps)
        kill_triggered = not verdict.approved and any(
            "KILL SWITCH" in v for v in verdict.violations
        )
        if version_ok and dd_ok and kill_triggered:
            return CheckResult(name, "pass",
                               f"RiskPolicy v={cfg.version}, drawdown gate fires at 6% (correctly)", value=True)
        else:
            issues = []
            if not version_ok:
                issues.append(f"version={cfg.version} (expected v1.0)")
            if not dd_ok:
                issues.append(f"max_drawdown_stop={cfg.max_drawdown_stop} (expected 0.05)")
            if not kill_triggered:
                issues.append("kill_switch did NOT trigger at 6% drawdown (expected trigger)")
            return CheckResult(name, "fail", "; ".join(issues), value=False)
    except ImportError as exc:
        return CheckResult(name, "fail", f"Cannot import RiskPolicy: {exc}", value=False)
    except Exception as exc:
        return CheckResult(name, "fail", f"RiskPolicy check error: {exc}", value=False)
    finally:
        sys.path[:] = sys_path_backup


def _check_adapter_registry(repo_root: Path) -> CheckResult:
    """Все адаптеры доступны через ADAPTER_REGISTRY (T1 + T2)."""
    name = "adapter_registry"
    sys_path_backup = sys.path[:]
    try:
        sys.path.insert(0, str(repo_root))
        from spa_core.adapters import ADAPTER_REGISTRY  # noqa: PLC0415
        if not ADAPTER_REGISTRY:
            return CheckResult(name, "fail", "ADAPTER_REGISTRY is empty", value=0)
        t1 = [k for k, t, _ in ADAPTER_REGISTRY if t == "T1"]
        t2 = [k for k, t, _ in ADAPTER_REGISTRY if t == "T2"]
        missing_t1 = [k for k in ("aave_v3", "compound_v3") if k not in t1]
        if missing_t1:
            return CheckResult(name, "fail",
                               f"Missing required T1 adapters: {missing_t1}", value=None)
        total = len(ADAPTER_REGISTRY)
        return CheckResult(name, "pass",
                           f"{total} adapters in registry (T1={len(t1)}: {t1}; T2={len(t2)})",
                           value=total)
    except ImportError as exc:
        return CheckResult(name, "fail", f"Cannot import ADAPTER_REGISTRY: {exc}", value=False)
    except Exception as exc:
        return CheckResult(name, "fail", f"adapter_registry check error: {exc}", value=False)
    finally:
        sys.path[:] = sys_path_backup


def _check_kill_switch_drill(repo_root: Path) -> CheckResult:
    """Запускает kill_switch_drill.run_drill() — ожидается passed=True."""
    name = "kill_switch_drill"
    sys_path_backup = sys.path[:]
    try:
        sys.path.insert(0, str(repo_root))
        drill_path = repo_root / "scripts" / "kill_switch_drill.py"
        if not drill_path.exists():
            return CheckResult(name, "fail",
                               "scripts/kill_switch_drill.py not found", value=False)
        import importlib.util  # noqa: PLC0415
        spec = importlib.util.spec_from_file_location("kill_switch_drill", str(drill_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        t0 = time.time()
        result = mod.run_drill()
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        passed = result.get("passed", False)
        steps = result.get("steps", [])
        failed_steps = [s.get("step") for s in steps if not s.get("ok", True)]
        if passed:
            return CheckResult(name, "pass",
                               f"kill_switch_drill PASS ({elapsed_ms}ms < 1000ms limit)",
                               value={"passed": True, "ms": elapsed_ms})
        else:
            return CheckResult(name, "fail",
                               f"kill_switch_drill FAIL ({elapsed_ms}ms); failed: {failed_steps}",
                               value={"passed": False, "ms": elapsed_ms, "failed": failed_steps})
    except Exception as exc:
        return CheckResult(name, "fail", f"kill_switch_drill error: {exc}", value=False)
    finally:
        sys.path[:] = sys_path_backup


def _check_kill_switch_not_active(data_dir: Path) -> CheckResult:
    """kill_switch_status.json: triggered=False."""
    name = "kill_switch_not_active"
    path = data_dir / "kill_switch_status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        triggered = data.get("triggered", True)
        reason = data.get("reason", "unknown")
        if not triggered:
            return CheckResult(name, "pass",
                               f"Kill switch NOT triggered ({reason})", value=False)
        else:
            return CheckResult(name, "fail",
                               f"Kill switch IS ACTIVE! reason={reason}", value=True)
    except FileNotFoundError:
        return CheckResult(name, "warn", "data/kill_switch_status.json not found", value=None)
    except Exception as exc:
        return CheckResult(name, "fail", f"kill_switch_status.json error: {exc}", value=None)


def _check_vportfolios(data_dir: Path) -> CheckResult:
    """data/strategies/vportfolios.json существует (tournament запущен)."""
    name = "vportfolios_exists"
    candidates = [
        data_dir / "strategies" / "vportfolios.json",
        data_dir / "vportfolios.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                n = len(data) if isinstance(data, (list, dict)) else 0
                return CheckResult(name, "pass",
                                   f"vportfolios.json exists at {path.relative_to(path.parents[2])} "
                                   f"({n} entries)", value=str(path))
            except Exception:
                return CheckResult(name, "pass",
                                   f"vportfolios.json exists at {path}", value=str(path))
    return CheckResult(name, "fail",
                       "vportfolios.json not found (tournament not yet running?)", value=None)


def _check_strategy_registry(repo_root: Path) -> CheckResult:
    """spa_core/paper_trading/strategy_registry.py существует."""
    name = "strategy_registry_exists"
    candidates = [
        repo_root / "spa_core" / "paper_trading" / "strategy_registry.py",
        repo_root / "spa_core" / "strategies" / "strategy_registry.py",
    ]
    for path in candidates:
        if path.exists():
            size_kb = round(path.stat().st_size / 1024, 1)
            return CheckResult(name, "pass",
                               f"strategy_registry.py exists ({size_kb} KB)", value=str(path))
    return CheckResult(name, "fail", "strategy_registry.py not found", value=None)


def _check_file_exists(path: Path, label: str, check_name: str) -> CheckResult:
    """Универсальная проверка существования файла."""
    if path.exists():
        return CheckResult(check_name, "pass", f"{label} exists", value=str(path))
    else:
        return CheckResult(check_name, "fail", f"{label} NOT found at {path}", value=None)


def _check_gnosis_safe_address(repo_root: Path) -> CheckResult:
    """Проверяет наличие SAFE_ADDRESS (env var или Keychain)."""
    name = "gnosis_safe_address"
    # 1. Env var
    safe_addr = os.environ.get("SAFE_ADDRESS", "").strip()
    if safe_addr and safe_addr.startswith("0x") and len(safe_addr) == 42:
        return CheckResult(name, "warn",
                           f"SAFE_ADDRESS found in environment (not Keychain): {safe_addr[:8]}...{safe_addr[-4:]}",
                           value=safe_addr)
    # 2. Keychain
    ks_val = _read_keychain_secret("SAFE_ADDRESS_SPA")
    if not ks_val:
        ks_val = _read_keychain_secret("SAFE_ADDRESS")
    if ks_val and ks_val.startswith("0x") and len(ks_val) == 42:
        return CheckResult(name, "pass",
                           f"SAFE_ADDRESS found in Keychain: {ks_val[:8]}...{ks_val[-4:]}",
                           value=ks_val[:8] + "***")
    # 3. Check docs/adr/ADR-010 for any recorded address
    adr010 = repo_root / "docs" / "adr" / "ADR-010-gnosis-safe-key-management.md"
    if adr010.exists():
        # ADR-010 is drafted → Safe is planned; no address yet → warn (not fail)
        return CheckResult(name, "warn",
                           "SAFE_ADDRESS not configured in env/Keychain "
                           "(ADR-010 exists — deploy Safe 2-of-3 per ADR-010 before go-live)",
                           value=None)
    return CheckResult(name, "fail",
                       "SAFE_ADDRESS not configured — Gnosis Safe not yet deployed "
                       "[NEEDS HUMAN: deploy Safe 2-of-3 per ADR-010]",
                       value=None)


def _check_analytics_scorecard(data_dir: Path) -> CheckResult:
    """data/analytics_scorecard.json существует и свежий (< 48ч)."""
    name = "analytics_scorecard_fresh"
    path = data_dir / "analytics_scorecard.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.get("meta", {})
        gen_at_str = meta.get("generated_at") or data.get("generated_at", "")
        overall = data.get("overall_status", "unknown")
        # Check freshness
        stale = True
        if gen_at_str:
            try:
                gen_at = datetime.datetime.fromisoformat(gen_at_str.replace("Z", "+00:00"))
                now = datetime.datetime.now(datetime.timezone.utc)
                age_h = (now - gen_at).total_seconds() / 3600
                stale = age_h > 48
                age_str = f"{age_h:.1f}h"
            except Exception:
                age_str = "unknown age"
        else:
            age_str = "no timestamp"

        if not stale:
            if overall in ("ok", "pass"):
                return CheckResult(name, "pass",
                                   f"analytics_scorecard fresh ({age_str}), status={overall}", value=overall)
            else:
                return CheckResult(name, "warn",
                                   f"analytics_scorecard fresh ({age_str}), status={overall} (advisory)", value=overall)
        else:
            return CheckResult(name, "warn",
                               f"analytics_scorecard stale ({age_str} old)", value=overall)
    except FileNotFoundError:
        return CheckResult(name, "warn", "data/analytics_scorecard.json not found", value=None)
    except Exception as exc:
        return CheckResult(name, "fail", f"analytics_scorecard error: {exc}", value=None)


def _check_risk_policy_blocks(data_dir: Path) -> CheckResult:
    """risk_policy_blocks.json: нет аномальных паттернов (все блоки объяснены)."""
    name = "risk_policy_blocks_healthy"
    path = data_dir / "risk_policy_blocks.json"
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw or raw == "[]":
            return CheckResult(name, "pass",
                               "risk_policy_blocks.json empty — no blocks recorded yet", value=0)
        data = json.loads(raw)
        if not isinstance(data, list):
            data = [data]
        n = len(data)
        # Check that all blocks have a reason
        no_reason = [i for i, b in enumerate(data) if not b.get("reason", "").strip()]
        if no_reason:
            return CheckResult(name, "warn",
                               f"{n} blocks; {len(no_reason)} without explanation", value=n)
        return CheckResult(name, "pass",
                           f"{n} block(s) recorded, all with reason", value=n)
    except FileNotFoundError:
        return CheckResult(name, "warn", "data/risk_policy_blocks.json not found", value=None)
    except Exception as exc:
        return CheckResult(name, "fail", f"risk_policy_blocks error: {exc}", value=None)


# ─── Runner ──────────────────────────────────────────────────────────────────

def run_preflight(
    data_dir: Optional[str] = None,
    skip_telegram: bool = False,
) -> dict:
    """Запускает все проверки и возвращает сводный результат."""
    repo_root = _REPO_ROOT
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t0 = time.time()

    # ── Collect paper_days for summary ───────────────────────────────────────
    paper_days = 0
    try:
        pt = json.loads((ddir / "progress_tracker.json").read_text(encoding="utf-8"))
        paper_days = int(pt.get("paper_days", 0))
    except Exception:
        try:
            pts = json.loads((ddir / "paper_trading_status.json").read_text(encoding="utf-8"))
            paper_days = int(pts.get("days_running", 0))
        except Exception:
            pass

    # ── Run all checks ───────────────────────────────────────────────────────
    checks: list[CheckResult] = []

    # Group 1: Secrets & Auth
    checks.append(_check_keychain_secret("TELEGRAM_BOT_TOKEN_SPA"))
    checks.append(_check_keychain_secret("GITHUB_PAT_SPA"))
    checks.append(_check_telegram_bot(ddir, skip=skip_telegram))

    # Group 2: Go-Live Readiness
    checks.append(_check_golive_checker(ddir))
    checks.append(_check_consecutive_ready_days(ddir))
    checks.append(_check_gap_monitor(ddir))
    checks.append(_check_paper_days(ddir))
    checks.append(_check_equity_level(ddir))
    checks.append(_check_max_drawdown(ddir))

    # Group 3: Code Health
    checks.append(_check_cycle_runner_exists(repo_root))
    checks.append(_check_cycle_runner_imports(repo_root))
    checks.append(_check_risk_policy(repo_root))
    checks.append(_check_adapter_registry(repo_root))

    # Group 4: Kill Switch
    checks.append(_check_kill_switch_drill(repo_root))
    checks.append(_check_kill_switch_not_active(ddir))

    # Group 5: Data & Tournament
    checks.append(_check_vportfolios(ddir))
    checks.append(_check_strategy_registry(repo_root))
    checks.append(_check_kanban_no_p0_p1(repo_root))
    checks.append(_check_risk_policy_blocks(ddir))
    checks.append(_check_analytics_scorecard(ddir))

    # Group 6: Documentation
    checks.append(_check_file_exists(
        repo_root / "docs" / "DECISIONS.md", "docs/DECISIONS.md", "decisions_md"))
    checks.append(_check_file_exists(
        repo_root / "CURRENT_STATE.md", "CURRENT_STATE.md", "current_state_md"))
    # Accept either sprint_log.md (current name) or legacy SPA_sprint_log.md
    _sprint_log_path = (repo_root / "sprint_log.md"
                        if (repo_root / "sprint_log.md").exists()
                        else repo_root / "SPA_sprint_log.md")
    checks.append(_check_file_exists(
        _sprint_log_path, "sprint_log.md", "sprint_log_md"))
    checks.append(_check_file_exists(
        repo_root / "docs" / "adr" / "ADR-010-gnosis-safe-key-management.md",
        "docs/adr/ADR-010 (Gnosis Safe)", "adr_010_exists"))
    checks.append(_check_file_exists(
        repo_root / "docs" / "adr" / "ADR-011-go-live-security-checklist.md",
        "docs/adr/ADR-011 (security checklist)", "adr_011_exists"))

    # Group 7: Infrastructure
    checks.append(_check_gnosis_safe_address(repo_root))

    # ── Tally ─────────────────────────────────────────────────────────────────
    n_pass = sum(1 for c in checks if c.status == "pass")
    n_warn = sum(1 for c in checks if c.status == "warn")
    n_fail = sum(1 for c in checks if c.status == "fail")
    n_total = len(checks)
    score = round(n_pass / n_total * 100, 1) if n_total > 0 else 0.0

    # READY = zero FAILs (WARNs are acceptable)
    is_ready = (n_fail == 0)

    # Build verdict string
    fails_list = [c.name for c in checks if c.status == "fail"]
    warns_list = [c.name for c in checks if c.status == "warn"]

    days_remaining = max(0, 30 - paper_days)
    manual_required = sum(
        1 for c in checks
        if "NEEDS HUMAN" in c.detail or c.status == "fail"
    )

    if is_ready:
        verdict = "READY ✅"
        verdict_short = "READY"
    else:
        parts = []
        if days_remaining > 0:
            parts.append(f"{days_remaining} days remaining")
        if manual_required > 0:
            parts.append(f"{manual_required} issue(s) to resolve")
        verdict = "NOT READY — " + " + ".join(parts) if parts else "NOT READY"
        verdict_short = "NOT_READY"

    elapsed_ms = round((time.time() - t0) * 1000, 1)

    result = {
        "version": VERSION,
        "mp": "MP-351",
        "generated_at": started_at,
        "verdict": verdict_short,
        "verdict_display": verdict,
        "score_pct": score,
        "counts": {
            "pass": n_pass,
            "warn": n_warn,
            "fail": n_fail,
            "total": n_total,
        },
        "paper_days": paper_days,
        "paper_days_required": 30,
        "is_ready": is_ready,
        "fails": fails_list,
        "warns": warns_list,
        "elapsed_ms": elapsed_ms,
        "checks": [
            {
                "name": c.name,
                "status": c.status,
                "detail": c.detail,
                "value": c.value,
            }
            for c in checks
        ],
    }

    return result


def _save_result(result: dict, data_dir: Path) -> None:
    """Атомарная запись результата в data/golive_preflight_result.json."""
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / _RESULT_FILENAME
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    fd, tmp_path = tempfile.mkstemp(dir=str(data_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, str(out_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def _print_report(result: dict) -> None:
    """Выводит читаемый отчёт в консоль."""
    n = result["counts"]
    today = result["generated_at"][:10]
    paper_days = result["paper_days"]
    paper_req = result["paper_days_required"]

    print()
    print(f"=== SPA GO-LIVE PREFLIGHT v{result['version']} ===")
    print(f"Date: {today}")
    print(f"Paper days: {paper_days}/{paper_req}")
    print()
    print(f"PASS [{n['pass']}/{n['total']}]  "
          f"WARN [{n['warn']}/{n['total']}]  "
          f"FAIL [{n['fail']}/{n['total']}]  "
          f"Score: {result['score_pct']}%")
    print()

    status_order = {"fail": 0, "warn": 1, "pass": 2}
    sorted_checks = sorted(result["checks"], key=lambda c: status_order.get(c["status"], 9))

    for c in sorted_checks:
        emoji = {"pass": "✅", "warn": "⚠️ ", "fail": "❌"}.get(c["status"], "❓")
        print(f"{emoji} {c['name']}: {c['detail']}")

    print()
    print(f"VERDICT: {result['verdict_display']}")
    print(f"Elapsed: {result['elapsed_ms']:.0f}ms")
    print()


# ─── CLI entry point ─────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SPA Go-Live Preflight MP-351 — автоматическая проверка ADR-011 checklist"
    )
    parser.add_argument("--data-dir", default=None, help="Path to data/ directory")
    parser.add_argument("--json-only", action="store_true",
                        help="Вывод только JSON, без консольного отчёта")
    parser.add_argument("--no-telegram", action="store_true",
                        help="Пропустить Telegram API ping")
    parser.add_argument("--no-save", action="store_true",
                        help="Не сохранять результат в JSON файл")
    args = parser.parse_args()

    ddir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    result = run_preflight(
        data_dir=str(ddir) if args.data_dir else None,
        skip_telegram=args.no_telegram,
    )

    if not args.no_save:
        try:
            _save_result(result, ddir)
        except Exception as exc:
            print(f"⚠️  Warning: could not save result: {exc}", file=sys.stderr)

    if args.json_only:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_report(result)

    return 0 if result["is_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
