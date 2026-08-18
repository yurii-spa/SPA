"""Что из `data/` МОЖНО возить в git — закрытый список, а не «всё кроме перечисленного».

ЗАЧЕМ (авария 2026-08-18, карточка `agent-track-data-git-durability-guard`).

`data/kill_switch_active.json` лежал в индексе git, хотя `.gitignore` правилом
`data/*.json` его исключает (правило бессильно против уже отслеживаемого файла).
Поэтому `git checkout -- data/` / `git reset --hard` / развёртывание из резерва
ЗАТИРАЛИ живую аварийную остановку версией из коммита: `active: true` молча
становилось `active: false`, и торговля шла дальше. Разбор и оба положительных
контроля — `spa_core/tests/test_halt_state_survives_tree_restore.py`.

Замер того же дня: **остановка была не одна такая**. Мимо разрешающего списка
`.gitignore:151-154` отслеживается 322 файла состояния (296 в корне `data/`,
26 в подкаталогах). Сторож на ОДИН файл эту аварию не закрывает — нужен сторож
КЛАССА, и он здесь.

ТРИ ИСХОДА ОТКАТА (`git checkout -- data/`) — по ним и разложен весь состав:

  CANON   — файл ОБЯЗАН быть в git. Откат возвращает ровно то, что задумано:
            либо ручной конфиг (`risk_policy.json` — писателя в коде НЕТ,
            только читатели `kill_switch.py:117/455/591/617`), либо канон
            трека, который сторож сайта возит в тот же коммит (ADR-093 п.3).
            Для CANON опасность ОБРАТНАЯ — не откат, а ПРОТУХАНИЕ: git-копия
            замирает, а числа сайта из репозитория проверить нельзя.

  HARMFUL — откат возвращает ОПАСНОЕ или устаревшее значение. Четыре механизма,
            каждый подтверждён чтением кода-потребителя (см. `_HARMFUL`):
              H-SAFETY   защитный вердикт («стоим»/«гейт закрыт») подменяется
                         июньским «всё чисто» — то же, что было с остановкой;
              H-CAPITAL  состояние капитала/одобренной цели откатывается к
                         чужой раскладке;
              H-LEDGER   append-only журнал (в т.ч. hash-chain) усекается —
                         запись невосстановима, следующий цикл её не вернёт;
              H-REPLAY   состояние идемпотентности (offset/дедуп/счётчик)
                         откатывается → повторное исполнение уже сделанного:
                         повторная обработка команд владельца, повторный запуск
                         push-скриптов, шторм алертов, рестарт-шторм адаптеров.

  DERIVED — производный отчёт: писатель перезаписывает файл целиком в следующий
            свой запуск, ни один гейт по нему не судит. Откат безвреден.
            Подкласс DERIVED-RING (кольцевые advisory-журналы `*_log.json`):
            решения не меняет, но откат усекает advisory-историю; в git они
            лежат ПУСТЫМИ (`[]`), то есть git-копия не несёт вообще ничего.

ПРАВИЛО ОТНЕСЕНИЯ (детерминированное, без вкуса):
  1. Писателя в коде НЕТ, файл ведётся руками  → CANON (конфиг).
  2. Файл — канон публичного трека / период-стейтмент / фикстура истории → CANON.
  3. Иначе, если потребитель ЧИТАЕТ файл ради решения (гейт, капитал,
     идемпотентность) или файл дописывается и не восстановим → HARMFUL.
  4. Иначе → DERIVED.

ХРАПОВИК И ЧЕСТНОСТЬ. Разрешающий список ЗАКРЫТ: любой отслеживаемый файл
`data/**` обязан быть назван в одном из трёх списков — неназванный файл красит
сторожа (`UNCLASSIFIED`). Известный долг (HARMFUL, который сегодня всё ещё
отслеживается) вынесен в `data_git_baseline.json` и может ТОЛЬКО УМЕНЬШАТЬСЯ:
снятие с отслеживания — доставка через владельца (`push_to_github.py` удалений
не умеет), поэтому агент называет и ждёт. Добавлять файл в базу, чтобы погасить
падение, ЗАПРЕЩЕНО (инвариант 16) — чинить надо состав git.

Модуль read-only: ничего не пишет, ничего не удаляет, `data/` не трогает
(`equity_curve_daily.json` — живой трек — только читается как имя в списке).
Только stdlib. LLM здесь запрещён.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REPO_DEFAULT = Path(__file__).resolve().parents[2]
_BASELINE_FILENAME = "data_git_baseline.json"

CANON = "CANON"
HARMFUL = "HARMFUL"
DERIVED = "DERIVED"
UNCLASSIFIED = "UNCLASSIFIED"

# ── (в) КАНОН — файл ОБЯЗАН быть в git ───────────────────────────────────────
# Закрытый список. Ключ — путь от корня репозитория.
_CANON: Dict[str, str] = {
    # ── канон сайта (ADR-093 п.3): сторож сайта кладёт их в тот же коммит, что
    #    и landing/src/data/track_snapshot.json; без них owner-gate не может
    #    пересчитать изменившееся число. Уже перечислены в .gitignore:151-154.
    "data/golive_status.json":
        "канон сайта/гейтов (ADR-093 п.3); негация .gitignore",
    "data/equity_curve_daily.json":
        "ЖИВОЙ ТРЕК — публичная кривая капитала; негация .gitignore; только чтение",
    "data/paper_trading_status.json":
        "канон сайта: статус paper-трека; негация .gitignore",
    "data/tier1_packages.json":
        "канон сайта: net-APY и worst-DD карточек тиров; негация .gitignore",
    # ── канон трека, который сегодня отслеживается МИМО негаций ──────────────
    "data/paper_evidence.json":
        "публичный evidence трека; artifact_freshness помечает его committed=True — "
        "то есть его git-копия СУДИТСЯ на свежесть, значит он обязан быть в git",
    "data/paper_evidence_history.json":
        "история evidence; названа как committed track snapshot в шапке .gitignore:23-25",
    # ── ручной конфиг: писателя в коде НЕТ, только читатели ──────────────────
    "data/risk_policy.json":
        "ПОРОГИ, читаемые kill_switch.py:117/455/591/617 и analytics_runner.py:69. "
        "Писателя нет — файл ведётся руками, и версионировать его ОБЯЗАТЕЛЬНО: "
        "иначе порог остановки меняется без следа в git (вопреки ADR-034/048)",
    "data/capital_config.json":
        "стартовый капитал и лимиты аллокации; писателя нет, читает golive_readiness_report",
    "data/AUDIT_BASELINE.json":
        "ручной список подавленных находок аудита; писателя нет — версионируемый конфиг",
    "data/monitoring/monitoring_config.json":
        "конфиг мониторинга, ведётся руками",
    # ── период-стейтменты и фикстуры истории: неизменяемы после закрытия ─────
    "data/monthly_reports/2026-06.json": "закрытый месячный отчёт — канон трека",
    "data/statements/2026-06.json": "закрытый стейтмент периода — канон трека",
    "data/statements/2026-06_i1.json": "закрытый стейтмент периода — канон трека",
    "data/statements/2026-06_i2.json": "закрытый стейтмент периода — канон трека",
    "data/historical_apy/aave_v3_usdc.json": "историческая база APY (фикстура red_flags)",
    "data/historical_apy/compound_v3_usdc.json": "историческая база APY (фикстура red_flags)",
    "data/historical_apy/morpho_blue_usdc.json": "историческая база APY (фикстура red_flags)",
    "data/historical_apy/sky_susds.json": "историческая база APY (фикстура red_flags)",
    "data/historical_apy/yearn_v3_usdc.json": "историческая база APY (фикстура red_flags)",
    # ── определения стратегий: конфиг, не состояние ──────────────────────────
    "data/strategies/s0_baseline.json": "определение стратегии — конфиг",
    "data/strategies/s1_concentration.json": "определение стратегии — конфиг",
    "data/strategies/s2_momentum.json": "определение стратегии — конфиг",
    "data/strategies/s3_risk_parity.json": "определение стратегии — конфиг",
    "data/strategies/s4_kelly.json": "определение стратегии — конфиг",
    "data/strategies/s5_yield_spread.json": "определение стратегии — конфиг",
    # ── исследовательские фикстуры BEE: сценарии, а не состояние ─────────────
    "data/bee/event_catalog.json": "каталог исторических событий — фикстура",
    "data/bee/counterfactual_FTX_CONTAGION_2022.json": "сценарий контрфакта — фикстура",
    "data/bee/counterfactual_STETH_DISCOUNT_2022.json": "сценарий контрфакта — фикстура",
    "data/bee/counterfactual_USDC_SVB_2023.json": "сценарий контрфакта — фикстура",
    "data/bee/counterfactual_USDE_DN_STRESS.json": "сценарий контрфакта — фикстура",
    "data/bee/counterfactual_UST_LUNA_2022.json": "сценарий контрфакта — фикстура",
}

# ── (а) ВРЕДНО — откат возвращает опасное/устаревшее значение ────────────────
# (файл, механизм, чем подтверждено — потребитель в коде)
_HARMFUL: Dict[str, Tuple[str, str]] = {
    # ─── H-SAFETY: защитный вердикт подменяется старым «всё чисто» ───────────
    "data/kill_switch_active.json": (
        "H-SAFETY",
        "ЭТАЛОН КЛАССА (авария 2026-08-18). kill_switch.py:534 читает active=false "
        "как СНЯТИЕ остановки; откат затирал живую остановку. Снят с отслеживания.",
    ),
    "data/live_trading_gate.json": (
        "H-SAFETY",
        "состояние ВООРУЖЕНИЯ живой торговли (spa_core/safety/live_trading_gate.py:41, "
        "читает execution/arming.py:22). Сегодня в коммите active=false — то есть "
        "безопасность держится на СОДЕРЖИМОМ коммита, ровно как было с остановкой: "
        "коммит с active=true вернул бы прод вооружённым.",
    ),
    "data/emergency_status.json": (
        "H-SAFETY",
        "вердикт аварийных брейкеров (пишет risk/emergency_breakers.py, читает "
        "monitoring/threat_reactor.py:107). Откат возвращает status=CLEAR поверх живого triggered.",
    ),
    "data/kill_switch_status.json": (
        "H-SAFETY",
        "вердикт лестницы drawdown; читают agents/risk_sentinel.py:241 и incident_commander.py:34. "
        "В коммите triggered=false, reason='all triggers clear' от 2026-06-21.",
    ),
    "data/risk_limits_check.json": (
        "H-SAFETY",
        "вердикт DL-01..DL-05 (reporting/daily_telegram_report.py:88). В коммите gate=PASS.",
    ),
    "data/gate_status.json": (
        "H-SAFETY",
        "верхнеуровневые гейты go-live (golive_readiness_report.py:627, data_freshness_monitor.py:49). "
        "В коммите снимок от 2026-06-20 с paper_trading_day_count=2.",
    ),
    "data/policy_violations.json": (
        "H-SAFETY",
        "нарушения аллокации (risk/position_validator.py:34, читает registry_coverage_watch.py:32). "
        "В коммите valid=true, violations_count=0 — откат прячет живое нарушение.",
    ),
    "data/red_flags.json": (
        "H-SAFETY",
        "красные флаги протоколов; agents/risk_sentinel.py:221 превращает каждый в алерт severity=high. "
        "Откат подменяет живой набор июньским.",
    ),
    # ─── H-CAPITAL: состояние капитала / одобренной цели ─────────────────────
    "data/current_positions.json": (
        "H-CAPITAL",
        "экспозиция и equity книги (reporting/tear_sheet.py:122, portal_data.py:95); "
        "deployment_acceptance.py:87 судит по нему свежесть цикла. Откат возвращает чужую книгу.",
    ),
    "data/last_approved_allocation.json": (
        "H-CAPITAL",
        "ОДОБРЕННАЯ цель аллокации (scheduler/loop_scheduler.py:83; scripts/portfolio_cio_shadow.py:94 "
        "отказывает без неё). Откат = решение цикла подменяется раскладкой от 2026-06-21.",
    ),
    # ─── H-LEDGER: невосстановимый append-only журнал ────────────────────────
    "data/trades.json": (
        "H-LEDGER",
        "журнал сделок трека (reporting/tear_sheet.py:127). Откат усекает его до 2026-06-18; "
        "следующий цикл дописывает, но потерянные записи не возвращает.",
    ),
    "data/audit_trail.jsonl": (
        "H-LEDGER",
        "hash-chain аудита (reporting/portal_data.py:103). Откат рвёт цепочку — "
        "усечённый hash-chain и есть потеря доказуемости.",
    ),
    "data/live_execution_log.json": (
        "H-LEDGER",
        "журнал попыток живого исполнения (execution/engine_bridge.py:73). Невосстановим.",
    ),
    "data/risk_policy_blocks.json": (
        "H-LEDGER",
        "кольцевой буфер блокировок риск-гейта (reporting/daily_telegram_report.py:81). "
        "Канон-форма для истории — каталог data/risk_blocks_daily/ (негация .gitignore:134).",
    ),
    # ─── H-REPLAY: откат идемпотентности = повтор уже сделанного ─────────────
    "data/tg_bot_v2_offset.json": (
        "H-REPLAY",
        "offset getUpdates Telegram (telegram/bot.py:69, читает _read_offset:363). В коммите "
        "offset от 2026-06-18 — откат заставит бота ЗАНОВО обработать два месяца команд владельца.",
    ),
    "data/autopush_state.json": (
        "H-REPLAY",
        "last_version=1208 (scripts/smart_autopush.py) — запускаются только скрипты с версией ВЫШЕ. "
        "Откат = повторный запуск уже применённых push-скриптов.",
    ),
    "data/alert_dispatcher_dedup.json": (
        "H-REPLAY",
        "дедуп алертов (alerts/alert_dispatcher.py:51). Откат = шторм повторных алертов; "
        "вдобавок в коммите лежит тестовый мусор ('Test Alert', 'A0'..'A3').",
    ),
    "data/telegram_cooldowns.json": (
        "H-REPLAY", "кулдауны отправки (alerts/telegram_manager.py:55) — откат снимает их",
    ),
    "data/telegram_alert_state.json": (
        "H-REPLAY", "какие сводки уже отправлены (telegram/reports/daily.py:52)",
    ),
    "data/milestone_alert_state.json": (
        "H-REPLAY", "список уже разосланных майлстоунов (alerts/milestone_alert.py:30)",
    ),
    "data/cycle_gap_state.json": (
        "H-REPLAY",
        "alert_sent по разрыву цикла (paper_trading/cycle_gap_monitor.py) — откат шлёт алерт повторно",
    ),
    "data/uptime_prev_state.json": (
        "H-REPLAY",
        "ПРЕДЫДУЩЕЕ состояние флота для детекции фронта (monitoring/uptime_monitor.py:56). "
        "Откат = ложные «агент упал»/«агент поднялся» по всему флоту.",
    ),
    "data/watchdog_state.json": (
        "H-REPLAY",
        "почасовые счётчики рестартов адаптеров (scheduler/adapter_watchdog.py:69) — "
        "откат обнуляет их и снимает потолок рестартов.",
    ),
    "data/orchestrator_trigger.json": (
        "H-REPLAY",
        "флаг adapter_restarted для оркестратора (scheduler/adapter_watchdog.py:71)",
    ),
    # ─── H-JUNK: временный вывод CLI, которого в git быть не должно вовсе ────
    "data/_cli_check_out.json": (
        "H-JUNK", "временный вывод CLI-прогона; ни одной ссылки в коде",
    ),
    "data/_run_out_tmp.json": (
        "H-JUNK", "временный вывод CLI-прогона; ни одной ссылки в коде",
    ),
}


# Каталоги, целиком разрешённые негациями `.gitignore:96-135` — исследовательские
# карточки и дневные срезы блокировок. Это канон по каталогу, а не по файлу:
# состав меняется, разрешение — нет.
_CANON_PREFIXES: Dict[str, str] = {
    "data/strategy_cards/": "негация .gitignore:96 — research-карточки стратегий",
    "data/protocol_cards/": "негация .gitignore:98 — research-карточки протоколов",
    "data/stablecoin_cards/": "негация .gitignore:100 — research-карточки стейблов",
    "data/research_reports/": "негация .gitignore:102",
    "data/ic_memos/": "негация .gitignore:104",
    "data/risk_reviews/": "негация .gitignore:106",
    "data/red_team_reviews/": "негация .gitignore:108",
    "data/strategy_candidates/": "негация .gitignore:110",
    "data/risk_blocks_daily/": "негация .gitignore:134 — дневные срезы блокировок риск-гейта",
}


def _canon_prefix(path: str) -> Optional[str]:
    for pref in _CANON_PREFIXES:
        if path.startswith(pref):
            return pref
    return None


@dataclass(frozen=True)
class Violation:
    """Одно нарушение политики состава git."""
    path: str
    kind: str          # TRACKED_HARMFUL | CANON_NOT_TRACKED | UNCLASSIFIED | BASELINE_GREW
    detail: str


def _run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def tracked_data_files(repo: Path = _REPO_DEFAULT) -> List[str]:
    """Все файлы `data/**`, лежащие в индексе git. Источник правды — сам git."""
    out = _run_git(repo, "ls-files", "data/")
    return sorted(p for p in out.splitlines() if p.strip())


def classify(path: str) -> str:
    """Один путь → один из четырёх вердиктов. Список закрыт: неизвестное = UNCLASSIFIED."""
    if path in _CANON or _canon_prefix(path):
        return CANON
    if path in _HARMFUL:
        return HARMFUL
    if path in load_baseline().get("derived_tolerated", []):
        return DERIVED
    return UNCLASSIFIED


def harm_class(path: str) -> Optional[str]:
    """Механизм вреда (H-SAFETY / H-CAPITAL / H-LEDGER / H-REPLAY / H-JUNK) или None."""
    entry = _HARMFUL.get(path)
    return entry[0] if entry else None


def reason(path: str) -> str:
    """Чем подтверждено отнесение — потребитель в коде, а не мнение."""
    if path in _CANON:
        return _CANON[path]
    pref = _canon_prefix(path)
    if pref:
        return _CANON_PREFIXES[pref]
    if path in _HARMFUL:
        return _HARMFUL[path][1]
    return ""


def load_baseline(repo: Path = _REPO_DEFAULT) -> dict:
    """Известный долг: что отслеживается сегодня и ждёт решения владельца."""
    p = Path(__file__).resolve().parent / _BASELINE_FILENAME
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"harmful_debt": [], "derived_tolerated": []}


def audit(repo: Path = _REPO_DEFAULT, *, tracked: Optional[List[str]] = None) -> List[Violation]:
    """Полный разбор состава git по политике. Ничего не пишет и не чинит.

    `tracked` инъектируется тестами — тогда реальный репозиторий не читается вовсе.
    """
    files = tracked if tracked is not None else tracked_data_files(repo)
    known = set(files)
    baseline = load_baseline(repo)
    debt = set(baseline.get("harmful_debt", []))
    tolerated = set(baseline.get("derived_tolerated", []))

    out: List[Violation] = []
    for path in sorted(known):
        if path in _CANON or _canon_prefix(path):
            continue
        if path in _HARMFUL:
            if path in debt:
                continue  # известный долг, ждёт владельца — считается отдельным тестом
            out.append(Violation(path, "TRACKED_HARMFUL",
                                 f"{_HARMFUL[path][0]}: {_HARMFUL[path][1]}"))
            continue
        if path in tolerated:
            continue
        out.append(Violation(
            path, "UNCLASSIFIED",
            "файл data/** попал в git, не будучи названным ни в одном из трёх списков "
            "(CANON / HARMFUL / derived_tolerated). Разрешающий список ЗАКРЫТ: "
            "классифицировать по риску отката, а не добавлять в базу ради зелёного.",
        ))

    for path in sorted(_CANON):
        if path not in known:
            out.append(Violation(path, "CANON_NOT_TRACKED",
                                 f"канон обязан быть в git: {_CANON[path]}"))
    return out


def summary(repo: Path = _REPO_DEFAULT) -> dict:
    """Счётный срез для отчётов/дашбордов. Read-only."""
    files = tracked_data_files(repo)
    counts: Dict[str, int] = {CANON: 0, HARMFUL: 0, DERIVED: 0, UNCLASSIFIED: 0}
    for p in files:
        counts[classify(p)] += 1
    harm: Dict[str, int] = {}
    for p in files:
        h = harm_class(p)
        if h:
            harm[h] = harm.get(h, 0) + 1
    return {
        "tracked_total": len(files),
        "by_class": counts,
        "harmful_by_mechanism": harm,
        "violations": [v.__dict__ for v in audit(repo)],
    }


if __name__ == "__main__":  # pragma: no cover - ручной прогон
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
