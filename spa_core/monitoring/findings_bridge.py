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

from spa_core.utils.observation import observed, observed_number
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
    "data/capital_observability_history.json",
    "data/unobserved_turnover_dependence.json",
    "data/unobserved_leg_remedy_class.json",
    "data/hit_rate_denominator_recovery.json",
    "data/remedy_class_single_forward_day.json",
    "data/writer_universe_lever_floor.json",
    "data/polled_never_observed_census.json",
    "data/silent_leg_day_price.json",
    "data/criterion_population_floor.json",
    "data/criterion_value_interval.json",
    "data/act_day_recovery.json",
    "data/run_identity_key_price.json",
    "data/heir_all_rows_price.json",
    "data/judge_alone_price.json",
    "data/adapter_repair_price.json",
    "data/criterion_sign_price.json",
    "data/move_cost_composition_price.json",
    "data/swap_existence_price.json",
    "data/asset_registry_gap_price.json",
    "data/intraday_rate_input_movement.json",
    "data/audit_trail_rate_input_coverage.json",
    "data/run_axis_time_stitch.json",
    "data/rate_observation_census.json",
    "data/census_consumer_census.json",
    "data/subject_population_census.json",
    "data/substring_structure_assertions.json",
    "data/haystack_origin_census.json",
    # Заказ G35 п. 5 (ADR-411). Перепись доставлена #626 с записью на прод-пути
    # и БЕЗ читателя: три реестра шага 0-офис о ней не знали, объявления здесь
    # не было, а производящего вызова не существовало вовсе — число лежало
    # файлом, который никто не открывает. Такт недельный и решает его ФАЙЛ
    # (`list_identity_census.run` → `measurement_due`), поэтому SLO 192ч.
    "data/list_identity_census.json",
    # Заказ G37 п. 2 (он же п. 2 заказа G36). ВТОРОЕ ПЛЕЧО того же опыта: сосед
    # выше жил ступенью, а этот прибор — строкой в промпте (шаг (1ж)), и замер
    # 18.09 показал, что строка не есть вызов: автоматического зова не
    # наблюдалось НИ ОДНОГО, отметку каждый раз ставила рука цикла. Опыт
    # закончен, ответ получен — плечо проводится. Такт недельный и решает его
    # ФАЙЛ (`python_reader_clock_doors.run` → `measurement_due`), SLO 192ч.
    "data/python_reader_clock_doors.json",
    # Заказ G97 п. 3 (ADR-562). ТРЕТЬЕ плечо того же семейства «часы как вход»:
    # сосед выше спрашивает, закрывается ли дверь читателя пином, а этот — ПРАВДА
    # ЛИ ВОЗРАСТ артефакта, то есть доходит ли инъектированный `now` до САМОЙ
    # отметки `generated_at`. Подмена часов у такого производителя проходит все
    # контроли вердикта и врёт только в отметке — ровно там, где её читает
    # сторож свежести. Мера зовёт сотню ЧУЖИХ производителей, и они ПИШУТ,
    # поэтому зов идёт в КОПИИ дерева (`sandbox=True`), а в живой `data/` ложится
    # ровно один файл — отчёт прибора. Цена ИЗМЕРЕНА: 25.2 мин на 98
    # производителей в двух плечах (ADR-562), поэтому такт недельный и решает
    # его ФАЙЛ (`artifact_stamp_clock_doors.run` → `measurement_due`), SLO 192ч.
    "data/artifact_stamp_clock_doors.json",
    # Заказ G39 п. 3 (ADR-415). Перепись гейтов такта: у скольких производителей
    # решение «пора ли производить» лежит ВНЕ производящей функции, так что
    # второй звавший обязан завести свою копию правила (класс ADR-220). Такта у
    # этой переписи НЕТ намеренно: зов есть разбор AST в одном процессе и стоит
    # секунды (замер 5.7с, ADR-415), поэтому недельный гейт не купил бы ничего,
    # а завёл бы ровно ту вторую копию правила, которую перепись и ищет. Отсюда
    # и SLO: он равняется такту БЕГУНА (6ч агента), а не недельному такту
    # соседей — 12ч.
    "data/tact_gate_census.json",
    # Заказ G41 п. 1 (ADR-417). Перепись «одно правило — две копии»: у скольких
    # правил есть ИСПОЛНИТЕЛЬ (код, который отказывает) и СТОРОЖ (тест),
    # проверяющие одно условие РАЗНЫМ кодом. Такта у переписи нет по той же
    # причине, что у соседа выше: зов — разбор AST в одном процессе (замер 9.3с),
    # а недельный гейт завёл бы вторую копию правила о сроке. SLO равняется
    # такту БЕГУНА (6ч агента) — 12ч.
    "data/rule_second_copy_census.json",
    # Заказ G44 п. 1 (ADR-420). Перепись сторожей, зеленеющих на ОПУСТОШЁННОМ
    # входе-перечне: «нарушений нет» и «никуда не смотрели» обязаны быть
    # различимы (инв. #17, но про сторожей). Такта нет по той же причине, что у
    # двух соседей выше — зов есть разбор AST в одном процессе; SLO равняется
    # такту БЕГУНА (6ч агента) — 12ч. Поведенческий зонд сюда НЕ подключён
    # намеренно: один его прогон стои́т сотен прогонов pytest, и место ему —
    # рука, а не шестичасовой агент.
    "data/vacuous_guard_census.json",
    # Заказ G92 п. 2 (ADR-543) — перепись тестов, зелёных ПО ПОСТРОЕНИЮ.
    # Ступень ДОРОГАЯ (сотни прогонов pytest), поэтому у неё ТАКТ: срок решает
    # ФАЙЛ (`green_by_construction_census.run` -> `measurement_due`), SLO 192ч,
    # и население ступени УРЕЗАНО до одного файла проб — полный замер зовётся
    # рукой через CLI и стои́т часа.
    "data/green_by_construction_census.json",
    # Заказ G93 п. 2 (ADR-545) — какое ДЕРЕВО способно ответить на §49 приказа
    # «Portfolio CIO». Ступень ДОРОГАЯ (настоящие пробы §49 по каждому дереву,
    # минуты) и предмет у неё — КОНФИГУРАЦИЯ деревьев, которая не меняется
    # ежечасно; поэтому ТАКТ, срок решает ФАЙЛ
    # (`acceptance_tree_capability.run` -> `measurement_due`), SLO 192ч.
    "data/acceptance_tree_capability.json",
    # Заказ G93 п. 3 (ADR-547) — КТО обязан звать сводку §49 и с каким
    # ТАКТОМ. Такт не выбран, а ВЫЧИСЛЕН: он равен самому короткому
    # `slo_hours` среди входов, объявленных мерой критериев §49 (замер
    # 03.10 — 7ч, ставит `Costs`). Ступень несёт и САМО ТАЛЛИ §49
    # (выполнено · не выполнено · не измерено) — иначе прибор был бы
    # ответом «читателя нет» без читателя. Гейт такта 6ч < пола, SLO 14ч
    # (гейт 6ч + наблюдённый период бегуна, ADR-506).
    "data/s49_tally_tact.json",
    # Заказ G94 (ADR-549) — выдерживает ли производитель ОБЪЯВЛЕННЫЙ `slo_hours`
    # по НАБЛЮДЁННОМУ такту. ADR-506 измерил этот класс РУКОЙ у одного агента
    # (объявлено 7ч, наблюдено до 7.84ч — семь периодов из восьми длиннее срока)
    # и назвал его: порог, который производитель не может выдержать никогда, не
    # отличает здоровье от болезни. Ступень дешёвая (разбор текстовых логов в
    # одном процессе), поэтому такта у неё НЕТ: SLO равняется такту БЕГУНА —
    # гейт 6ч + наблюдённый период прогона (ADR-506) = 14ч.
    "data/slo_keepability.json",
    # Заказ G94 п. 3 (ADR-550) — сколько привязок конституции держится ПРОЗОЙ и
    # у скольких из них есть второй читатель. Замер ПЕРЕД объявлением поля:
    # ADR-506 назвал цену у десяти §49-привязок, но населения прозы целиком не
    # мерил никто, а «объявить поле механически» уже стоило нам G86 п. 4.
    # Ступень дешёвая (разбор конституции и дерева в одном процессе, 0.6 с),
    # поэтому такта у неё НЕТ: SLO равняется такту БЕГУНА — гейт 6ч +
    # наблюдённый период прогона (ADR-506) = 14ч.
    "data/prose_binding_census.json",
    # Заказ G96 п. 2 (ADR-508) — сколько мутационных подмен считаются
    # ПРИМЕНЁННЫМИ, не спросив о якоре. Класс измерен рукой в цикле #727 (из 16
    # подмен применились 7, девять молча пропущены), и прибора на него не было.
    # Ступень дешёвая (разбор AST дерева в одном процессе, ~14 с), поэтому
    # такта у неё НЕТ: предмет меняется КАЖДЫМ циклом, который пишет батарею,
    # то есть почти каждым, и платить такт значило бы отвечать вчерашним
    # числом. SLO равняется такту БЕГУНА — гейт 6ч + наблюдённый период
    # прогона (ADR-506) = 14ч.
    "data/mutation_application_census.json",
    # Заказ G45 п. 1 (ADR-421) — СОСЕДНЯЯ координата, не та же: ADR-420 мерил
    # входы, записанные ЛИТЕРАЛОМ, и опустошал их правкой; здесь вход собирает
    # ВЫЗОВ (`ROOT.rglob`, `read_text`, `_collect()`), и опустошить его правкой
    # не нужно вовсе — каталога нет, перечень пуст. Ступень статическая, зов
    # есть разбор AST в одном процессе; SLO равняется такту БЕГУНА (6ч) — 12ч.
    "data/call_sourced_input_census.json",
    # Заказ G49 п. 2 (ADR-427) — перепись зовущих ОБЩЕЙ ПРОВОДКИ прогонов:
    # у кого из них вход обрезается МОЛЧА. Координата соседняя, не та же:
    # ADR-420/421 мерили ВХОД сторожа (перечень, который он обходит), здесь
    # мерится ВЫВОД подпроцесса, у которого проводка отрезает голову. Ступень
    # статическая, зов есть разбор AST в одном процессе; SLO равняется такту
    # БЕГУНА (6ч агента) — 12ч.
    "data/truncated_input_census.json",
    # Заказ G50 п. 2 (ADR-428) — та же пара вопросов ВТОРОЙ проводке
    # подпроцессов: `subprocess.run(..., capture_output=True)` зовётся своими
    # руками из многих мест, и срез там ставит САМ зовущий — в обе стороны, а
    # не только с головы. Ступень статическая, зов есть разбор AST в одном
    # процессе; SLO равняется такту БЕГУНА (6ч агента) — 12ч.
    "data/hand_truncation_census.json",
    # Заказ G46 п. 2 (ADR-424) — ответ на дыру ПРЕДЫДУЩЕЙ ступени: 195 её
    # осмотренных мест остались с НЕВЫЧИСЛЕННЫМ путём, то есть её ответ был
    # нижней границей неизвестного размера. Ступень статическая, зов есть
    # разбор AST в одном процессе; SLO равняется такту БЕГУНА (6ч) — 12ч.
    "data/unresolved_path_census.json",
    # Заказ G98 п. 1 (ADR-565) — ответ на оговорку, которую ADR-517 назвал сам:
    # достижимость доказывает ДОРОГУ, а не событие. Ступень спрашивает у ЖИВОГО
    # артефакта каждого недостижимого раскола, встречался ли класс вне перечня.
    # Зов есть разбор AST плюс чтение четырёх артефактов в одном процессе; цена
    # ИЗМЕРЕНА — 19.7 с. SLO равняется такту БЕГУНА (6ч агента) — 12ч.
    # Ступень читает артефакт СОСЕДА (`rule_second_copy_census`), поэтому
    # стои́т ПОСЛЕ него: прочитав прошлый такт, она сверяла бы своё население с
    # позавчерашним числом.
    "data/unknown_class_in_the_artifact.json",
    # Ступень G103 п. 1 (ADR-594): верность реестра `SITE_NUMBER_SOURCES`,
    # спрошенная у ЖИВОЙ страницы. Операнд — отчёт кустодиана
    # (`com.spa.site_freshness`, такт 6ч), а НЕ продукт моста: ступень в сеть
    # не ходит, поэтому порядка относительно других ступеней у неё нет. Цена
    # ИЗМЕРЕНА — чтение одного JSON плюс разбор модуля кустодиана.
    "data/declared_source_live_parity.json",
    # Ступень G103 п. 2 (ADR-620): тот же вопрос, заданный ВСЕМ читателям
    # чужой разметки, а не одному кустодиану. Ступень в сеть НЕ ходит —
    # оракулом ей служит само дерево, — поэтому порядка относительно других
    # ступеней у неё нет. Цена ИЗМЕРЕНА — 87 с (разбор ~5 000 модулей плюс
    # обход ~2 700 файлов разметки одним проходом); SLO 24ч, по такту
    # дерева: реестр личностей меняется пушем, а не часами.
    "data/foreign_markup_reader_census.json",
    # Ступень G98 п. 2 (ADR-566): стык двух осей — читателя и писателя — у
    # ОСТАЛЬНЫХ открытых счётчиков, которых шаг достижимости не спрашивал.
    # Цена ИЗМЕРЕНА — 24.8 с (три соседских обхода одним проходом дерева);
    # SLO равняется такту БЕГУНА — 12ч. Стои́т ПОСЛЕ ступени
    # `rule_second_copy_census`: население И обе КРАЕВЫЕ раскладки берутся у
    # соседа, и прочитав прошлый такт, ступень сверяла бы сегодняшнее дерево
    # с позавчерашним замером.
    "data/reachability_of_the_rest.json",
    # Критерий §49 `Anti-churn` приказа владельца «Portfolio CIO» (ADR-480,
    # цикл #701). Возвращалась ли книга в состояние, которое сама же покинула,
    # и видел ли это гистерезис разворота. Ступень читает журнал ходов — то
    # есть ЖИВОЙ `data/`, а не дерево, — поэтому такт у неё суточный, как у
    # самого журнала: чаще мерить нечего, реже — прыжок узнаётся не в тот день.
    "data/book_oscillation_census.json",
    # Критерий §49 `Economics` приказа владельца «Portfolio CIO» (ADR-484,
    # цикл #702). Побеждает ли DO NOTHING ту раскладку, которую тот же документ
    # зовёт оптимальной. Ступень читает журналы вердиктов — то есть ЖИВОЙ
    # `data/`, а не дерево, — поэтому такт у неё суточный, как у самих журналов.
    "data/keep_dominance_census.json",
    # Критерий §49 `Risk` приказа владельца «Portfolio CIO» (ADR-486, цикл #705).
    # Нарушала ли объявленные потолки книга, которая РЕАЛЬНО стояла, — и определён
    # ли ответ, если ярлык тира лежит в пяти копиях. Ступень читает журнал ходов
    # (ЖИВОЙ `data/`) и историю файла политики, поэтому такт суточный, как у
    # самого журнала.
    "data/policy_binding_census.json",
    # Критерий §49 `Persistence` приказа владельца «Portfolio CIO» (ADR-485,
    # цикл #702). Сколько дней жило преимущество, которым ход был оправдан.
    # Ступень читает журнал ходов и наблюдённый ряд ставок — то есть ЖИВОЙ
    # `data/`, — поэтому такт суточный, как у самого ряда: чаще мерить нечего
    # (новой точки ряда нет), реже — умершее преимущество узнаётся не в тот день.
    "data/gain_persistence_census.json",
    # Критерий §49 `Pre-trade safety` приказа владельца «Portfolio CIO»
    # (ADR-487, цикл #708). Было ли у исполненного хода ВТОРОЕ наблюдение входов
    # между предложением и исполнением. Ступень читает цепочку аудита — то есть
    # ЖИВОЙ `data/`, — поэтому такт у неё суточный, как у самой цепочки.
    "data/pre_trade_recheck_census.json",
    # Критерий §49 `Owner visibility` приказа владельца «Portfolio CIO»
    # (ADR-488, цикл #709). Доходят ли до владельца ТРИ названных им числа
    # (current/optimal APY, Yield Gap) и рекомендация. Ступень читает журнал
    # решений и выдачу слоя отображения — то есть ЖИВОЙ `data/`, — поэтому такт
    # у неё суточный, как у самого журнала.
    "data/owner_visibility_census.json",
    # Цена класса «две сессии на одном предмете» — заказ G38 п. 3 (ADR-413,
    # ADR-498). Ступень читает журнал объявлений (живой `data/`) и дерево
    # базового ref, поэтому такт у неё суточный, как у самого журнала.
    "data/duplicate_subject_census.json",
    # Виден ли ДВЕРИ шага 0a/0b предмет захвата — НОМЕР ЗАКАЗА, а не путь
    # карточки — заказ G109 п. 2 (ADR-534, измерен ADR-678). Ступень читает
    # журнал объявлений (живой `data/`), дерево базового ref и поднимает
    # одноразовые сцены, поэтому такт у неё суточный, как у соседа.
    "data/order_subject_census.json",
    # Переживает ли запись прогона ОТМЕНУ — заказ G109 п. 1 (ADR-534, измерен
    # ADR-679). Ступень спрашивает GitHub API (население прогонов, строки записей,
    # длительность шага выгрузки) и локальный клон (воркфлоу того sha, на котором
    # шёл прогон), поэтому такт у неё суточный, как у соседей.
    "data/record_survival_census.json",
    # Кто окажется ЧИТАТЕЛЕМ квитанции read-only проверки захвата — заказ G88 п. 1
    # (ADR-498, измерен ADR-535). Ступень поднимает одноразовые сцены и читает
    # ЖИВОЕ дерево (кто грузит сторожа), поэтому такт у неё суточный, как у соседа.
    "data/claim_guard_receipt_readers.json",
    # Согласны ли ДВЕРИ ЧАСОВ одного поля между собой — заказ G110 п. 3 (ADR-535,
    # измерен ADR-682). Ступень грузит двери живого дерева и зовёт их на закрытом
    # словаре форм; сети нет, такт суточный, как у соседей.
    "data/announce_clock_door_census.json",
    "data/receipt_channel_cost.json",
    # Цена ветви «освобождение по КАРТОЧКЕ» — заказ G111 п. 1 (ADR-536,
    # измерен ADR-685). Ступень перепроигрывает журнал объявлений (живой
    # `data/`) и поднимает одноразовую сцену двери, поэтому такт у неё
    # суточный, как у соседа ADR-536.
    "data/foreign_done_cost.json",
    # Кто и когда ЗАКРЫВАЕТ захват, и чего стоил бы срок годности — заказ G88 п. 2
    # (ADR-498, измерен ADR-536). Ступень читает журнал объявлений (живой `data/`) и
    # спрашивает ОС о живости держателей, поэтому такт у неё суточный, как у соседа.
    "data/claim_release_census.json",
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
    "capital_observability_history",
    "unobserved_turnover_dependence",
    "unobserved_leg_remedy_class",
    "hit_rate_denominator_recovery",
    "remedy_class_single_forward_day",
    "writer_universe_lever_floor",
    "polled_never_observed_census",
    "silent_leg_day_price",
    "criterion_population_floor",
    "criterion_value_interval",
    "act_day_recovery",
    "run_identity_key_price",
    "heir_all_rows_price",
    "judge_alone_price",
    "adapter_repair_price",
    "criterion_sign_price",
    "move_cost_composition_price",
    "swap_existence_price",
    "asset_registry_gap_price",
    "intraday_rate_input_movement",
    "audit_trail_rate_input_coverage",
    "run_axis_time_stitch",
    "rate_observation_census",
    "census_consumer_census",
    "subject_population_census",
    "substring_structure_assertions",
    "haystack_origin_census",
    "list_identity_census",
    "python_reader_clock_doors",
    "artifact_stamp_clock_doors",
    "tact_gate_census",
    "rule_second_copy_census",
    "vacuous_guard_census",
    "green_by_construction_census",
    "acceptance_tree_capability",
    "s49_tally_tact",
    "slo_keepability",
    "prose_binding_census",
    "mutation_application_census",
    "call_sourced_input_census",
    "truncated_input_census",
    "hand_truncation_census",
    "unresolved_path_census",
    "unknown_class_in_the_artifact",
    "reachability_of_the_rest",
    "declared_source_live_parity",
    "foreign_markup_reader_census",
    "book_oscillation_census",
    "keep_dominance_census",
    "policy_binding_census",
    "gain_persistence_census",
    "pre_trade_recheck_census",
    "owner_visibility_census",
    "duplicate_subject_census",
    "order_subject_census",
    "record_survival_census",
    "claim_guard_receipt_readers",
    "announce_clock_door_census",
    "receipt_channel_cost",
    "foreign_done_cost",
    "claim_release_census",
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
    "capital_observability_history": {
        "module": "spa_core/monitoring/capital_observability_history.py",
        "artifact": "data/capital_observability_history.json"},
    "unobserved_turnover_dependence": {
        "module": "spa_core/monitoring/unobserved_turnover_dependence.py",
        "artifact": "data/unobserved_turnover_dependence.json"},
    "unobserved_leg_remedy_class": {
        "module": "spa_core/monitoring/unobserved_leg_remedy_class.py",
        "artifact": "data/unobserved_leg_remedy_class.json"},
    "hit_rate_denominator_recovery": {
        "module": "spa_core/monitoring/hit_rate_denominator_recovery.py",
        "artifact": "data/hit_rate_denominator_recovery.json"},
    "remedy_class_single_forward_day": {
        "module": "spa_core/monitoring/remedy_class_single_forward_day.py",
        "artifact": "data/remedy_class_single_forward_day.json"},
    "writer_universe_lever_floor": {
        "module": "spa_core/monitoring/writer_universe_lever_floor.py",
        "artifact": "data/writer_universe_lever_floor.json"},
    "polled_never_observed_census": {
        "module": "spa_core/monitoring/polled_never_observed_census.py",
        "artifact": "data/polled_never_observed_census.json"},
    "silent_leg_day_price": {
        "module": "spa_core/monitoring/silent_leg_day_price.py",
        "artifact": "data/silent_leg_day_price.json"},
    "criterion_population_floor": {
        "module": "spa_core/monitoring/criterion_population_floor.py",
        "artifact": "data/criterion_population_floor.json"},
    "criterion_value_interval": {
        "module": "spa_core/monitoring/criterion_value_interval.py",
        "artifact": "data/criterion_value_interval.json"},
    "act_day_recovery": {
        "module": "spa_core/monitoring/act_day_recovery.py",
        "artifact": "data/act_day_recovery.json"},
    "run_identity_key_price": {
        "module": "spa_core/monitoring/run_identity_key_price.py",
        "artifact": "data/run_identity_key_price.json"},
    "heir_all_rows_price": {
        "module": "spa_core/monitoring/heir_all_rows_price.py",
        "artifact": "data/heir_all_rows_price.json"},
    "judge_alone_price": {
        "module": "spa_core/monitoring/judge_alone_price.py",
        "artifact": "data/judge_alone_price.json"},
    "adapter_repair_price": {
        "module": "spa_core/monitoring/adapter_repair_price.py",
        "artifact": "data/adapter_repair_price.json"},
    "criterion_sign_price": {
        "module": "spa_core/monitoring/criterion_sign_price.py",
        "artifact": "data/criterion_sign_price.json"},
    "move_cost_composition_price": {
        "module": "spa_core/monitoring/move_cost_composition_price.py",
        "artifact": "data/move_cost_composition_price.json"},
    "swap_existence_price": {
        "module": "spa_core/monitoring/swap_existence_price.py",
        "artifact": "data/swap_existence_price.json"},
    "asset_registry_gap_price": {
        "module": "spa_core/monitoring/asset_registry_gap_price.py",
        "artifact": "data/asset_registry_gap_price.json"},
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
    "list_identity_census": {
        "module": "spa_core/monitoring/list_identity_census.py",
        "artifact": "data/list_identity_census.json"},
    "python_reader_clock_doors": {
        "module": "spa_core/monitoring/python_reader_clock_doors.py",
        "artifact": "data/python_reader_clock_doors.json"},
    "artifact_stamp_clock_doors": {
        "module": "spa_core/monitoring/artifact_stamp_clock_doors.py",
        "artifact": "data/artifact_stamp_clock_doors.json"},
    "tact_gate_census": {
        "module": "spa_core/monitoring/tact_gate_census.py",
        "artifact": "data/tact_gate_census.json"},
    "rule_second_copy_census": {
        "module": "spa_core/monitoring/rule_second_copy_census.py",
        "artifact": "data/rule_second_copy_census.json"},
    "vacuous_guard_census": {
        "module": "spa_core/monitoring/vacuous_guard_census.py",
        "artifact": "data/vacuous_guard_census.json"},
    "green_by_construction_census": {
        "module": "spa_core/monitoring/green_by_construction_census.py",
        "artifact": "data/green_by_construction_census.json"},
    "acceptance_tree_capability": {
        "module": "spa_core/monitoring/acceptance_tree_capability.py",
        "artifact": "data/acceptance_tree_capability.json"},
    "s49_tally_tact": {
        "module": "spa_core/monitoring/s49_tally_tact.py",
        "artifact": "data/s49_tally_tact.json"},
    "slo_keepability": {
        "module": "spa_core/monitoring/slo_keepability.py",
        "artifact": "data/slo_keepability.json"},
    "prose_binding_census": {
        "module": "spa_core/monitoring/prose_binding_census.py",
        "artifact": "data/prose_binding_census.json"},
    "mutation_application_census": {
        "module": "spa_core/monitoring/mutation_application_census.py",
        "artifact": "data/mutation_application_census.json"},
    "call_sourced_input_census": {
        "module": "spa_core/monitoring/call_sourced_input_census.py",
        "artifact": "data/call_sourced_input_census.json"},
    "truncated_input_census": {
        "module": "spa_core/monitoring/truncated_input_census.py",
        "artifact": "data/truncated_input_census.json"},
    "hand_truncation_census": {
        "module": "spa_core/monitoring/hand_truncation_census.py",
        "artifact": "data/hand_truncation_census.json"},
    "unresolved_path_census": {
        "module": "spa_core/monitoring/unresolved_path_census.py",
        "artifact": "data/unresolved_path_census.json"},
    "unknown_class_in_the_artifact": {
        "module": "spa_core/monitoring/unknown_class_in_the_artifact.py",
        "artifact": "data/unknown_class_in_the_artifact.json"},
    "reachability_of_the_rest": {
        "module": "spa_core/monitoring/reachability_of_the_rest.py",
        "artifact": "data/reachability_of_the_rest.json"},
    "declared_source_live_parity": {
        "module": "spa_core/monitoring/declared_source_live_parity.py",
        "artifact": "data/declared_source_live_parity.json"},
    "foreign_markup_reader_census": {
        "module": "spa_core/monitoring/foreign_markup_reader_census.py",
        "artifact": "data/foreign_markup_reader_census.json"},
    "book_oscillation_census": {
        "module": "spa_core/monitoring/book_oscillation_census.py",
        "artifact": "data/book_oscillation_census.json"},
    "keep_dominance_census": {
        "module": "spa_core/monitoring/keep_dominance_census.py",
        "artifact": "data/keep_dominance_census.json"},
    "policy_binding_census": {
        "module": "spa_core/monitoring/policy_binding_census.py",
        "artifact": "data/policy_binding_census.json"},
    "gain_persistence_census": {
        "module": "spa_core/monitoring/gain_persistence_census.py",
        "artifact": "data/gain_persistence_census.json"},
    "pre_trade_recheck_census": {
        "module": "spa_core/monitoring/pre_trade_recheck_census.py",
        "artifact": "data/pre_trade_recheck_census.json"},
    "owner_visibility_census": {
        "module": "spa_core/monitoring/owner_visibility_census.py",
        "artifact": "data/owner_visibility_census.json"},
    "duplicate_subject_census": {
        "module": "spa_core/monitoring/duplicate_subject_census.py",
        "artifact": "data/duplicate_subject_census.json"},
    "order_subject_census": {
        "module": "spa_core/monitoring/order_subject_census.py",
        "artifact": "data/order_subject_census.json"},
    "record_survival_census": {
        "module": "spa_core/monitoring/record_survival_census.py",
        "artifact": "data/record_survival_census.json"},
    "claim_guard_receipt_readers": {
        "module": "spa_core/monitoring/claim_guard_receipt_readers.py",
        "artifact": "data/claim_guard_receipt_readers.json"},
    "announce_clock_door_census": {
        "module": "spa_core/monitoring/announce_clock_door_census.py",
        "artifact": "data/announce_clock_door_census.json"},
    "receipt_channel_cost": {
        "module": "spa_core/monitoring/receipt_channel_cost.py",
        "artifact": "data/receipt_channel_cost.json"},
    "foreign_done_cost": {
        "module": "spa_core/monitoring/foreign_done_cost.py",
        "artifact": "data/foreign_done_cost.json"},
    "claim_release_census": {
        "module": "spa_core/monitoring/claim_release_census.py",
        "artifact": "data/claim_release_census.json"},
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

    # Контур подъёма тира (11.09, docs/TIER_LIFECYCLE_AUDIT_2026-09-11.md §8–§9):
    # у data/tier_curator_report.json не было НИ ОДНОГО читателя — PROMOTE_CANDIDATE
    # писался и умирал. Четвёртый источник замыкает контур ДО решения: кандидат ⇒
    # карточка агенту «собрать доказательства ADR-041, написать ADR». Ярлык тира по
    # этому пути НЕ меняется (docs/tier_criteria.md §5) — только ADR, в T1 — владелец;
    # поэтому severity всегда WARN (inbox), никогда CRITICAL (owner-decision): ADR-285
    # не пускает к владельцу вопрос, у которого ещё нет собранных доказательств.
    # Гистерезис моста (REQUIRED_SIGHTINGS замеров подряд) и есть «N дней подряд по
    # критериям» из ADR-055; measured_at — замер куратора, не прогон моста (ADR-266).
    curator_rel = os.path.join("data", "tier_curator_report.json")
    try:
        cur = json.load(open(os.path.join(root, curator_rel)))
        stamp = cur.get("generated_at")
        held = set((cur.get("summary") or {}).get("held_flagged") or [])
        for proto, v in sorted((cur.get("verdicts") or {}).items()):
            if not isinstance(v, dict):
                continue
            reasons = "; ".join(str(r) for r in (v.get("reasons") or [])) or "причины не названы"
            if v.get("verdict") == "PROMOTE_CANDIDATE":
                cur_t = v.get("current_tier") or "?"
                tgt = v.get("target_tier") or "?"
                gate = " Промоушен в T1 — только владелец, через ADR." if v.get("owner_gated") else ""
                findings.append({
                    "key": f"tier_promote:{proto}",
                    "severity": "WARN",
                    "message": (
                        f"Кандидат на подъём {cur_t}→{tgt}: {proto} — {reasons}. "
                        "ADR-041: ИЗМЕРЕНО куратором — живой TVL ≥ 5×floor, стабильность APY "
                        "≥ 14 дн, Tier-A чист; НЕ ИЗМЕРЕНО — возраст майннета, аудиты, инциденты "
                        "за 12 мес, латентность выхода, выживание в стрессе. Действие агента: "
                        "собрать недостающие доказательства и написать ADR; ярлык тира меняет "
                        "только ADR." + gate),
                    "source": "tier_curator", "measured_at": stamp})
            elif v.get("verdict") == "DEMOTE_SIGNAL" and proto in held:
                findings.append({
                    "key": f"tier_demote_held:{proto}",
                    "severity": "WARN",
                    "message": (
                        f"Удерживаемый {proto} под DEMOTE_SIGNAL: {reasons}. Гейты уже не дают "
                        "свежего капитала (Step 2c-pre / _fundable / RiskPolicy-ADR-053) — "
                        "карточка о ВИДИМОСТИ, не о защите: проверить, почему исключён, и что "
                        "позиция сокращается штатно (cap-at-held, без forced-sell)."),
                    "source": "tier_curator", "measured_at": stamp})
    except Exception:
        unread.append(curator_rel)

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
    # ADR-551: a closing carries who closed it and on what evidence — for the bridge the evidence IS
    # the disappearance of the finding that bred the card.
    try:
        _fm = _frontmatter(card_path)
    except Exception:  # noqa: BLE001 — the key is a courtesy in the evidence text, never a gate
        _fm = {}
    _key = (_fm or {}).get("finding_key") or os.path.basename(card_path)
    try:
        return _queue(root, "set-status", card_path, "done", "--closed-by", "findings_bridge",
                      "--evidence", f"finding {_key} absent in the fresh report (ADR-066 C2)").returncode == 0
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


def conflated_line(zero_vs_absent: dict | None) -> str:
    """«N из M» координат, сливающих ноль с отсутствием, — или НЕ ИЗМЕРЕНО.

    Вынесено из `main()` ради контроля: строка живёт внутри длинного переписного
    блока, и прежняя форма `sum((_zc.get("counts") or {}).values())` печатала
    «из 0» там, где знаменателя не наблюдали вовсе (инв. #17). Это ровно тот
    дефект, против которого двумя строками выше стои́т комментарий «`or {}` здесь
    запрещён намеренно»: заслон поставили на секцию и не поставили на её
    подраздел.
    """
    if not isinstance(zero_vs_absent, dict) or not zero_vs_absent.get("measured"):
        return "НЕ ИЗМЕРЕНО"
    counts = observed(zero_vs_absent, "counts", kind=dict)
    if counts is None:
        return "НЕ ИЗМЕРЕНО"
    conflated = observed(zero_vs_absent, "conflated", kind=list)
    if conflated is None:
        return "НЕ ИЗМЕРЕНО"
    return "%s из %s" % (len(conflated), sum(counts.values()))


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
               censuses: dict | None = None,
               run_started_at: dt.datetime | None = None) -> dict:
    """`run_started_at` — когда ЗАПУСТИЛСЯ процесс бегуна, а не когда начался мост.

    Два разных момента, и до цикла #750 наружу ехал только второй. Мост —
    ПОСЛЕДНЯЯ фаза прогона: ступень переписей идёт перед ним и на живом Маке
    занимает часы, поэтому `generated_at` отстоит от старта процесса далеко.
    Замер 02.10: процесс стартовал `04:46:42Z` (баннер START, pid 74604),
    `generated_at` = `08:10:17Z` — зазор **3 ч 24 мин**.

    Кто на этом спотыкался: `artifact_absence.verdict` спрашивает «успел ли
    бегун увидеть производителя» и сравнивал дату модуля с `generated_at`.
    Код ступени `claim_guard_receipt_readers` (ADR-535) лёг в прод-дерево в
    `05:49:42Z` — то есть на час ПОЗЖЕ старта процесса и на два часа РАНЬШЕ
    `generated_at`. Процесс к тому времени свой `findings_bridge` уже
    импортировал, ступени в исполняемом коде не было по построению — а шаг
    0-офис объявил исправную проводку находкой «объявленный артефакт без
    производящего вызова (форма ADR-259)». Это тот же класс, что ADR-478:
    сторож сверял артефакт с НЕ ТЕМ моментом и указывал не ту дверь.

    Момент импорта и есть момент, после которого код процесса неизменяем
    (`.claude/rules/deployment.md`, «долгоживущий агент держит код с момента
    старта»). Поле пишется ТОЛЬКО когда его передали: отсутствие поля —
    самостоятельный третий исход у читателя, а не молчаливая подстановка
    `generated_at` под видом старта.
    """
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
              # Старт ПРОЦЕССА (не моста) — см. докстроку `run_bridge`. Ключа
              # нет, если звавший его не передал: «не измерено» обязано быть
              # отличимо от «равно generated_at» (инв. #17).
              **({"run_started_at": run_started_at.isoformat()}
                 if run_started_at is not None else {}),
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
    # Старт процесса снимается ЗДЕСЬ — до ступени переписей, которая на живом
    # Маке занимает часы. Это момент, после которого код процесса неизменяем;
    # именно его спрашивает `artifact_absence.verdict` у вопроса «успел ли
    # бегун увидеть производителя». Снимать его внутри `run_bridge` было бы
    # тем же `generated_at` под новым именем (зазор 02.10 — 3 ч 24 мин).
    run_started_at = dt.datetime.now(dt.timezone.utc)
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
    # Заказ #586 (в хвосте ADR-364). Сосед выше меряет ГРАНИЦУ критерия, этот —
    # НАБЛЮДЁННОСТЬ ВХОДОВ по дням его знаменателя: приёмка G1 приказа CIO снята
    # ADR-364 за ОДИН день, а `hit_rate` посчитан по многим. Мост находок его НЕ
    # читает по той же причине, что и соседей: единственное действие по итогам —
    # тронуть критерий или писателя журнала, то есть путь капитала и мандат
    # владельца. Потребитель — шаг 0-офис.
    try:
        from spa_core.monitoring import capital_observability_history
        crep = capital_observability_history.run(root=args.root)
        print(f"capital_observability_history: {crep['overall']} "
              f"(critical={crep['counts']['critical']} "
              f"warn={crep['counts']['warn']} "
              f"unchecked={crep['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "capital_observability_history", e)
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
    # ЧЕТЫРЕ ПРИБОРА РЯДА G6→G9, объявленные в `CENSUS_STAGE` и ни разу отсюда
    # НЕ ЗВАННЫЕ (замер цикла #595). Это не оговорка: имя в составе ступени и
    # вызов в теле `main()` — РАЗНЫЕ утверждения, и до сих пор их связывал только
    # обычай. Отсюда и авария, за которую заведена карточка
    # `inbox-begun-perepisei-ne-soobschaet-chto-proiz`: артефакт G7 в проде
    # отсутствовал, шаг 0-офис докладывал «НЕ ПРОЧИТАН», и прочли это как
    # «бегун звал и промолчал». Бегун НЕ ЗВАЛ. Молчание ступени о неназванном
    # приборе неотличимо от её исправной работы — ровно инвариант #17, только
    # про вызов, а не про число. Красный `test_constant_matches_the_stage_
    # actually_run_by_main` говорил об этом с самого появления G6; он и есть
    # положительный контроль к этим четырём блокам.
    # Заказ #587 (ADR-368): ЦЕНА слепоты входов в долларах оборота.
    try:
        from spa_core.monitoring import unobserved_turnover_dependence
        _utd = unobserved_turnover_dependence.run(root=args.root)
        print(f"unobserved_turnover_dependence: {_utd['overall']} "
              f"(critical={_utd['counts']['critical']} "
              f"warn={_utd['counts']['warn']} "
              f"unchecked={_utd['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "unobserved_turnover_dependence", e)
    # Заказ #590 (ADR-369, G7): КАКОЙ РЫЧАГ снимает эту слепоту и чей он.
    try:
        from spa_core.monitoring import unobserved_leg_remedy_class
        _ulr = unobserved_leg_remedy_class.run(root=args.root)
        print(f"unobserved_leg_remedy_class: {_ulr['overall']} "
              f"(critical={_ulr['counts']['critical']} "
              f"warn={_ulr['counts']['warn']} "
              f"unchecked={_ulr['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "unobserved_leg_remedy_class", e)
    # Заказ #591 (ADR-371, G8): сколько ДНЕЙ знаменателя вернул бы рычаг.
    try:
        from spa_core.monitoring import hit_rate_denominator_recovery
        _hrd = hit_rate_denominator_recovery.run(root=args.root)
        print(f"hit_rate_denominator_recovery: {_hrd['overall']} "
              f"(critical={_hrd['counts']['critical']} "
              f"warn={_hrd['counts']['warn']} "
              f"unchecked={_hrd['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "hit_rate_denominator_recovery", e)
    # Заказ #592 (ADR-375, G9): те же доллары под правилом ОДНОГО форвардного дня.
    try:
        from spa_core.monitoring import remedy_class_single_forward_day
        _rcs = remedy_class_single_forward_day.run(root=args.root)
        print(f"remedy_class_single_forward_day: {_rcs['overall']} "
              f"(critical={_rcs['counts']['critical']} "
              f"warn={_rcs['counts']['warn']} "
              f"unchecked={_rcs['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "remedy_class_single_forward_day", e)
    # Заказ #596 (ADR-378, G10): ПУСТ ли потолок самого дешёвого рычага —
    # сколько его долларов подпёрто материалом в истории фидов.
    try:
        from spa_core.monitoring import writer_universe_lever_floor
        _wuf = writer_universe_lever_floor.run(root=args.root)
        print(f"writer_universe_lever_floor: {_wuf['overall']} "
              f"(critical={_wuf['counts']['critical']} "
              f"warn={_wuf['counts']['warn']} "
              f"unchecked={_wuf['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "writer_universe_lever_floor", e)
    # Заказ #597 (ADR-378, G11): кого мы ОПРАШИВАЕМ и не слышали ни разу —
    # поимённо, с длительностью молчания и долей капитала книги на них сегодня.
    try:
        from spa_core.monitoring import polled_never_observed_census
        _pnc = polled_never_observed_census.run(root=args.root)
        print(f"polled_never_observed_census: {_pnc['overall']} "
              f"(critical={_pnc['counts']['critical']} "
              f"warn={_pnc['counts']['warn']} "
              f"unchecked={_pnc['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "polled_never_observed_census", e)
    # Заказ #598 (ADR-379, G12): честная цена починки молчащей ноги в ДНЯХ
    # знаменателя `hit_rate` — сколько поднимается в одиночку, сколько держит
    # вторая нога (поимённо, с причиной) и сколько не поднимает ничто из нашего
    # кода. Объявления ступени НЕДОСТАТОЧНО: урок ADR-376 — объявленная ступень
    # не звалась вовсе, и артефакт не рождался молча. Поэтому вызов здесь.
    try:
        from spa_core.monitoring import silent_leg_day_price
        _sldp = silent_leg_day_price.run(root=args.root)
        print(f"silent_leg_day_price: {_sldp['overall']} "
              f"(critical={_sldp['counts']['critical']} "
              f"warn={_sldp['counts']['warn']} "
              f"unchecked={_sldp['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "silent_leg_day_price", e)
    # Заказ #599 (ADR-380, G13): доля населения критерия, посчитанная по ПОЛУ
    # знаменателя (что подпирает материал сегодня), а не по потолку. Сводит пол
    # соседа ADR-380 и потолок соседа ADR-371; своего знаменателя не имеет ни
    # одного. Объявления ступени НЕДОСТАТОЧНО: урок ADR-376 — объявленная
    # ступень не звалась вовсе, и артефакт не рождался молча. Поэтому вызов здесь.
    try:
        from spa_core.monitoring import criterion_population_floor
        _cpf = criterion_population_floor.run(root=args.root)
        print(f"criterion_population_floor: {_cpf['overall']} "
              f"(critical={_cpf['counts']['critical']} "
              f"warn={_cpf['counts']['warn']} "
              f"unchecked={_cpf['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "criterion_population_floor", e)
    # Заказ #600 (ADR-381, G14): ЗНАЧЕНИЕ критерия на знаменателе ступени
    # `our_code_floor` — двумя границами. Ряд G6→G13 мерил цену починок; этот
    # прибор меряет ОТДАЧУ, то есть меняется ли от починки решение о взводе.
    # Объявления ступени НЕДОСТАТОЧНО: урок ADR-376 — объявленная ступень не
    # звалась вовсе, и артефакт не рождался молча. Поэтому вызов здесь.
    try:
        from spa_core.monitoring import criterion_value_interval
        _cvi = criterion_value_interval.run(root=args.root)
        print(f"criterion_value_interval: {_cvi['overall']} "
              f"(critical={_cvi['counts']['critical']} "
              f"warn={_cvi['counts']['warn']} "
              f"unchecked={_cvi['counts']['unchecked']})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "criterion_value_interval", e)
    # Заказ #601 (G15, ADR-383): существует ли рычаг, возвращающий ACT-день в
    # ОЦЕНЁННЫЙ набор. Вызов здесь, а не одно объявление ступени: урок ADR-376 —
    # объявленная ступень не звалась вовсе, и артефакт молча не рождался.
    try:
        from spa_core.monitoring import act_day_recovery
        _adr = act_day_recovery.run(root=args.root)
        _bounds = _adr.get("bounds") or {}
        print(f"act_day_recovery: {_adr['overall']} "
              f"(в журнал {_bounds.get('act_days_recoverable_to_journal')} ACT-дн., "
              f"в оценённый набор [{_bounds.get('scored_act_days_lower')}, "
              f"{_bounds.get('scored_act_days_upper')}], "
              f"у владельца {_bounds.get('blocked_on_owner_lever')})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "act_day_recovery", e)
    # Заказ #602 (G16, ADR-384): во что обойдётся отмена двойного счёта — ключ
    # прогона вместо даты — и сколько ACT-дней это вернуло бы. Вызов здесь, а не
    # одно объявление ступени (урок ADR-376).
    try:
        from spa_core.monitoring import run_identity_key_price
        _rikp = run_identity_key_price.run(root=args.root)
        _b = _rikp.get("act_bounds") or {}
        _r = _rikp.get("readers") or {}
        _o = _r.get("outcomes") or {}
        print(f"run_identity_key_price: {_rikp['overall']} "
              f"(схлопывают день сами не менее "
              f"{_o.get('collapses_to_last', 0) + _o.get('collapses_to_first', 0)} "
              f"читателей из {len(_r.get('modules') or [])}; "
              f"ACT-дней вернулось бы [{_b.get('lower')}, {_b.get('upper')}])")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "run_identity_key_price", e)
    # Заказ #603 (G17, ADR-385): цена ТРЕТЬЕЙ половины рычага — наследников.
    # Вызов здесь, а не одно объявление ступени (урок ADR-376).
    try:
        from spa_core.monitoring import heir_all_rows_price
        _harp = heir_all_rows_price.run(root=args.root)
        _ho = _harp.get("heir_outcomes") or {}
        print(f"heir_all_rows_price: {_harp.get('status')} "
              f"(из {_harp.get('heirs_population')} схлопывающих наследников "
              f"раздуваются на ПОВТОРЕ {_ho.get('double_counts', 0)}, "
              f"вернули бы стёртое решение {_ho.get('recovers', 0)})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "heir_all_rows_price", e)
    # Заказ #605 (G18, ADR-386): цена починки СУДЬИ отдельно от остальных.
    # Вызов здесь, а не одно объявление ступени (урок ADR-376).
    try:
        from spa_core.monitoring import judge_alone_price
        _jap = judge_alone_price.run(root=args.root)
        _vo = _jap.get("value_outcomes") or {}
        _ret = (_jap.get("returns_today") or {}).get("act_days")
        print(f"judge_alone_price: {_jap.get('status')} "
              f"(раздуваются на ПОВТОРЕ {_vo.get('inflates', 0)} из "
              f"{_jap.get('values_population')} величин судьи; сегодня критерию "
              f"возвращается {_ret} ACT-дн.)")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "judge_alone_price", e)
    # Заказ #606 (G19, ADR-387): цена починки АДАПТЕРОВ в той же валюте — ACT-дни до
    # критерия. Вызов здесь, а не одно объявление ступени (урок ADR-376). Ёмкость
    # мерится вместе с сегодняшним чтением: весь замер стои́т ~5 с, и разделять их
    # значило бы оставить в цикле ТОЛЬКО сегодняшний ноль — то есть самую
    # соблазнительную половину ответа.
    try:
        from spa_core.monitoring import adapter_repair_price
        _arp = adapter_repair_price.run(root=args.root)
        _today = (_arp.get("returns_today") or {}).get(
            "act_days_returned_by_full_grant")
        _cap = observed(_arp, "capacity", kind=dict) or {}
        _cap_days = _cap.get("act_days_returned_by_full_grant", "НЕ ИЗМЕРЕНО")
        print(f"adapter_repair_price: {_arp.get('status')} "
              f"(дней отвергнуто {(_arp.get('blocked_days') or {}).get('count')}; "
              f"критерию возвращается сегодня {_today} ACT-дн., "
              f"на ёмкостном стенде {_cap_days})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "adapter_repair_price", e)
    # Заказ #607 (G20, ADR-388): закрывается ли критерий №3 ПОЛОЖИТЕЛЬНО хоть при
    # каком-то состоянии гейтов, и если нет — какая величина держит знак. Вызов
    # здесь, а не одно объявление ступени (урок ADR-376). Дифференциал мерится
    # вместе с перебором: весь замер стои́т ~0.2 с, а без него ответ «ни одно
    # состояние» остался бы без доказательства, что прибор вообще способен сказать
    # другое.
    try:
        from spa_core.monitoring import criterion_sign_price
        _csp = criterion_sign_price.run(root=args.root)
        _sub = observed(_csp, "gate_subsets", kind=dict) or {}
        _dif = observed(_csp, "differential", kind=dict) or {}
        _exhausted = sorted(n for n, v in (_dif.get("by_input") or {}).items()
                            if v.get("lever_exhausted"))
        print(f"criterion_sign_price: {_csp.get('status')} "
              f"(состояний гейтов {_sub.get('subsets_enumerated')}; "
              f"достаточных {_sub.get('sufficient_subsets')}; ACT-дней до критерия "
              f"{_sub.get('act_days_to_criterion')}; рычаг исчерпан у "
              f"{', '.join(_exhausted) or 'ни одного входа'})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "criterion_sign_price", e)
    # Заказ #608 (G21, ADR-389): от чего зависит ЦЕНА хода поимённо, каким
    # основанием объясняются дни с отрицательной выгодой, и сколько ACT-дней
    # вернула бы критерию медианная цена. Вызов здесь, а не одно объявление
    # ступени (урок ADR-376): ступень, которую никто не зовёт, производит
    # артефакт ровно ноль раз.
    try:
        from spa_core.monitoring import move_cost_composition_price
        _mcc = move_cost_composition_price.run(root=args.root)
        _cmp = observed(_mcc, "composition", kind=dict) or {}
        _swp = observed(_mcc, "cost_level_sweep", kind=dict) or {}
        _flip = (_swp.get("flip_level_bps") or {}).get("flip_bps")
        print(f"move_cost_composition_price: {_mcc.get('status')} "
              f"(воспроизведено {_cmp.get('days_reproduced')} дн. из "
              f"{_cmp.get('days_total')}, расхождений {_cmp.get('days_divergent')}, "
              f"НЕ ИЗМЕРЕНО {_cmp.get('days_unmeasured')}; перелом на "
              f"{_flip if _flip is not None else 'НЕ НАЙДЕН'} bps оборота; "
              f"при медианной цене ACT-дней "
              f"{(_swp.get('named') or {}).get('median')})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "move_cost_composition_price", e)
    # Заказ #609 (G22, ADR-390): существует ли операция, которую оценивает
    # SLIPPAGE_BPS_STABLE. Актив пула у каждой ноги — тождеством кода, а не по
    # виду имени; доля потока, не меняющая актива; провенанс константы (на
    # обрезанной истории — честный отказ, а не чужая дата); и сколько ACT-дней
    # вернуло бы снятие проскальзывания с долларов, которые актива не меняли.
    try:
        from spa_core.monitoring import swap_existence_price
        _sep = swap_existence_price.run(root=args.root)
        # `or {}` здесь запрещён намеренно (инв. #17): пустой словарь вместо
        # ненаблюдённой секции превратил бы «прибор не ответил» в «дней 0» —
        # ровно ту подмену отсутствия благополучием, которую сторож
        # `test_absent_observation_ratchet` и ловит.
        _ex = observed(_sep, "existence", kind=dict)
        _cf = observed(_sep, "counterfactual", kind=dict)
        _tot = (observed(_ex, "totals_all_measured_days", kind=dict)
                if _ex is not None else None)
        _ns_min = observed_number(_tot, "no_swap_share_min") if _tot else None
        _ns_max = observed_number(_tot, "no_swap_share_max") if _tot else None
        _no_swap = ("НЕ ИЗМЕРЕНО" if _ns_min is None or _ns_max is None
                    else "%.2f %%…%.2f %%" % (100 * _ns_min, 100 * _ns_max))
        _back = ("НЕ ИЗМЕРЕНО"
                 if _cf is None or not _cf.get("measured")
                 else "%s…%s" % (_cf.get("act_days_returned_min"),
                                 _cf.get("act_days_returned_max")))
        _seen = "НЕ ИЗМЕРЕНО" if _ex is None else _ex.get("days_measured")
        _all = "НЕ ИЗМЕРЕНО" if _ex is None else _ex.get("days_total")
        print(f"swap_existence_price: {_sep.get('status')} "
              f"(дней измерено {_seen} из {_all}; "
              f"без свопа {_no_swap} потока; "
              f"ACT-дней возвращается {_back})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "swap_existence_price", e)
    # Заказ #610 (G23, ADR-391): (а) сколько оборота ослеплено ключом без актива
    # и ПОЧЕМУ два реестра разошлись — ответ структурный, у канонического реестра
    # есть второй путь роста (условная допись за import-guard), у реестра активов
    # его нет ни одного; (б) чем ещё судья не отличает ноль от отсутствия —
    # перебор по КАЖДОМУ числовому полю, которое он читает, с третьим исходом
    # «не измерено» вместо ложного «различает».
    try:
        from spa_core.monitoring import asset_registry_gap_price
        _arg = asset_registry_gap_price.run(root=args.root)
        # `or {}` здесь запрещён намеренно (инв. #17): пустой словарь вместо
        # ненаблюдённой секции превратил бы «прибор не ответил» в «координат 0».
        _bl = observed(_arg, "blinded_turnover", kind=dict)
        _zc = observed(_arg, "zero_vs_absent", kind=dict)
        _blind = ("НЕ ИЗМЕРЕНО" if _bl is None or not _bl.get("measured")
                  else "$%s на %s ключ(ах)" % (
                      f"{_bl.get('leg_usd_blinded'):,.2f}",
                      _bl.get("blinded_keys_count")))
        _conf = conflated_line(_zc)
        print(f"asset_registry_gap_price: {_arg.get('status')} "
              f"(ослеплённый поток {_blind}; "
              f"координат сливают ноль с отсутствием {_conf})")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "asset_registry_gap_price", e)
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
    # Перепись личности списков (G34 п. 1, ADR-410) — НЕДЕЛЬНЫМ тактом, и срок
    # решает ФАЙЛ (`measurement_due` по отметке артефакта), а не расписание
    # бегуна: иначе «раз в неделю» держалось бы на том, что никто не менял такт
    # агента. Внутри такта вызов ничего не считает и ничего не пишет.
    #
    # Почему ступень моста, а не строка обязательного промпта. Соседняя перепись
    # (G33, `python_reader_clock_doors`) подключена шагом (1ж) промпта — и замер
    # 18.09 показал, что автоматического зова не наблюдалось НИ ОДНОГО: строка в
    # промпте не есть вызов, отметку артефакта каждый раз ставила рука цикла.
    # Здесь зовёт агент `com.spa.decision_loop`, а состав ступени сверяется с
    # ЭТИМ телом разбором AST — перепись, добавленная мимо, краснеет.
    #
    # «Не мерили» и «измерено» — разные исходы (инв. #17): внутри такта печатается
    # причина, а не вердикт о населении, которого никто не смотрел.
    try:
        from spa_core.monitoring import list_identity_census
        _lic = list_identity_census.run(root=args.root)
        if _lic.get("measured"):
            # Знаменатель читается ЧЕСТНОЙ формой: отсутствие счётчика — не ноль
            # (инв. #17), иначе строка «знаменатель 0» была бы утверждением о
            # населении, которого прибор не измерял.
            _lc = observed(_lic["doc"], "counts", kind=dict)
            _den = (None if _lc is None
                    else observed_number(_lc, "denominator_of_finding"))
            print(f"list_identity_census: {_lic['doc'].get('status')} — "
                  f"{_lic['doc'].get('reason')} (знаменатель "
                  f"{'НЕ ИЗМЕРЕНО' if _den is None else int(_den)})")
        else:
            print(f"list_identity_census: внутри такта, НЕ мерили — "
                  f"{_lic.get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "list_identity_census", e)
    # (G37 п. 2 = п. 2 заказа G36, `python_reader_clock_doors`) ВТОРОЕ ПЛЕЧО
    # того же опыта. Сосед выше был проведён ступенью, этот прибор оставался
    # строкой в промпте (шаг (1ж)) — и замер 18.09 ответил: строка не есть
    # вызов, автоматического зова не наблюдалось ни одного. Опыт закончен,
    # ответ получен; плечо проводится, а `invoked_by` продолжает различать, чья
    # это была рука, независимо от проводки (ADR-412).
    #
    # ЦЕНА ЗОВА НАЗВАНА, а не умолчана: замер этого цикла — см. ADR-414. Такт
    # НЕДЕЛЬНЫЙ и решает его ФАЙЛ, поэтому в 167 прогонах агента из 168 ступень
    # стоит одного чтения отметки; дорогим оказывается один прогон в неделю.
    #
    # «Не мерили» и «измерено» — разные исходы (инв. #17): внутри такта
    # печатается причина, а не вердикт о населении, которого никто не смотрел.
    try:
        from spa_core.monitoring import python_reader_clock_doors
        _prcd = python_reader_clock_doors.run(root=args.root)
        if _prcd.get("measured"):
            # Знаменатель — ЧЕСТНОЙ формой: отсутствие счётчика не ноль
            # (инв. #17), иначе «население 0» стало бы утверждением о том,
            # чего прибор не мерил.
            _pc = observed(_prcd["doc"], "counts", kind=dict)
            _pop = (None if _pc is None
                    else observed_number(_pc, "python_branch"))
            _rest = (None if _pc is None
                     else observed_number(_pc, "rest_on_import_bound_door"))
            print(f"python_reader_clock_doors: {_prcd['doc'].get('status')} — "
                  f"на дверях, связанных на импорте, держатся "
                  f"{'НЕ ИЗМЕРЕНО' if _rest is None else int(_rest)} из "
                  f"{'НЕ ИЗМЕРЕНО' if _pop is None else int(_pop)}")
        else:
            print(f"python_reader_clock_doors: внутри такта, НЕ мерили — "
                  f"{_prcd.get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "python_reader_clock_doors", e)
    # (G97 п. 3, ADR-562) ТРЕТЬЕ плечо семейства «часы как вход». Сосед выше
    # спрашивает, закрывается ли дверь ЧИТАТЕЛЯ пином класса; этот — доходит ли
    # инъектированный `now` до САМОЙ отметки `generated_at` у ПРОИЗВОДИТЕЛЯ.
    # Разница не в оттенке: у производителя вердикт от часов не зависит, поэтому
    # подмена часов проходит все контроли вердикта и врёт ТОЛЬКО в возрасте
    # артефакта — то есть ровно там, где его читает сторож свежести.
    #
    # `sandbox=True` обязателен и не является осторожностью: мера зовёт сотню
    # ЧУЖИХ производителей, а они ПИШУТ. Зов идёт в копии дерева, живой `data/`
    # получает ровно ОДИН новый файл — отчёт самого прибора. В главном дереве
    # прибор отказывает замером (`assert_disposable_tree`), а не доверием.
    #
    # ЦЕНА НАЗВАНА, а не умолчана: 25.2 мин на 98 производителей в двух плечах
    # (замер 04.10, ADR-562). Такт НЕДЕЛЬНЫЙ и решает его ФАЙЛ, поэтому в 167
    # прогонах агента из 168 ступень стоит одного чтения отметки.
    #
    # «Не мерили» и «измерено» — разные исходы (инв. #17): внутри такта
    # печатается причина, а не вердикт о населении, которого никто не смотрел.
    try:
        from spa_core.monitoring import artifact_stamp_clock_doors
        _ascd = artifact_stamp_clock_doors.run(root=args.root, if_due=True,
                                               sandbox=True)
        if _ascd.get("skipped"):
            print(f"artifact_stamp_clock_doors: внутри такта, НЕ мерили — "
                  f"{_ascd.get('reason')}")
        else:
            # Счётчики — ЧЕСТНОЙ формой: отсутствие блока не ноль находок
            # (инв. #17), иначе «находок 0» стало бы утверждением о том, чего
            # прибор не мерил.
            _af = _ascd.get("findings_total")
            _au = _ascd.get("unmeasured_total")
            _ac = observed(_ascd, "counts", kind=dict)
            _ar = (None if _ac is None
                   else _ac.get(artifact_stamp_clock_doors.REACHES, 0))
            print(f"artifact_stamp_clock_doors: инъекция доходит до отметки у "
                  f"{'НЕ ИЗМЕРЕНО' if _ar is None else int(_ar)} из "
                  f"{_ascd.get('planned')}; находок "
                  f"{'НЕ ИЗМЕРЕНО' if _af is None else int(_af)}, НЕ ИЗМЕРЕНО "
                  f"{'НЕ ИЗМЕРЕНО' if _au is None else int(_au)}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "artifact_stamp_clock_doors", e)
    # Перепись гейтов такта (G39 п. 3, ADR-415): где у производителя лежит
    # решение «пора ли производить». Гейта такта у САМОЙ переписи нет, и это
    # замер, а не поблажка: зов — разбор AST в одном процессе, 5.7с против
    # минут у двух соседей выше, которые поднимают подпроцессы. Недельный гейт
    # здесь не сэкономил бы ничего и завёл бы вторую копию правила о сроке —
    # ровно тот класс, который перепись и меряет.
    #
    # «Не измерено» и «измерено» — разные исходы (инв. #17): корень не прочитан
    # ⇒ печатается причина, а не вердикт CLEAN о населении, которого не видели.
    try:
        from spa_core.monitoring import tact_gate_census
        _tgc = tact_gate_census.run(root=args.root)
        if _tgc.get("measured"):
            _tc = observed(_tgc["doc"], "counts", kind=dict)
            _cli = (None if _tc is None
                    else observed_number(_tc, "gate_at_cli_only"))
            _two = (None if _tc is None
                    else observed_number(_tc, "two_rules"))
            print(f"tact_gate_census: {_tgc['doc'].get('status')} — гейт вне "
                  f"производителя у "
                  f"{'НЕ ИЗМЕРЕНО' if _cli is None else int(_cli)}, два правила "
                  f"у {'НЕ ИЗМЕРЕНО' if _two is None else int(_two)}")
        else:
            print(f"tact_gate_census: НЕ ИЗМЕРЕНО — "
                  f"{_tgc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "tact_gate_census", e)
    # Перепись «одно правило — две копии» (G41 п. 1, ADR-417): у скольких правил
    # есть ИСПОЛНИТЕЛЬ и СТОРОЖ, проверяющие одно условие РАЗНЫМ кодом. Заказ
    # родился из ADR-416, где такая пара расходилась молча и покрасила `main`
    # при ВЕРНОМ состоянии дерева. Ступень, а не строка промпта: ADR-412 замерил,
    # что строка промпта не даёт ни одного автоматического зова.
    #
    # «Не измерено» и «измерено» — разные исходы (инв. #17): корень не прочитан
    # ⇒ печатается причина, а не вердикт CLEAN о населении, которого не видели.
    try:
        from spa_core.monitoring import rule_second_copy_census
        _rsc = rule_second_copy_census.run(root=args.root)
        if _rsc.get("measured"):
            _rc = observed(_rsc["doc"], "counts", kind=dict)
            _two_copies = (None if _rc is None
                           else observed_number(_rc, "two_copies"))
            print(f"rule_second_copy_census: {_rsc['doc'].get('status')} — правил "
                  f"в двух копиях "
                  f"{'НЕ ИЗМЕРЕНО' if _two_copies is None else int(_two_copies)}")
        else:
            print(f"rule_second_copy_census: НЕ ИЗМЕРЕНО — "
                  f"{_rsc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "rule_second_copy_census", e)
    # Перепись вырожденных сторожей (G44 п. 1, ADR-420): сколько сторожей
    # остаются ЗЕЛЁНЫМИ с опустошённым входом-перечнем. Заказ родился из
    # побочной находки ADR-419 (`tests/test_no_utcnow.py` проходит при пустом
    # `SCAN_DIRS`): зелёный сторож, осмотревший ноль, тише красного и потому
    # опаснее. Ступень статическая; поведенческие вердикты берутся из журнала
    # зонда, который перепись только ЧИТАЕТ.
    try:
        from spa_core.monitoring import vacuous_guard_census
        _vgc = vacuous_guard_census.run(root=args.root)
        if _vgc.get("measured"):
            _vc = observed(_vgc["doc"], "counts", kind=dict)
            _vac = (None if _vc is None
                    else observed_number(_vc, vacuous_guard_census.VERDICT_VACUOUS))
            print(f"vacuous_guard_census: {_vgc['doc'].get('status')} — сторожей, "
                  f"зелёных на пустом входе, "
                  f"{'НЕ ИЗМЕРЕНО' if _vac is None else int(_vac)}")
        else:
            print(f"vacuous_guard_census: НЕ ИЗМЕРЕНО — "
                  f"{_vgc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "vacuous_guard_census", e)
    # Перепись «зелёный по построению» (G92 п. 2, ADR-543): тесты, чей зелёный
    # не зависит НИ ОТ ОДНОГО решения прибора, который они проверяют. Ступень
    # ПОВЕДЕНЧЕСКАЯ (настоящие прогоны pytest на одноразовых копиях), поэтому
    # у неё ТАКТ и УРЕЗАННОЕ население; «внутри такта» и «измерено» — разные
    # исходы, и ноль в первой ветке не печатается.
    try:
        from spa_core.monitoring import green_by_construction_census as _gbc
        _gbcr = _gbc.run(root=args.root)
        if _gbcr.get("measured"):
            _gc = observed(_gbcr["doc"], "counts", kind=dict)
            _found = (None if _gc is None else observed_number(
                _gc, _gbc.VERDICT_GREEN_BY_CONSTRUCTION))
            print(f"green_by_construction_census: {_gbcr['doc'].get('status')} — "
                  f"тестов, зелёных по построению, "
                  f"{'НЕ ИЗМЕРЕНО' if _found is None else int(_found)} "
                  f"(население ступени урезано до "
                  f"{len(_gbc.STAGE_TEST_FILES)} файл(ов))")
        else:
            print(f"green_by_construction_census: внутри такта, НЕ мерили — "
                  f"{_gbcr.get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "green_by_construction_census", e)
    # Дерево приёмки §49 (G93 п. 2, ADR-545): способно ли дерево ВООБЩЕ вынести
    # вердикт по критерию приказа — вопрос соседний с «выполнен ли критерий», и
    # мера у него ДИФФЕРЕНЦИАЛЬНАЯ: у одного дерева слепота дерева неотличима от
    # отсутствия наблюдения на свете. Ступень с ТАКТОМ (пробы настоящие);
    # «внутри такта» и «измерено» — разные исходы, и ноль в первой ветке не
    # печатается.
    try:
        from spa_core.monitoring import acceptance_tree_capability as _atc
        _atcr = _atc.run(root=args.root)
        if _atcr.get("measured"):
            _adoc = _atcr["doc"]
            if str(_adoc.get("status")) != "OK":
                print(f"acceptance_tree_capability: НЕ ИЗМЕРЕНО — "
                      f"{_adoc.get('reason')}")
            else:
                _acounts = observed(_adoc, "counts", kind=dict)
                _bound = (None if _acounts is None else
                          observed_number(_acounts, _atc.TREE_BOUND))
                print(f"acceptance_tree_capability: дерево приёмки — "
                      f"{_adoc.get('acceptance_tree') or 'НЕ ИЗМЕРЕНО'}; "
                      f"критериев, у которых место приёмки РЕШАЕТ, "
                      f"{'НЕ ИЗМЕРЕНО' if _bound is None else int(_bound)}")
        else:
            print(f"acceptance_tree_capability: внутри такта, НЕ мерили — "
                  f"{_atcr.get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "acceptance_tree_capability", e)
    # Такт сводки §49 (G93 п. 3, ADR-547): такт ВЫЧИСЛЕН из входов вердикта,
    # а не объявлен; ступень несёт и само ТАЛЛИ §49, потому что вердикт сводки
    # доходит до читателя ТОЛЬКО артефактом.
    try:
        from spa_core.monitoring import s49_tally_tact as _stt
        _sttr = _stt.run(root=args.root)
        if _sttr.get("measured"):
            _sdoc = _sttr["doc"]
            if str(_sdoc.get("status")) != "OK":
                print(f"s49_tally_tact: НЕ ИЗМЕРЕНО — {_sdoc.get('reason')}")
            else:
                _stally = observed(_sdoc, "tally", kind=dict) or {}
                _sfloor = observed(_sdoc, "tact_floor_hours", kind=(int, float))
                print(f"s49_tally_tact: ТАЛЛИ §49 — выполнено "
                      f"{observed_number(_stally, 'satisfied')} · не выполнено "
                      f"{observed_number(_stally, 'not_satisfied')} · не измерено "
                      f"{observed_number(_stally, 'unmeasured')} из "
                      f"{_sdoc.get('population')}; такт-пол "
                      f"{'НЕ ИЗМЕРЕН' if _sfloor is None else f'{float(_sfloor):g}ч'}, "
                      f"вердикт {_sdoc.get('verdict')}")
        else:
            print(f"s49_tally_tact: внутри такта, НЕ мерили — "
                  f"{_sttr.get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "s49_tally_tact", e)
    # Заказ G94 (ADR-549): выдерживает ли производитель ОБЪЯВЛЕННЫЙ срок годности.
    # Предмет — АРТЕФАКТ, а не агент: обещание дано файлу, а служить ему могут
    # несколько производителей, и поагентный вердикт печатал бы находку там, где
    # срок выдерживается. Такта у ступени нет: замер есть разбор логов.
    try:
        # Приёмник зова назван ПО МОДУЛЮ, а не псевдонимом: сторож
        # `test_census_stage_root_contract` выводит население ступени из ИМЕНИ
        # приёмника и затем импортирует его как модуль пакета. Псевдоним
        # (`_atc`, `_stt`) ему не импортируется, и сторож краснеет —
        # предсуществующий красный с #758/#760, карточка заведена. Своя ступень
        # этот класс не пополняет.
        #
        # Имя приёмника в КОММЕНТАРИИ тоже становится населением: сторож читает
        # текст, а не дерево разбора, поэтому форму зова здесь дословно НЕ
        # приводим — первая редакция этого комментария завела ступень «X».
        from spa_core.monitoring import slo_keepability
        _slokr = slo_keepability.run(root=args.root)
        _slokdoc = _slokr["doc"]
        if str(_slokdoc.get("status")) != "OK":
            print(f"slo_keepability: НЕ ИЗМЕРЕНО — {_slokdoc.get('reason')}")
        else:
            _sltally = observed(_slokdoc, "tally", kind=dict) or {}
            print(f"slo_keepability: объявленный срок годности — выдерживаем "
                  f"{observed_number(_sltally, slo_keepability.KEEPABLE)} · НЕ выдерживаем "
                  f"{observed_number(_sltally, slo_keepability.UNKEEPABLE)} · такт не наблюдён "
                  f"{observed_number(_sltally, slo_keepability.UNMEASURED)} из "
                  f"{_slokdoc.get('population')}; вердикт {_slokdoc.get('verdict')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "slo_keepability", e)
    # Заказ G94 п. 3 (ADR-550): сколько привязок конституции держится ПРОЗОЙ и
    # у скольких из них есть ВТОРОЙ читатель. Замер стои́т ПЕРЕД решением
    # объявлять поле — «объявить механически» уже стоило нам G86 п. 4.
    try:
        # Приёмник зова назван ПО МОДУЛЮ, а не псевдонимом: сторож
        # `test_census_stage_root_contract` выводит население ступени из ИМЕНИ
        # приёмника и затем импортирует его как модуль пакета (предсуществующий
        # красный с #758/#760, карточка заведена). Своя ступень класс не
        # пополняет, и форму зова в комментарии дословно НЕ приводим — сторож
        # читает ТЕКСТ, и пояснение рядом с ним есть часть его входа (#761).
        from spa_core.monitoring import prose_binding_census
        _pbcr = prose_binding_census.run(root=args.root)
        _pbcdoc = _pbcr["doc"]
        if str(_pbcdoc.get("status")) != "OK":
            print(f"prose_binding_census: НЕ ИЗМЕРЕНО — {_pbcdoc.get('reason')}")
        else:
            _pbcplaces = observed(_pbcdoc, prose_binding_census.PLACES_KEY, kind=dict) or {}
            print(f"prose_binding_census: привязок конституции "
                  f"{_pbcdoc.get('population')} — держится прозой "
                  f"{_pbcdoc.get('on_prose')} · поле обходится "
                  f"{observed_number(_pbcplaces, prose_binding_census.FIELD_BYPASSED)} · "
                  f"родов без единого читателя прозы "
                  f"{len(_pbcdoc.get('kinds_without_a_prose_parser') or [])}; "
                  f"вердикт {_pbcdoc.get('verdict')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "prose_binding_census", e)
    # Применённость мутационной подмены (G96 п. 2, ADR-508): батарея, считающая
    # подмену применённой без вопроса о якоре, лжёт о покрытии — и лжёт в
    # СТРОГУЮ сторону («тесты слабее, чем они есть»), поэтому вердикт её никто
    # не оспаривает. Приёмник зова назван ПО МОДУЛЮ, а не псевдонимом.
    try:
        from spa_core.monitoring import mutation_application_census
        _macr = mutation_application_census.run(root=args.root)
        _macdoc = _macr["doc"]
        if str(_macdoc.get("status")) != "OK":
            print(f"mutation_application_census: НЕ ИЗМЕРЕНО — {_macdoc.get('reason')}")
        else:
            _macb = observed(_macdoc, "counts_batteries", kind=dict) or {}
            _maca = observed(_macb, "anchor", kind=dict) or {}
            print(f"mutation_application_census: подмен {_macdoc.get('sites')} — "
                  f"из них батарей {sum(_maca.values())}, применённость НЕ спрошена "
                  f"у {observed_number(_maca, mutation_application_census.ANCHOR_UNCHECKED)}"
                  f" · слепа к кратности у "
                  f"{observed_number(_maca, mutation_application_census.ANCHOR_PRESENCE)};"
                  f" НАХОДОК {len(_macdoc.get('findings') or [])}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "mutation_application_census", e)
    # Перепись входов, собранных ВЫЗОВОМ (G45 п. 1, ADR-421): что сторож ДЕЛАЕТ,
    # когда его вход пуст. Дыра названа самим ADR-420: перечень, собранный
    # вызовом, в то население не входил ПО ПОСТРОЕНИЮ, а пустота у него
    # достижима без единой правки исходника — свежий worktree без `data/` есть
    # штатное, протоколом предписанное дерево.
    try:
        from spa_core.monitoring import call_sourced_input_census
        _csi = call_sourced_input_census.run(root=args.root)
        if _csi.get("measured"):
            _cf = observed_number(_csi["doc"], "findings")
            print(f"call_sourced_input_census: {_csi['doc'].get('status')} — "
                  f"входов-перечней из вызова с зелёной дверью, "
                  f"{'НЕ ИЗМЕРЕНО' if _cf is None else int(_cf)}")
        else:
            print(f"call_sourced_input_census: НЕ ИЗМЕРЕНО — "
                  f"{_csi['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "call_sourced_input_census", e)

    # Ступень G49 п. 2 (ADR-427): у кого из зовущих ОБЩЕЙ ПРОВОДКИ прогонов
    # вход обрезается молча. Проводка возвращает ХВОСТ вывода, а перечень
    # (имена упавших тестов, строки `git worktree list`) живёт по всему выводу
    # — обрезание уносит его голову и не говорит об этом ничего. Замер #643
    # нашёл ОДИН такой случай руками; ступень задаёт тот же вопрос всему
    # населению зовущих каждый прогон.
    try:
        from spa_core.monitoring import truncated_input_census
        _tic = truncated_input_census.run(root=args.root)
        if _tic.get("measured"):
            _tc = observed(_tic["doc"], "counts", kind=dict)
            _ts = (None if _tc is None
                   else observed_number(_tc, truncated_input_census.CLASS_SILENT))
            print(f"truncated_input_census: {_tic['doc'].get('status')} — "
                  f"зовущих, чей перечень режется молча, "
                  f"{'НЕ ИЗМЕРЕНО' if _ts is None else int(_ts)}")
        else:
            print(f"truncated_input_census: НЕ ИЗМЕРЕНО — "
                  f"{_tic['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "truncated_input_census", e)

    # Ступень G50 п. 2 (ADR-428): кто режет вывод подпроцесса СВОЕЙ РУКОЙ и
    # читает ли при этом перечень. У общей проводки сторона разреза одна и
    # задана её кодом; у своей руки она ПОЛЕ вызова — `[:N]` уносит хвост со
    # сводкой там, где `[-N:]` унесло бы голову с перечнем. Предполагать
    # сторону по соседу значило бы завести вторую копию правила с неверной
    # посылкой.
    try:
        from spa_core.monitoring import hand_truncation_census
        _htc = hand_truncation_census.run(root=args.root)
        if _htc.get("measured"):
            _hc = observed(_htc["doc"], "counts", kind=dict)
            _hs = (None if _hc is None
                   else observed_number(_hc, hand_truncation_census.CLASS_SILENT))
            print(f"hand_truncation_census: {_htc['doc'].get('status')} — "
                  f"зовущих, чей ПЕРЕЧЕНЬ режется своей рукой молча, "
                  f"{'НЕ ИЗМЕРЕНО' if _hs is None else int(_hs)}")
        else:
            print(f"hand_truncation_census: НЕ ИЗМЕРЕНО — "
                  f"{_htc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "hand_truncation_census", e)

    # Ступень G46 п. 2 (ADR-424): сколько невычисленных путей соседней переписи
    # разрешимо УЖЕСТОЧЕНИЕМ вычислителя. Без неё её собственный ответ —
    # нижняя граница, о размере которой не сказано ничего.
    try:
        from spa_core.monitoring import unresolved_path_census
        _upc = unresolved_path_census.run(root=args.root)
        if _upc.get("measured"):
            _ur = observed_number(_upc["doc"], "resolved_by_tightening")
            print(f"unresolved_path_census: {_upc['doc'].get('status')} — "
                  f"невычисленных путей разрешимо ужесточением "
                  f"{'НЕ ИЗМЕРЕНО' if _ur is None else int(_ur)}")
        else:
            print(f"unresolved_path_census: НЕ ИЗМЕРЕНО — "
                  f"{_upc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "unresolved_path_census", e)

    # Ступень G98 п. 1 (ADR-565): встречался ли в ЖИВОМ артефакте недостижимого
    # раскола класс вне перечня, который писатель заводит сегодня. Стои́т ПОСЛЕ
    # ступени `rule_second_copy_census` намеренно: население и его ЧИСЛО берутся
    # у соседа, и прочитав прошлый такт, ступень сверяла бы себя с позавчерашним
    # числом. Заголовочное число — «сколько раз прибор упал бы сегодня»; второе,
    # НЕ складываемое с ним, — значения, которые едут в записи мимо счётчика.
    try:
        from spa_core.monitoring import unknown_class_in_the_artifact
        _ucia = unknown_class_in_the_artifact.run(root=args.root)
        if _ucia.get("measured"):
            _raise = observed_number(_ucia["doc"], "would_raise_today")
            _rides = observed_number(_ucia["doc"], "rides_in_the_record_only")
            print(f"unknown_class_in_the_artifact: "
                  f"{_ucia['doc'].get('status')} — писатель впустил незнакомый "
                  f"класс "
                  f"{'НЕ ИЗМЕРЕНО' if _raise is None else int(_raise)} раз(а); "
                  f"едет в записи мимо счётчика "
                  f"{'НЕ ИЗМЕРЕНО' if _rides is None else int(_rides)}")
        else:
            print(f"unknown_class_in_the_artifact: НЕ ИЗМЕРЕНО — "
                  f"{_ucia['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "unknown_class_in_the_artifact", e)

    # Ступень G98 п. 2 (ADR-566): у ОСТАЛЬНЫХ открытых счётчиков две оси —
    # читателя и писателя — лежали рядом и не смотрели друг на друга. Стои́т
    # ПОСЛЕ ступени `rule_second_copy_census`: и население, и обе краевые
    # раскладки сверяются с ОПУБЛИКОВАННЫМИ числами соседа. Заголовочное
    # число — раскол доказан, писатель молчит, достижимость не спрашивал
    # никто; рядом, и НЕ складываясь с ним, — три разных незнания.
    try:
        from spa_core.monitoring import reachability_of_the_rest
        _ror = reachability_of_the_rest.run(root=args.root)
        if _ror.get("measured"):
            _cross = observed(_ror["doc"], "cross", kind=dict) or {}
            _harm = observed_number(
                _cross, reachability_of_the_rest.CELL_HARM_REACHABLE)
            _rest = observed_number(_ror["doc"], "the_rest")
            print(f"reachability_of_the_rest: "
                  f"{_ror['doc'].get('status')} — у остатка "
                  f"{'НЕ ИЗМЕРЕНО' if _rest is None else int(_rest)} "
                  f"раскол доказан и писатель молчит "
                  f"{'НЕ ИЗМЕРЕНО' if _harm is None else int(_harm)} раз(а)")
        else:
            print(f"reachability_of_the_rest: НЕ ИЗМЕРЕНО — "
                  f"{_ror['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "reachability_of_the_rest", e)

    # Ступень G103 п. 1 (ADR-594): реестр `SITE_NUMBER_SOURCES` есть
    # УТВЕРЖДЕНИЕ о живой разметке, и верность его не спрашивалась у сайта ни
    # одним числом. Операнд — отчёт кустодиана (`com.spa.site_freshness`), а не
    # продукт моста: ступень в сеть не ходит, поэтому порядка относительно
    # соседних ступеней у неё нет, а возраст отчёта есть ПОЛЕ её ответа.
    # Заголовочное число — опровергнутых объявлений; рядом, и НЕ складываясь с
    # ним, — их разделение на молчаливые (сосед по label отвечает, кустодиан
    # зелёный) и громкие (кустодиан краснеет сам).
    try:
        from spa_core.monitoring import declared_source_live_parity
        _dslp = declared_source_live_parity.run(root=args.root)
        if _dslp.get("measured"):
            _ref = observed_number(_dslp["doc"], "refuted")
            _sil = observed_number(_dslp["doc"], "refuted_silently")
            print(f"declared_source_live_parity: "
                  f"{_dslp['doc'].get('status')} — живая страница опровергает "
                  f"{'НЕ ИЗМЕРЕНО' if _ref is None else int(_ref)} "
                  f"объявленн(ый/ых) источник(ов), из них МОЛЧА "
                  f"{'НЕ ИЗМЕРЕНО' if _sil is None else int(_sil)}")
        else:
            print(f"declared_source_live_parity: НЕ ИЗМЕРЕНО — "
                  f"{_dslp['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "declared_source_live_parity", e)

    # Ступень G103 п. 2 (ADR-620): КЛАСС ШИРЕ КУСТОДИАНА. Сосед выше спросил
    # верность ОДНОГО реестра у живой страницы; эта ступень спрашивает ту же
    # претензию у ВСЕХ читателей дерева, которые ищут конкретную личность
    # элемента в разметке, которую пишет кто-то другой. Оракул — дерево, не
    # сеть, поэтому порядка относительно соседних ступеней у неё нет.
    # Заголовочное число — претензий, не подтверждённых ничем, кроме себя;
    # рядом, и НЕ складываясь с ним, — остаток «происхождение стога не
    # свёрнуто», который в класс не зачтён.
    try:
        from spa_core.monitoring import foreign_markup_reader_census
        _fmrc = foreign_markup_reader_census.run(root=args.root)
        if _fmrc.get("measured"):
            _uns = observed_number(_fmrc["doc"], "unsupported")
            _rem = observed_number(_fmrc["doc"], "origin_unresolved")
            print(f"foreign_markup_reader_census: "
                  f"{_fmrc['doc'].get('status')} — претензий к чужой "
                  f"разметке, не подтверждённых ничем кроме себя, "
                  f"{'НЕ ИЗМЕРЕНО' if _uns is None else int(_uns)}; "
                  f"остаток «происхождение стога не свёрнуто» "
                  f"{'НЕ ИЗМЕРЕНО' if _rem is None else int(_rem)}")
        else:
            print(f"foreign_markup_reader_census: НЕ ИЗМЕРЕНО — "
                  f"{_fmrc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "foreign_markup_reader_census", e)

    # Ступень §49 `Anti-churn` приказа CIO (ADR-480): прыгала ли книга между
    # одними и теми же opportunities. Читает журнал ходов и ничего не чинит;
    # заголовочное число — возвраты, которые гистерезису НЕЧЕМ увидеть, потому
    # что он сверяет ноги с ходом непосредственно предыдущим.
    try:
        from spa_core.monitoring import book_oscillation_census
        _boc = book_oscillation_census.run(root=args.root)
        if _boc.get("measured"):
            _bi = observed_number(_boc["doc"], "invisible_by_construction")
            print(f"book_oscillation_census: {_boc['doc'].get('status')} — "
                  f"возвратов книги, невидимых гистерезису по построению, "
                  f"{'НЕ ИЗМЕРЕНО' if _bi is None else int(_bi)}")
        else:
            print(f"book_oscillation_census: НЕ ИЗМЕРЕНО — "
                  f"{_boc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "book_oscillation_census", e)

    # Ступень §49 `Economics` приказа CIO (ADR-484): побеждает ли решение ничего
    # не делать ту раскладку, которую документ советника зовёт оптимальной.
    # Читает журналы вердиктов и ничего не чинит; заголовочное число — сколько
    # раз опубликованный оптимум проиграл KEEP по СВОЕЙ же мерке, до издержек.
    try:
        from spa_core.monitoring import keep_dominance_census
        _kdc = keep_dominance_census.run(root=args.root)
        if _kdc.get("measured"):
            _kd = observed_number(_kdc["doc"], "dominated_by_keep")
            print(f"keep_dominance_census: {_kdc['doc'].get('status')} — "
                  f"опубликованный оптимум проиграл DO NOTHING "
                  f"{'НЕ ИЗМЕРЕНО' if _kd is None else int(_kd)} раз")
        else:
            print(f"keep_dominance_census: НЕ ИЗМЕРЕНО — "
                  f"{_kdc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "keep_dominance_census", e)

    # Ступень §49 `Risk` приказа CIO (ADR-486): нарушала ли потолки книга, которая
    # РЕАЛЬНО стояла. Читает журнал ходов и историю файла политики, ничего не
    # чинит; заголовочное число — состояния, нарушившие потолок по ТЕМ копиям
    # ярлыка тира, которые читает сам risk_gate.
    try:
        from spa_core.monitoring import policy_binding_census
        _pbc = policy_binding_census.run(root=args.root)
        if _pbc.get("measured"):
            _gate = (_pbc["doc"].get("gate_binding") or {})
            _gv = observed_number(_gate, "violating_count")
            print(f"policy_binding_census: {_pbc['doc'].get('status')} — "
                  f"исполненных состояний, нарушивших потолок по копиям гейта, "
                  f"{'НЕ ИЗМЕРЕНО' if _gv is None else int(_gv)}")
        else:
            print(f"policy_binding_census: НЕ ИЗМЕРЕНО — "
                  f"{_pbc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "policy_binding_census", e)

    # Ступень §49 `Persistence` приказа CIO (ADR-485): сколько дней жило
    # преимущество, которым ход был оправдан. Читает журнал ходов и наблюдённый
    # ряд ставок, ничего не чинит; заголовочное число — ходы, чьё преимущество
    # умерло раньше горизонта окупаемости владельца.
    try:
        from spa_core.monitoring import gain_persistence_census
        _gpc = gain_persistence_census.run(root=args.root)
        if _gpc.get("measured"):
            _gd = observed_number(_gpc["doc"], "advantage_died_total")
            print(f"gain_persistence_census: {_gpc['doc'].get('status')} — ходов, "
                  f"чьё преимущество умерло раньше горизонта окупаемости, "
                  f"{'НЕ ИЗМЕРЕНО' if _gd is None else int(_gd)}")
        else:
            print(f"gain_persistence_census: НЕ ИЗМЕРЕНО — "
                  f"{_gpc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "gain_persistence_census", e)

    # Ступень §49 `Pre-trade safety` приказа CIO (ADR-487): было ли у ходa второе
    # наблюдение входов между предложением и исполнением. Читает цепочку аудита,
    # ничего не чинит; заголовочное число — исполнения БЕЗ второго наблюдения.
    try:
        from spa_core.monitoring import pre_trade_recheck_census
        _ptr = pre_trade_recheck_census.run(root=args.root)
        if _ptr.get("measured"):
            _nr = observed_number(_ptr["doc"], "no_recheck")
            print(f"pre_trade_recheck_census: {_ptr['doc'].get('status')} — "
                  f"исполнений без второго наблюдения входов "
                  f"{'НЕ ИЗМЕРЕНО' if _nr is None else int(_nr)}")
        else:
            print(f"pre_trade_recheck_census: НЕ ИЗМЕРЕНО — "
                  f"{_ptr['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "pre_trade_recheck_census", e)

    # Ступень §49 `Owner visibility` приказа CIO (ADR-488): доходят ли до
    # владельца названные им числа. Читает журнал решений и выдачу слоя
    # отображения, ничего не чинит; заголовочное число — предметы, которые
    # ЗАПИСАНЫ, но до владельца не доставлены.
    try:
        from spa_core.monitoring import owner_visibility_census
        _ovc = owner_visibility_census.run(root=args.root)
        if _ovc.get("measured"):
            _lost = observed_number(_ovc["doc"], "recorded_but_not_delivered")
            print(f"owner_visibility_census: {_ovc['doc'].get('status')} — "
                  f"записано, но до владельца не доставлено "
                  f"{'НЕ ИЗМЕРЕНО' if _lost is None else int(_lost)}")
        else:
            print(f"owner_visibility_census: НЕ ИЗМЕРЕНО — "
                  f"{_ovc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "owner_visibility_census", e)

    # Ступень заказа G38 п. 3 (ADR-498): цена класса «две сессии на одном
    # предмете». Читает добровольный журнал объявлений и дерево базового ref,
    # ничего не чинит; заголовочное число — координаты, сделанные двумя и
    # более сессиями и не доехавшие ни до одной.
    try:
        from spa_core.monitoring import duplicate_subject_census
        _dsc = duplicate_subject_census.run(root=args.root)
        if _dsc.get("measured"):
            # `... or {}` здесь был бы ровно тем, что запрещает инв. #17:
            # «раздела нет» склеилось бы с «потерь ноль».
            _price = observed(_dsc["doc"], "price", kind=dict)
            _lost = None if _price is None else observed_number(_price, "lost_coordinates")
            print(f"duplicate_subject_census: {_dsc['doc'].get('status')} — "
                  f"координат сделано дважды и потеряно "
                  f"{'НЕ ИЗМЕРЕНО' if _lost is None else int(_lost)}")
        else:
            print(f"duplicate_subject_census: НЕ ИЗМЕРЕНО — "
                  f"{_dsc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "duplicate_subject_census", e)

    # Ступень заказа G109 п. 2 (ADR-534, измерена ADR-678): виден ли ДВЕРИ шага
    # 0a/0b предмет захвата — НОМЕР ЗАКАЗА, а не путь карточки. Предмет у этой
    # ступени ДРУГОЙ, чем у соседа выше: тот меряет цену в КООРДИНАТАХ и
    # намеренно не считает сессии на карточке (стоячий приказ по инв. #14
    # остаётся `in-progress` вечно), а внутри одной карточки работа нарезана на
    # ЗАКАЗЫ, и предмет работы есть номер заказа. Прибор только ЧИТАЕТ;
    # заголовочное число — видит ли дверь предмет, измеренное ИСХОДОМ.
    try:
        from spa_core.monitoring import order_subject_census
        _osc = order_subject_census.run(root=args.root)
        if _osc.get("measured"):
            # `... or {}` здесь был бы ровно тем, что запрещает инв. #17:
            # «раздела нет» склеилось бы с «дверь предмет видит».
            _door = observed(_osc["doc"], "door", kind=dict)
            _sees = None if _door is None else _door.get("door_sees_order")
            print(f"order_subject_census: {_osc['doc'].get('status')} — дверь "
                  f"предмет (номер заказа) "
                  f"{'НЕ ИЗМЕРЕНО' if _sees is None else ('ВИДИТ' if _sees else 'НЕ ВИДИТ')}"
                  f"; пересечений {_osc['doc'].get('intersections_total')}")
        else:
            print(f"order_subject_census: НЕ ИЗМЕРЕНО — "
                  f"{_osc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "order_subject_census", e)

    # Ступень заказа G109 п. 1 (ADR-534, измерена ADR-679): переживает ли ЗАПИСЬ
    # прогона отмену. Предмет ДРУГОЙ, чем у соседа `failed_name_survival_census`
    # (ADR-528): тот спрашивает про путь ОТКАЗА и отвечает зелёным верно, а
    # отмена есть ГЛАВНЫЙ путь прогона, и среди его исходов её нет вовсе.
    # Прибор только ЧИТАЕТ; заголовочное число — доля уцелевшей записи на пути
    # отмены. Сеть есть ВХОД: её отсутствие — третий исход с названной причиной.
    try:
        from spa_core.monitoring import record_survival_census
        _rsc = record_survival_census.run(root=args.root)
        if _rsc.get("measured"):
            # `... or {}` здесь склеило бы «раздела нет» с «уцелело ноль» (инв. #17).
            _surv = observed(_rsc["doc"], "survival", kind=dict)
            _cancel = None if _surv is None else observed(_surv, "cancellation_path",
                                                          kind=dict)
            _share = None if _cancel is None else _cancel.get("share_pct")
            print(f"record_survival_census: {_rsc['doc'].get('status')} — запись "
                  f"переживает ОТМЕНУ у "
                  f"{'НЕ ИЗМЕРЕНО' if _share is None else f'{_share} %'} прогонов")
        else:
            print(f"record_survival_census: НЕ ИЗМЕРЕНО — "
                  f"{_rsc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "record_survival_census", e)

    # Ступень заказа G110 п. 3 (ADR-682): согласны ли ДВЕРИ ЧАСОВ одного поля
    # между собой. Прибор только ЧИТАЕТ: двери живого дерева грузятся и зовутся
    # на закрытом словаре форм, ни одна строка сторожа не правится. Заголовочное
    # число — сколько дверей ШИРЕ или УЖЕ той, что гейтит взятие карточки.
    try:
        from spa_core.monitoring import announce_clock_door_census
        _acdc = announce_clock_door_census.run(root=args.root)
        if _acdc.get("measured"):
            # `... or {}` здесь склеило бы «раздела нет» с «расхождений ноль» (инв. #17).
            _ans = observed(_acdc["doc"], "answer", kind=dict)
            _dis = None if _ans is None else _ans.get("doors_disagreeing")
            print(f"announce_clock_door_census: {_acdc['doc'].get('status')} — "
                  f"дверей ШИРЕ/УЖЕ эталона "
                  f"{'НЕ ИЗМЕРЕНО' if _dis is None else _dis}")
        else:
            print(f"announce_clock_door_census: НЕ ИЗМЕРЕНО — "
                  f"{_acdc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "announce_clock_door_census", e)

    # Ступень заказа G110 п. 1 (ADR-684): во что обходится КАНАЛ квитанции у её
    # ЧИТАТЕЛЯ. Прибор только ЧИТАЕТ и поднимает одноразовые сцены в `mkdtemp`;
    # заголовочное число — вердикт по двум кандидатам канала (третье состояние
    # записи журнала против второго файла).
    try:
        from spa_core.monitoring import receipt_channel_cost
        _rcc = receipt_channel_cost.run(root=args.root)
        if _rcc.get("measured"):
            # `... or {}` здесь склеило бы «раздела нет» с «вреда нет» (инв. #17).
            _ans = observed(_rcc["doc"], "answer", kind=dict)
            _out = None if _ans is None else _ans.get("journal_state_door_outcome")
            print(f"receipt_channel_cost: {_rcc['doc'].get('status')} — третье "
                  f"состояние записи у двери сторожа "
                  f"{'НЕ ИЗМЕРЕНО' if _out is None else _out}")
        else:
            print(f"receipt_channel_cost: НЕ ИЗМЕРЕНО — "
                  f"{_rcc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "receipt_channel_cost", e)

    # Ступень заказа G111 п. 1 (ADR-685): чего стоит ветвь «освобождение по
    # КАРТОЧКЕ» — сколько ЖИВЫХ захватов снял бы чужой `done` задним числом.
    # Прибор только ЧИТАЕТ: перепроигрывает журнал объявлений и поднимает
    # одноразовую сцену двери в `mkdtemp`; заголовочное число — засвидетельствованный
    # вред ветви против её пользы, измеренной соседом ADR-536.
    try:
        from spa_core.monitoring import foreign_done_cost
        _fdc = foreign_done_cost.run(root=args.root)
        if _fdc.get("measured"):
            # `... or {}` здесь склеило бы «раздела нет» с «вреда нет» (инв. #17).
            _harm = observed(_fdc["doc"], "harm", kind=dict)
            _witnessed = None if _harm is None else _harm.get("witnessed_harm")
            print(f"foreign_done_cost: {_fdc['doc'].get('status')} — чужой `done` снял "
                  f"бы живых захватов "
                  f"{'НЕ ИЗМЕРЕНО' if _witnessed is None else _witnessed}")
        else:
            print(f"foreign_done_cost: НЕ ИЗМЕРЕНО — "
                  f"{_fdc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — перепись не смеет валить мост
        census_skipped(_skipped, "foreign_done_cost", e)

    # Ступень заказа G88 п. 1 (ADR-535): у кого квитанция read-only проверки
    # захвата окажется ЧИТАТЕЛЕМ. Прибор только ЧИТАЕТ и поднимает одноразовые
    # сцены в `mkdtemp`; заголовочное число — вердикт проводки квитанции.
    try:
        from spa_core.monitoring import claim_guard_receipt_readers
        _cgr = claim_guard_receipt_readers.run(root=args.root)
        if _cgr.get("measured"):
            # `... or {}` здесь склеило бы «раздела нет» с «читателей ноль» (инв. #17).
            _rd = observed(_cgr["doc"], "verdict_readers", kind=dict)
            _names = None if _rd is None else observed(_rd, "readers", kind=list)
            print(f"claim_guard_receipt_readers: {_cgr['doc'].get('status')} — "
                  f"читателей вердикта "
                  f"{'НЕ ИЗМЕРЕНО' if _names is None else len(_names)}")
        else:
            print(f"claim_guard_receipt_readers: НЕ ИЗМЕРЕНО — "
                  f"{_cgr['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "claim_guard_receipt_readers", e)

    # Ступень заказа G88 п. 2 (ADR-536): кто и когда ЗАКРЫВАЕТ захват, и чего стоил
    # бы срок годности. Заголовочное число — захваты, стоящие открытыми при карточке,
    # про которую уже сказано «закрыта»: это и есть находка, а не размер населения.
    try:
        from spa_core.monitoring import claim_release_census
        _crc = claim_release_census.run(root=args.root)
        if _crc.get("measured"):
            # `... or {}` здесь склеило бы «раздела нет» с «таких захватов ноль» (инв. #17).
            _oc = observed(_crc["doc"], "open_claims", kind=dict)
            _stuck = None if _oc is None else observed(
                _oc, "card_declared_done_by_another_identity", kind=int)
            print(f"claim_release_census: {_crc['doc'].get('status')} — захватов, "
                  f"открытых при закрытой карточке: "
                  f"{'НЕ ИЗМЕРЕНО' if _stuck is None else _stuck}")
        else:
            print(f"claim_release_census: НЕ ИЗМЕРЕНО — {_crc['doc'].get('reason')}")
    except Exception as e:  # noqa: BLE001 — прибор не смеет валить мост
        census_skipped(_skipped, "claim_release_census", e)
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
                             "skipped": _skipped},
                   run_started_at=run_started_at)
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
