#!/bin/bash
# ============================================================================
# scripts/agent_orchestrator.sh — headless orchestrator agent (ENV_SETUP v3 §3.5)
# ============================================================================
# Runs ONE orchestrator cycle by launching a headless Claude Code session that
# executes docs/ORCHESTRATOR_PROTOCOL.md (read STATE → parse Inbox → ingest
# Owner-Done → ADRs → update STATE/journal → notify new Needs-Owner).
#
# The mechanical steps are deterministic (scripts/orchestrator_queue.py); the
# judgment steps are the Claude session. This is project-management, NOT
# risk/execution/monitoring — LLM is allowed here (and forbidden there).
#
# SAFETY / ACTIVATION GATE (Этап 8):
#   INERT by default. Without env SPA_ORCHESTRATOR_ARMED=1 the agent logs a
#   notice and exits 0 WITHOUT invoking Claude. This makes the plist safe to
#   exist (or even be loaded) before the smoke-test. Activate at Stage 8 by
#   setting SPA_ORCHESTRATOR_ARMED=1 in the plist's EnvironmentVariables and
#   choosing the permission mode with the owner.
# ============================================================================

set -uo pipefail

REPO_ROOT="/Users/yuriikulieshov/Documents/SPA_Claude"
CLAUDE_BIN="${CLAUDE_BIN:-/Users/yuriikulieshov/.local/bin/claude}"
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"
# SPA_ORCHESTRATOR_LOG_SUFFIX (owner-decision 26.08, 2 параллельных агента): второй
# инстанс пишет в СВОЙ файл — без этого два процесса чередовали бы строки в одном
# /tmp/spa_orchestrator.log, и читать «что сделал этот цикл» стало бы нельзя. По
# умолчанию (не задан) — тот же путь, что и всегда, ничего не меняется.
LOG="/tmp/spa_orchestrator${SPA_ORCHESTRATOR_LOG_SUFFIX:-}.log"

export PATH="/Users/yuriikulieshov/.local/bin:/Users/yuriikulieshov/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export HOME="/Users/yuriikulieshov"

cd "$REPO_ROOT" || exit 1

ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }
echo "[$(ts)] === orchestrator cycle START ===" >> "$LOG"

# Bound the log.
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 800 ]; then
    tail -400 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# ── ARMING GATE ─────────────────────────────────────────────────────────────
if [ "${SPA_ORCHESTRATOR_ARMED:-0}" != "1" ]; then
    echo "[$(ts)] INERT: SPA_ORCHESTRATOR_ARMED != 1 — not invoking Claude. (Activate at Stage 8.)" >> "$LOG"
    echo "[$(ts)] === orchestrator cycle END (inert, exit 0) ===" >> "$LOG"
    exit 0
fi

# ── OWNER-GATE ACTIVE (ADR-OWN-2026-07-autoship, owner-approved full auto-ship) ──
# Mark autonomous context so the deterministic push interlock in push_to_github*.py
# enforces the owner-gate on any landing/ push (SAFE ships to live; owner-gated classes
# — yield numbers / tier naming / legal / solicitation — are routed to a needs-owner card
# by scripts/safe_site_push.py, never auto-shipped). Kill = unset SPA_ORCHESTRATOR_ARMED.
export SPA_AUTONOMOUS=1

# ── DURABLE SESSION IDENTITY (card agent-durable-session-id) ────────────────
# THIS shell is the cycle's long-lived process: it waits for claude below and exits with it.
# Announcing it makes "is that session still working?" a measurement instead of a guess —
# scripts/log_session_change.py records session_pid + its start time, and steps 0a/0b use them
# as the primary criterion (the announcement's age stays the fallback). Without this, every
# entry carried the pid of a one-shot CLI process that was already dead when written, so `ps`
# said "no such process" for every cycle, alive or orphaned.
export SPA_SESSION_PID=$$
export SPA_SESSION_ID="${SPA_SESSION_ID:-cycle-$$}"

# ── CYCLE LOCK (ADR-070 п.9, решение владельца 2026-08-07; N слотов — решение владельца
# 26.08 «проверь и внедри, если безопасно», ускорение разгрузки очереди) ────────────────
# По умолчанию (SPA_ORCHESTRATOR_MAX_CONCURRENT не задан) — один цикл за раз, ПОВЕДЕНИЕ
# НЕ МЕНЯЕТСЯ. Карточки от одновременной работы защищены с 30.07, сам цикл — нет: захват
# карточки ловит столкновение уже ПОСЛЕ шагов 0/0a/0b и не ловит вовсе, когда вторая
# сессия берёт следующую карточку и два автономных пушера идут в origin/main наперегонки.
# Замок общий (в главном рабочем дереве — циклы работают из /tmp-worktree), atomic-mkdir,
# живость держателя ИЗМЕРЯЕТСЯ тем же кодом, что шаги 0a/0b. Код 3 = занято живой сессией:
# это не ошибка, а вежливый выход (agent_health не должен краснеть на здоровое поведение).
# Поломка самого замка => `unprotected`, код 0: цикл идёт и говорит об этом вслух.
# Поднять до 2 параллельных циклов — ОДИН флаг здесь + второй launchd-агент (см.
# launchd/com.spa.orchestrator2.plist), а не переписывание замка: safety-ревью 26.08
# нашло и починило единственную незакрытую гонку (дубли в Telegram — telegram_client.
# outbound_lock), карточкам/STATE/пушу уже ничего не грозит при двух держателях.
LOCK_PY="$REPO_ROOT/scripts/orchestrator_cycle_lock.py"
MAX_CONCURRENT="${SPA_ORCHESTRATOR_MAX_CONCURRENT:-1}"
if [ ! -f "$LOCK_PY" ]; then
    # Дерево прода отстаёт от origin (синк идёт Step 0 дневного цикла). Молчать нельзя:
    # незаметно потерянная защита — это класс fail-OPEN, ради которого замок и написан.
    echo "[$(ts)] lock: ⚠️ нет $LOCK_PY — цикл идёт БЕЗ защиты от одновременного прогона" >> "$LOG"
else
    LOCK_OUT="$("$PYTHON" "$LOCK_PY" acquire --max-concurrent "$MAX_CONCURRENT" \
                --session "$SPA_SESSION_ID" --pid "$SPA_SESSION_PID" 2>&1)"
    LOCK_RC=$?
    echo "[$(ts)] lock: $LOCK_OUT" >> "$LOG"
    if [ "$LOCK_RC" -eq 3 ]; then
        echo "[$(ts)] === orchestrator cycle END (busy, polite exit 0) ===" >> "$LOG"
        exit 0
    fi
fi
# Снимаем и при аварийном выходе — брошенный замок хоть и снимается следующим прогоном по
# измеренной смерти держателя, но лишний круг «занято» никому не нужен.
release_lock() {
    [ -f "$LOCK_PY" ] || return 0
    "$PYTHON" "$LOCK_PY" release --max-concurrent "$MAX_CONCURRENT" \
        --session "$SPA_SESSION_ID" --pid "$SPA_SESSION_PID" >> "$LOG" 2>&1
}
trap release_lock EXIT

# ── ПЕРВАЯ ДОСТАВКА ВОПРОСОВ ВЛАДЕЛЬЦУ (цикл #345) ──────────────────────────
# Вопрос, попавший на origin НЕ через живую сессию (merge ветки / PR / другая машина),
# до владельца не доезжал ничем: отправитель умеет обе стороны очереди с #330, но у него
# НЕТ вызывающего — `resend-open` был только подкомандой CLI. Замер 22.08: три `needs-owner`
# на origin, все `delivered: false`, два из них настоящие (Protection Lab, PR #30).
# Здесь именно ПЕРВАЯ отправка: `owner_requested` не ставится, дедуп/анти-шторм/лимит потока
# стоят все; потолок за прогон, остаток называется поимённо. Пересылка по просьбе владельца
# (`resend-open`) — по-прежнему только руками.
# Подоболочка и `|| true`: доставка не смеет ронять цикл (урок #221 — секция, способная
# уронить обёртку, гасит агента молча). Скрипта нет (прод отстал от origin) => говорим вслух.
if [ -f "$REPO_ROOT/scripts/orchestrator_queue.py" ]; then
    DELIVER_OUT="$( ( "$PYTHON" "$REPO_ROOT/scripts/orchestrator_queue.py" deliver-new ) 2>&1 || true )"
    echo "[$(ts)] deliver-new: ${DELIVER_OUT:-(нет вывода)}" >> "$LOG"
else
    echo "[$(ts)] deliver-new: ⚠️ нет $REPO_ROOT/scripts/orchestrator_queue.py — первая доставка вопросов владельцу НЕ выполнялась" >> "$LOG"
fi

# ── ШАГ 0a-ГОЛОД (карточка inbox-critical-kartochka-goloda-et-4-dnya-pri-40-tsiklah) ──
# Сторож родился 26.08 вместе с шагом протокола — и БЕЗ вызывающего: протокол его называл,
# запускать его было некому, а упоминание в docs/ проводкой намеренно не считается
# (spa_core/tests/_unwired.py). Ровно тот класс, ради которого заведён храповик
# неподключённых скриптов: доставлен, покрыт 19 зелёными тестами, мёртв.
#
# Здесь он не просто ЗАПУСКАЕТСЯ, а ДОХОДИТ ДО СЕССИИ: находка обязывает взять голодающую
# карточку первой, а сессия читает только PROMPT. Строка в логе этого не делает — цикл в
# лог не смотрит. Поэтому вердикт вклеивается в начало промпта, ПЕРЕД остальным протоколом.
#
# Fail-CLOSED в обе стороны: код 1 — находка; код 0 — голода нет; ЛЮБОЙ другой код (и
# отсутствие скрипта в отставшем прод-дереве) — «НЕ ИЗМЕРЕНО», и это тоже уезжает в промпт.
# Молчание здесь читалось бы как «не голодает», а это ровно тот fail-OPEN, из-за которого
# critical-приказ владельца простоял четверо суток при 40+ прошедших циклах.
STARVE_PY="$REPO_ROOT/scripts/check_owner_order_starvation.py"
STARVE_PREFIX=""
if [ ! -f "$STARVE_PY" ]; then
    STARVE_OUT="нет $STARVE_PY (прод-дерево отстало от origin)"
    STARVE_RC=2
else
    STARVE_OUT="$("$PYTHON" "$STARVE_PY" 2>&1)"
    STARVE_RC=$?
fi
echo "[$(ts)] starvation(rc=$STARVE_RC): ${STARVE_OUT:-(нет вывода)}" >> "$LOG"
if [ "$STARVE_RC" -eq 1 ]; then
    STARVE_PREFIX="ШАГ 0a-ГОЛОД — НАХОДКА, исполняется ПЕРВЫМ, до шага 0a и до разбора очереди \
(исключение — активная авария/стоп-кран): $STARVE_OUT. Возьми ЭТУ карточку первой; если берёшь другую — \
назови причину в журнале. Дальше — обычный протокол. "
elif [ "$STARVE_RC" -ne 0 ]; then
    STARVE_PREFIX="ШАГ 0a-ГОЛОД НЕ ИЗМЕРЕН (код $STARVE_RC): $STARVE_OUT. Это НЕ «приказ владельца не голодает» — \
проверь голодание руками перед выбором задачи и заведи карточку на сам сторож. "
fi

# ── ARMED: run one headless GOVERNED-AUTONOMY cycle ─────────────────────────
PROMPT="${STARVE_PREFIX}Ты — оркестратор SPA под НОВЫМ протоколом «управляемая автономия» (owner-approved 2026-07-15). \
Исполни ПОЛНОСТЬЮ docs/ORCHESTRATOR_PROTOCOL.md за один цикл, включая раздел «Автономный рабочий мандат»: \
(1) прочитай docs/STATE.md + docs/decisions/INDEX.md + docs/SYSTEM_BRIEFING.md + свежие data/session_changes.jsonl, \
затем ОБЯЗАТЕЛЬНО python3 scripts/consume_office_reports.py (ADR-066: офис+сторож архитектуры в контекст, \
квитанции потребления; RED/CRITICAL/НЕ-ПРОЧИТАН из вывода => карточка, не молчание); \
(1в) ОБЯЗАТЕЛЬНО из своего worktree python3 scripts/cycle_analytics_audit.py (ADR-130, решение владельца \
24.08 вариант 2: ежедневный аудит протокол-слепоты — шаг цикла; прогон идёт в песочнице, живое data/ не \
трогается; код 1 => обновлённый spa_core/analytics/_protocol_blindness.py доставить ЭТИМ ЖЕ пушем, код 2 => карточка); \
(2) разбери Inbox (задача/идея/непонятно) и инжест owner-done (ADR + set-status ingested через \
scripts/orchestrator_queue.py; НИКОГДА не ставь owner-done); (3) если явных заданий нет — возьми ОДНУ \
безопасную задачу сам (hardening/тесты/доки/мелкие НЕ-owner-gated фичи из backlog/roadmap). \
ОБЯЗАТЕЛЬНО: объяви владение файлами (scripts/log_session_change.py) до правок; изолированный worktree; \
ТЕСТЫ ЗЕЛЁНЫЕ до пуша; пуш КОДА через push_to_github.py, а пуш ЛЮБЫХ файлов сайта (landing/**) — ТОЛЬКО \
через scripts/safe_site_push.py (owner-gate ADR-OWN-2026-07: безопасные layout/копирайт/SEO/багфиксы \
уезжают в live сами; числа доходности/нейминг тиров/legal/solicitation линтер САМ заворачивает в карточку). \
ЗАПРЕЩЕНО: трогать RiskPolicy/kill/risk-логику, живой трек data/equity_curve_daily.json, деплой/выгрузку \
агентов, МОЛЧА ослаблять/отключать тесты — всё это ТОЛЬКО карточкой needs-owner + notify, не делать. \
Обнови STATE + journal. Ничего «в воздухе». По завершении — краткий отчёт что сделано/что в карточки."

# Headless: не может отвечать на интерактивные запросы разрешений → bypass (машина владельца,
# гардрейлы в промпте + стоп-правила протокола + инвариант #16). Выключение = снять
# SPA_ORCHESTRATOR_ARMED из plist (launchctl bootout com.spa.orchestrator).
echo "[$(ts)] ARMED: invoking headless Claude (governed autonomy, skip-permissions)" >> "$LOG"
"$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions >> "$LOG" 2>&1
RC=$?
echo "[$(ts)] === orchestrator cycle END (claude exit $RC) ===" >> "$LOG"
exit $RC
