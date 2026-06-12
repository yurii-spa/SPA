#!/bin/bash
# МЕГА-ПУШ всех накопленных файлов из незакрытых задач
# MP-016b / MP-103 / MP-108 / MP-109 / MP-111 / MP-112
# MP-201 / MP-207 / SPA-V416 / model_config / MP-009-fix + текущие изменения
# PAT берётся из macOS Keychain через push_to_github.py — токены не встроены

cd ~/Documents/SPA_Claude

FILES=""

# ── MP-016b: Telegram Alerts ──────────────────────────────────────────────────
for f in \
  spa_core/alerts/bot_commands.py \
  spa_core/alerts/alert_manager.py \
  spa_core/alerts/telegram_client.py \
  spa_core/tests/test_telegram_alerts.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── MP-103: PDF Reporting ─────────────────────────────────────────────────────
for f in \
  spa_core/reporting/pdf_report.py \
  spa_core/tests/test_pdf_report.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── MP-108: Kill Switch ───────────────────────────────────────────────────────
for f in \
  spa_core/governance/kill_switch.py \
  scripts/kill_switch_drill.py \
  spa_core/tests/test_kill_switch.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── MP-109: DB Persistence ────────────────────────────────────────────────────
for f in \
  spa_core/persistence/db.py \
  spa_core/persistence/json_compat.py \
  scripts/db_migrate.py \
  spa_core/tests/test_db.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── MP-111: Milestone Tracker ─────────────────────────────────────────────────
for f in \
  spa_core/milestone/milestone_tracker.py \
  spa_core/tests/test_milestone_tracker.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── MP-112: Stress Engine ─────────────────────────────────────────────────────
for f in \
  spa_core/stress/stress_engine.py \
  spa_core/tests/test_stress_engine.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── MP-207: Allocation Tuner ──────────────────────────────────────────────────
for f in \
  spa_core/tuner/__init__.py \
  spa_core/tuner/allocation_tuner.py \
  spa_core/paper_trading/cycle_runner.py \
  scripts/run_tuner.py \
  spa_core/tests/test_allocation_tuner.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── MP-201: Pendle PT Adapter ─────────────────────────────────────────────────
for f in \
  spa_core/adapters/pendle_pt.py \
  spa_core/tests/test_pendle_pt.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── Model Config (spa_core/config/) ───────────────────────────────────────────
for f in \
  spa_core/config/__init__.py \
  spa_core/config/model_config.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── MP-009 fix: launchd plists ────────────────────────────────────────────────
for f in \
  spa_core/launchd/com.spa.httpserver.plist \
  spa_core/launchd/com.spa.autopush.plist
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── SPA-V416: LLM Forbidden Lint + CI ────────────────────────────────────────
for f in \
  spa_core/ci/__init__.py \
  spa_core/ci/llm_forbidden_lint.py \
  spa_core/tests/test_llm_forbidden_lint.py \
  spa_core/tests/test_dashboard_adapter_sync.py \
  data/llm_forbidden_lint.json
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── Текущие изменения: model routing (Fable5 architect) ──────────────────────
for f in \
  spa_core/dev_agents/architect.py \
  spa_core/agents/model_config.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── SPA-V417: Adapter SDK v1 ──────────────────────────────────────────────────
for f in \
  spa_core/adapter_sdk/__init__.py \
  spa_core/adapter_sdk/base.py \
  spa_core/adapter_sdk/declarative.py \
  spa_core/adapter_sdk/registry.py \
  spa_core/adapter_sdk/validator.py \
  spa_core/tests/test_adapter_sdk.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── SPA-V417: Adapter SDK core files ─────────────────────────────────────────
for f in \
  spa_core/adapter_sdk/contract.py \
  spa_core/adapter_sdk/declarative_adapter.py \
  spa_core/adapter_sdk/manifest.py \
  spa_core/adapter_sdk/registry.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── SPA-V418: Candidate auto-discovery ────────────────────────────────────────
for f in \
  spa_core/adapter_sdk/discovery.py \
  spa_core/tests/test_discovery.py \
  data/candidate_registry.json
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── SPA-V419: 9 новых манифестов (MP-206 инкремент 1) ────────────────────────
for f in \
  spa_core/adapter_sdk/manifests/ethena_susde.yaml \
  spa_core/adapter_sdk/manifests/gearbox.yaml \
  spa_core/adapter_sdk/manifests/across.yaml \
  spa_core/adapter_sdk/manifests/stargate.yaml \
  spa_core/adapter_sdk/manifests/velodrome_stable.yaml \
  spa_core/adapter_sdk/manifests/convex_3pool.json \
  spa_core/adapter_sdk/manifests/balancer_stable.json \
  spa_core/adapter_sdk/manifests/aerodrome_stable.json \
  spa_core/adapter_sdk/manifests/venus.json \
  spa_core/tests/test_adapter_manifests.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── SPA-V420: 9 новых манифестов (MP-206 финал, итого 21) ────────────────────
for f in \
  spa_core/adapter_sdk/manifests/crvusd_llamalend.yaml \
  spa_core/adapter_sdk/manifests/fraxlend.yaml \
  spa_core/adapter_sdk/manifests/notional_v3.yaml \
  spa_core/adapter_sdk/manifests/silo.yaml \
  spa_core/adapter_sdk/manifests/moonwell.yaml \
  spa_core/adapter_sdk/manifests/dolomite.json \
  spa_core/adapter_sdk/manifests/benqi.json \
  spa_core/adapter_sdk/manifests/clearpool.json \
  spa_core/adapter_sdk/manifests/ipor.json
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── SPA-V421: Agent Runtime v1 (MP-301) ──────────────────────────────────────
for f in \
  spa_core/agent_runtime/__init__.py \
  spa_core/agent_runtime/mandate.py \
  spa_core/agent_runtime/budget.py \
  spa_core/agent_runtime/runtime.py \
  spa_core/agent_runtime/mandates/ceo.json \
  spa_core/agent_runtime/mandates/alpha.json \
  spa_core/agent_runtime/mandates/reporting.json \
  spa_core/tests/test_agent_runtime.py
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── Bot fix: continuous long-polling daemon ───────────────────────────────────
for f in \
  spa_core/alerts/bot_commands.py \
  com.spa.bot_commands.plist
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── Статус и план ─────────────────────────────────────────────────────────────
for f in \
  KANBAN.json \
  SPA_sprint_log.md
do
  [ -f "$f" ] && FILES="$FILES $f"
done

# ── Итог перед пушем ──────────────────────────────────────────────────────────
echo "=== FILES TO PUSH ==="
for f in $FILES; do echo "  $f"; done
echo "====================="
echo "Total: $(echo $FILES | wc -w | tr -d ' ') files"
echo ""

if [ -z "$FILES" ]; then
  echo "ERROR: No files found to push!"
  exit 1
fi

python3 push_to_github.py \
  --files $FILES \
  --message "feat: mega-push MP-016b/103/108/109/111/112/201/207/V416-V421 + model routing + 21 SDK manifests + agent_runtime (MP-301) + bot continuous daemon ✅"

echo ""
echo "✅ Push done!"
