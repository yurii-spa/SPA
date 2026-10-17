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
# ── МЕТКА ВЛАДЕНИЯ (ADR-720) ───────────────────────────────────────────────────────────
# Замок держит ЗАПУСКАТЕЛЬ (этот скрипт), а работу делает РАБОТНИК (headless claude),
# которого обёртка поднимает лидером СВОЕЙ сессии. Сигнал, снимающий нашу группу, его не
# достаёт: мы умираем, `trap release_lock EXIT` снимает замок, работник продолжает писать,
# и следующий цикл стартует поверх идущей работы. Замер 2026-10-14: 19 взятий замка, 0
# отказов, живой осиротевший работник (pid 69661) правил своё дерево, пока следующий цикл
# получал ту же голодающую карточку владельца.
# Поэтому метка рождается ЗДЕСЬ, до взятия замка, и отдаётся ОБЕИМ сторонам: замок пишет
# её в holder.json, обёртка ставит в ОКРУЖЕНИЕ работника (там её наследуют все потомки и
# она переживает осиротение). Один вопрос «идёт ли ещё работа» — один ответ.
# НЕ экспортируем: иначе метку нёс бы и сам запускатель, и его жизнь снова читалась бы
# как жизнь работника — ровно та подмена, которую правка и убирает.
# ── СТРАХОВКА ПОТЕРЯННОЙ ПОБУДКИ ПРИЁМА (ARB 16.10, запись пульта) ─────────────────
# Пульт будит приём одним переименованием `inbox/.cockpit-wake` (launchd WatchPaths). Побудка
# теряется: приём занят (замок) или в дребезге, процесс убит посреди прогона, launchd событие
# не доставил. Тогда запись лежит `new` без `intake_seen`, и следующей побудки может не быть
# никогда. Здесь — ДО замка цикла, то есть и в часы, когда цикл «занят»: запись пульта старше
# 10 мин без отметки приёма ⇒ побудить приём ЕЩЁ раз. Сам приём отсюда НЕ запускается (только
# штатная дверь launchd, её замок и дребезг), повтор безопасен: принятое помечено `intake_seen`.
COCKPIT_DISPATCH="$REPO_ROOT/spa_core/owner_queue/cockpit_dispatch.py"
if [ -f "$COCKPIT_DISPATCH" ]; then
    REWAKE_OUT="$( ( "$PYTHON" -m spa_core.owner_queue.cockpit_dispatch rewake ) 2>&1 )"
    REWAKE_RC=$?
    case "$REWAKE_RC" in
        0) ;;
        1) echo "[$(ts)] cockpit-rewake: ⚠️ ПРОБЛЕМА — запись пульта не принята приёмом дольше 10 мин, побудка повторена: $REWAKE_OUT" >> "$LOG" ;;
        *) echo "[$(ts)] cockpit-rewake: ❌ НЕ ИЗМЕРЕНО/не разбужено (код $REWAKE_RC): $REWAKE_OUT" >> "$LOG" ;;
    esac
else
    echo "[$(ts)] cockpit-rewake: ⚠️ нет $COCKPIT_DISPATCH (прод-дерево отстало) — потерянная побудка приёма НЕ страхуется" >> "$LOG"
fi

RUN_SUFFIX="$( { uuidgen 2>/dev/null || od -An -tx1 -N16 /dev/urandom 2>/dev/null || date +%s; } | tr -dc 'a-zA-Z0-9' )"
CYCLE_RUN_ID="orchestrator-$$-${RUN_SUFFIX:-$(date +%s)}"

LOCK_PY="$REPO_ROOT/scripts/orchestrator_cycle_lock.py"
MAX_CONCURRENT="${SPA_ORCHESTRATOR_MAX_CONCURRENT:-1}"
if [ ! -f "$LOCK_PY" ]; then
    # Дерево прода отстаёт от origin (синк идёт Step 0 дневного цикла). Молчать нельзя:
    # незаметно потерянная защита — это класс fail-OPEN, ради которого замок и написан.
    echo "[$(ts)] lock: ⚠️ нет $LOCK_PY — цикл идёт БЕЗ защиты от одновременного прогона" >> "$LOG"
else
    LOCK_OUT="$("$PYTHON" "$LOCK_PY" acquire --max-concurrent "$MAX_CONCURRENT" \
                --session "$SPA_SESSION_ID" --pid "$SPA_SESSION_PID" \
                --run-id "$CYCLE_RUN_ID" 2>&1)"
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

# ── ЗАПИСЬ ИЗ ПУЛЬТА ПОЛУЧАЕТ ИСПОЛНИТЕЛЯ (ARB 16.10: «автономность НЕ доказана») ────
# Принятая приёмом запись пульта (`new` + `intake_seen`) до сих пор ждала, пока исполнителя
# назначит человек: каждый цикл начинался с голодающего приказа, шаг 1 до неё не доходил.
# Детерминированный выбор (без LLM): самая старая принятая запись, проба только ОБЪЯВЛЕННАЯ
# (поле карточки или «проба: <имя>» в тексте), взятие — `cockpit_loop.take_card` (захват шага
# 0b на эту сессию → проба → in-progress). Пробы нет ⇒ не берётся: «не принято» с причиной и
# следующим шагом, одно уведомление владельцу. Взята ⇒ указание идёт в начало промпта (сессия
# читает только PROMPT), а после сессии обёртка сама перемеряет пробу (settle).
# Коды: 0 — нечего брать · 3 — взята · 4 — только «пробы нет» · иное — НЕ ИЗМЕРЕНО (в промпт).
COCKPIT_PREFIX=""
COCKPIT_CARD=""
if [ -f "$COCKPIT_DISPATCH" ]; then
    # Шаблон с XXXXXX и полным путём — одна форма для BSD (Mac) и GNU (Linux) mktemp.
    # `mktemp -t spa_cockpit_card` без X'ов на GNU — отказ «too few X's»: путь пуст, выбор
    # падал с кодом 1 и запись НЕ бралась (контрольный прогон CI 39003158532, шард 11).
    COCKPIT_CARD_FILE="$(mktemp "${TMPDIR:-/tmp}/spa_cockpit_card.XXXXXX")"
    COCKPIT_OUT="$("$PYTHON" -m spa_core.owner_queue.cockpit_dispatch dispatch \
                    --executor "$SPA_SESSION_ID" --card-out "$COCKPIT_CARD_FILE" \
                    --repo "$REPO_ROOT" --python "$PYTHON" 2>>"$LOG")"
    COCKPIT_RC=$?
    case "$COCKPIT_RC" in
        0|4) echo "[$(ts)] cockpit-dispatch(rc=$COCKPIT_RC): взятой записи пульта нет" >> "$LOG" ;;
        3) COCKPIT_CARD="$(cat "$COCKPIT_CARD_FILE" 2>/dev/null)"
           COCKPIT_PREFIX="$COCKPIT_OUT"
           echo "[$(ts)] cockpit-dispatch(rc=3): взята $COCKPIT_CARD исполнителем $SPA_SESSION_ID" >> "$LOG" ;;
        *) COCKPIT_PREFIX="ЗАПИСИ ПУЛЬТА: выбор исполнителя НЕ ИЗМЕРЕН (код $COCKPIT_RC) — это НЕ «записей нет». \
Посмотри принятые записи пульта (source: cockpit*, status new, intake_seen) руками перед выбором задачи. "
           echo "[$(ts)] cockpit-dispatch: ❌ НЕ ИЗМЕРЕНО (код $COCKPIT_RC)" >> "$LOG" ;;
    esac
    rm -f "$COCKPIT_CARD_FILE"
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
# Fail-CLOSED в обе стороны: код 3 — находка; код 0 — голода нет; ЛЮБОЙ другой код (и
# отсутствие скрипта в отставшем прод-дереве) — «НЕ ИЗМЕРЕНО», и это тоже уезжает в промпт.
# Молчание здесь читалось бы как «не голодает», а это ровно тот fail-OPEN, из-за которого
# critical-приказ владельца простоял четверо суток при 40+ прошедших циклах.
#
# ⚠️ Находка — код 3, а НЕ 1 (правка 12.09, цикл #571, ADR-347). Прежде находкой считалась
# единица — и ровно единицу выдаёт CPython при ЛЮБОМ необработанном исключении. В то утро
# сторож умер на собственном импорте `spa_core` (бутстрап `sys.path` стоял ниже импорта),
# вышел с кодом 1 — и эта ветка вклеила его ТРАССИРОВКУ в промпт цикла словами «ШАГ 0a-ГОЛОД
# — НАХОДКА, возьми ЭТУ карточку первой». Крах сторожа был предъявлен сессии как вердикт
# сторожа, и третий исход («НЕ ИЗМЕРЕНО») оказался недостижим для самой частой поломки.
# Классификация вынесена в sourceable-файл, потому что у неё обязан быть положительный
# контроль на паре «код 1, трассировка»: прежний изображал поломку кодом 7, которого у
# падающего python-скрипта не бывает — контроль был, настоящей аварии он не видел ни разу.
STARVE_LIB="$REPO_ROOT/scripts/lib/starvation_verdict.sh"
STARVE_PY="$REPO_ROOT/scripts/check_owner_order_starvation.py"
STARVE_PREFIX=""
if [ ! -f "$STARVE_PY" ]; then
    STARVE_OUT="нет $STARVE_PY (прод-дерево отстало от origin)"
    # 127 («команды нет»), а не 2: двойка теперь означает ИЗМЕРЕННУЮ неполноту (не прочитан
    # ref), и склеивать с ней «скрипта нет вовсе» значило бы снова смешать два исхода.
    STARVE_RC=127
else
    STARVE_OUT="$("$PYTHON" "$STARVE_PY" 2>&1)"
    STARVE_RC=$?
fi
echo "[$(ts)] starvation(rc=$STARVE_RC): ${STARVE_OUT:-(нет вывода)}" >> "$LOG"
if [ -f "$STARVE_LIB" ]; then
    # shellcheck disable=SC1090
    . "$STARVE_LIB"
    STARVE_PREFIX="$(starvation_prefix "$STARVE_RC" "$STARVE_OUT")"
else
    # Библиотеки нет (прод-дерево отстало) — молчать нельзя: молчание читается как «голода
    # нет». Классифицировать без неё мы не умеем, поэтому честный третий исход.
    STARVE_PREFIX="ШАГ 0a-ГОЛОД НЕ ИЗМЕРЕН: нет $STARVE_LIB — классифицировать вердикт сторожа \
(код $STARVE_RC) нечем. Это НЕ «приказ владельца не голодает» — проверь голодание руками перед \
выбором задачи. Вывод сторожа: $STARVE_OUT. "
fi

# ── ARMED: run one headless GOVERNED-AUTONOMY cycle ─────────────────────────
PROMPT="${COCKPIT_PREFIX}${STARVE_PREFIX}Ты — оркестратор SPA под НОВЫМ протоколом «управляемая автономия» (owner-approved 2026-07-15). \
Исполни ПОЛНОСТЬЮ docs/ORCHESTRATOR_PROTOCOL.md за один цикл, включая раздел «Автономный рабочий мандат»: \
(1) прочитай docs/STATE.md + docs/decisions/INDEX.md + docs/SYSTEM_BRIEFING.md + свежие data/session_changes.jsonl, \
затем ОБЯЗАТЕЛЬНО python3 scripts/consume_office_reports.py (ADR-066: офис+сторож архитектуры в контекст, \
квитанции потребления; RED/CRITICAL/НЕ-ПРОЧИТАН из вывода => карточка, не молчание); \
(1в) ОБЯЗАТЕЛЬНО из своего worktree python3 scripts/cycle_analytics_audit.py (ADR-130, решение владельца \
24.08 вариант 2: ежедневный аудит протокол-слепоты — шаг цикла; прогон идёт в песочнице, живое data/ не \
трогается; код 1 => обновлённый spa_core/analytics/_protocol_blindness.py доставить ЭТИМ ЖЕ пушем, код 2 => карточка); \
(1г) если цикл ДОБАВИЛ или ПРАВИЛ тест-файл — ОБЯЗАТЕЛЬНО python3 scripts/import_time_anchor_bombs.py (ADR-348: тест, чей якорь времени вычислен на импорте, краснеет от ДЛИТЕЛЬНОСТИ прогона, а не от кода; храповик замороженных дат этот фитиль не видит — литеральной даты в нём нет вовсе; код 1 => чинить тем же пушем, код 2 => НЕ ИЗМЕРЕНО, карточка); (1д) ОБЯЗАТЕЛЬНО python3 scripts/book_second_record.py — вторая запись о деньгах: журнал ходов обязан сходиться с книгой (ADR-350). Код 1 => расхождение НАЗВАНО в цикле (дыра в записи или переименование ключа), код 2 => НЕ ИЗМЕРЕНО, карточка. Прибор только ЧИТАЕТ и ничего не чинит; новая дыра обязана быть замечена в тот же день, а не через два месяца. (1е) ОБЯЗАТЕЛЬНО python3 scripts/capital_observability_census.py --data-dir <прод>/data — приёмка G1 приказа владельца «Portfolio CIO» (ADR-364): доля КАПИТАЛА на НАБЛЮДЁННЫХ числах, по ДВУМ осям (APY ранжирует, TVL допускает) и у ПОВЕРХНОСТИ РЕШЕНИЯ, а не у самого свежего файла. Код 1 => находка НАЗВАНА в цикле (доля упала ниже 100 % либо второй артефакт спорит), код 2 => НЕ ИЗМЕРЕНО, карточка. Прибор только ЧИТАЕТ. Из worktree живого data/ нет по построению — передавать --data-dir прод-дерева. (1е) ОБЯЗАТЕЛЬНО python3 scripts/publish_site_numbers.py (ADR-630: сборка --if-due по ОПУБЛИКОВАННОЙ витрине → ворота публикации → пуш через safe_site_push.py; на следующих прогонах сам доставляет витрину, одобренную владельцем) — витрина чисел сайта (ADR-365, установка владельца ADR-357 п. 5: один адрес чтения, такт НЕДЕЛЬНЫЙ, ставки годовые). Внутри недели команда ничего не переписывает и выходит 0; код 2 => НЕ ИЗМЕРЕНО (источник не прочитан или нет зеркала origin), карточка; код 4 => собранная витрина ждёт одобрения владельца — ничего не делать, следующий прогон доставит её сам после owner-done. Витрину руками не пушить: оба пушера и safe_site_push.py прогоняют scripts/verify_publication.py и без одобрения её не отдают. (1ж) СНЯТ циклом #630 (ADR-414): прибор python_reader_clock_doors проведён СТУПЕНЬЮ моста (findings_bridge, агент com.spa.decision_loop), его артефакт объявлен в конституции с SLO 192ч и читается шагом 0-офис поимённой веткой. Рукой его НЕ звать: такт недельный и решает ФАЙЛ, поэтому ручной зов внутри такта бесполезен, а на сроке — ЗАБИРАЕТ такт у ступени, и наблюдение «кто позвал» (заказ G37 п. 1, по invoked_by.entry) прочло бы руку вместо ступени, то есть объявило бы исправную проводку молчащей. Ступень молчит ⇒ это видно по возрасту артефакта в шаге 0-офис, а не по ручному зову. (2) разбери Inbox (задача/идея/непонятно) и инжест owner-done (ADR + set-status ingested через \
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
# Срок запуска и ВЛАДЕНИЕ его потомками держит общий прибор (ARB decision 18.09).
# `timeout`/`gtimeout` на машине НЕТ — прямой вызов дал бы 127 и выключил бы агента.
# Потомки claude отделяются в СВОЮ сессию, поэтому граница владения — доказанная
# принадлежность RUN_ID, а не группа. 124 = владение закрыто, 125 = не закрыто/не измерено.
echo "[$(ts)] ARMED: invoking headless Claude (governed autonomy, skip-permissions; срок ${SPA_ORCHESTRATOR_TIMEOUT_S:-14400}s)" >> "$LOG"
# ADR-551: the build loop's work (claude and every pytest/mutation child) starts at nice 10 —
# children inherit it — so a heavy cycle cannot starve the CRITICAL paper schedulers
# (architecture/resource_policy.json). Priority only; nothing is limited or killed.
nice -n 10 "$PYTHON" "$REPO_ROOT/scripts/claude_run_with_timeout.py" \
    --timeout-s "${SPA_ORCHESTRATOR_TIMEOUT_S:-14400}" \
    --grace-s "${SPA_ORCHESTRATOR_KILL_GRACE_S:-120}" \
    --log "$LOG" --label orchestrator --run-id "$CYCLE_RUN_ID" \
    -- "$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions
RC=$?
# Запись пульта, взятая этим циклом: «сделано» ставит только её проба, а не слово сессии.
if [ -n "$COCKPIT_CARD" ]; then
    SETTLE_OUT="$( ( "$PYTHON" -m spa_core.owner_queue.cockpit_dispatch settle \
                      --card "$COCKPIT_CARD" --executor "$SPA_SESSION_ID" ) 2>&1 )"
    echo "[$(ts)] cockpit-settle(rc=$?): $SETTLE_OUT" >> "$LOG"
fi
echo "[$(ts)] === orchestrator cycle END (claude exit $RC) ===" >> "$LOG"
exit $RC
