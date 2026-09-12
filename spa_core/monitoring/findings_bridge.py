"""findings_bridge.py — мост «находка → карточка» (ADR-066, Фаза 3, C2).

Замыкает петлю: находки сторожа архитектуры и gap-анализа ПРЕВРАЩАЮТСЯ в
карточки бэклога сами, без надежды на то, что кто-то вручную прочитает отчёт.

Дисциплина против спама (каждое правило — против конкретного отказа):
  dedup        одна ОТКРЫТАЯ карточка на ключ находки — и не больше;
  гистерезис   WARN становится карточкой только с REQUIRED_SIGHTINGS-го
               подряд наблюдения (флаппинг не рождает мусор); CRITICAL — сразу;
  rate-limit   ≤ MAX_CARDS_PER_DAY карточек/сутки; излишек — в отчёт с
               пометкой deferred, ГРОМКО, не молча (правило «no silent caps»);
  авто-закрытие исчезнувшая находка закрывает свою карточку, но ТОЛЬКО после
               REQUIRED_ABSENCES прогонов подряд без неё (молчание ОДНОГО
               прогона не есть починка — иначе находка возвращается, и это
               измерено) и ТОЛЬКО если карточка НЕТРОНУТА: `new` для inbox, `needs-owner` без следа
               владельца для owner-decision (цикл #172 — раньше правило знало
               лишь `new`, и вопрос владельца не закрывался никогда); взятую
               в работу не трогаем. Закрытие уведомлённой карточки уходит
               владельцу ОТЗЫВОМ — снимать вопрос молча нельзя;
  эскалация    WARN→CRITICAL по тому же ключу = новая карточка needs-owner.

Маршрутизация: CRITICAL → owner-decision (формат §2.4, 4 секции, по-русски)
+ Telegram-notify; WARN → inbox (agent-backlog). Всё — ТОЛЬКО через
scripts/orchestrator_queue.py (единственный мутационный API очереди).
Инвариант 14 соблюдён по построению: мост никогда не ставит owner-done.

Запуск: агент com.spa.decision_loop (каждые 6ч): сначала пересчёт
house_view_gap, затем мост. Состояние: data/findings_bridge_state.json;
отчёт: data/findings_bridge_report.json. LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

from spa_core.utils.observation import observed
from spa_core.monitoring.architecture_conformance import REPO_ROOT, subject_inputs

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода — вывести производителя разбором нельзя
#: (замер 28.08: верно 13 из 27, одна ошибка, семья harness недостижима).
#: Сверяется с фактической записью — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/adapter_feed_divergence.json",
    "data/capital_evidence_coverage.json",
    "data/pool_identity_collision.json",
    "data/decision_reproducibility.json",
    "data/marginal_apy_at_size.json",
    "data/rebalance_cost_evidence.json",
    "data/apy_forecast_accuracy.json",
    "data/cio_shadow_replay.json",
    "data/decision_audit_trail.json",
    "data/cio_failure_modes.json",
    "data/cio_explainability.json",
    "data/cio_kill_switch_controls.json",
    "data/cio_auto_execution_limits.json",
    # Объявлены здесь ПОСЛЕ находки сторожа архитектуры 07.09: манифест знал
    # продукт, которого не было в объявлении точки входа (#512 внёс запись
    # манифеста и пропустил эту строку). Артефакт без объявленного
    # производителя не проверяется вовсе — паритет манифест↔код и есть предмет
    # проверки `architecture_conformance`.
    "data/cio_target_producers.json",
    "data/cio_architecture_constraints.json",
    "data/cio_component_map.json",
    "data/cio_policy_change_procedure.json",
    "data/cio_post_trade_verification.json",
    # Объявлено ВМЕСТЕ с вызовом (цикл #522, ADR-259). ADR-257 внёс этот
    # артефакт в манифест и в читателя шага 0-офис, но производящего вызова
    # не было ни одного: измеритель существовал, тесты были зелёными, а файл
    # не появился ни разу. Строка объявления без вызова ниже — ровно тот
    # дефект, ради которого написан `test_declared_producer_is_reachable.py`.
    "data/cio_outcome_independence.json",
    # Объявлено ВМЕСТЕ с вызовом (цикл #523). Работа #520/#521 пришла из
    # осиротевшего дерева с записью манифеста и именным разделом шага 0-офис —
    # и БЕЗ производящего вызова, то есть ровно в форме ADR-259. Сторож
    # `test_declared_producer_is_reachable.py`, доставленный циклом #522
    # НАКАНУНЕ, покраснел на ней на первом же прогоне: положительный контроль
    # сработал в поле через один цикл после написания.
    "data/cio_substitution_census.json",
    "data/evidence_staleness.json",
    "data/apy_composition.json",
    "data/findings_bridge_report.json",
    "data/house_view_gap.json",
    "data/investment_os/outcomes.jsonl",
    "data/loop_health.json",
    "data/loop_retro.json",
    # Объявлены ЗАМЕРОМ (цикл #540), а не по памяти: карточка
    # `inbox-nahodka-petli-com-spa-decision-loop-kod` называла ТРИ артефакта,
    # известных манифесту и неизвестных этому объявлению, — на день замера их
    # было пять. Класс рос ПО ОДНОМУ ЗА ЦИКЛ: каждая новая перепись вносила
    # запись манифеста и строку `CENSUS_PRODUCT`, но не эту, а сторож B7
    # (`architecture_conformance`) читает именно её. `CENSUS_PRODUCT`
    # объявлением НЕ является: он говорит, чем перепись написана, а не что
    # агент обязуется произвести.
    #
    # У каждой строки ниже проверено ОБА условия, а не одно: в мосте есть
    # производящий вызов `<модуль>.run(root=args.root)` И модуль пишет свой
    # артефакт. Объявление без вызова — ровно дефект ADR-259, объявление без
    # записи было бы его зеркалом.
    "data/shadow_blockade_attribution.json",
    "data/target_stability.json",
    "data/ranking_tie_census.json",
    "data/ranking_tie_persistence.json",
    "data/decision_journal_coverage.json",
    "data/decision_record_verdict_sensitivity.json",
    "data/hit_rate_selection_bias.json",
    "data/g1_verdict_recoverability.json",
    "data/unevidenced_leg_causes.json",
    "data/journal_backfill_material.json",
    "data/arming_wall_order.json",
    "data/journal_population_backfill.json",
    "data/leg_provenance_split.json",
    "data/snapshot_minute_sensitivity.json",
    "data/decision_record_run_identity.json",
    "data/day_replacement_verdict_loss.json",
    "data/intraday_rate_input_movement.json",
    "data/audit_trail_rate_input_coverage.json",
    "data/run_axis_time_stitch.json",
    "data/rate_observation_census.json",
    "data/census_consumer_census.json",
    "data/subject_population_census.json",
    "data/substring_structure_assertions.json",
    "data/haystack_origin_census.json",
)

# Запись есть, продуктом не является (ADR-154): собственная память моста между
# прогонами (что уже видено, что уже стало карточкой). Её потребитель — сам мост
# на следующем запуске, а не читатель продукта; в коде читателей ноль (замер 29.08).
INTERNAL_WRITES = (
    "data/findings_bridge_state.json",
)

STATE_REL = os.path.join("data", "findings_bridge_state.json")
REPORT_REL = os.path.join("data", "findings_bridge_report.json")

#: Состав ступени переписей — то, что мост пробует ДО собственной работы.
#:
#: Зачем это в отчёте (цикл #524). Каждая перепись обёрнута своим
#: `try/except → print("… пропущено")`, и это верно: замер §-приёмки не смеет
#: валить мост. Но печать уходит в `/tmp/spa_decision_loop.log`, то есть
#: провалившаяся перепись видна ТОЛЬКО тому, кто откроет лог живого агента, —
#: сторож говорит в канал, который никто не читает. Наружу от неё остаётся
#: единственный след: артефакта нет на диске. А «нет на диске» шаг 0-офис до
#: #524 печатал как находку БЕЗУСЛОВНО — тем же текстом, каким описывается
#: контур, где производитель просто ещё ни разу не отработал с новым кодом.
#: Живой замер 2026-09-08: `cio_substitution_census.py` приехал в дерево в
#: 09:51, `com.spa.decision_loop` последний раз отработал в 07:05:59Z —
#: обязательный шаг напечатал «❌ НЕ ПРОЧИТАН» об ИСПРАВНОМ модуле (в
#: песочнице `run(write=False)` отрабатывает, `positive_control.passed`).
#: Это тот же класс, что #248 (там его закрыли для ПОЛЕЙ схемы, а для самого
#: СУЩЕСТВОВАНИЯ артефакта — нет).
#:
#: Поэтому мост теперь ОБЪЯВЛЯЕТ состав ступени и ЗАПИСЫВАЕТ причину каждого
#: пропуска в свой отчёт. Читателю (шаг 0-офис) это даёт прямой ответ на
#: вопрос «а бегун вообще пробовал?» — вместо вывода из даты файла.
#:
#: Список ОБЪЯВЛЕН, а не выведен (ADR-158): состав ступени — контракт, и
#: сверяется он с телом `main()` разбором AST
#: (`test_office_absent_artifact_producer_aware.py`), поэтому новая перепись,
#: добавленная мимо этого списка, краснеет, а не молчит.
CENSUS_STAGE: tuple[str, ...] = (
    "adapter_feed_divergence",
    "decision_reproducibility",
    "marginal_apy_at_size",
    "rebalance_cost_evidence",
    "apy_forecast_accuracy",
    "cio_shadow_replay",
    "decision_audit_trail",
    "cio_failure_modes",
    "cio_explainability",
    "cio_kill_switch_controls",
    "cio_auto_execution_limits",
    "cio_target_producers",
    "cio_architecture_constraints",
    "cio_component_map",
    "cio_policy_change_procedure",
    "cio_post_trade_verification",
    "cio_outcome_independence",
    "cio_substitution_census",
    "shadow_blockade_attribution",
    "target_stability",
    "ranking_tie_census",
    "ranking_tie_persistence",
    "decision_journal_coverage",
    "decision_record_verdict_sensitivity",
    "hit_rate_selection_bias",
    "g1_verdict_recoverability",
    "unevidenced_leg_causes",
    "journal_backfill_material",
    "arming_wall_order",
    "journal_population_backfill",
    "leg_provenance_split",
    "snapshot_minute_sensitivity",
    "decision_record_run_identity",
    "day_replacement_verdict_loss",
    "intraday_rate_input_movement",
    "audit_trail_rate_input_coverage",
    "run_axis_time_stitch",
    "rate_observation_census",
    "census_consumer_census",
    "subject_population_census",
    "substring_structure_assertions",
    "haystack_origin_census",
    "capital_evidence_coverage",
    "apy_composition",
    "pool_identity_collision",
    "evidence_staleness",
    "outcomes",
    "loop_retro",
    "loop_health",
)

#: ЧТО каждая перепись производит и ЧЕМ она написана — ОБЪЯВЛЕНО (ADR-158),
#: а не выведено из имени.
#:
#: Зачем отдельно от `CENSUS_STAGE` (замер цикла #525). ADR-261 научил ОДНОГО
#: читателя различать «бегун отработал и файла не оставил» от «бегун ещё не
#: отрабатывал», и ступень для этого ВЫВОДИЛ: `basename(модуль)` без
#: расширения. Для двух переписей из двадцати пяти выведенное имя не совпадает
#: с объявленным — `evidence_staleness` живёт в `evidence_staleness_monitor.py`,
#: `outcomes` в `outcomes_archive.py`, — и ветка «названа бегуном ⇒ находка» для
#: них не срабатывала НИКОГДА, по построению. Провалившаяся перепись с
#: записанной причиной проваливалась в ветку дат и при недавно правленом модуле
#: объявлялась «ещё не производился»: **fail-OPEN**, направление опаснее ложной
#: находки.
#:
#: Второе: артефакт → ступень нужен читателю, который ходит не по карте офиса, а
#: по `architecture/manifest.json` (сторож `architecture_conformance`). Без
#: объявления он либо не может спросить вовсе, либо подставляет ЧУЖОГО бегуна.
#:
#: Держат состав два храповика (`test_artifact_absence_shared_verdict.py`):
#: ключи обязаны совпадать с `CENSUS_STAGE` (а тот сверяется с телом `main()`
#: разбором AST), каждый `module` обязан существовать в дереве, каждый
#: `artifact` — быть объявлен в манифесте активным с производителем
#: `com.spa.decision_loop`. Три независимых объявления сверяются друг с другом;
#: ручной список отказывает ровно тогда, когда кто-то забыл.
CENSUS_PRODUCT: dict[str, dict[str, str]] = {
    "adapter_feed_divergence": {
        "module": "spa_core/monitoring/adapter_feed_divergence.py",
        "artifact": "data/adapter_feed_divergence.json"},
    "decision_reproducibility": {
        "module": "spa_core/monitoring/decision_reproducibility.py",
        "artifact": "data/decision_reproducibility.json"},
    "marginal_apy_at_size": {
        "module": "spa_core/monitoring/marginal_apy_at_size.py",
        "artifact": "data/marginal_apy_at_size.json"},
    "rebalance_cost_evidence": {
        "module": "spa_core/monitoring/rebalance_cost_evidence.py",
        "artifact": "data/rebalance_cost_evidence.json"},
    "apy_forecast_accuracy": {
        "module": "spa_core/monitoring/apy_forecast_accuracy.py",
        "artifact": "data/apy_forecast_accuracy.json"},
    "cio_shadow_replay": {
        "module": "spa_core/monitoring/cio_shadow_replay.py",
        "artifact": "data/cio_shadow_replay.json"},
    "decision_audit_trail": {
        "module": "spa_core/monitoring/decision_audit_trail.py",
        "artifact": "data/decision_audit_trail.json"},
    "cio_failure_modes": {
        "module": "spa_core/monitoring/cio_failure_modes.py",
        "artifact": "data/cio_failure_modes.json"},
    "cio_explainability": {
        "module": "spa_core/monitoring/cio_explainability.py",
        "artifact": "data/cio_explainability.json"},
    "cio_kill_switch_controls": {
        "module": "spa_core/monitoring/cio_kill_switch_controls.py",
        "artifact": "data/cio_kill_switch_controls.json"},
    "cio_auto_execution_limits": {
        "module": "spa_core/monitoring/cio_auto_execution_limits.py",
        "artifact": "data/cio_auto_execution_limits.json"},
    "cio_target_producers": {
        "module": "spa_core/monitoring/cio_target_producers.py",
        "artifact": "data/cio_target_producers.json"},
    "cio_architecture_constraints": {
        "module": "spa_core/monitoring/cio_architecture_constraints.py",
        "artifact": "data/cio_architecture_constraints.json"},
    "cio_component_map": {
        "module": "spa_core/monitoring/cio_component_map.py",
        "artifact": "data/cio_component_map.json"},
    "cio_policy_change_procedure": {
        "module": "spa_core/monitoring/cio_policy_change_procedure.py",
        "artifact": "data/cio_policy_change_procedure.json"},
    "cio_post_trade_verification": {
        "module": "spa_core/monitoring/cio_post_trade_verification.py",
        "artifact": "data/cio_post_trade_verification.json"},
    "cio_outcome_independence": {
        "module": "spa_core/monitoring/cio_outcome_independence.py",
        "artifact": "data/cio_outcome_independence.json"},
    "cio_substitution_census": {
        "module": "spa_core/monitoring/cio_substitution_census.py",
        "artifact": "data/cio_substitution_census.json"},
    "shadow_blockade_attribution": {
        "module": "spa_core/monitoring/shadow_blockade_attribution.py",
        "artifact": "data/shadow_blockade_attribution.json"},
    "target_stability": {
        "module": "spa_core/monitoring/target_stability.py",
        "artifact": "data/target_stability.json"},
    "ranking_tie_census": {
        "module": "spa_core/monitoring/ranking_tie_census.py",
        "artifact": "data/ranking_tie_census.json"},
    "ranking_tie_persistence": {
        "module": "spa_core/monitoring/ranking_tie_persistence.py",
        "artifact": "data/ranking_tie_persistence.json"},
    "decision_journal_coverage": {
        "module": "spa_core/monitoring/decision_journal_coverage.py",
        "artifact": "data/decision_journal_coverage.json"},
    "decision_record_verdict_sensitivity": {
        "module": "spa_core/monitoring/decision_record_verdict_sensitivity.py",
        "artifact": "data/decision_record_verdict_sensitivity.json"},
    "hit_rate_selection_bias": {
        "module": "spa_core/monitoring/hit_rate_selection_bias.py",
        "artifact": "data/hit_rate_selection_bias.json"},
    "g1_verdict_recoverability": {
        "module": "spa_core/monitoring/g1_verdict_recoverability.py",
        "artifact": "data/g1_verdict_recoverability.json"},
    "unevidenced_leg_causes": {
        "module": "spa_core/monitoring/unevidenced_leg_causes.py",
        "artifact": "data/unevidenced_leg_causes.json"},
    "journal_backfill_material": {
        "module": "spa_core/monitoring/journal_backfill_material.py",
        "artifact": "data/journal_backfill_material.json"},
    "arming_wall_order": {
        "module": "spa_core/monitoring/arming_wall_order.py",
        "artifact": "data/arming_wall_order.json"},
    "journal_population_backfill": {
        "module": "spa_core/monitoring/journal_population_backfill.py",
        "artifact": "data/journal_population_backfill.json"},
    "leg_provenance_split": {
        "module": "spa_core/monitoring/leg_provenance_split.py",
        "artifact": "data/leg_provenance_split.json"},
    "snapshot_minute_sensitivity": {
        "module": "spa_core/monitoring/snapshot_minute_sensitivity.py",
        "artifact": "data/snapshot_minute_sensitivity.json"},
    "decision_record_run_identity": {
        "module": "spa_core/monitoring/decision_record_run_identity.py",
        "artifact": "data/decision_record_run_identity.json"},
    "day_replacement_verdict_loss": {
        "module": "spa_core/monitoring/day_replacement_verdict_loss.py",
        "artifact": "data/day_replacement_verdict_loss.json"},
    "intraday_rate_input_movement": {
        "module": "spa_core/monitoring/intraday_rate_input_movement.py",
        "artifact": "data/intraday_rate_input_movement.json"},
    "audit_trail_rate_input_coverage": {
        "module": "spa_core/monitoring/audit_trail_rate_input_coverage.py",
        "artifact": "data/audit_trail_rate_input_coverage.json"},
    "run_axis_time_stitch": {
        "module": "spa_core/monitoring/run_axis_time_stitch.py",
        "artifact": "data/run_axis_time_stitch.json"},
    "rate_observation_census": {
        "module": "spa_core/monitoring/rate_observation_census.py",
        "artifact": "data/rate_observation_census.json"},
    "census_consumer_census": {
        "module": "spa_core/monitoring/census_consumer_census.py",
        "artifact": "data/census_consumer_census.json"},
    "subject_population_census": {
        "module": "spa_core/monitoring/subject_population_census.py",
        "artifact": "data/subject_population_census.json"},
    "substring_structure_assertions": {
        "module": "spa_core/monitoring/substring_structure_assertions.py",
        "artifact": "data/substring_structure_assertions.json"},
    "haystack_origin_census": {
        "module": "spa_core/monitoring/haystack_origin_census.py",
        "artifact": "data/haystack_origin_census.json"},
    "capital_evidence_coverage": {
        "module": "spa_core/monitoring/capital_evidence_coverage.py",
        "artifact": "data/capital_evidence_coverage.json"},
    "apy_composition": {
        "module": "spa_core/monitoring/apy_composition.py",
        "artifact": "data/apy_composition.json"},
    "pool_identity_collision": {
        "module": "spa_core/monitoring/pool_identity_collision.py",
        "artifact": "data/pool_identity_collision.json"},
    # Объявленное имя ступени и имя файла модуля РАЗНЫЕ — ровно тот случай,
    # ради которого эта карта заведена (см. комментарий выше).
    "evidence_staleness": {
        "module": "spa_core/monitoring/evidence_staleness_monitor.py",
        "artifact": "data/evidence_staleness.json"},
    "outcomes": {
        "module": "spa_core/monitoring/outcomes_archive.py",
        "artifact": "data/investment_os/outcomes.jsonl"},
    "loop_retro": {
        "module": "spa_core/monitoring/loop_retro.py",
        "artifact": "data/loop_retro.json"},
    "loop_health": {
        "module": "spa_core/monitoring/loop_health.py",
        "artifact": "data/loop_health.json"},
}

#: ПРЕДМЕТ вердикта моста об отказе доставки — не карточки, а РЕШАТЕЛЬ: именно
#: `card_delivery` решает «переносим правку на origin» или «перенести нечем,
#: сделайте руками». Карточки — живое состояние, их в провенанс объявлять
#: нельзя (комментарий `_SUBJECT` в `scripts/consume_office_reports.py`: тогда
#: находку давал бы каждый прогон); решатель — код, и он меняется редко.
#:
#: Замер цикла #471 (03.09), ADR-220. Отчёт 11:46:08Z объявил PARTIAL и звал
#: перенести ВРУЧНУЮ две карточки `…gas-price-agent…`; в 16:04:31Z коммит
#: 3425bd28 (ADR-219, цикл #470) научил `rebase_onto_ahead_origin` везти ровно
#: этот случай. Перемерено в 17:2xZ: `rebase_card()` строит кандидата для ОБЕИХ.
#: Обязательный шаг 0-офис печатал требование ручной работы 4.3 ч после того,
#: как машина научилась делать её сама, — и отличить «нечем» от «уже есть чем»
#: читателю было НЕЧЕМ: у отчёта есть возраст, но возраст меряет, давно ли
#: ходил мост, а не сменился ли под ним тот, кто выносит вердикт.
DECIDER_REL = "spa_core/monitoring/card_delivery.py"

REQUIRED_SIGHTINGS = 2
#: Столько прогонов ПОДРЯД находка обязана отсутствовать, чтобы её карточка
#: закрылась. Зеркало REQUIRED_SIGHTINGS: рождение карточки уже требовало
#: повтора, а закрытие обходилось ОДНИМ молчаливым прогоном — асимметрия и
#: была механизмом рецидива (замер loop_health 28.08: 4 находки вернулись
#: после закрытия, ВСЕ из класса `gap:opportunity_unnamed`; условие при этом
#: не менялось — менялось лишь то, попал ли протокол в top_opportunities
#: конкретного суточного снимка офиса). Молчание одного прогона — не починка.
REQUIRED_ABSENCES = 2
MAX_CARDS_PER_DAY = 5
SUBPROC_TIMEOUT = 60

# След владельца во frontmatter (кнопки ADR-069). Есть хоть один ⇒ карточку
# владелец уже видел и ответил — авто-закрытие к ней не применяется.
OWNER_TRACE_FIELDS = ("owner_choice", "owner_answered_at", "owner_answered_by")

# Статусы, в которых карточка моста считается ОТКРЫТОЙ (её находка — carded).
# `needs-owner` здесь обязателен: без него потеря состояния приводила бы к
# ДУБЛЮ вопроса владельцу — зеркало того же дефекта, что в авто-закрытии.
OPEN_CARD_STATUSES = ("new", "in-progress", "needs-owner")


# ── сбор находок из источников ───────────────────────────────────────────────

def collect_findings(root: str = REPO_ROOT) -> tuple[list[dict], list[str]]:
    """[{key, severity, message, source}], [источники, которые не прочитались]."""
    findings: list[dict] = []
    unread: list[str] = []

    conf_rel = os.path.join("data", "architecture_conformance.json")
    try:
        conf = json.load(open(os.path.join(root, conf_rel)))
        stamp = conf.get("generated_at")
        for f in (conf.get("findings") or []):
            findings.append({"key": f["key"], "severity": f["severity"],
                             "message": f["message"], "source": "architecture_conformance",
                             "measured_at": stamp})
    except Exception:
        unread.append(conf_rel)

    gap_rel = os.path.join("data", "house_view_gap.json")
    try:
        gap = json.load(open(os.path.join(root, gap_rel)))
        stamp = gap.get("generated_at")
        for g in (gap.get("gaps") or []):
            if g.get("severity") in ("WARN", "CRITICAL"):
                findings.append({"key": g["key"], "severity": g["severity"],
                                 "message": g["message"], "source": "house_view_gap",
                                 "measured_at": stamp})
    except Exception:
        unread.append(gap_rel)

    # Фаза 4: выводы еженедельного ретро — третий источник. Рекомендация не
    # имеет права остаться в отчёте, который никто не обязан открыть.
    retro_rel = os.path.join("data", "loop_retro.json")
    try:
        retro = json.load(open(os.path.join(root, retro_rel)))
        stamp = retro.get("generated_at")
        for f in (retro.get("findings") or []):
            if f.get("severity") in ("WARN", "CRITICAL"):
                findings.append({"key": f["key"], "severity": f["severity"],
                                 "message": f["message"], "source": "loop_retro",
                                 "measured_at": stamp})
    except Exception:
        unread.append(retro_rel)

    return findings, unread


# ── карточки через единственный мутационный API ──────────────────────────────

def _queue(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, os.path.join(root, "scripts", "orchestrator_queue.py"), *args],
        capture_output=True, text=True, timeout=SUBPROC_TIMEOUT, cwd=root)


def create_card(root: str, finding: dict) -> str | None:
    """Создать карточку; вернуть путь к файлу карточки или None."""
    critical = finding["severity"] == "CRITICAL"
    if critical:
        body = (
            "## Что случилось и почему это важно\n"
            f"Сторож петли ({finding['source']}) нашёл КРИТИЧНОЕ расхождение с архитектурой:\n"
            f"{finding['message']}\n\n"
            "## Что от тебя нужно\n"
            "Посмотреть находку и решить: чиним / принимаем осознанно (тогда фиксируем "
            "решение в манифесте или ADR). Рекомендация агента — чинить: критичные "
            "находки этого класса уже стоили нам молчаливых отказов.\n\n"
            "## Как понять, что готово\n"
            "Находка исчезает из data/architecture_conformance.json при следующем прогоне.\n\n"
            "## Что будет после\n"
            "Мост сам закроет эту карточку, когда находка исчезнет; сторож продолжит "
            "следить, чтобы она не вернулась.\n\n"
            f"_finding_key: `{finding['key']}` · источник: {finding['source']} · ADR-066_\n")
        args = ["create", "--type", "owner-decision", "--status", "needs-owner",
                "--source", "nimbalyst",
                "--title", f"Критичная находка петли: {finding['message'][:70]}",
                "--body", body, "--field", f"finding_key={finding['key']}"]
    else:
        body = (f"Находка петли ADR-066 ({finding['source']}, WARN, подтверждена "
                f"{REQUIRED_SIGHTINGS} прогонами подряд):\n\n{finding['message']}\n\n"
                f"Сделано = находка исчезает из отчёта источника при следующем прогоне "
                f"(мост закроет карточку сам).\n\n"
                f"_finding_key: `{finding['key']}` · ADR-066_\n")
        args = ["create", "--type", "inbox", "--status", "new", "--source", "nimbalyst",
                "--title", f"Находка петли: {finding['message'][:70]}",
                "--body", body, "--field", f"finding_key={finding['key']}"]
    try:
        r = _queue(root, *args)
        if r.returncode != 0:
            return None
        path = (r.stdout or "").strip().splitlines()[-1].strip()
        return path if path.endswith(".md") else None
    except Exception:
        return None


def notify_card(root: str, card_path: str) -> bool:
    try:
        return _queue(root, "notify", card_path).returncode == 0
    except Exception:
        return False


def _frontmatter(card_path: str) -> dict:
    """Поля frontmatter карточки (только внутри ограды `---`, без вложенных блоков).

    Читаем именно ограду, а не «первую строку с двоеточием»: тело карточки моста
    заканчивается строкой `_finding_key: ...`, и наивный разбор принял бы её за поле.
    """
    fields: dict = {}
    try:
        with open(card_path, encoding="utf-8") as f:
            if f.readline().strip() != "---":
                return fields
            for line in f:
                if line.strip() == "---":
                    break
                if line.startswith((" ", "\t", "-")):  # вложенный блок (trackerStatus)
                    continue
                if ":" in line:
                    k, v = line.split(":", 1)
                    fields[k.strip()] = v.strip().strip("`'\"")
    except Exception:
        pass
    return fields


def card_status(card_path: str) -> str | None:
    return _frontmatter(card_path).get("status")


def card_is_untouched(card_path: str) -> bool:
    """Карточку моста никто не брал ⇒ исчезнувшая находка вправе её закрыть.

    Два типа карточек — два разных «нетронута», и знать надо ОБА (цикл #172):

    * `inbox` рождается `new` — нетронута, пока `new`;
    * `owner-decision` рождается `needs-owner` — то есть под старым правилом
      («закрываем только `new`») CRITICAL-карточка не закрывалась НИКОГДА, хотя
      её собственный текст обещает владельцу «мост закроет сам». Ложная тревога
      оставалась вечным вопросом в очереди владельца.

    След владельца во frontmatter (кнопки ADR-069: `owner_choice` /
    `owner_answered_at` / `owner_answered_by`) = вопрос УЖЕ увидели и ответили —
    такую не трогаем, как и любую взятую в работу (`in-progress`/`ingested`/
    `owner-done`/`done`). Инвариант #14 не задет: закрытие идёт в `done`,
    отвечать за владельца мост по-прежнему не смеет.
    """
    fm = _frontmatter(card_path)
    status = fm.get("status")
    if status == "new":
        return True
    if status == "needs-owner":
        return not any(fm.get(k) for k in OWNER_TRACE_FIELDS)
    return False


def close_card(root: str, card_path: str) -> bool:
    """Закрыть ТОЛЬКО нетронутую карточку моста. Взятую в работу не трогаем."""
    if not card_is_untouched(card_path):
        return False
    try:
        return _queue(root, "set-status", card_path, "done").returncode == 0
    except Exception:
        return False


def retract_card(root: str, card_path: str) -> bool:
    """Дописать владельцу, что вопрос снят: находка исчезла, тревога была ложной.

    Молчаливое снятие вопроса, о котором владельцу УЖЕ написали, — отдельный дефект,
    а не решение: в чате остаётся висеть «нужно решение», на которое нельзя ответить.
    Заодно гасим кнопки этой карточки (ADR-069), чтобы нажатие через три дня не
    записало «ответ владельца» в уже закрытую карточку.
    """
    try:
        from spa_core.owner_queue.notify import notify_card_withdrawn
        notify_card_withdrawn(card_path)
        return True
    except Exception:  # noqa: BLE001 — отзыв не смеет уронить мост
        return False


# ── ядро моста ───────────────────────────────────────────────────────────────

def _load_state(root: str) -> dict:
    try:
        return json.load(open(os.path.join(root, STATE_REL)))
    except Exception:
        return {"findings": {}, "daily": {}}


def _reconcile_with_tracker(root: str, st_findings: dict) -> int:
    """Самовосстановление состояния из РЕАЛЬНОСТИ (инцидент 2026-08-05 23:55:
    findings_bridge_state.json исчез между прогонами — виновник не установлен,
    файл нетрекаемый). Карточки моста несут `finding_key:` во frontmatter —
    открытая карточка на диске ⇒ находка carded, что бы ни говорило состояние.
    Предотвращает дубли карточек после ЛЮБОЙ потери состояния. Возвращает
    число восстановленных записей."""
    tdir = os.path.join(root, "nimbalyst-local", "tracker")
    if not os.path.isdir(tdir):
        return 0
    restored = 0
    for fn in sorted(os.listdir(tdir)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(tdir, fn)
        fk = status = None
        try:
            with open(path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if line.startswith("finding_key:"):
                        fk = line.split(":", 1)[1].strip().strip("`'\"")
                    elif line.startswith("status:"):
                        status = line.split(":", 1)[1].strip()
                    if i > 40:
                        break
        except Exception:
            continue
        if not fk or status not in OPEN_CARD_STATUSES:
            continue
        entry = st_findings.get(fk)
        if entry is None or (entry.get("status") != "carded"):
            now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
            prev = entry or {}
            # Тяжесть восстанавливаем ИЗ ТИПА карточки, а не из умолчания «WARN»:
            # `needs-owner` рождает только CRITICAL, а запись с чужой тяжестью на
            # следующем же прогоне сработала бы как эскалация WARN→CRITICAL и
            # создала второй вопрос владельцу — тот самый дубль, от которого
            # это восстановление и защищает.
            owner_card = status == "needs-owner"
            severity = "CRITICAL" if owner_card else prev.get("severity", "WARN")
            st_findings[fk] = {"first_seen": prev.get("first_seen", now_iso),
                               "seen_count": int(prev.get("seen_count", 0)),
                               "severity": severity,
                               # уведомление уже ушло вместе с рождением карточки —
                               # значит и отзыв при закрытии обязан уйти
                               "notified": bool(prev.get("notified", owner_card)),
                               "card": path, "status": "carded",
                               "carded_at": prev.get("carded_at", now_iso),
                               "recurrences": int(prev.get("recurrences", 0)),
                               "reconciled": True}
            restored += 1
    return restored


def _deliver_touched(root: str, created: list, closed: list,
                     now: dt.datetime, deliver=None) -> dict:
    """Довезти до origin карточки, которых мост за прогон КОСНУЛСЯ.

    Закрытые везём наравне с созданными: карточка, закрытая только в прод-дереве,
    остаётся на origin открытой — очередь показывает работу, которой нет
    (тот же класс, что #147).

    Список здесь — ТОЛЬКО тронутое за прогон, и это НЕ полный ответ на вопрос
    «что должно оказаться на origin»: провалившаяся доставка тронутой в следующем
    прогоне уже не будет (карточка помечена `closed` в состоянии моста), а значит
    сюда не попадёт никогда. Повтор живёт этажом ниже — в `card_delivery.deliver`,
    который сам добавляет к пачке свой ДОЛГ (ADR-081). Заводить повтор здесь
    было бы починкой одного вызывающего из нескольких.
    """
    paths = [c["card"] for c in created if c.get("card")]
    paths += [c["card"] for c in closed if c.get("card")]
    try:
        fn = deliver
        if fn is None:
            from spa_core.monitoring.card_delivery import deliver as fn
        return fn(paths, root=root, now=now)
    except Exception as e:  # noqa: BLE001 — доставка не смеет уронить мост,
        # но «не измерено» обязано быть НАЗВАНО, а не выглядеть успехом.
        return {"status": "UNCHECKED", "attempted": paths, "delivered": [],
                "reason": f"доставка не измерена: {type(e).__name__}: {e}",
                "generated_at": now.isoformat()}


def _deliver_owner_answers(root: str, now: dt.datetime, run_answers=None) -> dict:
    """Довезти до origin СЛЕД решения владельца (ADR-086).

    Почему это делает мост, а не отдельный агент: сторожу нужен регулярный
    прогон из ПРОД-дерева (только туда бот пишет ответ) — а это ровно то, чем
    мост уже является. Новый агент означал бы новую точку входа, новый plist и
    новый класс «доставлен, но не включён» (капкан #232), тогда как здесь
    проводка появляется одной строкой в уже работающем такте (6 ч).

    Список сторож строит ЗАНОВО каждый прогон, поэтому долг ему не нужен:
    не доехало — на следующем прогоне находка та же и поедет снова.
    """
    try:
        fn = run_answers
        if fn is None:
            from spa_core.monitoring.owner_answer_delivery import run as fn
        return fn(root=root, now=now)
    except Exception as e:  # noqa: BLE001 — сторож не смеет уронить мост,
        # но «не измерено» обязано быть НАЗВАНО, а не выглядеть успехом.
        return {"status": "UNCHECKED", "delivered": [], "pending": [],
                "reason": f"доставка следа решения владельца не измерена: "
                          f"{type(e).__name__}: {e}",
                "generated_at": now.isoformat()}


def census_skipped(record: dict, name: str, exc: BaseException) -> None:
    """Пропуск переписи — ЗАПИСЬ в отчёт, а не только строка в /tmp-логе.

    До #524 у провалившейся переписи был ровно один след наружу: отсутствие
    её артефакта на диске. Причина оставалась в логе живого агента, который
    читает лишь тот, кто уже знает, что смотреть. Теперь причина едет в
    `findings_bridge_report.json`, и «производитель пробовал и не смог»
    перестаёт быть неотличимым от «производитель ещё не пробовал».
    """
    record[name] = f"{type(exc).__name__}: {exc}"
    print(f"{name}: пропущено ({exc})")


def run_bridge(root: str = REPO_ROOT, now: dt.datetime | None = None,
               create=create_card, close=close_card, notify=notify_card,
               deliver=None, retract=retract_card, deliver_answers=None,
               censuses: dict | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    state = _load_state(root)
    findings, unread = collect_findings(root)
    current = {f["key"]: f for f in findings}
    st_findings: dict = state.setdefault("findings", {})
    reconciled = _reconcile_with_tracker(root, st_findings)
    daily: dict = state.setdefault("daily", {})
    created_today = int(daily.get(today, 0))

    created, deferred, closed, waiting, escalated = [], [], [], [], []
    # Находка, встреченная повторно в ТОМ ЖЕ замере (ADR-266): счётчик наблюдений
    # не растёт. Список существует затем, чтобы «не засчитано» не стало тишиной.
    resighted: list[str] = []
    # Источник без `generated_at`: замер не опознан, наблюдение засчитано по
    # старому правилу. Названо вслух — подмена «не измерено» на «измерено»
    # обязана быть видимой.
    unidentified: list[str] = []
    closing: list[dict] = []
    withdrawn: list[dict] = []

    for key, f in sorted(current.items()):
        entry = st_findings.get(key)
        if entry is None:
            entry = st_findings[key] = {"first_seen": now.isoformat(), "seen_count": 0,
                                        "severity": f["severity"], "card": None,
                                        "status": "observed"}
        elif entry.get("status") in ("closed", "resolved_untouched"):
            # РЕЦИДИВ: закрытая находка вернулась. Без сброса статуса она никогда
            # больше не родила бы карточку (needs_card требует observed) — молчаливый
            # провал петли, найден при построении loop_health (Фаза 4).
            entry.update(status="observed", seen_count=0, card=None,
                         first_seen=now.isoformat(),
                         # Рецидив начинает счёт заново — вместе с ним обнуляется
                         # и опознанный замер, иначе первое наблюдение рецидива
                         # совпало бы с последним замером ДО закрытия и не было
                         # бы засчитано (ADR-266).
                         last_measured_at=None,
                         recurrences=int(entry.get("recurrences", 0)) + 1)
        # НАБЛЮДЕНИЕ — это ЗАМЕР, а не прогон моста (ADR-266).
        #
        # `REQUIRED_SIGHTINGS = 2` написан затем, чтобы карточка рождалась лишь
        # у находки, ПЕРЕЖИВШЕЙ повторный замер. Считался же он прогонами моста,
        # а мост читает ФАЙЛ отчёта — и один и тот же замер попадал в счётчик
        # столько раз, сколько раз мост успевал прочитать этот файл.
        #
        # Замер конституции: `architecture_conformance` ходит раз в 6ч
        # (interval:21600s), мост — из `decision_loop` (те же 6ч) И из дневного
        # цикла (08:00), то есть ~5 прогонов моста на 4 замера в сутки. Значит
        # ДВА прогона моста регулярно приходятся на ОДИН замер, и порог из двух
        # наблюдений преодолевался без единого повторного измерения. Гистерезис,
        # рождённый защищать от мигающей находки, защищал от неё не всегда.
        #
        # Класс тот же, что нашла перепись вердикт-данных у B3:no_consumption:
        # «ещё не переспрошено» выдавалось за «подтверждено». Разница в том, что
        # у сторожа третий исход был НЕДОСТИЖИМ по построению, а здесь он есть —
        # просто его не спрашивали. Поэтому чинится ПОТРЕБИТЕЛЬ: сторож меряет
        # верно, а слово в решение превращается тут.
        #
        # Замер не опознан (у источника нет `generated_at`) ⇒ считаем, как
        # прежде, и НАЗЫВАЕМ это вслух. Здесь fail-CLOSED — именно так: не
        # засчитать нельзя, иначе находка без часов не родит карточку НИКОГДА
        # («irreversible UNCHECKED starves the queue»); молчать о подмене —
        # тоже нельзя.
        stamp = f.get("measured_at")
        if stamp is None:
            unidentified.append(key)
            entry["seen_count"] = int(entry.get("seen_count", 0)) + 1
        elif entry.get("last_measured_at") != stamp:
            entry["seen_count"] = int(entry.get("seen_count", 0)) + 1
            entry["last_measured_at"] = stamp
        else:
            resighted.append(key)
        entry["last_seen"] = now.isoformat()
        # Находка на месте ⇒ счётчик отсутствий обнуляется: закрытия требует
        # РЯД молчаливых прогонов подряд, а не их сумма за всю историю.
        entry["absent_count"] = 0

        esc = (f["severity"] == "CRITICAL" and entry.get("severity") != "CRITICAL"
               and entry.get("status") == "carded")
        entry["severity"] = f["severity"]
        needs_card = (entry.get("status") == "observed"
                      and (f["severity"] == "CRITICAL"
                           or entry["seen_count"] >= REQUIRED_SIGHTINGS)) or esc

        if not needs_card:
            if entry.get("status") == "observed":
                waiting.append(key)
            continue
        if created_today >= MAX_CARDS_PER_DAY:
            deferred.append(key)  # ГРОМКО в отчёте — не молчаливое обрезание
            continue
        path = create(root, f)
        if path:
            created_today += 1
            entry.update(status="carded", card=path, carded_at=now.isoformat())
            created.append({"key": key, "card": path, "severity": f["severity"]})
            if esc:
                escalated.append(key)
            if f["severity"] == "CRITICAL":
                # Запоминаем сам ФАКТ уведомления: без него закрытие карточки
                # оставит владельца с вопросом в чате, на который уже никто
                # не ждёт ответа (см. retract_card).
                entry["notified"] = bool(notify(root, path))

    for key in sorted(set(st_findings) - set(current)):
        entry = st_findings[key]
        if entry.get("status") == "carded" and entry.get("card"):
            # Гистерезис закрытия — зеркало гистерезиса рождения. Источник,
            # промолчавший ОДИН раз, ничего не чинит: суточный снимок офиса
            # перетасовывает top_opportunities, находка выпадает из отчёта,
            # карточка закрывается, назавтра находка возвращается дословно.
            # Счётчик виден в отчёте — «жду подтверждения» не должно выглядеть
            # как «ничего не происходит».
            entry["absent_count"] = int(entry.get("absent_count", 0)) + 1
            if entry["absent_count"] < REQUIRED_ABSENCES:
                closing.append({"key": key, "card": entry["card"],
                                "absent_count": entry["absent_count"],
                                "required": REQUIRED_ABSENCES})
                continue
            if close(root, entry["card"]):
                entry["status"] = "closed"
                entry["closed_at"] = now.isoformat()
                closed.append({"key": key, "card": entry["card"]})
                if entry.get("notified"):
                    ok = bool(retract(root, entry["card"]))
                    entry["withdrawn"] = ok
                    withdrawn.append({"key": key, "card": entry["card"], "sent": ok})
            else:
                entry["status"] = "resolved_untouched"  # взята в работу — решит человек
                entry["resolved_at"] = now.isoformat()
        elif entry.get("status") == "observed":
            del st_findings[key]  # мигнула и исчезла — гистерезис отработал

    daily[today] = created_today
    # Последний метр: карточка, рождённая в прод-дереве, на origin не попадает
    # НИКОГДА (замер цикла #170: из рождённых в рантайме доставлено 0 из 4), а
    # `needs-owner` вне origin для очереди владельца не существует. Доставка —
    # отдельный модуль, исключений не бросает и о своём исходе не молчит.
    delivery = _deliver_touched(root, created, closed, now, deliver)
    report = {"generated_at": now.isoformat(), "adr": "ADR-066",
              # Провенанс предмета в ТОЙ ЖЕ форме, что у architecture_conformance
              # (одна функция на обоих) — читает `_subject_drift` шага 0-офис.
              "inputs": subject_inputs(root, (DECIDER_REL,)),
              "delivery": delivery,
              "owner_answer_delivery": _deliver_owner_answers(root, now, deliver_answers),
              "created": created, "deferred": deferred, "closed": closed,
              "withdrawn": withdrawn,
              "waiting_hysteresis": waiting, "escalated": escalated,
              # Карточки, у которых находка пропала, но ряд молчаливых прогонов
              # ещё не набран. Ждать МОЛЧА нельзя: иначе «мост ничего не сделал»
              # неотличимо от «мост ждёт подтверждения» — та же болезнь, что
              # лечится в rate-limit'е словом deferred.
              "closing_hysteresis": closing,
              # Находки, встреченные повторно в ТОМ ЖЕ замере, и находки, чей
              # замер опознать нечем (ADR-266). Оба списка — про то, ЧЕМ
              # измерен гистерезис; без них «наблюдений два» неотличимо от
              # «замеров два», а это и была починенная подмена.
              "resighted_same_measurement": resighted,
              "measurement_unidentified": unidentified,
              "sources_unread": unread, "reconciled_from_tracker": reconciled,
              "open_cards": sum(1 for e in st_findings.values() if e.get("status") == "carded"),
              "rate_limit": {"max_per_day": MAX_CARDS_PER_DAY, "used_today": created_today}}
    # Ключ пишется ТОЛЬКО когда ступень переписей действительно шла (её
    # ведёт `main()`, а не `run_bridge`). Прямой вызов моста — из теста
    # или из чужого кода — ступени не выполняет, и объявлять «пробовали
    # все 25» было бы претензией без замера. Отсутствие ключа читатель
    # понимает как «этот отчёт про состав ступени не свидетельствует».
    if censuses is not None:
        report["censuses"] = censuses

    from spa_core.utils.atomic import atomic_save
    atomic_save(state, os.path.join(root, STATE_REL))
    atomic_save(report, os.path.join(root, REPORT_REL))

    from spa_core.monitoring.consumption_receipts import write_receipt
    for rel in ("data/architecture_conformance.json", "data/house_view_gap.json"):
        if rel not in unread:
            write_receipt(rel, "findings_to_cards", root=root)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--skip-gap", action="store_true",
                    help="не пересчитывать house_view_gap перед мостом")
    args = ap.parse_args(argv)
    if not args.run:
        ap.print_help()
        return 0
    # Ступень переписей. Что она пробовала и на чём споткнулась — едет в
    # отчёт моста (`censuses`), потому что снаружи у пропуска нет иного
    # следа, кроме отсутствующего артефакта, а его шаг 0-офис до #524
    # читал как находку безусловно.
    _skipped: dict[str, str] = {}
    if not args.skip_gap:
        from spa_core.monitoring import house_view_gap
        house_view_gap.run(root=args.root)
    # Сверка двух артефактов адаптеров (D6 ADR-060): считается ЗДЕСЬ, а не отдельным
    # агентом — вопрос «сходятся ли фиды» родствен house_view_gap («сходится ли офис с
    # книгой») и стоит миллисекунды. Новый launchd-агент ради него означал бы деплой,
    # то есть решение владельца, и сторож ушёл бы в очередь вместо того, чтобы работать.
    # Мост находок его пока НЕ читает намеренно: потребитель — шаг 0-офис оркестратора,
    # то есть решение принимает сессия, а не авто-карточка (выбор числа для 20 % книги —
    # money-path, ADR-060 D6 ждёт владельца).
    try:
        from spa_core.monitoring import adapter_feed_divergence
        afd = adapter_feed_divergence.run(root=args.root)
        print(f"adapter_feed_divergence: {afd['overall']} "
              f"(critical={afd['counts']['critical']} warn={afd['counts']['warn']} "
              f"unchecked={afd['counts']['unchecked']}), "
              f"протоколов сверено {len(afd['compared_protocols'])}")
    except Exception as e:  # noqa: BLE001 — сверка фидов не смеет валить мост
        census_skipped(_skipped, "adapter_feed_divergence", e)
    # Приёмка §5 ТЗ «Portfolio CIO» (ADR-226): доля КАПИТАЛА, ранжированного по
    # наблюдённым числам. Считается ЗДЕСЬ по той же причине, что и сверка фидов:
    # вопрос родствен («сходится ли то, чем мы объясняем книгу, с самой книгой»),
    # стоит миллисекунды, а отдельный launchd-агент означал бы деплой — решение
    # владельца, — и приёмка ушла бы в очередь вместо того, чтобы работать.
    # Мост находок его НЕ читает намеренно: потребитель — шаг 0-офис, то есть
    # решение принимает сессия. Автокарточка здесь была бы вредна: «не 100 %»
    # почти всегда означает работу над ФИДАМИ, у которой уже есть свои карточки.
    # §49 ТЗ «Portfolio CIO»: воспроизводим ли расчёт вообще. Считается ЗДЕСЬ по
    # той же причине, что соседи выше: отдельный launchd-агент означал бы деплой,
    # то есть решение владельца, и приёмка ушла бы в очередь вместо того, чтобы
    # работать. Цена ИЗМЕРЕНА на живом снимке 06.09 (544 файла): 3 прогона × 2
    # субъекта = 6 полных расчётов за 1.24 с — дороже соседних миллисекунд,
    # поэтому число прогонов держится минимальным (расхождение от соли хеша
    # видно на ЛЮБОЙ паре разных солей, сотни ему не нужны), а дословные 100
    # прогонов владельца доступны командой `--runs 100`.
    # Мост находок его НЕ читает намеренно: потребитель — шаг 0-офис, то есть
    # решение принимает сессия. Невоспроизводимый расчёт — это разбор архитектуры,
    # а не строка в автокарточке.
    try:
        from spa_core.monitoring import decision_reproducibility
        rep = decision_reproducibility.run(root=args.root)
        print(f"decision_reproducibility: {rep['overall']} "
              f"(critical={rep['counts']['critical']} warn={rep['counts']['warn']} "
              f"unchecked={rep['counts']['unchecked']}), прогонов {rep['runs']}")
    except Exception as e:  # noqa: BLE001 — замер воспроизводимости не смеет валить мост
        census_skipped(_skipped, "decision_reproducibility", e)
    # §12/§49 ТЗ CIO: влияет ли НАШ размер на ставку, по которой нас ранжируют.
    # Мост находок его НЕ читает — по той же причине, что и соседа выше: линейность
    # целевой функции это разбор архитектуры и решение владельца (money-path), а не
    # строка автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import marginal_apy_at_size
        mrep = marginal_apy_at_size.run(root=args.root)
        print(f"marginal_apy_at_size: {mrep['overall']} "
              f"(critical={mrep['counts']['critical']} warn={mrep['counts']['warn']} "
              f"unchecked={mrep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — замер маржинальности не смеет валить мост
        census_skipped(_skipped, "marginal_apy_at_size", e)
    # §49 ТЗ CIO «Costs»: газ/комиссии/проскальзывание в решении о перекладке.
    # Мост находок его НЕ читает — по той же причине, что и два соседа выше:
    # подстановка наблюдённого газа в `_move_cost_usd` меняет гейт, решающий о
    # движении капитала, то есть money-path и решение владельца, а не строка
    # автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import rebalance_cost_evidence
        crep = rebalance_cost_evidence.run(root=args.root)
        print(f"rebalance_cost_evidence: {crep['overall']} "
              f"(critical={crep['counts']['critical']} warn={crep['counts']['warn']} "
              f"unchecked={crep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — замер стоимости не смеет валить мост
        census_skipped(_skipped, "rebalance_cost_evidence", e)
    # §49 ТЗ CIO «Forecast accuracy»: ошибка прогноза APY и break-even. Мост
    # находок его НЕ читает по той же причине, что и трёх соседей выше:
    # подстройка прогноза меняет гейты `gain_above_band` и
    # `payback_within_horizon`, то есть money-path и решение владельца, а не
    # строка автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import apy_forecast_accuracy
        frep = apy_forecast_accuracy.run(root=args.root)
        print(f"apy_forecast_accuracy: {frep['overall']} "
              f"(critical={frep['counts']['critical']} warn={frep['counts']['warn']} "
              f"unchecked={frep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — замер прогноза не смеет валить мост
        census_skipped(_skipped, "apy_forecast_accuracy", e)
    # §38 ТЗ CIO «Historical replay»: прогон Current Strategy против CIO-тени по
    # девяти метрикам. Мост находок его НЕ читает по той же причине, что и
    # четырёх соседей выше: единственное действие по итогам прогона — тронуть
    # порог оборота или стоимость хода, то есть money-path и решение владельца,
    # а не строка автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_shadow_replay
        rrep = cio_shadow_replay.run(root=args.root)
        print(f"cio_shadow_replay: {rrep['overall']} "
              f"(critical={rrep['counts']['critical']} warn={rrep['counts']['warn']} "
              f"unchecked={rrep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — исторический прогон не смеет валить мост
        census_skipped(_skipped, "cio_shadow_replay", e)
    # Заказ G5 карточки CIO (ADR-271): чей вход СВЯЗЫВАЕТ названного блокера
    # взвода — дырка владельца или собственное предложение тени. Мост находок
    # его НЕ читает по той же причине, что и соседей выше: единственное действие
    # по итогам — тронуть порог оборота или починить цель, то есть money-path и
    # решение владельца, а не строка автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import shadow_blockade_attribution
        brep = shadow_blockade_attribution.run(root=args.root)
        print(f"shadow_blockade_attribution: {brep['overall']} "
              f"(critical={brep['counts']['critical']} "
              f"unchecked={brep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — атрибуция не смеет валить мост
        census_skipped(_skipped, "shadow_blockade_attribution", e)
    # Заказ #534 по карточке CIO: ОТКУДА берётся неустойчивость цели, которую
    # атрибуция выше назвала причиной блокады. Мост находок его НЕ читает по той
    # же причине, что и соседей: единственное действие по итогам — сменить форму
    # целевой функции (наливать по потолок победителю ничьи) или ввести
    # гистерезис порядка, то есть money-path и решение владельца, а не строка
    # автокарточки. Потребитель — обязательный шаг 0-офис.
    try:
        from spa_core.monitoring import target_stability
        trep = target_stability.run(root=args.root)
        print(f"target_stability: {trep['overall']} "
              f"(critical={trep['counts']['critical']} "
              f"unchecked={trep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "target_stability", e)
    # Заказ #535 по карточке CIO: СКОЛЬКО ЕЩЁ пар решают деньги ничьёй, помимо
    # той одной, что назвал ADR-279. Мост находок его НЕ читает по той же
    # причине, что и соседей: единственное действие по итогам — сменить форму
    # целевой функции или ввести гистерезис порядка, то есть money-path и
    # решение владельца, а не строка автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import ranking_tie_census
        rrep = ranking_tie_census.run(root=args.root)
        print(f"ranking_tie_census: {rrep['overall']} "
              f"(critical={rrep['counts']['critical']} "
              f"unchecked={rrep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "ranking_tie_census", e)
    # Заказ #536 по карточке CIO: ничья РАЗ В ТРИДЦАТЬ ДНЕЙ и ничья КАЖДЫЙ
    # ДЕНЬ требуют разных решений владельца, а перепись #535 считает их на
    # снимке ОДНОГО дня и в отчёте не различает. Мост находок его НЕ читает по
    # той же причине, что и соседей: единственное действие по итогам — сменить
    # форму целевой функции или ввести гистерезис порядка, то есть money-path и
    # решение владельца, а не строка автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import ranking_tie_persistence
        prep = ranking_tie_persistence.run(root=args.root)
        print(f"ranking_tie_persistence: {prep['overall']} "
              f"(critical={prep['counts']['critical']} "
              f"warn={prep['counts']['warn']} "
              f"unchecked={prep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "ranking_tie_persistence", e)
    # Заказ #539 по карточке CIO: журнал решений покрывает 4–6 ставок в день
    # против ~19 ранжируемых живым снимком, и каждый вопрос о РЕЖИМЕ платит эту
    # цену. Прибор мерит У ПИСАТЕЛЯ: что он держит, что пишет, каким признаком
    # отсекает (проба мутацией, не чтением исходника) и во что расширение
    # обошлось бы СЕМИ потребителям журнала. Мост находок его НЕ читает по той
    # же причине, что и соседей: единственное действие по итогам — дописать поле
    # в запись решения, то есть тронуть путь, по которому двигается капитал.
    # Потребитель — обязательный шаг 0-офис.
    try:
        from spa_core.monitoring import decision_journal_coverage
        drep = decision_journal_coverage.run(root=args.root)
        print(f"decision_journal_coverage: {drep['overall']} "
              f"(critical={drep['counts']['critical']} "
              f"warn={drep['counts']['warn']} "
              f"unchecked={drep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "decision_journal_coverage", e)
    # Заказ #540 по карточке CIO: расширение записи решения — это про ПРИБОРЫ
    # или про САМО РЕШЕНИЕ? Прибор разводит две поверхности с противоположными
    # ответами (живой путь вердикта — запись там ВЫХОД; путь реплея — вход) и
    # обязан носить положительный контроль: отрицательный результат без
    # доказанной способности перевернуть вердикт вакуумен. Мост находок его НЕ
    # читает по той же причине, что и соседей: единственное действие по итогам —
    # тронуть запись решения, то есть путь капитала. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import decision_record_verdict_sensitivity
        vrep = decision_record_verdict_sensitivity.run(root=args.root)
        print(f"decision_record_verdict_sensitivity: {vrep['overall']} "
              f"(critical={vrep['counts']['critical']} "
              f"warn={vrep['counts']['warn']} "
              f"unchecked={vrep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "decision_record_verdict_sensitivity", e)
    # Заказ #541 по карточке CIO: `hit_rate` — не приборная величина, а КРИТЕРИЙ
    # ВЗВОДА (MIN_HIT_RATE, мандат владельца ADR-067). ADR-295 назвал следствие
    # («hit_rate=1.0 посчитан на подмножестве дней, которое потолок дал оценить»),
    # прибор меряет, СМЕЩЁН ли он систематически, и на трёх осях сразу. Мост
    # находок его НЕ читает по той же причине, что и соседей: единственное
    # действие по итогам — тронуть стоимость или сам критерий, то есть путь
    # капитала и мандат владельца. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import hit_rate_selection_bias
        hrep = hit_rate_selection_bias.run(root=args.root)
        print(f"hit_rate_selection_bias: {hrep['overall']} "
              f"(critical={hrep['counts']['critical']} "
              f"warn={hrep['counts']['warn']} "
              f"unchecked={hrep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "hit_rate_selection_bias", e)
    # Заказ #541 (ADR-299 поставил вопрос): поднимет ли закрытие G1 хоть ОДИН
    # день журнала. Единица ответа — ДНИ, а не добавленные ключи: заказ назвал
    # подмену этих двух чисел заранее. Мост находок его НЕ читает по той же
    # причине, что и соседей: единственное действие по итогам — тронуть
    # POLLED_ADAPTERS, то есть путь капитала и решение владельца. Потребитель —
    # шаг 0-офис.
    try:
        from spa_core.monitoring import g1_verdict_recoverability
        grep_ = g1_verdict_recoverability.run(root=args.root)
        print(f"g1_verdict_recoverability: {grep_['overall']} "
              f"(critical={grep_['counts']['critical']} "
              f"warn={grep_['counts']['warn']} "
              f"unchecked={grep_['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "g1_verdict_recoverability", e)
    # Заказ #543 (ADR-300 поставил вопрос): ПОЧЕМУ у опрашиваемой ноги в
    # конкретный день нет живой ставки. Мост находок его НЕ читает по той же
    # причине, что и соседей: единственное действие по итогам — тронуть писателя
    # журнала решений, то есть запись, по которой судят перекладки капитала.
    # Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import unevidenced_leg_causes
        _ulc = unevidenced_leg_causes.run(root=args.root)
        print(f"unevidenced_leg_causes: {_ulc['overall']} "
              f"(critical={_ulc['counts']['critical']} "
              f"warn={_ulc['counts']['warn']} "
              f"unchecked={_ulc['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "unevidenced_leg_causes", e)
    # Заказ #545 (ADR-305 поставил вопрос): остаётся ли расширение записи на
    # критическом пути к взводу — по ОБОИМ порядкам снятия стен. Мост находок
    # его НЕ читает по той же причине, что и соседей: единственное действие по
    # итогам — снять стену, то есть тронуть пороги оборота либо писателя журнала
    # решений, а это money-path и предмет №1 ADR-285. Потребитель — шаг 0-офис.
    # Заказ #546 (ADR-306 поставил вопрос): проводка или значение — почему у
    # ноги книги нет живой ставки. Мост находок его НЕ читает по той же причине,
    # что и соседей: единственное действие по итогам — тронуть POLLED_ADAPTERS
    # либо путь ставки к записи, то есть money-path. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import leg_provenance_split
        _lps = leg_provenance_split.run(root=args.root)
        print(f"leg_provenance_split: {_lps['overall']} "
              f"(critical={_lps['counts']['critical']} "
              f"warn={_lps['counts']['warn']} "
              f"unchecked={_lps['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "leg_provenance_split", e)
    # Заказ #549 (ADR-312): решает ли МИНУТА снимка и где теряется наблюдённое
    # значение. Мост находок его НЕ читает по той же причине, что и соседей:
    # единственное действие по итогам — тронуть писателя журнала решений либо
    # частоту опроса, то есть money-path. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import snapshot_minute_sensitivity
        _sms = snapshot_minute_sensitivity.run(root=args.root)
        print(f"snapshot_minute_sensitivity: {_sms['overall']} "
              f"(critical={_sms['counts']['critical']} "
              f"warn={_sms['counts']['warn']} "
              f"unchecked={_sms['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "snapshot_minute_sensitivity", e)
    # Заказ #550/#551 (ADR-314): сколько снимков в день видит запись решения и
    # один ли это выбор. Мост находок его НЕ читает по той же причине, что и
    # соседей: единственное действие по итогам — тронуть писателя журнала
    # решений, то есть money-path. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import decision_record_run_identity
        _drri = decision_record_run_identity.run(root=args.root)
        print(f"decision_record_run_identity: {_drri['overall']} "
              f"(critical={_drri['counts']['critical']} "
              f"warn={_drri['counts']['warn']} "
              f"unchecked={_drri['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "decision_record_run_identity", e)
    # Заказ #564 (ADR-327). Сколько ПОТРЕБИТЕЛЕЙ у переписей этой самой ступени
    # и согласны ли они, что значит `root`. Мост находок артефакт НЕ читает:
    # действие по итогам — правка формы зова у сторожа контракта, то есть кода
    # проверки, а не капитала. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import census_consumer_census
        _ccc = census_consumer_census.run(root=args.root)
        print(f"census_consumer_census: {_ccc['overall']} "
              f"(critical={_ccc['counts']['critical']} "
              f"warn={_ccc['counts']['warn']} "
              f"unchecked={_ccc['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "census_consumer_census", e)
    # Заказ #565 (ADR-333). Сколько ЕЩЁ сторожей выводят своё население из ТЕКСТА
    # соседа и у скольких из них форма опирается на переименовываемое. Мост
    # находок артефакт НЕ читает: единственное действие по итогам — правка формы
    # вывода населения у сторожа, то есть кода проверки, а не капитала.
    # Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import subject_population_census
        _spc = subject_population_census.run(root=args.root)
        print(f"subject_population_census: {_spc['overall']} "
              f"(critical={_spc['counts']['critical']} "
              f"warn={_spc['counts']['warn']} "
              f"unchecked={_spc['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "subject_population_census", e)
    # Заказ #567 (ADR-338). Утверждения, судящие о СТРУКТУРЕ соседа ПОДСТРОКОЙ
    # её сериализованного вида. Мост находок артефакт НЕ читает: единственное
    # действие по итогам — расширить утверждение в ТЕСТЕ, то есть код проверки,
    # а не капитал. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import substring_structure_assertions
        _ssa = substring_structure_assertions.run(root=args.root)
        print(f"substring_structure_assertions: {_ssa['overall']} "
              f"(population={_ssa['counts']['population']} "
              f"truncating={_ssa['counts']['truncating']} "
              f"unmeasured={_ssa['counts']['unmeasured']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "substring_structure_assertions", e)
    # Заказ #568 (ADR-343). Откуда пришло содержимое стога у тех сайтов, которые
    # ADR-338 оставил ЗА своей границей: настоящий сосед под корнем дерева или
    # байты, написанные самим тестом. Мост находок артефакт НЕ читает по той же
    # причине, что и у соседа выше: единственное действие по итогам — расширить
    # утверждение в ТЕСТЕ, то есть код проверки, а не капитал. Потребитель —
    # шаг 0-офис.
    try:
        from spa_core.monitoring import haystack_origin_census
        _hoc = haystack_origin_census.run(root=args.root)
        print(f"haystack_origin_census: {_hoc['overall']} "
              f"(repo={_hoc['counts']['repo_neighbour'] + _hoc['counts']['repo_copy']} "
              f"self={_hoc['counts']['self_written']} "
              f"unmeasured={_hoc['counts']['unmeasured']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "haystack_origin_census", e)
    # Заказ #552 (ADR-316). Что теряет hit_rate от правила «одна строка в день».
    # Мост находок артефакт НЕ читает по той же причине, что и у соседей выше:
    # единственное действие по итогам — тронуть ПИСАТЕЛЯ журнала решений и его
    # правило замены строки дня, то есть запись, по которой судят перекладки
    # капитала, и критерий взвода MIN_HIT_RATE. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import day_replacement_verdict_loss
        _drvl = day_replacement_verdict_loss.run(root=args.root)
        print(f"day_replacement_verdict_loss: {_drvl['overall']} "
              f"(critical={_drvl['counts']['critical']} "
              f"warn={_drvl['counts']['warn']} "
              f"unchecked={_drvl['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "day_replacement_verdict_loss", e)
    # Заказ #554 (ADR-316). Двигался ли ВТОРОЙ вход тени — ставки — внутри дня.
    # Мост находок артефакт НЕ читает по той же причине, что и у соседей выше:
    # единственное действие по итогам — тронуть ЧАСТОТУ опроса ставок либо
    # писателя носителя, то есть вход, по которому судят перекладки капитала.
    # Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import intraday_rate_input_movement
        _irim = intraday_rate_input_movement.run(root=args.root)
        print(f"intraday_rate_input_movement: {_irim['overall']} "
              f"(critical={_irim['counts']['critical']} "
              f"warn={_irim['counts']['warn']} "
              f"unchecked={_irim['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "intraday_rate_input_movement", e)
    # Заказ #555 (ADR-318). Сколько дней знаменателя рассуживает audit_trail.
    # Мост находок артефакт НЕ читает по той же причине, что и у соседей выше:
    # единственное действие по итогам — тронуть ПИСАТЕЛЯ трейла, то есть вход,
    # по которому судят перекладки капитала. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import audit_trail_rate_input_coverage
        _atric = audit_trail_rate_input_coverage.run(root=args.root)
        print(f"audit_trail_rate_input_coverage: {_atric['overall']} "
              f"(critical={_atric['counts']['critical']} "
              f"warn={_atric['counts']['warn']} "
              f"unchecked={_atric['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "audit_trail_rate_input_coverage", e)
    # Мост артефакт НЕ читает по той же причине, что у соседа выше: единственное
    # действие по итогам — тронуть ПИСАТЕЛЯ носителя ставок либо частоту опроса,
    # то есть входы money-path. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import run_axis_time_stitch
        _rats = run_axis_time_stitch.run(root=args.root)
        print(f"run_axis_time_stitch: {_rats['overall']} "
              f"(critical={_rats['counts']['critical']} "
              f"warn={_rats['counts']['warn']} "
              f"unchecked={_rats['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "run_axis_time_stitch", e)
    # Ровно та же причина, что у соседа выше: единственное действие по итогам —
    # тронуть такт переписчика, `max_runs` кольцевого буфера или частоту опроса,
    # то есть входы money-path. Мост артефакт НЕ читает; потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import rate_observation_census
        _roc = rate_observation_census.run(root=args.root)
        print(f"rate_observation_census: {_roc.get('overall')} "
              f"(pairs={_roc['counts']['pairs']} "
              f"judged={_roc['counts']['pairs_judged']} "
              f"outside_carrier={_roc['counts']['runs_provable_outside_carrier']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "rate_observation_census", e)
    try:
        from spa_core.monitoring import arming_wall_order
        _awo = arming_wall_order.run(root=args.root)
        print(f"arming_wall_order: {_awo['overall']} "
              f"(critical={_awo['counts']['critical']} "
              f"warn={_awo['counts']['warn']} "
              f"unchecked={_awo['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "arming_wall_order", e)
    # Заказ #544 (ADR-302 поставил вопрос): чем ЗАКРЫВАЕМА дыра переписи задним
    # числом и той ли это пробы. Мост находок его НЕ читает по той же причине,
    # что и соседа выше: единственное действие по итогам — тронуть писателя
    # журнала решений либо переписать уже написанные записи, то есть запись, по
    # которой судят перекладки капитала. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import journal_backfill_material
        _jbm = journal_backfill_material.run(root=args.root)
        print(f"journal_backfill_material: {_jbm['overall']} "
              f"(critical={_jbm['counts']['critical']} "
              f"warn={_jbm['counts']['warn']} "
              f"unchecked={_jbm['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "journal_backfill_material", e)
    # Ответ владельца «Вариант Б» (2026-09-10, ADR-309): что и чем закрываемо
    # задним числом, поимённо и с числом. Прибор строит ПЛАН и ничего не пишет
    # в журнал: применение — отдельная команда, и оно ждёт решения о правиле
    # потребления дописанного (предмет №1 ADR-285). Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import journal_population_backfill
        _jpb = journal_population_backfill.run(root=args.root)
        print(f"journal_population_backfill: {_jpb['status']} "
              f"(план={_jpb.get('values_planned')} значений на "
              f"{len(_jpb.get('days_touched') or [])} дн.)")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "journal_population_backfill", e)
    # §43 ТЗ CIO «Audit trail»: отвечают ли ДАННЫЕ на вопрос о прошлой перекладке
    # («почему 13 августа переложили $12 000»), или на него отвечает только память
    # сессии. Мост находок его НЕ читает по той же причине, что и пять соседей
    # выше: дописать поле в запись решения значит изменить путь, по которому
    # двигается капитал, — money-path и решение владельца. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import decision_audit_trail
        arep = decision_audit_trail.run(root=args.root)
        print(f"decision_audit_trail: {arep['overall']} "
              f"(critical={arep['counts']['critical']} warn={arep['counts']['warn']} "
              f"unchecked={arep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — сверка трейла не смеет валить мост
        census_skipped(_skipped, "decision_audit_trail", e)
    # §47 ТЗ CIO «Failure modes»: отказывает ли путь решения на десяти
    # названных владельцем деградациях входа. Мост находок его НЕ читает по той
    # же причине, что и шесть соседей выше: построить недостающую дверь значит
    # изменить путь, по которому двигается капитал, — money-path и решение
    # владельца, а не строка автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_failure_modes
        frep = cio_failure_modes.run(root=args.root)
        t = frep["tally"]
        print(f"cio_failure_modes: {frep['overall']} "
              f"(отказывает {t['REFUSES']}/{frep['conditions_total']}, "
              f"частично {t['PARTIAL']}, не отказывает {t['PROCEEDS']}, "
              f"не измерено {t['UNCHECKED']})")
    except Exception as e:  # noqa: BLE001 — замер §47 не смеет валить мост
        census_skipped(_skipped, "cio_failure_modes", e)
    # §44 ТЗ CIO «Explainability»: из чего состоит объяснение, которое система
    # даёт владельцу о своём решении. Мост находок его НЕ читает по той же
    # причине, что и соседи выше: дописать факт во фразу значит изменить то,
    # что система говорит о движении денег, — решение владельца, а не строка
    # автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_explainability
        xrep = cio_explainability.run(root=args.root)
        t = xrep.get("tally") or {}
        if not xrep["control"]["passed"]:
            print(f"cio_explainability: {xrep['overall']} "
                  f"(положительный контроль не пройден — счёт не читать)")
        else:
            print(f"cio_explainability: {xrep['overall']} "
                  f"(произносится {t.get('SPOKEN')}/{xrep['facts_total']}, "
                  f"измерено но молчим {t.get('SILENT')}, "
                  f"не считает никто {t.get('ABSENT')})")
    except Exception as e:  # noqa: BLE001 — замер §44 не смеет валить мост
        census_skipped(_skipped, "cio_explainability", e)
    # §42 ТЗ CIO «Kill switch»: сколько из трёх названных владельцем органов
    # остановки у него есть, что каждый делает с книгой и переживают ли
    # наблюдение с отчётом нажатие. Мост находок его НЕ читает по той же
    # причине, что и соседи выше: дать владельцу ручку, которая останавливает
    # движение денег, — money-path и решение владельца, а не строка
    # автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_kill_switch_controls
        krep = cio_kill_switch_controls.run(root=args.root)
        t = krep.get("tally") or {}
        if not krep["control"]["passed"]:
            print(f"cio_kill_switch_controls: {krep['overall']} "
                  f"(положительный контроль не пройден — счёт не читать)")
        else:
            print(f"cio_kill_switch_controls: {krep['overall']} "
                  f"(есть {t.get('PRESENT')}/{krep['controls_total']}, "
                  f"подменено {t.get('CONFLATED')}, "
                  f"нет {t.get('ABSENT')}; отделимость "
                  f"{(krep.get('separability') or {}).get('verdict')})")
    except Exception as e:  # noqa: BLE001 — замер §42 не смеет валить мост
        census_skipped(_skipped, "cio_kill_switch_controls", e)
    # §41 ТЗ CIO «Auto-execution limits»: какие из двенадцати названных
    # владельцем ограничений реально стоя́т на пути решения и на какой из трёх
    # поверхностей (аллокатор предлагает · экономика судит цену хода · гейт
    # допускает) каждое связывает. Мост находок его НЕ читает по той же причине,
    # что и соседей выше: поставить auto-execution недостающий лимит — money-path
    # и решение владельца, а не строка автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_auto_execution_limits
        lrep = cio_auto_execution_limits.run(root=args.root)
        t = lrep.get("tally") or {}
        if not lrep["control"]["passed"]:
            print(f"cio_auto_execution_limits: {lrep['overall']} "
                  f"(положительный контроль не пройден — счёт не читать)")
        else:
            print(f"cio_auto_execution_limits: {lrep['overall']} "
                  f"(связывают с ручкой владельца {t.get(cio_auto_execution_limits.BINDING)}"
                  f"/{lrep['limits_total']}, "
                  f"порог в коде {t.get(cio_auto_execution_limits.LITERAL)}, "
                  f"объявлены но не спрашиваются "
                  f"{t.get(cio_auto_execution_limits.DECLARED_INERT)}, "
                  f"нет {t.get(cio_auto_execution_limits.ABSENT)})")
    except Exception as e:  # noqa: BLE001 — замер §41 не смеет валить мост
        census_skipped(_skipped, "cio_auto_execution_limits", e)
    # Остаток ADR-250: КТО ЕЩЁ производит цель, кроме StrategyAllocator, и
    # стоя́т ли у каждого производителя три ограничения владельца (суммарный
    # потолок тира · незнакомый тир · сеть). Мост находок его НЕ читает по той
    # же причине, что и соседей выше: достроить недостающее ограничение —
    # money-path и решение владельца, а не строка автокарточки. Потребитель —
    # шаг 0-офис.
    try:
        from spa_core.monitoring import cio_target_producers
        prep = cio_target_producers.run(root=args.root)
        if not prep["control"]["passed"]:
            print(f"cio_target_producers: {prep['overall']} "
                  f"(положительный контроль не пройден — счёт не читать)")
        else:
            silent = {r["producer"] for r in prep["matrix"]
                      if r["outcome"] == cio_target_producers.SILENT}
            print(f"cio_target_producers: {prep['overall']} "
                  f"(производителей цели {len(prep['producers'])}, "
                  f"принимают нарушающую цель хотя бы по одному ограничению "
                  f"{len(silent)})")
    except Exception as e:  # noqa: BLE001 — замер не смеет валить мост
        census_skipped(_skipped, "cio_target_producers", e)
    # §45 ТЗ CIO «Architecture constraints»: не совмещены ли в ОДНОМ модуле
    # пять названных владельцем ответственностей (рынок · APY · gas · risk
    # decision · подпись) и не стал ли LLM финансовым control layer. Мост
    # находок его НЕ читает по той же причине, что и соседей выше: разнести
    # ответственности живых адаптеров исполнения и расширить сторожа
    # инварианта #3 — money-path и решение владельца, а не строка
    # автокарточки. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_architecture_constraints
        arep = cio_architecture_constraints.run(root=args.root)
        if not arep["control"]["passed"]:
            print(f"cio_architecture_constraints: {arep['overall']} "
                  f"(положительный контроль не пройден — счёт не читать)")
        else:
            conc = arep["concentration"]
            print(f"cio_architecture_constraints: {arep['overall']} "
                  f"(максимум ответственностей в одном модуле {conc['max']}"
                  f"/{conc['of']}, совмещают рынок и подпись "
                  f"{len(conc['market_and_sign'])}, дверей к LLM "
                  f"{len(arep['llm']['doors'])})")
    except Exception as e:  # noqa: BLE001 — замер §45 не смеет валить мост
        census_skipped(_skipped, "cio_architecture_constraints", e)
    # §46 ТЗ CIO «Минимальный proposed component map»: у каких из ДЕСЯТИ
    # названных владельцем ступеней есть эквивалент в дереве и НЕСЁТ ли цепь
    # ход через него. Мост находок его НЕ читает: соединить разорванный стык
    # значит изменить путь решения о капитале — money-path и решение владельца.
    # Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_component_map
        cmap = cio_component_map.run(root=args.root)
        if not cmap["positive_control"]["passed"]:
            print(f"cio_component_map: {cmap['overall']} "
                  f"(положительный контроль не пройден — счёт не читать)")
        else:
            print(f"cio_component_map: {cmap['overall']} "
                  f"(ступеней с эквивалентом "
                  f"{cmap['stages_present']}/{cmap['stages_total']}, "
                  f"стыков несут ход {cmap['edges_wired']}/{cmap['edges_total']}, "
                  f"critical={cmap['counts']['critical']})")
    except Exception as e:  # noqa: BLE001 — замер §46 не смеет валить мост
        census_skipped(_skipped, "cio_component_map", e)
    # §48 ТЗ CIO «Изменения Risk Policy»: не ослаблена ли политика МОЛЧА и
    # находят ли решение, которым правку объясняют. Мост находок его НЕ читает:
    # и правка порога, и перенос дома решений — не автоматическое действие.
    # Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_policy_change_procedure
        pcp = cio_policy_change_procedure.run(root=args.root)
        if not pcp["positive_control"]["passed"]:
            print("cio_policy_change_procedure: "
                  f"{pcp['overall']} (положительный контроль не пройден — счёт не читать)")
        else:
            print(f"cio_policy_change_procedure: {pcp['overall']} "
                  f"(ослаблено {len(pcp['knobs_relaxed'])}, "
                  f"добавлено {len(pcp['knobs_added'])}, "
                  f"не менялось {pcp['knobs_unchanged']} из {pcp['knobs_total']}, "
                  f"critical={pcp['counts']['critical']})")
    except Exception as e:  # noqa: BLE001 — замер §48 не смеет валить мост
        census_skipped(_skipped, "cio_policy_change_procedure", e)
    # §5 ТЗ CIO, ступень `post-trade verification`: есть ли предмет сверки и
    # подают ли ей наблюдённый исход. Мост находок его НЕ читает: подать
    # ступени фактическую книгу значит изменить путь решения о капитале —
    # money-path и решение владельца. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_post_trade_verification
        ptv = cio_post_trade_verification.run(root=args.root)
        if not ptv["positive_control"]["passed"]:
            print("cio_post_trade_verification: "
                  f"{ptv['overall']} (положительный контроль не пройден — "
                  "счёт не читать)")
        else:
            print(f"cio_post_trade_verification: {ptv['overall']} "
                  f"(предмет {ptv['subject']['verdict']}, "
                  f"ходов книги {ptv['subject'].get('moves')}, "
                  f"вызовов сверки вне тестов {ptv['inputs']['sites_production']} "
                  f"из них с наблюдённым исходом "
                  f"{ptv['inputs']['counts']['OBSERVED']}, "
                  f"critical={ptv['counts']['critical']})")
    except Exception as e:  # noqa: BLE001 — замер §5 не смеет валить мост
        census_skipped(_skipped, "cio_post_trade_verification", e)
    # §5 ТЗ CIO, продолжение ступени сверки: существует ли НЕЗАВИСИМОЕ
    # наблюдение исхода книги (ADR-257). Вопрос отдельный от предыдущего: тот
    # меряет, подают ли сверке наблюдённый исход, этот — есть ли на свете чем
    # его наблюдать. Мост находок артефакт НЕ читает: соединение наблюдателя с
    # книгой требует ДВУХ решений владельца (наблюдатель вне `execution/` и
    # реальный капитал на цепи). Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_outcome_independence
        oid = cio_outcome_independence.run(root=args.root)
        if not oid["positive_control"]["passed"]:
            print("cio_outcome_independence: "
                  f"{oid['overall']} (положительный контроль не пройден — "
                  "счёт не читать)")
        else:
            print(f"cio_outcome_independence: {oid['overall']} "
                  f"(вердикт {oid['verdict']}, кандидатов "
                  f"{len(oid['candidates'])}, независимых "
                  f"{sum(1 for v in oid['per_candidate_verdict'] if v['independent'])}, "
                  f"critical={oid['counts']['critical']})")
    except Exception as e:  # noqa: BLE001 — замер §5 не смеет валить мост
        census_skipped(_skipped, "cio_outcome_independence", e)
    # Заказ циклов #518/#519 (ADR-258): где ещё функция, не сумевшая получить
    # вход, возвращает ПРАВДОПОДОБНОЕ число вместо отказа, и доходит ли хоть
    # одно такое число до решения о капитале. Мост находок артефакт НЕ читает:
    # правка любого найденного места — money-path и решение владельца.
    # Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import cio_substitution_census
        sub = cio_substitution_census.run(root=args.root)
        if not sub["positive_control"]["passed"]:
            print("cio_substitution_census: "
                  f"{sub['overall']} (положительный контроль не пройден — "
                  "счёт не читать)")
        else:
            cen = (sub.get("measurement") or {}).get("census") or {}
            reach = (sub.get("measurement") or {}).get("reachable") or {}
            print(f"cio_substitution_census: {sub['overall']} "
                  f"(перепись {cen.get('substitutions')} подстановок в "
                  f"{cen.get('files')} файлах — НАСЕЛЕНИЕ; достижимо от решения "
                  f"{len(reach.get('substitutions') or [])} подстановок и "
                  f"{len(reach.get('constants') or [])} констант, "
                  f"critical={sub['counts']['critical']})")
    except Exception as e:  # noqa: BLE001 — замер заказа не смеет валить мост
        census_skipped(_skipped, "cio_substitution_census", e)
    try:
        from spa_core.monitoring import capital_evidence_coverage
        cec = capital_evidence_coverage.run(root=args.root)
        agg = cec.get("all_books") or {}
        print(f"capital_evidence_coverage: {cec['verdict']} "
              f"(живой трек {cec['capital_coverage_pct']}% по наблюдению, "
              f"развёрнуто {cec['deployed_usd']}, "
              f"не измерено {(observed(cec, 'usd', kind=dict) or {}).get('unmeasured')}; "
              f"ВСЕ книги {agg.get('coverage_pct')}% — "
              f"литералом {(observed(agg, 'usd', kind=dict) or {}).get('literal')}, "
              f"книг померено {len(observed(agg, 'books_measured', kind=list) or [])}"
              f"/{len(agg.get('books_declared') or [])})")
    except Exception as e:  # noqa: BLE001 — приёмка не смеет валить мост
        census_skipped(_skipped, "capital_evidence_coverage", e)
    # Состав ставки (ADR-230): доход операции или раздача токена. Считается тем же
    # прогоном и по той же причине, что сверка фидов: вопрос родствен («чем именно
    # платит пул, число которого ранжирует капитал»), стоит миллисекунды, а новый
    # launchd-агент означал бы деплой — решение владельца, — и сторож ушёл бы в
    # очередь вместо того, чтобы работать. Мост находок его НЕ читает намеренно:
    # считать ли эмиссию доходностью и какой из двух пулов есть `spark_susds` —
    # money-path, то есть решение владельца, а не авто-карточка.
    try:
        from spa_core.monitoring import apy_composition
        apyc = apy_composition.run(root=args.root)
        print(f"apy_composition: {apyc['overall']} "
              f"(critical={apyc['counts']['critical']} warn={apyc['counts']['warn']} "
              f"unchecked={apyc['counts']['unchecked']}), "
              f"ключей с наблюдением {len(apyc['observed_adapters'])}")
    except Exception as e:  # noqa: BLE001 — состав ставки не смеет валить мост
        census_skipped(_skipped, "apy_composition", e)
    # Тождество пулов (гэп G1): считается тем же прогоном и по той же причине —
    # вопрос родствен сверке фидов, стоит миллисекунды, новый агент означал бы
    # деплой. Сторож только НАЗЫВАЕТ: снятие ключа с финансирования и правка
    # потолков — money-path, а значит решение владельца, не авто-карточка.
    try:
        from spa_core.monitoring import pool_identity_collision
        pic = pool_identity_collision.run(root=args.root)
        print(f"pool_identity_collision: {pic['overall']} "
              f"(critical={pic['counts']['critical']} warn={pic['counts']['warn']} "
              f"unchecked={pic['counts']['unchecked']}), "
              f"ключей сверено {len(pic['keys_compared'])}")
    except Exception as e:  # noqa: BLE001 — сверка тождества не смеет валить мост
        census_skipped(_skipped, "pool_identity_collision", e)
    # Устаревание наблюдения (ADR-167): считается тем же прогоном и по той же
    # причине — вопрос родствен сверке фидов, стоит миллисекунды, новый агент
    # означал бы деплой. До #494 канал `governance/evidence_staleness.py` НИКТО
    # не спрашивал: решение владельца от 29.08 было принято, канал написан и
    # покрыт тестами, а объявленная им тревога по массовой слепоте прозвучать
    # не могла. Сторож только НАЗЫВАЕТ: MASS_BLINDNESS капитал не трогает
    # намеренно, а исполнение де-риска — money-path, то есть решение владельца
    # (карточка `agent-derisk-po-slepote-podklyuchit-k-rebalansu`), не авто-карточка.
    try:
        from spa_core.monitoring import evidence_staleness_monitor
        ev = evidence_staleness_monitor.run(root=args.root)
        c = ev["counts"]
        print(f"evidence_staleness: {ev['overall']} (действие {ev['action']}) — "
              f"свежих {c['fresh']} мягких {c['soft_stale']} жёстких {c['hard_stale']} "
              f"без часов {c['unknown_age']}; без наблюдения ${ev['usd']['unknown_age']:,.0f}")
    except Exception as e:  # noqa: BLE001 — лестница устаревания не смеет валить мост
        census_skipped(_skipped, "evidence_staleness", e)
    # Цикл 3 ADR-067: правая половина hit-rate — строка исхода за сегодня
    # (идемпотентно по дате; 4 шанса в день догнать evidenced-бар).
    try:
        from spa_core.monitoring.outcomes_archive import append_daily_outcome
        oc = append_daily_outcome(root=args.root)
        print(f"outcomes: {'записан ' + oc['date'] if oc['appended'] else oc['reason']}")
    except Exception as e:  # noqa: BLE001 — архив исходов не смеет валить мост
        census_skipped(_skipped, "outcomes", e)
    # Фаза 4: ретро — раз в неделю, самозапуск внутри 6ч-агента (без нового
    # launchd-агента); loop_health — каждый прогон (дёшево).
    try:
        from spa_core.monitoring import loop_retro
        from spa_core.monitoring.architecture_conformance import _parse_iso
        retro_path = os.path.join(args.root, loop_retro.RETRO_REL)
        prev_ts = None
        try:
            prev_ts = _parse_iso(json.load(open(retro_path)).get("generated_at"))
        except Exception:
            pass
        # Пересчёт при каждом прогоне старше 6ч (стоит миллисекунды): findings
        # ретро кормят мост, и недельная свежесть блокировала бы авто-закрытие
        # исчезнувшей находки на неделю (замечено на verdict_archive_lagging).
        # «Еженедельность» ретро — это КАДЕНЦИЯ ОТЧЁТА владельцу, не свежести.
        if prev_ts is None or (dt.datetime.now(dt.timezone.utc) - prev_ts).total_seconds() >= 6 * 3600:
            rr = loop_retro.run(root=args.root)
            print(f"loop_retro: кандидатов={len(rr['candidates'])} "
                  f"findings={len(rr['findings'])} unchecked={len(rr['unchecked'])}")
    except Exception as e:  # noqa: BLE001 — ретро не смеет валить мост
        census_skipped(_skipped, "loop_retro", e)
    r = run_bridge(root=args.root,
                   censuses={"attempted": list(CENSUS_STAGE),
                             "skipped": _skipped})
    try:
        from spa_core.monitoring import loop_health
        loop_health.run(root=args.root)
    except Exception as e:  # noqa: BLE001
        census_skipped(_skipped, "loop_health", e)
    print(f"findings_bridge: created={len(r['created'])} closed={len(r['closed'])} "
          f"deferred={len(r['deferred'])} waiting={len(r['waiting_hysteresis'])} "
          f"closing={len(r.get('closing_hysteresis') or [])} "
          f"open_cards={r['open_cards']} unread={r['sources_unread']}")
    for c in r["created"]:
        print(f"  + [{c['severity']}] {os.path.basename(c['card'])}")
    for c in r["closed"]:
        print(f"  ✓ закрыта {os.path.basename(c['card'])}")
    for c in r.get("withdrawn") or []:
        mark = "отзыв отправлен" if c["sent"] else "⚠️ ОТЗЫВ НЕ УШЁЛ (вопрос висит в чате)"
        print(f"  ↩︎ {os.path.basename(c['card'])}: {mark}")
    try:
        from spa_core.monitoring.card_delivery import render as render_delivery
        print("  " + render_delivery(r.get("delivery") or {}))
    except Exception as e:  # noqa: BLE001
        print(f"  card_delivery: ⚠️ квитанция не прочитана ({e})")
    for c in r.get("closing_hysteresis") or []:
        # Вслух: карточка ЖИВА намеренно, а не по недосмотру.
        print(f"  ⏳ {os.path.basename(c['card'])}: находка пропала "
              f"{c['absent_count']}/{c['required']} прогон(а) подряд — "
              f"закрытия ЖДЁМ (молчание одного прогона не есть починка)")
    if r["deferred"]:
        print(f"  ⚠️ ОТЛОЖЕНО rate-limit'ом ({MAX_CARDS_PER_DAY}/сутки): {r['deferred']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
