"""
SPA GitHub Multi-File Pusher
Usage: python -m spa_core.tools.github_pusher [--dry-run]
       (PAT read from Keychain GITHUB_PAT_SPA, or GITHUB_TOKEN env var)

Pushes all changed files to yurii-spa/SPA repo.
Files are pushed one by one (GitHub API doesn't support multi-file commits natively)
but sequentially with progress reporting.
"""

import argparse
import base64
import os
import sys
import time
import urllib.request
import urllib.error
import json

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
REPO_OWNER = "yurii-spa"
REPO_NAME  = "SPA"
BRANCH     = "main"
API_BASE   = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents"

# ──────────────────────────────────────────────
# File manifest  (local_path, repo_path, commit_message)
# ──────────────────────────────────────────────
PUSH_MANIFEST = [
    # Frontend
    ("index.html", "index.html",
     "feat: v1.6 dashboard — System Health tab, pipeline monitor, data freshness"),

    # Core Python modules
    ("spa_core/export_data.py", "spa_core/export_data.py",
     "feat: sections 1-20, all exports incl backtest+golive"),
    ("spa_core/paper_trading/engine.py", "spa_core/paper_trading/engine.py",
     "feat: v2 strategy, decision logging"),
    ("spa_core/paper_trading/strategies.py", "spa_core/paper_trading/strategies.py",
     "feat: strategy registry"),
    ("spa_core/paper_trading/pendle_strategy.py", "spa_core/paper_trading/pendle_strategy.py",
     "feat: PendlePosition dataclass + pendle_allocation_size()"),
    ("spa_core/risk/policy.py", "spa_core/risk/policy.py",
     "feat: v1.0 versioned, multi-chain limits"),
    ("spa_core/risk/versions/__init__.py", "spa_core/risk/versions/__init__.py",
     "feat: policy versions"),
    ("spa_core/risk/versions/v1_0_passive.py", "spa_core/risk/versions/v1_0_passive.py",
     "feat: frozen v1.0 snapshot"),
    ("spa_core/data_pipeline/defillama_fetcher.py", "spa_core/data_pipeline/defillama_fetcher.py",
     "fix: correct 12-pool whitelist (arbitrum+base only), fetch_with_pendle()"),
    ("spa_core/data_pipeline/sky_monitor.py", "spa_core/data_pipeline/sky_monitor.py",
     "feat: Sky/sUSDS GSM Pause Delay monitor"),
    ("spa_core/data_pipeline/pendle_fetcher.py", "spa_core/data_pipeline/pendle_fetcher.py",
     "feat: Pendle PT pool fetcher (DeFiLlama, 7 gates)"),
    ("spa_core/data_pipeline/apy_gap_report.py", "spa_core/data_pipeline/apy_gap_report.py",
     "feat: APY gap analysis report (DeFiLlama vs Pendle)"),

    # New modules
    ("spa_core/agents/llm_agent.py", "spa_core/agents/llm_agent.py",
     "feat: Claude API agent reasoning"),
    ("spa_core/agents/chat_handler.py", "spa_core/agents/chat_handler.py",
     "feat: chat routing with LLM"),
    ("spa_core/agents/decision_logger.py", "spa_core/agents/decision_logger.py",
     "feat: agent decision audit log"),
    ("spa_core/alerts/email_sender.py", "spa_core/alerts/email_sender.py",
     "feat: Gmail SMTP alerts"),
    ("spa_core/alerts/telegram_sender.py", "spa_core/alerts/telegram_sender.py",
     "feat: Telegram bot alerts"),
    ("spa_core/alerts/__init__.py", "spa_core/alerts/__init__.py",
     "feat: alerts package"),
    ("spa_core/alerts/daily_report.py", "spa_core/alerts/daily_report.py",
     "feat: daily summary report alert"),
    ("spa_core/alerts/risk_monitor.py", "spa_core/alerts/risk_monitor.py",
     "feat: real-time risk monitor alert"),
    ("spa_core/backtesting/__init__.py", "spa_core/backtesting/__init__.py",
     "feat: backtesting package"),
    ("spa_core/backtesting/tournament.py", "spa_core/backtesting/tournament.py",
     "fix: v2_aggressive RiskConfig fields, StrategyTournament weighted scoring"),
    ("spa_core/backtesting/engine.py", "spa_core/backtesting/engine.py",
     "feat: BacktestEngine"),
    ("spa_core/backtesting/metrics.py", "spa_core/backtesting/metrics.py",
     "feat: Sharpe, drawdown, win rate"),
    ("spa_core/backtesting/data_loader.py", "spa_core/backtesting/data_loader.py",
     "feat: DeFiLlama + synthetic data"),
    ("spa_core/analytics/__init__.py", "spa_core/analytics/__init__.py",
     "feat: analytics package"),
    ("spa_core/analytics/portfolio_stats.py", "spa_core/analytics/portfolio_stats.py",
     "feat: Calmar, Sortino, Ulcer, rolling metrics"),
    ("spa_core/optimization/__init__.py", "spa_core/optimization/__init__.py",
     "feat: optimization package"),
    ("spa_core/optimization/kelly.py", "spa_core/optimization/kelly.py",
     "feat: Kelly criterion sizing"),
    ("spa_core/optimization/markowitz.py", "spa_core/optimization/markowitz.py",
     "feat: Markowitz pure Python"),
    ("spa_core/optimization/recommender.py", "spa_core/optimization/recommender.py",
     "feat: allocation recommender"),
    ("spa_core/golive/__init__.py", "spa_core/golive/__init__.py",
     "feat: golive package"),
    ("spa_core/golive/checklist.py", "spa_core/golive/checklist.py",
     "feat: 9-criteria go-live checker"),
    ("spa_core/golive/report_card.py", "spa_core/golive/report_card.py",
     "feat: ASCII report card"),
    ("spa_core/reports/__init__.py", "spa_core/reports/__init__.py",
     "feat: reports package"),
    ("spa_core/reports/pdf_generator.py", "spa_core/reports/pdf_generator.py",
     "feat: reportlab PDF"),
    ("spa_core/reports/report_scheduler.py", "spa_core/reports/report_scheduler.py",
     "feat: report scheduler"),
    ("spa_core/execution/__init__.py", "spa_core/execution/__init__.py",
     "feat: execution scaffold"),
    ("spa_core/execution/wallet.py", "spa_core/execution/wallet.py",
     "feat: SPAWallet scaffold"),
    ("spa_core/execution/safety_checks.py", "spa_core/execution/safety_checks.py",
     "feat: pre-execution safety"),
    ("spa_core/execution/position_monitor.py", "spa_core/execution/position_monitor.py",
     "feat: position monitor"),
    ("spa_core/api/server.py", "spa_core/api/server.py",
     "feat: FastAPI + WebSocket + /api/chat"),
    ("spa_core/api/agent_broadcaster.py", "spa_core/api/agent_broadcaster.py",
     "feat: WS broadcaster"),
    ("spa_core/api/__init__.py", "spa_core/api/__init__.py",
     "feat: api package"),
    ("spa_core/requirements.txt", "spa_core/requirements.txt",
     "chore: add reportlab, fastapi, uvicorn, websockets"),
    ("run_server.py", "run_server.py",
     "feat: quick-start FastAPI server"),

    # Tests
    ("spa_core/tests/conftest.py", "spa_core/tests/conftest.py",
     "test: shared fixtures"),
    ("spa_core/tests/test_optimization.py", "spa_core/tests/test_optimization.py",
     "test: optimization suite"),
    ("spa_core/tests/test_backtesting.py", "spa_core/tests/test_backtesting.py",
     "test: backtesting suite"),
    ("spa_core/tests/test_golive.py", "spa_core/tests/test_golive.py",
     "test: go-live criteria"),
    ("spa_core/tests/test_email.py", "spa_core/tests/test_email.py",
     "test: email alerts"),
    ("spa_core/tests/test_alerts.py", "spa_core/tests/test_alerts.py",
     "test: daily_report + risk_monitor alerts"),
    ("spa_core/tests/test_pendle.py", "spa_core/tests/test_pendle.py",
     "test: Pendle PT fetcher suite"),

    # Docs
    ("docs/adr/ADR_TEMPLATE.md", "docs/adr/ADR_TEMPLATE.md",
     "docs: ADR template"),
    ("docs/adr/ADR_001_initial_risk_policy.md", "docs/adr/ADR_001_initial_risk_policy.md",
     "docs: initial risk policy ADR"),
    ("docs/adr/ADR_002_pendle_pt_integration.md", "docs/adr/ADR_002_pendle_pt_integration.md",
     "docs: ADR-002 Pendle PT integration (PROPOSED)"),
    ("docs/setup_email_alerts.md", "docs/setup_email_alerts.md",
     "docs: email setup guide"),
    ("docs/setup_telegram_alerts.md", "docs/setup_telegram_alerts.md",
     "docs: Telegram setup guide"),
    ("docs/setup_llm_agents.md", "docs/setup_llm_agents.md",
     "docs: LLM agent setup"),
    ("docs/run_locally.md", "docs/run_locally.md",
     "docs: local dev guide"),
    ("docs/v2_architecture.md", "docs/v2_architecture.md",
     "docs: v2.0 real capital architecture"),
    ("docs/v2_activation_checklist.md", "docs/v2_activation_checklist.md",
     "docs: v2 activation steps"),
    ("docs/emergency.md", "docs/emergency.md",
     "docs: emergency runbook"),
    ("docs/api_reference.md", "docs/api_reference.md",
     "docs: FastAPI endpoint reference"),
    ("docs/data_schema.md", "docs/data_schema.md",
     "docs: data/*.json file schemas"),
    ("docs/architecture.md", "docs/architecture.md",
     "docs: system architecture and agent hierarchy"),
    ("docs/paper_trading_guide.md", "docs/paper_trading_guide.md",
     "docs: 8-week paper trading guide"),
    ("docs/operator_runbook.md", "docs/operator_runbook.md",
     "docs: operator runbook for day-to-day management"),

    # Workflow scripts
    ("push_workflow.command", "push_workflow.command",
     "chore: push workflow helper script"),
    ("trigger_workflow.command", "trigger_workflow.command",
     "chore: trigger GitHub Actions workflow script"),

    # GitHub Actions
    (".github/workflows/spa-run.yml", ".github/workflows/spa-run.yml",
     "ci: pytest before export, wildcard git add"),

    # Sprint log
    ("SPA_sprint_log.md", "SPA_sprint_log.md",
     "docs: full sprint history v0.1-v1.0"),

    # Root README
    ("README.md", "README.md",
     "docs: project README"),

    # Agents package (new modules)
    ("spa_core/agents/__init__.py", "spa_core/agents/__init__.py",
     "feat: agents package init"),
    ("spa_core/agents/base.py", "spa_core/agents/base.py",
     "feat: base agent class"),
    ("spa_core/agents/ceo_agent.py", "spa_core/agents/ceo_agent.py",
     "feat: CEO orchestration agent"),
    ("spa_core/agents/data_agent.py", "spa_core/agents/data_agent.py",
     "feat: data-fetching agent"),
    ("spa_core/agents/model_config.py", "spa_core/agents/model_config.py",
     "feat: LLM model config registry"),
    ("spa_core/agents/monitoring_agent.py", "spa_core/agents/monitoring_agent.py",
     "feat: monitoring agent"),
    ("spa_core/agents/strategy_agent.py", "spa_core/agents/strategy_agent.py",
     "feat: strategy selection agent"),

    # Backtesting new modules
    ("spa_core/backtesting/replay.py", "spa_core/backtesting/replay.py",
     "feat: historical replay engine"),
    ("spa_core/backtesting/scenario_runner.py", "spa_core/backtesting/scenario_runner.py",
     "feat: multi-scenario batch runner"),

    # Data pipeline package init
    ("spa_core/data_pipeline/__init__.py", "spa_core/data_pipeline/__init__.py",
     "feat: data_pipeline package init"),

    # Database
    ("spa_core/database/__init__.py", "spa_core/database/__init__.py",
     "feat: database package init"),
    ("spa_core/database/init_db.py", "spa_core/database/init_db.py",
     "feat: DB schema initializer"),

    # Go-live new modules
    ("spa_core/golive/activate.py", "spa_core/golive/activate.py",
     "feat: live-capital activation flow"),
    ("spa_core/golive/daily_check.py", "spa_core/golive/daily_check.py",
     "feat: daily go-live health check"),

    # Message bus
    ("spa_core/message_bus/__init__.py", "spa_core/message_bus/__init__.py",
     "feat: message bus package init"),
    ("spa_core/message_bus/bus.py", "spa_core/message_bus/bus.py",
     "feat: in-process message bus"),
    ("spa_core/message_bus/topics.py", "spa_core/message_bus/topics.py",
     "feat: bus topic constants"),

    # Monitor
    ("spa_core/monitor/__init__.py", "spa_core/monitor/__init__.py",
     "feat: monitor package init"),
    ("spa_core/monitor/alerts.py", "spa_core/monitor/alerts.py",
     "feat: monitor alert dispatcher"),
    ("spa_core/monitor/health_check.py", "spa_core/monitor/health_check.py",
     "feat: system health checks"),

    # Orchestrator
    ("spa_core/orchestrator/__init__.py", "spa_core/orchestrator/__init__.py",
     "feat: orchestrator package init"),
    ("spa_core/orchestrator/graph.py", "spa_core/orchestrator/graph.py",
     "feat: LangGraph agent graph"),
    ("spa_core/orchestrator/state.py", "spa_core/orchestrator/state.py",
     "feat: shared orchestrator state"),

    # Paper trading package init
    ("spa_core/paper_trading/__init__.py", "spa_core/paper_trading/__init__.py",
     "feat: paper_trading package init"),

    # Risk package init
    ("spa_core/risk/__init__.py", "spa_core/risk/__init__.py",
     "feat: risk package init"),

    # Tools package
    ("spa_core/tools/__init__.py", "spa_core/tools/__init__.py",
     "feat: tools package init"),
    ("spa_core/tools/github_pusher.py", "spa_core/tools/github_pusher.py",
     "chore: multi-file GitHub pusher v2"),

    # API README
    ("spa_core/api/README.md", "spa_core/api/README.md",
     "docs: API module README"),

    # Frontend README
    ("spa_frontend/README.md", "spa_frontend/README.md",
     "docs: frontend README"),

    # New tests
    ("spa_core/tests/__init__.py", "spa_core/tests/__init__.py",
     "test: tests package init"),
    ("spa_core/tests/run_sky_tests.py", "spa_core/tests/run_sky_tests.py",
     "test: Sky monitor test runner script"),
    ("spa_core/tests/test_analytics.py", "spa_core/tests/test_analytics.py",
     "test: portfolio analytics suite"),
    ("spa_core/tests/test_api.py", "spa_core/tests/test_api.py",
     "test: FastAPI endpoint suite"),
    ("spa_core/tests/test_api_logic.py", "spa_core/tests/test_api_logic.py",
     "test: API business logic suite"),
    ("spa_core/tests/test_golive_extended.py", "spa_core/tests/test_golive_extended.py",
     "test: extended go-live criteria"),
    ("spa_core/tests/test_message_bus.py", "spa_core/tests/test_message_bus.py",
     "test: message bus suite"),
    ("spa_core/tests/test_monitor.py", "spa_core/tests/test_monitor.py",
     "test: monitor suite"),
    ("spa_core/tests/test_paper_trading.py", "spa_core/tests/test_paper_trading.py",
     "test: paper trading engine suite"),
    ("spa_core/tests/test_replay.py", "spa_core/tests/test_replay.py",
     "test: replay engine suite"),
    ("spa_core/tests/test_risk_policy.py", "spa_core/tests/test_risk_policy.py",
     "test: risk policy suite"),
    ("spa_core/tests/test_sky_monitor.py", "spa_core/tests/test_sky_monitor.py",
     "test: Sky/sUSDS monitor suite"),
    ("spa_core/tests/test_tournament.py", "spa_core/tests/test_tournament.py",
     "test: strategy tournament suite"),

    # Retry logic + pipeline health tests (top-level tests/)
    ("tests/test_retry_logic.py", "tests/test_retry_logic.py",
     "test: retry logic and pipeline health tests"),

    # Concurrent fetch + caching tests
    ("tests/test_concurrent_fetch.py", "tests/test_concurrent_fetch.py",
     "test: concurrent fetch and caching tests"),

    # Portfolio drift rebalancing tests
    ("tests/test_rebalancing.py", "tests/test_rebalancing.py",
     "test: portfolio drift rebalancing tests"),

    # ADR docs
    ("docs/ADR_003_rate_limiting.md", "docs/ADR_003_rate_limiting.md",
     "docs: ADR-003 rate limiting and circuit breaker"),

    # NOTE: requires 'workflow' scope token — use push_workflow.command
    (".github/workflows/deploy-pages.yml", ".github/workflows/deploy-pages.yml",
     "ci: GitHub Pages auto-deploy workflow"),

    # Demo data seeder
    ("spa_core/tools/seed_demo_data.py", "spa_core/tools/seed_demo_data.py",
     "feat: demo data seeder for dashboard testing"),
    ("tests/test_seed_demo.py", "tests/test_seed_demo.py",
     "test: demo data seeder tests"),

    # Shared conftest fixtures for top-level tests/
    ("tests/conftest.py", "tests/conftest.py",
     "test: shared pytest fixtures for full test suite"),
    ("tests/test_conftest_fixtures.py", "tests/test_conftest_fixtures.py",
     "test: conftest fixture validation tests"),

    # End-to-end integration suite
    ("tests/test_integration_e2e.py", "tests/test_integration_e2e.py",
     "test: end-to-end integration suite — full pipeline mock tests"),

    # APY history tracker
    ("spa_core/analytics/apy_tracker.py", "spa_core/analytics/apy_tracker.py",
     "feat: APY history tracker with 90-day rolling store"),
    ("tests/test_apy_tracker.py", "tests/test_apy_tracker.py",
     "test: APY tracker trend analysis tests"),

    # Dev agents — Layer 1 (development tooling, not product agents)
    ("spa_core/dev_agents/__init__.py", "spa_core/dev_agents/__init__.py",
     "feat: dev_agents package init"),
    ("spa_core/dev_agents/architect.py", "spa_core/dev_agents/architect.py",
     "feat: Architect agent — LLM-powered sprint planner and idea reviewer"),
    ("spa_core/dev_agents/tester.py", "spa_core/dev_agents/tester.py",
     "feat: Tester agent — pytest runner with Telegram reporting"),

    # ADR-004 — two-layer agent architecture
    ("docs/ADR_004_two_layer_agents.md", "docs/ADR_004_two_layer_agents.md",
     "docs: ADR-004 two-layer agent architecture (dev vs product)"),

    # Dev agent tests
    ("tests/test_dev_agents.py", "tests/test_dev_agents.py",
     "test: Architect and Tester agent unit tests"),

    # Kanban board
    ("KANBAN.json", "KANBAN.json",
     "feat: kanban — architect review sprint items added"),
    ("kanban.html", "kanban.html",
     "feat: kanban board dashboard"),

    # Kanban guide
    ("docs/kanban_guide.md", "docs/kanban_guide.md",
     "docs: kanban board usage guide"),

    # Claude Code context file
    ("CLAUDE.md", "CLAUDE.md",
     "docs: CLAUDE.md project context for Claude Code"),

    # Architect review + 7-week roadmap
    ("docs/architect_review_2026-05-22.md", "docs/architect_review_2026-05-22.md",
     "docs: architect review and 7-week roadmap"),
]

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _token_from_keychain(service: str = "GITHUB_PAT_SPA") -> str:
    """Read the GitHub PAT from the macOS Keychain (preferred source).

    Returns "" if unavailable (non-macOS, not set, or `security` missing) so
    the caller can fall back to env/CLI. The token is never logged or printed.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _api_get(url: str, token: str) -> dict | None:
    """GET a GitHub API URL. Returns parsed JSON or None on 404."""
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _api_put(url: str, token: str, payload: dict) -> tuple[int, dict]:
    """PUT a GitHub API URL. Returns (status_code, parsed_json)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={**_headers(token), "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read())
        except Exception:
            pass
        return e.code, body


# ──────────────────────────────────────────────
# Core functions
# ──────────────────────────────────────────────

def get_file_sha(repo_path: str, token: str) -> str | None:
    """Return the current blob SHA for repo_path, or None if it doesn't exist yet."""
    url = f"{API_BASE}/{repo_path}?ref={BRANCH}"
    result = _api_get(url, token)
    if result is None:
        return None
    return result.get("sha")


def push_file(local_path: str, repo_path: str, commit_msg: str, token: str) -> dict:
    """
    Read local_path, base64-encode it, and PUT to GitHub.
    Returns the API response dict (or an error dict with key 'error').

    Retries once on 429 (rate-limit) after a 60-second wait.
    """
    # Read file bytes (works for both text and binary)
    with open(local_path, "rb") as fh:
        raw = fh.read()

    content_b64 = base64.b64encode(raw).decode("ascii")
    sha = get_file_sha(repo_path, token)

    payload: dict = {
        "message": commit_msg,
        "content": content_b64,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    url = f"{API_BASE}/{repo_path}"

    for attempt in range(2):          # at most 2 tries (1 retry on 429)
        status, body = _api_put(url, token, payload)

        if status in (200, 201):
            return body

        if status == 429:
            reset_wait = 60
            print(f"\n  ⏳  Rate-limited (429). Waiting {reset_wait}s …", flush=True)
            time.sleep(reset_wait)
            continue                  # retry

        # Any other 4xx / 5xx — return error dict (caller decides whether to abort)
        return {"error": True, "status": status, "body": body}

    # Exhausted retries
    return {"error": True, "status": 429, "body": {"message": "Rate-limited after retry"}}


# ──────────────────────────────────────────────
# Dry-run helper
# ──────────────────────────────────────────────

def dry_run(project_root: str) -> None:
    total = len(PUSH_MANIFEST)
    present, missing = [], []

    for local_path, repo_path, _ in PUSH_MANIFEST:
        full = os.path.join(project_root, local_path)
        if os.path.exists(full):
            present.append(local_path)
        else:
            missing.append(local_path)

    print(f"\n{'─'*60}")
    print(f"DRY RUN — {total} files in manifest")
    print(f"  ✅  Present : {len(present)}")
    print(f"  ❌  Missing : {len(missing)}")
    print(f"{'─'*60}")

    if missing:
        print("\nMISSING FILES:")
        for f in missing:
            print(f"  ✗  {f}")

    print("\nWould push (first 10):")
    for local_path, repo_path, msg in PUSH_MANIFEST[:10]:
        marker = "✓" if os.path.exists(os.path.join(project_root, local_path)) else "✗"
        print(f"  [{marker}] {repo_path}  — {msg[:60]}")
    if total > 10:
        print(f"  … and {total - 10} more")
    print()


# ──────────────────────────────────────────────
# Main push loop
# ──────────────────────────────────────────────

def push_all(token: str, project_root: str) -> None:
    total   = len(PUSH_MANIFEST)
    pushed  = 0
    skipped = 0
    errors  = []

    width = len(str(total))   # for zero-padded counters

    print(f"\nPushing {total} files to {REPO_OWNER}/{REPO_NAME} …\n")

    for idx, (local_path, repo_path, commit_msg) in enumerate(PUSH_MANIFEST, start=1):
        counter = f"[{str(idx).zfill(width)}/{total}]"
        full_local = os.path.join(project_root, local_path)

        if not os.path.exists(full_local):
            print(f"  {counter} SKIP  {repo_path}  (file not found locally)")
            skipped += 1
            continue

        print(f"  {counter} pushing {repo_path} … ", end="", flush=True)
        result = push_file(full_local, repo_path, commit_msg, token)

        if result.get("error"):
            status = result.get("status", "?")
            msg    = result.get("body", {}).get("message", "unknown error")
            print(f"✗  (HTTP {status}: {msg})")
            errors.append((repo_path, status, msg))
        else:
            print("✓")
            pushed += 1

    # ── Summary ──────────────────────────────
    print(f"\n{'═'*60}")
    print(f"Push complete: {pushed}/{total} files pushed")
    if skipped:
        print(f"Skipped (missing locally): {skipped}")
    if errors:
        print(f"Errors: {len(errors)}")
        for path, status, msg in errors:
            print(f"  ✗  {path}  HTTP {status}: {msg}")
    print(f"Commits: {pushed}  (one per file — GitHub API limitation)")
    print(f"Repo:      https://github.com/{REPO_OWNER}/{REPO_NAME}")
    print(f"Dashboard: https://{REPO_OWNER}.github.io/{REPO_NAME}/")
    print(f"GitHub Actions: workflow will trigger on next cron (every 4h)")
    print(f"{'═'*60}\n")


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPA GitHub Multi-File Pusher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m spa_core.tools.github_pusher              # PAT from Keychain GITHUB_PAT_SPA
  python -m spa_core.tools.github_pusher --dry-run
  GITHUB_TOKEN=<PAT> python -m spa_core.tools.github_pusher
        """,
    )
    parser.add_argument("--token",   help="GitHub PAT (DISCOURAGED: leaks into shell history; "
                                          "prefer Keychain GITHUB_PAT_SPA or GITHUB_TOKEN env)")
    parser.add_argument("--dry-run", action="store_true", help="List files that would be pushed, no actual push")
    args = parser.parse_args()

    # Resolve project root (two levels above this file: spa_core/tools/ → project root)
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    if args.dry_run:
        dry_run(project_root)
        return

    # Token resolution order (most-secure first):
    #   1. macOS Keychain (GITHUB_PAT_SPA) — preferred, never on CLI/history
    #   2. GITHUB_TOKEN env var
    #   3. --token CLI arg (discouraged: visible in `ps` and shell history)
    token = _token_from_keychain() or os.environ.get("GITHUB_TOKEN", "") or (args.token or "")
    if not token:
        print("ERROR: No GitHub token provided.\n"
              "  Preferred: store in Keychain →\n"
              "    security add-generic-password -s GITHUB_PAT_SPA -a \"$USER\" -w <PAT>\n"
              "  Or: export GITHUB_TOKEN=<PAT>   (avoid --token: leaks into shell history)",
              file=sys.stderr)
        sys.exit(1)

    push_all(token, project_root)


if __name__ == "__main__":
    main()
