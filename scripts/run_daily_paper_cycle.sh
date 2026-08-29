#!/bin/bash
# scripts/run_daily_paper_cycle.sh
# Daily paper trading cycle — CANONICAL runner (called by launchd com.spa.daily_cycle).
#
# Replaces the legacy com.spa.cyclerunner agent (disabled 2026-06-20). That agent
# was the only thing actually advancing the paper track; this script now owns that job.
#
# Two steps, in order:
#   1. cycle_runner — THE engine. Pulls live APY/TVL, runs strategies + RiskPolicy,
#      rebalances the virtual portfolio, writes paper_trading_status.json /
#      equity_curve_daily.json / trades.json / audit_trail (source="cycle_runner").
#      This is what makes the track advance. WITHOUT it the track silently freezes.
#   2. CPACycleWithEvidence — evidence report built ON TOP of the fresh state (non-fatal).
#
# Logs to logs/daily_cycle_YYYYMMDD.log
#
# NOTE: no `set -e` — we capture the cycle's exit code and still run the evidence
# report even if the cycle returns non-zero, then exit with the cycle's code.
#
# HEARTBEAT: status lines go through `tee` so they reach BOTH the dated log and
# this script's stdout. Under launchd, stdout is captured into the plist's
# StandardOutPath (logs/launchd_stdout.log) — which is what agent_health checks
# for freshness. The heavy cycle/evidence output stays in the dated log only.
# Result: agent fired → fresh launchd_stdout.log; cycle failed → non-zero exit
# (agent_health flags last_exit); never ran → stale/missing log → CRITICAL.
#
# PATH: launchd does not inherit the shell PATH, so PYTHON is hardcoded (miniconda).

PYTHON=/Users/yuriikulieshov/miniconda3/bin/python3

# AGENT_MODULE: spa_core.paper_trading.cycle_runner
# Точка входа, НЕСУЩАЯ КОНТРАКТ этого агента (его PRODUCES). Шагов в скрипте
# несколько (движок, аудитор аллокации, evidencer APY, снимок сайта), и вывести
# один модуль из четырёх нельзя — перепись контрактов честно отказывала, а вместе
# с отказом агент молча пропадал из неё целиком. Объявление снимает догадку.

cd ~/Documents/SPA_Claude

LOG_DIR=~/Documents/SPA_Claude/logs
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_cycle_$(date +%Y%m%d).log"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting daily paper cycle (cycle_runner)" | tee -a "$LOG_FILE"

# ── Кто нас позвал (решение владельца 2026-08-09, вариант 1) ───────────────
# 08.08 цикл отработал 8 раз не по расписанию, и КТО его звал — система не записывала.
# Разбор дважды упёрся в догадки. Риск не теоретический: сессия, умершая в пределах двух
# часов до 08:00, может стоить дня трека, а без имени вызывающего чинить нечего.
#
# Это ИЗМЕРЕНИЕ, а не изменение поведения: ни один прогон отсюда не начнётся и не
# прекратится. Всё в подоболочке с подавлением ошибок — учёт не имеет права уронить цикл
# (лечение не должно быть опаснее болезни).
CALLER_NAME=$(ps -o comm= -p "$PPID" 2>/dev/null | tr -d ' ' || true)
CALLER_ARGS=$(ps -o args= -p "$PPID" 2>/dev/null | head -c 160 || true)
# Признак — метка ОКРУЖЕНИЯ, а не родитель. Замер 10.08 показал, почему: за сутки
# 51 запись, все с ppid=1 и name=launchd, и вывод «значит расписание» ОКАЗАЛСЯ ЛОЖНЫМ.
# `ppid=1` так же выглядит у ОСИРОТЕВШЕГО процесса: родитель умер, ядро переподвесило
# потомка к pid 1. Сессия, запустившая цикл и завершившаяся, неотличима от расписания.
# Проверка отвечала на «кто мой родитель СЕЙЧАС», а читалась как «кто меня запустил».
#
# XPC_SERVICE_NAME ставит сам launchd запускаемому агенту; в сессии её нет и подделать
# её случайно нельзя. ppid остаётся в строке как СПРАВОЧНОЕ поле.
# Второй признак — SPA_LAUNCHD=1 из EnvironmentVariables плиста. Нужен потому, что
# XPC_SERVICE_NAME проверить в тесте НЕЛЬЗЯ: подмена этой переменной роняет процесс
# (SIGABRT, замерено 10.08). Признак, который невозможно проверить, — это признак,
# которому нельзя доверять; поэтому рядом стоит тот, что проверяется безопасно.
if [ "${SPA_LAUNCHD:-}" = "1" ] || [ -n "${XPC_SERVICE_NAME:-}" ]; then
    CALLER_KIND="scheduled"
    CALLER_SVC="${XPC_SERVICE_NAME:-${SPA_LAUNCHD:+plist}}"
else
    CALLER_KIND="ad-hoc"
    CALLER_SVC="-"
fi
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] CYCLE_CALLER kind=$CALLER_KIND svc=${CALLER_SVC} ppid=$PPID name=${CALLER_NAME:-?} args=${CALLER_ARGS:-?}" | tee -a "$LOG_FILE"

# ── Step 0: code sync from origin/main (agent-prod-clean-checkout-variant2) ─
# Pushes land on origin via API and never touch this tree; without this step the cycle
# executes stale code (2026-08-03: prod ran July-15 code for weeks). Whole-dir sync of
# spa_core/scripts/tests + pushers, fail-safe (rolls back on broken imports, non-zero exit).
# NON-FATAL for the cycle: on sync failure we run on the previous (verified) code — the
# failure is loud in data/code_sync_status.json + /tmp/spa_code_sync.log + drift monitor.
# NOTE: this may replace run_daily_paper_cycle.sh itself on disk. Safe: git-checkout/tar
# replace files by unlink+create (new inode), so the running shell keeps reading the OLD
# inode to completion; code_sync additionally wraps itself in main() for the same reason.
bash scripts/code_sync_from_origin.sh >> "$LOG_FILE" 2>&1
SYNC_EXIT=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] code_sync exit=$SYNC_EXIT (0=synced/in-sync, 1=rolled back)" | tee -a "$LOG_FILE"

# ── Step 1: real cycle engine — advances the paper track ───────────────────
# OWNER-APPROVED 2026-07-06 (money-path allocation dial): use the constrained yield
# optimizer instead of the risk_adjusted heuristic. It concentrates into the highest-yield
# protocols WITHIN the RiskPolicy caps (TVL floor, 40% T1 / 20% T2 per-protocol, T2≤50%,
# APY≤30%) — targets ~6-8% projected (~5-7% realized after cash buffer/costs) vs the ~3.2%
# the risk_adjusted default was delivering. Reversible: unset this env to revert to the default.
export SPA_ALLOCATOR_MODEL="optimized_yield"

# WRITE-INTERLOCK (track-integrity): cycle_runner is fail-CLOSED by default and
# will NOT write the canonical live track without an explicit opt-in. This is
# THE production cycle, so it MUST pass --live (== SPA_ALLOW_LIVE_WRITE=1).
# Without --live the daily track would silently freeze (writes go to a sandbox).
"$PYTHON" -m spa_core.paper_trading.cycle_runner --verbose --live >> "$LOG_FILE" 2>&1
CYCLE_EXIT=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] cycle_runner exit=$CYCLE_EXIT" | tee -a "$LOG_FILE"

# ── Step 2: evidence report on top of the fresh state (non-fatal) ──────────
"$PYTHON" -c "
import sys
sys.path.insert(0, '.')
from spa_core.backtesting.cpa_cycle_with_evidence import CPACycleWithEvidence
print(CPACycleWithEvidence(base_dir='.').run())
" >> "$LOG_FILE" 2>&1 \
  || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] evidence report failed (non-fatal)" >> "$LOG_FILE"

# ── Step 2b: Allocation Auditor (AI1-1.1) — соответствует ли СЕГОДНЯШНЯЯ книга
# записанной политике (docs/allocation_logic_explicit.md). Только читает и сообщает:
# капитал не двигает, ничего не гейтит. Код выхода 0/1/2 (норма / не измерено /
# нарушения) ЛОГИРУЕТСЯ и намеренно НЕ влияет на цикл — надзор не имеет права
# останавливать трек. Подключено с разрешения владельца 2026-08-29.
"$PYTHON" -m spa_core.agents.allocation_auditor >> "$LOG_FILE" 2>&1
ALLOC_AUDIT_EXIT=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] allocation_auditor exit=$ALLOC_AUDIT_EXIT (0=норма, 1=не измерено, 2=нарушения; НЕ гейт)" | tee -a "$LOG_FILE"

# ── Step 2c: APY Evidencer (AI1-2.2) — уровень доказательности каждому записанному
# числу доходности (ADR-YL-006: APY нельзя записывать без уровня). Тоже read-only,
# тоже не гейт.
"$PYTHON" -m spa_core.agents.apy_evidencer >> "$LOG_FILE" 2>&1
APY_EVIDENCE_EXIT=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] apy_evidencer exit=$APY_EVIDENCE_EXIT (0=всё наблюдаемо, 1=есть непроцитируемые, 2=есть неизмеримые; НЕ гейт)" | tee -a "$LOG_FILE"

# ── Step 3: Site Custodian auto-deploy (ADR-YL-011) — regenerate the public track_snapshot from the
# fresh golive/equity state and push it if changed, triggering deploy-landing.yml (landing/** trigger).
# Non-fatal: a deploy hiccup must never fail the cycle. Result: fresh snapshot -> fresh site, <=30 min lag.
"$PYTHON" scripts/deploy_site_snapshot.py >> "$LOG_FILE" 2>&1 \
  || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] site snapshot deploy failed (non-fatal)" >> "$LOG_FILE"

# ── Step 4: fleet-parity drift guard (Q3-2) — the THIRD watchman of .claude/rules/deployment.md:
# "is the fleet COMPOSITION the one we declared?" (drift monitor answers "is it the code we accepted",
# acceptance answers "can it start", agent_health answers "is it alive" — none of them answers this one).
# It had no caller at all: written in July, invoked once by hand, then silent for 597h while
# agent_health honestly repeated "fleet parity stale" into a void (agent-fleet-parity-guard-never-scheduled).
# Here instead of its own LaunchAgent on purpose: the fleet must not grow by one just to watch itself,
# and a guard that lives inside the cycle cannot be forgotten by the installer the way it just was.
# NON-FATAL and deliberately so: exit 1 means DRIFT (a real finding to read in data/fleet_parity.json),
# not a broken cycle. If this step stops running, fleet_parity.json goes stale and agent_health WARNs
# within 26h — the silence itself is alarmed.
"$PYTHON" scripts/fleet_parity_check.py >> "$LOG_FILE" 2>&1 \
  || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] fleet parity: DRIFT or check failed (non-fatal, see data/fleet_parity.json)" >> "$LOG_FILE"

# ── Шагов сверки офис↔книга и моста находок здесь НЕТ намеренно (цикл #125, 2026-08-06).
# Эту работу выполняет РАЗВЁРНУТЫЙ агент `com.spa.decision_loop` (каждые 6ч,
# `spa_core.monitoring.findings_bridge --run`, ADR-066 Фаза 3). Дублировать его шагом
# цикла — значит гонять два писателя за один `data/house_view_gap.json`. Если агент
# замолчит, это увидит `agent_health` (свежесть по plist) и B2 сторожа архитектуры
# (SLO артефакта) — молчание алармится, а не проходит незамеченным.

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Cycle completed (cycle_runner exit $CYCLE_EXIT)" | tee -a "$LOG_FILE"
exit $CYCLE_EXIT
