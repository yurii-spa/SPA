#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# DEPLOY.sh — Мастер-деплой SPA (2026-06-14)
# Коммитит всё локально + пушит всё на GitHub + устанавливает агентов
#
# Запуск: bash ~/Documents/SPA_Claude/scripts/DEPLOY.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

CD="$HOME/Documents/SPA_Claude"
cd "$CD"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
fail() { echo -e "${RED}❌ $*${NC}"; }

echo "═══════════════════════════════════════════════════════"
echo "  SPA Master Deploy — $(date '+%Y-%m-%d %H:%M')"
echo "═══════════════════════════════════════════════════════"

# ── 1. PAT ─────────────────────────────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat | tr -d '[:space:]')
# Отклоняем плейсхолдер
[[ "$PAT" == *"ТВОЙ"* ]] && PAT=""
[[ "$PAT" == "ghp_ТВОЙ"* ]] && PAT=""

if [ -z "$PAT" ]; then
  fail "PAT не найден. Получи токен на github.com/settings/tokens и добавь:"
  echo "   security add-generic-password -s GITHUB_PAT_SPA -a spa -w ghp_ТВОЙ_ТОКЕН"
  echo ""
  warn "GitHub-пуш пропущен. Локальный коммит и установка агентов продолжатся."
  SKIP_PUSH=1
else
  ok "PAT найден (${#PAT} символов)"
  SKIP_PUSH=0
fi

# ── 2. Git: снимаем stale lock ──────────────────────────────────────
if [ -f ".git/index.lock" ]; then
  rm -f ".git/index.lock"
  ok "Удалён stale git index.lock"
fi

# ── 3. Git commit ──────────────────────────────────────────────────
echo ""
echo "── Локальный git commit ───────────────────────────────"
git config user.email "yuriycooleshov@gmail.com" 2>/dev/null || true
git config user.name "Yurii SPA" 2>/dev/null || true
git add -A 2>/dev/null || true
CHANGED=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
if [ "$CHANGED" -gt 0 ]; then
  git commit -m "feat: SPA v8.12-v8.18 analytics (551 tests) + Telegram Bot v2.0 + P0 fixes (uptime_monitor, bot plist, cloudflared, install_agents) + AGENT_AUDIT_V2 + KANBAN 854 done (2026-06-14)" || true
  ok "Git commit: $CHANGED файлов"
else
  ok "Git: нечего коммитить (уже чисто)"
fi

# ── 4. GitHub push ──────────────────────────────────────────────────
if [ "$SKIP_PUSH" = "0" ]; then
  echo ""
  echo "── GitHub push ────────────────────────────────────────"

  _push() {
    local name="$1"; shift
    local msg="$1"; shift
    local files=("$@")

    # Фильтруем только существующие файлы
    existing=()
    for f in "${files[@]}"; do
      [ -f "$f" ] && existing+=("$f")
    done

    if [ ${#existing[@]} -eq 0 ]; then
      warn "$name: нет файлов для пуша"
      return
    fi

    echo -n "  → $name (${#existing[@]} файлов)... "
    if python3 push_to_github.py --message "$msg" --pat "$PAT" --files "${existing[@]}" 2>&1 | tail -1 | grep -q "✅\|pushed\|success\|OK\|commit"; then
      ok "$name"
    else
      python3 push_to_github.py --message "$msg" --pat "$PAT" --files "${existing[@]}" 2>&1 | tail -3
      warn "$name: проверь выше"
    fi
    sleep 1  # rate limit
  }

  # === Аналитические модули v8.12-v8.18 ===
  _push "v8.12 — MEV + Borrower Concentration" \
    "feat(v8.12): MP-1106 MEV protection + MP-1107 borrower concentration | 141 tests" \
    spa_core/analytics/defi_protocol_mev_protection_effectiveness_analyzer.py \
    spa_core/analytics/defi_protocol_borrower_concentration_risk_analyzer.py \
    spa_core/tests/test_defi_protocol_mev_protection_effectiveness_analyzer.py \
    spa_core/tests/test_defi_protocol_borrower_concentration_risk_analyzer.py

  _push "v8.13 — Insurance Fund + Yield Harvesting" \
    "feat(v8.13): MP-1108 insurance fund + MP-1109 yield harvesting optimizer | 131 tests" \
    spa_core/analytics/defi_protocol_insurance_fund_adequacy_analyzer.py \
    spa_core/analytics/defi_protocol_yield_harvesting_frequency_optimizer.py \
    spa_core/tests/test_defi_protocol_insurance_fund_adequacy_analyzer.py \
    spa_core/tests/test_defi_protocol_yield_harvesting_frequency_optimizer.py

  _push "v8.14 — Lending Utilization + Cross-Chain Basis" \
    "feat(v8.14): MP-1110 lending utilization elasticity + MP-1111 cross-chain basis risk | 132 tests" \
    spa_core/analytics/defi_protocol_lending_utilization_elasticity_analyzer.py \
    spa_core/analytics/defi_protocol_cross_chain_yield_basis_risk_analyzer.py \
    spa_core/tests/test_defi_protocol_lending_utilization_elasticity_analyzer.py \
    spa_core/tests/test_defi_protocol_cross_chain_yield_basis_risk_analyzer.py

  _push "v8.15 — Stablecoin Redemption + Emergency Withdrawal" \
    "feat(v8.15): MP-1148 stablecoin par redemption + MP-1149 emergency withdrawal pause risk | 207 tests" \
    spa_core/analytics/defi_protocol_stablecoin_par_redemption_capacity_analyzer.py \
    spa_core/analytics/defi_protocol_emergency_withdrawal_pause_risk_analyzer.py \
    spa_core/tests/test_defi_protocol_stablecoin_par_redemption_capacity_analyzer.py \
    spa_core/tests/test_defi_protocol_emergency_withdrawal_pause_risk_analyzer.py

  _push "v8.16 — Min Profitable Position + Keeper Reliability" \
    "feat(v8.16): MP-1150 min profitable position + MP-1151 keeper reliability | 207 tests" \
    spa_core/analytics/defi_protocol_minimum_profitable_position_size_analyzer.py \
    spa_core/analytics/defi_protocol_auto_compound_keeper_reliability_analyzer.py \
    spa_core/tests/test_defi_protocol_minimum_profitable_position_size_analyzer.py \
    spa_core/tests/test_defi_protocol_auto_compound_keeper_reliability_analyzer.py

  _push "v8.17 — Performance Fee HWM + Crystallization" \
    "feat(v8.17): MP-1152 performance fee HWM + MP-1153 crystallization frequency | 280 tests" \
    spa_core/analytics/defi_protocol_performance_fee_high_water_mark_analyzer.py \
    spa_core/analytics/defi_protocol_performance_fee_crystallization_frequency_analyzer.py \
    spa_core/tests/test_defi_protocol_performance_fee_high_water_mark_analyzer.py \
    spa_core/tests/test_defi_protocol_performance_fee_crystallization_frequency_analyzer.py

  _push "v8.18 — Deposit Cap + Depositor Concentration" \
    "feat(v8.18): MP-1154 deposit cap headroom + MP-1155 depositor concentration | 240 tests" \
    spa_core/analytics/defi_protocol_deposit_cap_headroom_analyzer.py \
    spa_core/analytics/defi_protocol_depositor_concentration_analyzer.py \
    spa_core/tests/test_defi_protocol_deposit_cap_headroom_analyzer.py \
    spa_core/tests/test_defi_protocol_depositor_concentration_analyzer.py

  # === Module registry (общий для всех спринтов) ===
  _push "Module Registry (Tier-B 402 modules)" \
    "feat: analytics _module_registry.py — Tier-B 402 modules (v8.12-v8.18)" \
    spa_core/analytics/_module_registry.py \
    spa_core/analytics/signal_aggregator.py

  # === Telegram Bot v2.0 ===
  _push "Telegram Bot v2.0" \
    "feat: Telegram Bot v2.0 — 9 commands, polling, inline buttons, stdlib only, 17 tests" \
    spa_core/telegram/__init__.py \
    spa_core/telegram/bot.py \
    tests/test_telegram_bot_v2.py

  # === P0/P1 Bug Fixes ===
  _push "fix P0-1: uptime_monitor exit 256" \
    "fix(P0-1): uptime_monitor always-exit-1 on DEGRADED → now returns 0, adds --strict flag | 21 tests" \
    spa_core/monitoring/uptime_monitor.py \
    tests/test_uptime_monitor.py \
    scripts/com.spa.uptime_monitor.plist

  _push "fix P0-2: Telegram plist conflict" \
    "fix(P0-2): resolve 3x com.spa.bot_commands.plist conflict — canonical in scripts/, others renamed .bak" \
    scripts/com.spa.bot_commands.plist \
    com.spa.bot_commands.plist.bak \
    launchd/com.spa.bot_commands.plist.bak

  _push "fix P0-3: cloudflared + install_agents all 19" \
    "fix(P0-3,P1): cloudflared HOME env var + run_cloudflared.sh paths + install_agents auto-discover all 19 plists" \
    scripts/com.spa.cloudflared.plist \
    scripts/run_cloudflared.sh \
    scripts/install_agents.sh

  # === Agent Audit v2 ===
  _push "Agent Audit v2 + KANBAN" \
    "docs: AGENT_AUDIT_V2.md — full agent gap analysis, 11 P0/P1 tasks added to KANBAN | Tier 1 roadmap" \
    docs/AGENT_AUDIT_V2.md \
    KANBAN.json \
    sprint_log.md \
    CURRENT_STATE.md \
    RULES.md \
    docs/ADR-031-analytics-integration.md \
    docs/ADR-032-push-strategy.md \
    docs/DISASTER_RECOVERY.md \
    .gitignore

  # === Scripts ===
  _push "Deploy scripts" \
    "chore: deploy scripts, plists, kill-switch fix, governance fix" \
    scripts/DEPLOY.sh \
    scripts/deploy_all.sh \
    scripts/agent_status.sh \
    scripts/com.spa.analytics_tier_c.plist \
    scripts/com.spa.daily-paper-report.plist \
    scripts/com.spa.checkpoint-7day.plist \
    scripts/com.spa.fund-api.plist \
    scripts/com.spa.autopush.plist \
    data/kill_switch_active.json

  ok "Все пуши завершены"
fi

# ── 5. Установка агентов ────────────────────────────────────────────
echo ""
echo "── Установка launchd агентов ──────────────────────────"
bash scripts/install_agents.sh 2>&1 | grep -E "✅|❌|⚠️|Loaded|Error|com\.spa" | head -30
ok "Агенты обновлены"

# ── 6. Финальный статус ─────────────────────────────────────────────
echo ""
echo "── Статус агентов ─────────────────────────────────────"
launchctl list 2>/dev/null | grep "com.spa" | awk '{
  if ($1 != "-") {
    status = "✅ RUNNING (pid=" $1 ")"
  } else if ($2 == "0") {
    status = "⏸ IDLE"
  } else {
    status = "❌ CRASHED (exit=" $2 ")"
  }
  printf "  %-44s %s\n", $3, status
}' | sort

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  DEPLOY DONE"
echo "  Dashboard: http://localhost:8766"
echo "  Telegram:  /status в боте"
echo "═══════════════════════════════════════════════════════"
