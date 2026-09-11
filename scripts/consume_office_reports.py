#!/usr/bin/env python3
"""consume_office_reports.py — обязательный шаг цикла оркестратора (ADR-066, Фаза 2).

Читает В КОНТЕКСТ сессии всё, что конституция (architecture/manifest.json)
объявила потребляемым оркестратором: продукты инвест-офиса, отчёт сторожа
соответствия, системный брифинг. Для каждого УСПЕШНО прочитанного артефакта
пишет квитанцию потребления (consumer = "orchestrator_protocol").

Честность:
  - отсутствующий/нечитаемый файл печатается как «❌ НЕ ПРОЧИТАН» и квитанцию
    НЕ получает;
  - отсутствующее поле печатается как «НЕ ИЗМЕРЕНО», НИКОГДА как `None`:
    `None` в выводе читается глазом как «пусто, всё в порядке» — это ровно
    fail-OPEN, сторож молчит утвердительно;
  - у КАЖДОГО артефакта печатается возраст: рекомендация 19-часовой давности
    и рекомендация свежая — разные вещи, и решает это читатель, а не выжимка;
  - скрипт информационный: пока офис ИЗМЕРЕН, exit 0 — красные строки в выводе
    это сигналы ОРКЕСТРАТОРУ действовать (карточки), а не коды выхода;
  - исключение — exit 3 «офис НЕ ИЗМЕРЕН»: в этом дереве нет НИ ОДНОГО
    артефакта офиса (типично — запуск из git-worktree, где они в `.gitignore`).
    Это не состояние офиса, а невозможность его измерить, и печатается ОДНОЙ
    строкой: прежний вывод давал двадцать «❌ НЕ ПРОЧИТАН» под подписью
    «действовать (карточки)» и звал завести двадцать карточек о мёртвом
    инвест-офисе, который жив (цикл #207). Читать чужие артефакты явно —
    `--data-dir <прод>/data`, и вывод НАЗЫВАЕТ, чьи они;
  - ведом манифестом: новый consumer_required-продукт с потребителем
    "orchestrator_protocol" автоматически попадает в этот шаг без правки кода.

LLM_FORBIDDEN (детерминированный экстрактор; выводами занимается сессия).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, REPO_ROOT)

CONSUMER = "orchestrator_protocol"

# Порог, с которого возраст артефакта проговаривается вслух. Это МЕТКА ПЕЧАТИ,
# а не гейт: политика свежести офиса живёт в `investment_os/health.py` и здесь
# не дублируется. Смысл метки — 19.4 ч и 0.2 ч не должны выглядеть одинаково.
STALE_HOURS = 24.0

_UNMEASURED = "НЕ ИЗМЕРЕНО"

# Исходы §42 (`cio_kill_switch_controls`). Имена держатся здесь строками, а не
# импортом из модуля-производителя: шаг 0-офис читает ОТЧЁТ, а не код, и должен
# печатать его и тогда, когда производитель из этого дерева не импортируется.
_PRESENT, _CONFLATED, _ABSENT = "PRESENT", "CONFLATED", "ABSENT"
_UNCHECKED_KEY = "UNCHECKED"
# Исходы §41 (`cio_auto_execution_limits`). `_ABSENT` и `_UNCHECKED_KEY` общие с
# §42 намеренно: одно и то же слово в двух отчётах обязано значить одно и то же.
_BINDING, _LITERAL, _DECLARED_INERT = "BINDING", "LITERAL", "DECLARED_INERT"

# ЧТО каждая именованная ветка читает у производителя — объявлено ДАННЫМИ, а не
# спрятано в теле ветки, и сверяется с настоящим артефактом на каждом прогоне.
#
# Почему так, а не «проверить ветки глазами». Класс «ветка читает поля, которых
# производитель не пишет» рецидивировал в ЭТОМ файле трижды подряд:
#   * `findings_bridge` — читала файл `findings_bridge.json` и `counts.opened/
#     pending`, которых нет ни у одного производителя (починено циклом #170);
#   * `house_view_gap` — читала `overall` / `counts.critical` / `findings`, а
#     производитель пишет `gaps` / `counts.warn|info|unchecked`, и обязательный
#     шаг печатал «вердикт: None» при ДВУХ реальных расхождениях (#176);
#   * `_health` — читала `stale` / `failing` / `unknown` на верхнем уровне, где
#     их нет: протухший аналитик не был бы назван вовсе (найдено тем же замером).
# Каждый раз это находили вручную и по одной ветке. Объявленная схема + строка
# «СХЕМА РАЗОШЛАСЬ» переводят проверку из «посмотреть внимательно» в измерение,
# которое само краснеет на живых файлах в тот цикл, когда производитель уехал.
#
# Путь с точкой — вложенное поле (`house_view.overall_posture`): у house_view
# всё интересное лежит на втором уровне, и проверка только верхнего уровня
# пропустила бы ровно тот дрейф, ради которого она заведена.
_READ_SCHEMA: dict[str, tuple[str, ...]] = {
    "chief_investment.json": ("house_view.overall_posture", "house_view.conflicts",
                              "house_view.top_opportunities"),
    "_health.json": ("overall", "counts.total", "counts.healthy", "counts.stale",
                     "counts.missing", "counts.unknown_or_corrupt", "analysts"),
    "architecture_conformance.json": ("overall", "counts.critical", "counts.warn",
                                      "counts.aged", "counts.unchecked", "findings"),
    "house_view_gap.json": ("gaps", "unchecked", "counts.warn", "counts.info",
                            "counts.unchecked"),
    # `censuses` (#524) читает НЕ выжимка этого артефакта, а вердикт об
    # ОТСУТСТВИИ соседнего (`_absent_verdict`): состав ступени переписей — это
    # ответ на вопрос «а бегун вообще пробовал?». Объявлен здесь по общему
    # правилу — чтение, не объявленное схемой, и есть тот класс, ради которого
    # схема заведена. Сегодня он даст «отчёт СТАРОГО ОБРАЗЦА (не находка)», и
    # это правильный ответ: производитель ключ пишет, отчёт произведён раньше.
    "findings_bridge_report.json": ("created", "closed", "deferred", "waiting_hysteresis",
                                    "escalated", "sources_unread", "open_cards", "delivery",
                                    "owner_answer_delivery", "censuses"),
    "loop_retro.json": ("findings", "outcomes_completeness"),
    # ADR-240. `should_rebalance` объявлен НАМЕРЕННО рядом с `verdict` и
    # `unmeasured`: до цикла #500 файл нёс ТОЛЬКО первое поле, и `false` в нём
    # читалось как «повода нет», хотя все пять проверок отвечали из пустоты.
    "rebalance_trigger.json": ("should_rebalance", "triggered", "unmeasured",
                               "verdict", "checks", "checked_at"),
    "loop_health.json": ("open_cards", "recurrences_total", "cards_fate",
                         "latency_finding_to_card", "latency_card_to_close",
                         "note", "closure_drift"),
    "code_sync_status.json": ("timestamp", "result", "detail", "origin_main",
                             "files_changed", "retired_instructions", "retired_code"),
    "adapter_feed_divergence.json": ("overall", "counts.critical", "counts.warn",
                                     "counts.info", "counts.unchecked", "findings",
                                     "unchecked", "compared_protocols",
                                     "history.status", "history.by_key",
                                     "history.blind_snapshots", "history.window_truncated"),
    "apy_composition.json": ("overall", "counts.critical", "counts.warn",
                            "counts.unchecked", "observed_adapters", "findings",
                            "unchecked", "book_note", "history.status",
                            "history.by_adapter", "history.covered_days",
                            "history.window_truncated", "history.blind_snapshots"),
    "pool_identity_collision.json": ("overall", "counts.critical", "counts.warn",
                                    "counts.info", "counts.unchecked", "keys_compared",
                                    "collisions", "unreachable_refusals", "findings",
                                    "unchecked"),
    # §49 ТЗ CIO. `runs` объявлен НАМЕРЕННО рядом с вердиктом: «воспроизводимо»
    # на 3 прогонах и на 100 — разной силы утверждение, и отчёт, не называющий
    # число, читался бы как дословный опыт владельца, которым он не является.
    "decision_reproducibility.json": ("overall", "counts.critical", "counts.warn",
                                      "counts.info", "counts.unchecked", "runs",
                                      "subjects_measured", "measurements",
                                      "findings", "unchecked"),
    # §12/§49 ТЗ CIO. `unmeasured_capital_pct` объявлен рядом с вердиктом
    # НАМЕРЕННО: разбавление считается делением на TVL, и доля книги, стоящей на
    # литеральном знаменателе, — не деталь, а граница применимости всего отчёта.
    "marginal_apy_at_size.json": ("overall", "counts.critical", "counts.warn",
                                  "counts.info", "counts.unchecked",
                                  "unmeasured_capital_pct", "measurements",
                                  "policy_bound", "scale_ceiling", "findings",
                                  "unchecked"),
    # §49 ТЗ CIO «Costs». `substitution` объявлена рядом с вердиктом НАМЕРЕННО:
    # сам по себе вердикт «CRITICAL» не говорит, В КАКУЮ СТОРОНУ ошибается
    # стоимость, а сторона здесь и есть смысл — заряженная дороже наблюдённой
    # держит книгу неподвижной, то есть ровно та жалоба, с которой начато ТЗ.
    "rebalance_cost_evidence.json": ("overall", "counts.critical", "counts.warn",
                                     "counts.info", "counts.unchecked",
                                     "charged", "substitution", "slippage_check",
                                     "findings", "unchecked"),
    # §49 ТЗ CIO «Forecast accuracy». `population` объявлена рядом с вердиктом
    # НАМЕРЕННО: калибровка, снятая на одном полностью сверенном дне, и она же
    # на тридцати — утверждения разной силы, а вердикт «CRITICAL»/«WARN» их не
    # различает. `gate_relation` — по той же причине, что `substitution` у
    # соседа: сама величина ошибки ничего не решает, решает её отношение к
    # зазору, которым проходит гейт.
    "apy_forecast_accuracy.json": ("overall", "counts.critical", "counts.warn",
                                   "counts.info", "counts.unchecked",
                                   "population", "magnitude", "gate_relation",
                                   "sign_disagreements", "findings", "unchecked"),
    # §38 ТЗ CIO «Historical replay». `population` объявлена рядом с вердиктом по
    # той же причине, что у соседа: прогон, снятый на семи общих днях, и он же на
    # тридцати — утверждения разной силы. `columns` — обе колонки стоимости:
    # вывод, живущий только на заряженном газе, ADR-243 уже опроверг.
    "cio_shadow_replay.json": ("overall", "counts.critical", "counts.warn",
                               "counts.info", "counts.unchecked", "population",
                               "columns", "comparison", "false_rebalances",
                               "missed_opportunities", "findings", "unchecked"),
    # §43 ТЗ CIO «Audit trail». `owner_fields` объявлено рядом с вердиктом
    # намеренно: вопрос владельца — не «сколько находок», а «на какие из ДЕВЯТИ
    # его полей отвечают данные». `identity` — потому что вопрос поставлен через
    # ход, и join по неоднозначному имени отвечает двумя ходами сразу.
    "decision_audit_trail.json": ("overall", "counts.critical", "counts.warn",
                                  "counts.info", "counts.unchecked", "population",
                                  "owner_fields", "identity", "snapshot_id_probe",
                                  "findings", "unchecked"),
    # §47 ТЗ CIO «Failure modes». `tally` объявлен рядом с вердиктом намеренно:
    # вопрос владельца — не «сколько находок», а «на скольких из ДЕСЯТИ
    # названных им деградаций путь решения отказывает». `probes` — потому что
    # «частично» и «отказывает» в отчёте о fail-safe читаются одинаково, а
    # значат разное.
    "cio_failure_modes.json": ("overall", "counts.critical", "counts.warn",
                               "counts.info", "counts.unchecked",
                               "conditions_total", "tally", "probes",
                               "thresholds_provenance", "findings", "unchecked"),
    # §44 ТЗ CIO «Explainability». `tally` рядом с вердиктом по той же причине,
    # что у соседа: вопрос владельца — не «сколько находок», а «сколько из
    # ВОСЬМИ названных им фактов объяснение произносит». `control` в схеме
    # обязателен: без пройденного контроля счёт «произносится 2» означает не
    # неполноту объяснения, а неисправность измерителя, и читать его как
    # находку нельзя.
    "cio_explainability.json": ("overall", "counts.critical", "counts.warn",
                                "counts.info", "counts.unchecked",
                                "facts_total", "tally", "control",
                                "subject_book", "books", "explanation_layer",
                                "findings", "unchecked"),
    # §42 ТЗ CIO «Kill switch». `tally` рядом с вердиктом по той же причине,
    # что у соседей: вопрос владельца — не «сколько находок», а «сколько из ТРЁХ
    # названных им органов остановки у него есть». `control` обязателен: без
    # пройденного контроля «есть 1 из 3» означает не нехватку органов, а
    # неисправность измерителя. `separability` отдельно — это ВТОРОЕ требование
    # §42, и слить его с первым значит потерять половину вопроса.
    "cio_kill_switch_controls.json": ("overall", "counts.critical", "counts.warn",
                                      "counts.info", "counts.unchecked",
                                      "controls_total", "tally", "control",
                                      "owner_channel", "controls",
                                      "decision_layer_under_door",
                                      "separability", "findings", "unchecked"),
    # §41 ТЗ CIO «Auto-execution limits». `tally` рядом с вердиктом по той же
    # причине, что у §42: вопрос владельца — не «сколько находок», а «сколько
    # из ДВЕНАДЦАТИ названных им ограничений реально стои́т на пути решения».
    # `control` обязателен: без пройденного контроля «нет 6 из 12» означает не
    # нехватку лимитов, а неисправность измерителя. `surfaces` объявлены рядом
    # НАМЕРЕННО — ограничение может связывать на одной поверхности решения и
    # молчать на другой, и отчёт, не назвавший поверхность, отвечает верно на
    # не тот вопрос.
    "cio_auto_execution_limits.json": ("overall", "counts.critical", "counts.warn",
                                       "counts.info", "counts.unchecked",
                                       "limits_total", "tally", "control",
                                       "surfaces", "declared_policy_fields",
                                       "limits", "findings", "unchecked"),
    # Остаток ADR-250: КТО ЕЩЁ производит цель. `control` в схеме обязателен —
    # без пройденного контроля «принял нарушающую цель» означает не отсутствие
    # ограничения, а неисправность пробы. `live_books` объявлены рядом с
    # вердиктом намеренно: они отвечают на вопрос, теория это или сегодняшнее
    # состояние, и без них отчёт читается как рассуждение о коде.
    "cio_target_producers.json": ("overall", "counts.critical", "counts.warn",
                                  "counts.info", "counts.unchecked", "control",
                                  "enumeration", "producers", "live_books",
                                  "matrix", "findings", "unchecked"),
    # §45 «Architecture constraints». `control` в схеме обязателен по той же
    # причине, что у соседей: без пройденного контроля «концентрации нет»
    # означает не разделение слоёв, а слепую пробу. `llm` объявлен рядом
    # НАМЕРЕННО — достижимость двери и слепота её сторожа отвечают на РАЗНЫЕ
    # вопросы, и отчёт, назвавший только первое, читается как приговор там, где
    # владелец LLM прямо разрешает (explanation layer).
    "cio_architecture_constraints.json": ("overall", "counts.critical",
                                          "counts.warn", "counts.info",
                                          "counts.unchecked", "control",
                                          "responsibilities_declared",
                                          "layers_declared", "concentration",
                                          "llm", "modules_parsed",
                                          "findings", "unchecked"),
    # §46. `stages_declared` объявлен рядом с замером НАМЕРЕННО: без него
    # «ступеней 10/10» нечем прочитать — не видно, ЧТО именно объявлено
    # эквивалентом, и устаревшее объявление стало бы неотличимо от здорового.
    "cio_component_map.json": ("overall", "counts.critical", "counts.warn",
                               "counts.info", "counts.unchecked",
                               "positive_control", "stages_declared", "stages",
                               "stages_present", "stages_total", "edges",
                               "edges_wired", "edges_total", "orchestrators",
                               "findings"),
    # §48. `knobs` объявлен рядом со счётом НАМЕРЕННО: «ослаблено 1» нечем
    # прочитать без того, КАКОЕ поле и с какого значения — а «не менялось 11»
    # без состава неотличимо от молчания прибора.
    # §5 ТЗ CIO, последняя ступень цепи. `subject` объявлен рядом с вердиктом
    # НАМЕРЕННО: «ступень молчит» и «верифицировать нечего» — разные состояния,
    # и без предмета вторая строка читалась бы как поломка там, где её нет.
    "cio_post_trade_verification.json": ("overall", "counts.critical",
                                         "counts.warn", "counts.info",
                                         "counts.unchecked", "positive_control",
                                         "subject", "stage", "inputs", "content",
                                         "findings"),
    # Заказ #517: существует ли НЕЗАВИСИМОЕ наблюдение исхода книги. `verdict`
    # объявлен рядом со счётчиками намеренно: «независимых 0» и «кандидатов 0» —
    # РАЗНЫЕ состояния, и без списка кандидатов первое читалось бы как «в дереве
    # ничего нет», что измеренно неверно.
    "cio_outcome_independence.json": ("overall", "counts.critical", "counts.warn",
                                      "counts.info", "counts.unchecked",
                                      "positive_control", "verdict", "book",
                                      "identity", "candidates",
                                      "per_candidate_verdict", "findings"),
    # Заказ #518/#519: доходит ли подставленное число до решения о капитале.
    # `measurement.census` объявлен рядом с находками намеренно — население и
    # достижимость это РАЗНЫЕ ответы, и отчёт, назвавший только первое, отвечает
    # верно не на тот вопрос (ловушка 3 заказа).
    "cio_substitution_census.json": ("overall", "counts.critical", "counts.warn",
                                     "counts.info", "counts.unchecked",
                                     "positive_control", "measurement", "findings"),
    # Заказ G5 (ADR-271). `gate_attribution` и `lookahead_control` объявлены
    # рядом с находками намеренно: «какой гейт отказал» и «чей вход его
    # связывает» — РАЗНЫЕ ответы, и отчёт, назвавший только первый, адресует
    # владельца не к той ручке.
    "shadow_blockade_attribution.json": ("status", "named_blockers",
                                         "binding_cause", "material_days",
                                         "gate_attribution", "target_instability",
                                         "lookahead_control", "findings"),
    # Заказ #534. `determinism` и `injection_doors` объявлены рядом с находками
    # намеренно: замер маржи ничего не стои́т, если производитель недетерминирован
    # или возмущение до него не доходит, — и молчать об этих двух опорах значило бы
    # подать число как факт, не назвав, на чём оно держится.
    "target_stability.json": ("status", "determinism", "injection_doors",
                              "capital_on_noise_decided_usd", "protocols",
                              "unmeasured", "findings"),
    # Заказ #535. `by_yardstick` и `identity_census` объявлены рядом с находками
    # НАМЕРЕННО. Первый несёт ОБА ярлыка — букву заказа («разрыв в пределах
    # маржи») и ярлык, на который она заменена; отчёт, назвавший один, читался
    # бы как ответ на другой вопрос. Второй — ловушка заказа: тождество пула
    # (ADR-227) и ничья ранжирования разные предметы, и слив их в одну строку
    # закрыл бы вопрос ссылкой на чужую находку.
    "ranking_tie_census.json": ("status", "quantum_pp", "tie_break",
                                "universe_size", "pairs_examined",
                                "by_yardstick", "identity_census",
                                "adjacent_pairs", "capital_moved_by_tie_flips_usd",
                                "unmeasured", "findings"),
    # Заказ #536. `coverage_independence` и `day_axis_control` объявлены рядом
    # с находками НАМЕРЕННО. Первый — ЕДИНСТВЕННАЯ опора прибора: журнал несёт
    # 4–6 ставок в день против 14 ранжируемых, и право реконструировать день
    # держится на том, что счёт от покрытия не зависит; отчёт без него подавал
    # бы серии как измеренные, не сказав, чем они обеспечены. Второй ловит
    # прибор, повторивший снимок одного дня столько раз, сколько в журнале
    # строк. `not_measured_by_design` — то, что замер НЕ мерил (соседство и ход
    # капитала по дням): без этой строки молчание про пару читалось бы как
    # «пара не ничья».
    "ranking_tie_persistence.json": ("status", "quantum_pp",
                                     "coverage_independence", "day_axis_control",
                                     "journal_days", "journal_coverage",
                                     "census_pairs", "pairs", "counts_by_class",
                                     "analytic_vs_measured",
                                     "not_measured_by_design",
                                     "unmeasured", "findings"),
    # Заказ #539 (ADR-290). `criterion` и `readers` объявлены рядом с находками
    # НАМЕРЕННО, и каждый закрывает свой способ соврать. Первый несёт ПРИЧИНУ
    # отсечения, названную мутацией, вместе с её отрицательным контролем:
    # отчёт, показавший одну щель без причины, читался бы как «журнал сломан»,
    # тогда как писатель честно пишет книгу. Второй несёт НАПРАВЛЕНИЕ сдвига у
    # каждого потребителя — без него «вердикт изменился» неотличимо от
    # «потребитель сломается», а это ровно та подмена, на которой первая
    # редакция прибора изготовила ложную находку про четверых.
    # `not_measured_by_design` — то, что замер НЕ мерил (ставки прошлого для
    # непрофинансированных ключей): без этой строки расширенный журнал читался
    # бы как реконструкция истории, чем он не является.
    "decision_journal_coverage.json": ("status", "writer", "determinism",
                                       "ranked", "ranked_live", "gap",
                                       "never_written", "criterion", "readers",
                                       "not_measured_by_design", "findings"),
    # Заказ #540. `capability` объявлено В СХЕМЕ намеренно и рядом с `replay`:
    # без него отрицательный ответ («ни один вердикт не перевернулся») читается
    # как результат, тогда как он вакуумен, пока не показано, что переворот был
    # ДОСТИЖИМ. `live_path` и `replay` — две поверхности с противоположными
    # ответами, и обе обязаны быть на виду: одна названная вместо двух — верный
    # ответ не на тот вопрос. `prior_claim` в схеме потому, что находка прибора
    # есть ОПРОВЕРЖЕНИЕ уже доставленного утверждения, и молча пересматривать
    # чужой вердикт нельзя.
    "decision_record_verdict_sensitivity.json": ("status", "journal_rows",
                                                 "live_path", "replay",
                                                 "capability",
                                                 "rate_spread_observed",
                                                 "prior_claim", "findings"),
    # Заказ #541. `population` и `hit_rate_interval` в схеме обязательны: без
    # них строка «hit_rate = 1.0» читается как свойство МИРА, а не как число,
    # посчитанное на 43 % окна. `parity_control` — потому что при непройденном
    # паритете все остальные числа недействительны, и молчать об этом нельзя.
    "hit_rate_selection_bias.json": ("status", "journal_rows", "population",
                                     "hit_rate_as_is", "hit_rate_interval",
                                     "axis_a_horizon", "axis_b_cost",
                                     "axis_c_selection", "combined",
                                     "parity_control", "direction_is_uniform",
                                     "findings"),
    # Заказ #541. `population` и `scenarios` в схеме обязательны: без них строка
    # «G1 поднял 0 дней» читается как «G1 не нужен», тогда как честное чтение —
    # «блокируют ДРУГИЕ ноги, и вот они». `capability_control` — потому что ноль
    # без доказанной способности дать не-ноль вакуум, а не ответ.
    "g1_verdict_recoverability.json": ("status", "journal_rows", "population",
                                       "grant_sets", "scenarios",
                                       "blocking_legs", "parity_control",
                                       "capability_control",
                                       "derivation_cross_check", "findings"),
    # Заказ #543. `attribution` и `per_day` в схеме обязательны: заказ прямо
    # потребовал ответ «по дням и по причинам поимённо, а не одной долей», и
    # артефакт без этих ключей отвечал бы долей. `parity_control` — потому что
    # без сошедшегося паритета классифицированы не те ноги.
    "unevidenced_leg_causes.json": ("status", "journal_rows", "population",
                                    "attribution", "class_counts", "per_day",
                                    "scenarios", "parity_control",
                                    "derivation_cross_check", "findings"),
    # Заказ #546. `pairs` в схеме обязателен по той же причине, что `attribution`
    # у соседа: ответ «проводка или значение» без перечня пар выродится в долю.
    # `wiring_source`/`observation_source` — потому что оба ответа суть
    # утверждения О НОСИТЕЛЕ (объявленная на origin дорога · ОДНОСТОРОННИЙ журнал
    # расхождений), и артефакт без границ носителя читался бы как замер флота и
    # как «фид молчал». `none_coerced_to_empty_control` — потому что без него
    # третий исход неотличим от нуля.
    "leg_provenance_split.json": ("status", "journal_rows", "population",
                                  "class_counts", "pairs", "by_leg",
                                  "wiring_source", "observation_source",
                                  "none_coerced_to_empty_control", "findings"),
    # Заказ #549. `population` и `class_counts` обязательны по той же причине,
    # что у соседа: ответ «минута решает» без населения выродится в лозунг.
    # `movement` — потому что вердикт про вердикт стои́т на РАЗМАХЕ, и без него
    # читателю нечем проверить claim. `sensitivity` отдельно от `movement`
    # намеренно: «двинулось» и «двинулось БОЛЬШЕ МАРЖИ» — разные утверждения,
    # и склеив их мы бы объявили любое мигание решающим цель.
    "snapshot_minute_sensitivity.json": ("status", "journal_rows", "population",
                                         "class_counts", "movement",
                                         "sensitivity", "losses", "findings"),
    # Заказ #550/#551. `population` обязательно по той же причине, что у соседа:
    # ответ «запись видит один снимок» без населения выродится в лозунг. `days`
    # отдельно — потому что вердикт стои́т на ПОИМЁННОМ разборе дня (какой прогон
    # опознан, каким он был по счёту), и артефакт без него нечем перепроверить.
    # `does_not_report` в схеме обязателен намеренно: главный отказ прибора —
    # «сколько теневых целей затёрто, НЕ ИЗМЕРЕНО» — и артефакт, потерявший это
    # поле, читался бы как «затёрто ноль».
    "decision_record_run_identity.json": ("status", "journal_rows", "population",
                                          "days", "findings", "does_not_report"),
    # Заказ #552. `exposure` в схеме обязателен: ответ «что теряет hit_rate» без
    # НАСЕЛЕНИЯ знаменателя выродится в лозунг. `reconstruction_control` — потому
    # что слой движения входа стои́т на реконструкции книги, и артефакт, потерявший
    # её контроль, читался бы как измеренный. `third_outcomes` — потому что главный
    # отказ прибора («вердикты стёртых прогонов не измерены и неизмеримы») есть его
    # ГЛАВНЫЙ результат, и запись без этого поля читалась бы как «потеряно ноль».
    "day_replacement_verdict_loss.json": ("status", "journal_rows", "exposure",
                                          "reconstruction_control",
                                          "subject_distinctness", "days",
                                          "findings", "third_outcomes",
                                          "does_not_report"),
    # Заказ #554. `coverage` в схеме обязателен потому, что ПЕРВЫЙ результат
    # заказа — что носитель РЕАЛЬНО покрывает; артефакт без него выродился бы в
    # долю движения, снятую с чужого населения. `movement_outside_denominator`
    # — потому что это население ДРУГОЕ, и запись, потерявшая эту оговорку,
    # читалась бы как замер знаменателя. `kind_control` — потому что покрытие
    # без совпадения РОДА величин не даёт права на подстановку, и наоборот.
    # `substitution_trap` — потому что запрет на подстановку ряда по дням есть
    # ЗАМЕР, и артефакт без него цитировал бы ADR вместо измерения.
    # `third_outcomes` — главный результат прибора: «не измерено» на N парах;
    # запись без этого поля читалась бы как «не двигалось нигде».
    "intraday_rate_input_movement.json": ("status", "journal_rows", "carrier",
                                          "coverage",
                                          "movement_outside_denominator",
                                          "kind_control", "substitution_trap",
                                          "findings", "third_outcomes",
                                          "does_not_report"),
    # Заказ #555. `run_axis` в схеме обязателен потому, что это единственное,
    # что у трейла ЕСТЬ, и запись, потерявшая его, читалась бы как «носитель
    # ни при чём». `quantity` — потому что это ОТВЕТ на заказ: величины в
    # записи нет, и артефакт без этого поля выродился бы в долю покрытия по
    # запасной поверхности. `censoring` и `resolution` — два запрета,
    # НЕЗАВИСИМЫХ от покрытия: без них читатель решит, что дело в частоте
    # опроса и чинится вперёд. `run_axis_join` — потому что предмет следующего
    # заказа обязан быть виден, а не выведен. `third_outcomes` — главный
    # результат: «не измерено» на N парах; запись без него читалась бы как
    # «не двигалось нигде».
    "audit_trail_rate_input_coverage.json": ("status", "journal_rows", "carrier",
                                             "run_axis", "quantity", "coverage",
                                             "censoring", "resolution",
                                             "run_axis_join", "findings",
                                             "third_outcomes",
                                             "does_not_report"),
    # Заказ #556. `axis_candidates` в схеме обязателен ПЕРВЫМ по существу: на
    # нём стои́т всё остальное, и сам заказ промахнулся именно здесь — назвал ось
    # числом, а число принадлежало другому полю записи.
    # `what_the_stitch_cannot_remove` обязателен потому, что заказ потребовал
    # сказать оговорку ПРЕЖДЕ доли: запись без неё читалась бы как ответ на
    # вопрос о втором входе. `error_rate` — своя цена ошибки правила, включая
    # `out_of_sample_runs`: запас, выведенный из тех же наблюдений, которые
    # правило судит, есть свойство снимка. `transfer_to_denominator` — то, что
    # сшивка РЕАЛЬНО покупает; без него «сшивка состоялась» прочтётся как
    # «второй вход измерим».
    "run_axis_time_stitch.json": ("status", "axis_candidates",
                                  "what_the_stitch_cannot_remove",
                                  "forward_direction", "reverse_direction",
                                  "error_rate", "transfer_to_denominator",
                                  "findings", "does_not_report"),
    # Заказ #557. `independence` в схеме обязателен: без него «16 наблюдений вне
    # носителя» прочтётся как показание второго свидетеля, а свидетель, названный
    # заказом, замером оказался ТЕМ ЖЕ. `run_axis` и `comparable_axis` обязаны
    # стоять порознь: число наблюдений и число пригодных к сравнению — разные
    # величины, и заказ прямо потребовал сказать это прежде, чем называть разницу.
    # Заказ #564 (ADR-327). `stage_ratchet` в схеме ОБЯЗАТЕЛЕН: без него блок,
    # ради которого прибор и стои́т (сколько переписей ступени реально под
    # храповиком контракта), уехал бы к читателю необъявленным — ровно класс A
    # из ADR-325, и тревога «СХЕМА РАЗОШЛАСЬ» его бы не увидела. `consumers`
    # обязателен по той же причине: население по классам и есть первый результат
    # заказа, а не украшение отчёта.
    "census_consumer_census.json": ("status", "counts", "callees", "consumers",
                                    "stage_ratchet", "findings"),
    # Заказ #565. `population` и `blindness` объявлены ОБА и намеренно: население
    # — первый результат заказа, а слепота из него НЕ выводится («строит
    # регуляркой» ≠ «слеп»). Объявить только одно значило бы оставить второе вне
    # тревоги «СХЕМА РАЗОШЛАСЬ» — ровно дефект ADR-325. `other_forms` обязателен
    # тоже: прочие способы получить население считаются ПОРОЗНЬ, и их пропажа из
    # отчёта читалась бы как «их нет».
    "subject_population_census.json": ("status", "counts", "population",
                                       "blindness", "other_forms", "findings",
                                       "advisory"),
    # Заказ #567. `population` — первый результат заказа; `truncation` — ответ
    # на вторую его половину, и из населения он НЕ выводится (литерал, крывший
    # структуру до конца, обрывом не является). `haystack_kinds` объявлен
    # намеренно: им отделяется ловушка №1 («assertIn по списку ключей — не
    # дефект»), и пропажа его из отчёта читалась бы как «такого рода нет».
    "substring_structure_assertions.json": ("status", "counts", "population",
                                            "truncation", "haystack_kinds",
                                            "findings", "advisory"),
    # Заказ #568. `name_sign_vs_measure` объявлен намеренно: им МЕРЯЕТСЯ
    # названная заказом ловушка (признак-по-имени против замера), и пропажа
    # этого ключа из отчёта означала бы, что ловушка снова только пересказана.
    "haystack_origin_census.json": ("status", "counts", "split",
                                    "name_sign_vs_measure", "findings",
                                    "advisory"),
    "rate_observation_census.json": ("status", "independence", "run_axis",
                                     "comparable_axis", "mechanism",
                                     "outside_denominator", "counts",
                                     "findings", "advisory"),
    # Заказ #544. `per_pair` в схеме обязателен по той же причине, что
    # `attribution` у соседа: ответ «чем закрываема дыра» без перечня пар
    # выродится в долю. `series_provenance_exposure` — потому что наличие
    # материала и его ПРОБА суть разные величины, и артефакт, несущий только
    # первую, читался бы как «починка дешёвая».
    # Заказ #545. `orders` в схеме обязателен: заказ потребовал ОБА порядка
    # снятия стен, и артефакт с одним отвечал бы на «что блокирует сегодня».
    # `expansion_ceiling` — потому что «стена связывает» и «предложенное
    # расширение её снимет» суть РАЗНЫЕ утверждения, и артефакт, несущий только
    # первое, читался бы как приказ править писателя.
    "arming_wall_order.json": ("status", "material_days", "orders",
                               "branch_verdict", "expansion_ceiling",
                               "what_it_does_not_prove", "findings"),
    "journal_backfill_material.json": ("status", "pairs_cut_by_transcription",
                                       "material", "per_pair",
                                       "protocols_without_material",
                                       "series_provenance_exposure",
                                       "what_it_does_not_prove", "findings"),
    # ADR-309 (ответ владельца «Вариант Б»). `grade` в схеме ОБЯЗАТЕЛЕН: без
    # метки пробы артефакт читался бы как «ставки восстановлены», а условие
    # владельца ровно в том, чтобы дописанное никогда не выдавалось за живое.
    # `per_pair` обязателен по той же причине, что у соседа: отказ по паре —
    # именованный исход, а не пропущенная строка.
    "journal_population_backfill.json": ("status", "grade", "owner_answer",
                                         "plan", "per_pair", "counts",
                                         "values_planned", "days_touched",
                                         "what_it_does_not_prove", "findings"),
    "cio_policy_change_procedure.json": ("overall", "counts.critical",
                                         "counts.warn", "counts.info",
                                         "counts.unchecked", "positive_control",
                                         "knobs", "knobs_total", "knobs_relaxed",
                                         "knobs_added", "knobs_unchanged",
                                         "proposals", "homes", "findings"),
    "evidence_staleness.json": ("overall", "action", "reason", "counts.fresh",
                                "counts.soft_stale", "counts.hard_stale",
                                "counts.unknown_age", "counts.unchecked",
                                "usd.fresh", "usd.soft_stale", "usd.hard_stale",
                                "usd.unknown_age", "usd.total", "protocols",
                                "to_derisk", "unchecked", "ladder.soft_stale_h",
                                "ladder.hard_stale_h"),
    "capital_evidence_coverage.json": ("verdict", "verdict_live_track", "population",
                                       "all_books.verdict", "all_books.coverage_pct",
                                       "all_books.books_measured", "all_books.books_unmeasured",
                                       "books",
                                       "capital_coverage_pct", "target_pct",
                                       "baseline_pct", "deployed_usd", "usd.evidenced",
                                       "usd.literal", "usd.unmeasured", "by_protocol",
                                       "adapters_live_pct", "divergence_pp", "unchecked",
                                       "history.status", "history.covered_days",
                                       "history.window_truncated", "history.books_measured",
                                       "history.books_unmeasured", "history.coverage_pct_min",
                                       "history.coverage_pct_max"),
}

# Отметка времени в шапке md-артефакта: `Auto-updated: **2026-08-09 05:44 UTC**`.
_MD_TS_RE = re.compile(r"(20\d\d-\d\d-\d\d)[ T](\d\d:\d\d)(?::\d\d)?\s*UTC")


# КТО пишет каждый артефакт — объявлено данными и СВЕРЕНО тестом с исходником
# (`test_declared_schema_matches_the_live_producer`), а не взято на веру.
#
# Зачем производитель вообще нужен проверке схемы. До #248 «поля нет в файле»
# печаталось как «производитель его не пишет» — два РАЗНЫХ утверждения:
# артефакт, произведённый ДО доставки ключа, не может его содержать, и назвать
# это расхождением значит позвать сессию завести карточку на ИСПРАВНОЕ
# состояние. Живой замер 15.08 17:0xZ: `owner_answer_delivery` приехал с ADR-086
# в 16:0xZ, отчёт моста на диске — от 13:03Z, и обязательный шаг напечатал
# «СХЕМА РАЗОШЛАСЬ … читаем НЕ ТОТ файл» о полностью здоровом контуре. Ровно то
# же было в #204/#205 с блоком `debt`; автор #235 капкан уже НАЗВАЛ и обошёл
# руками (поле `house_view` сознательно не внесено в `_READ_SCHEMA`) — то есть
# обход был, а проверки не было, и следующий добавленный ключ повторял аварию.
# Вторая половина цены: настоящее расхождение печаталось ТЕМИ ЖЕ словами, что
# ложное, — читатель учится игнорировать строку, и сигнал теряется.
_PRODUCER: dict[str, str] = {
    "chief_investment.json": "spa_core/investment_os/agents/chief_investment.py",
    "_health.json": "spa_core/investment_os/health.py",
    "architecture_conformance.json": "spa_core/monitoring/architecture_conformance.py",
    "house_view_gap.json": "spa_core/monitoring/house_view_gap.py",
    "findings_bridge_report.json": "spa_core/monitoring/findings_bridge.py",
    "loop_retro.json": "spa_core/monitoring/loop_retro.py",
    "loop_health.json": "spa_core/monitoring/loop_health.py",
    "adapter_feed_divergence.json": "spa_core/monitoring/adapter_feed_divergence.py",
    "capital_evidence_coverage.json": "spa_core/monitoring/capital_evidence_coverage.py",
    "pool_identity_collision.json": "spa_core/monitoring/pool_identity_collision.py",
    "decision_reproducibility.json": "spa_core/monitoring/decision_reproducibility.py",
    "marginal_apy_at_size.json": "spa_core/monitoring/marginal_apy_at_size.py",
    "rebalance_cost_evidence.json": "spa_core/monitoring/rebalance_cost_evidence.py",
    "apy_forecast_accuracy.json": "spa_core/monitoring/apy_forecast_accuracy.py",
    "cio_shadow_replay.json": "spa_core/monitoring/cio_shadow_replay.py",
    "decision_audit_trail.json": "spa_core/monitoring/decision_audit_trail.py",
    "cio_failure_modes.json": "spa_core/monitoring/cio_failure_modes.py",
    "cio_explainability.json": "spa_core/monitoring/cio_explainability.py",
    "cio_kill_switch_controls.json": "spa_core/monitoring/cio_kill_switch_controls.py",
    "cio_auto_execution_limits.json": "spa_core/monitoring/cio_auto_execution_limits.py",
    "cio_target_producers.json": "spa_core/monitoring/cio_target_producers.py",
    "cio_architecture_constraints.json": "spa_core/monitoring/cio_architecture_constraints.py",
    "cio_component_map.json": "spa_core/monitoring/cio_component_map.py",
    "cio_policy_change_procedure.json": "spa_core/monitoring/cio_policy_change_procedure.py",
    "cio_post_trade_verification.json": "spa_core/monitoring/cio_post_trade_verification.py",
    "cio_outcome_independence.json": "spa_core/monitoring/cio_outcome_independence.py",
    "cio_substitution_census.json": "spa_core/monitoring/cio_substitution_census.py",
    "shadow_blockade_attribution.json": "spa_core/monitoring/shadow_blockade_attribution.py",
    "target_stability.json": "spa_core/monitoring/target_stability.py",
    "ranking_tie_census.json": "spa_core/monitoring/ranking_tie_census.py",
    "ranking_tie_persistence.json": "spa_core/monitoring/ranking_tie_persistence.py",
    "decision_journal_coverage.json": "spa_core/monitoring/decision_journal_coverage.py",
    "decision_record_verdict_sensitivity.json":
        "spa_core/monitoring/decision_record_verdict_sensitivity.py",
    "hit_rate_selection_bias.json":
        "spa_core/monitoring/hit_rate_selection_bias.py",
    "g1_verdict_recoverability.json":
        "spa_core/monitoring/g1_verdict_recoverability.py",
    "unevidenced_leg_causes.json":
        "spa_core/monitoring/unevidenced_leg_causes.py",
    "journal_backfill_material.json":
        "spa_core/monitoring/journal_backfill_material.py",
    "arming_wall_order.json":
        "spa_core/monitoring/arming_wall_order.py",
    "journal_population_backfill.json":
        "spa_core/monitoring/journal_population_backfill.py",
    "leg_provenance_split.json":
        "spa_core/monitoring/leg_provenance_split.py",
    "snapshot_minute_sensitivity.json":
        "spa_core/monitoring/snapshot_minute_sensitivity.py",
    "decision_record_run_identity.json":
        "spa_core/monitoring/decision_record_run_identity.py",
    "day_replacement_verdict_loss.json":
        "spa_core/monitoring/day_replacement_verdict_loss.py",
    "intraday_rate_input_movement.json":
        "spa_core/monitoring/intraday_rate_input_movement.py",
    "audit_trail_rate_input_coverage.json":
        "spa_core/monitoring/audit_trail_rate_input_coverage.py",
    "run_axis_time_stitch.json":
        "spa_core/monitoring/run_axis_time_stitch.py",
    "rate_observation_census.json":
        "spa_core/monitoring/rate_observation_census.py",
    "census_consumer_census.json":
        "spa_core/monitoring/census_consumer_census.py",
    "subject_population_census.json":
        "spa_core/monitoring/subject_population_census.py",
    "substring_structure_assertions.json":
        "spa_core/monitoring/substring_structure_assertions.py",
    "haystack_origin_census.json":
        "spa_core/monitoring/haystack_origin_census.py",
    "evidence_staleness.json": "spa_core/monitoring/evidence_staleness_monitor.py",
    "apy_composition.json": "spa_core/monitoring/apy_composition.py",
    "rebalance_trigger.json": "spa_core/paper_trading/rebalance_trigger.py",
    # Единственный производитель-СКРИПТ. Ключи он всё-таки пишет питоном —
    # heredoc'ом внутри shell, — поэтому сверка схемы здесь настоящая, а не
    # «неприменима»: разбирает встроенный питон (`_embedded_python`), а не
    # ищет имя ключа подстрокой по shell-тексту.
    "code_sync_status.json": "scripts/code_sync_from_origin.sh",
    # Внесён циклом #528 по замеру, а не по симметрии: ПЯТЬ красных печатей
    # шага («в отчёте нет блока origin_queue / branch_queue / accepted /
    # closed_on_origin_open_here / channel_buttons») спрашивали о судьбе блока,
    # а спросить было НЕ У КОГО — производителя артефакта здесь не значилось,
    # и третий исход («допишет сам») был недостижим ПО ПОСТРОЕНИЮ. Все пять
    # ключей — литералы этого модуля (сверено, по одному вхождению на ключ).
    # На `_schema_drift` строка не влияет: у артефакта нет объявления в
    # `_READ_SCHEMA`, и сверка схемы выходит раньше.
    "owner_decision_pending.json": "spa_core/monitoring/owner_decision_pending.py",
}


# ЧЕМ производитель называет собственное время. Умолчание — `generated_at`;
# отклонения объявляются здесь ДАННЫМИ, а не угадываются перебором ключей.
#
# ЗАЧЕМ. Артефакт, у которого возраст «НЕ ИЗМЕРЕН» ПО ПОСТРОЕНИЮ, — необратимое
# «не измерено» (класс #267): никакое состояние системы не сделает строку
# измеренной, а объявленный в манифесте `slo_hours` становится украшением —
# протухший артефакт неотличим от свежего. Живой замер #467: `code_sync_status.json`
# пишет `timestamp`, и первая же его печать дала «производитель не пишет
# generated_at» при отчёте возрастом шесть минут.
#
# Перебирать «ну хоть какое-нибудь похожее поле» ЗАПРЕЩЕНО намеренно: угаданное
# поле может означать не время производства, а что-то своё, и тогда возраст
# станет уверенно НЕВЕРНЫМ — хуже, чем честно неизмеренным. Здесь только то,
# что сверено с исходником производителя (тест `test_ts_field_matches_producer`).
_TS_FIELD: dict[str, str] = {
    # Свой отметчик времени: слой триггеров пишет `checked_at` (ADR-031).
    # Без этой строки возраст артефакта был бы «НЕ ИЗМЕРЕН» по построению.
    "rebalance_trigger.json": "checked_at",
    "code_sync_status.json": "timestamp",
}


def _produced_at(name: str, data):
    """Отметка времени производства — по объявлению, иначе `generated_at`."""
    if not isinstance(data, dict):
        return None
    return data.get(_TS_FIELD.get(name, "generated_at"))


# О ЧЁМ вынесен вердикт — предмет проверки, в отличие от `_PRODUCER` (кто её
# написал). Два разных вопроса, и до цикла #337 задавался только первый.
#
# Замер #337, живой. 21.08 07:44Z решение ADR-104 сменило в конституции такт
# `com.spa.io_chief_investment` (`interval:86400s → interval:300s`). В прод-дерево
# `architecture/` правка доехала в 19:21Z, а последний отчёт сторожа был
# произведён в 16:19Z — и обязательный шаг 0-офис три часа печатал
# `вердикт: OK (critical=0 warn=0 aged=0 unchecked=0)`. Строка была ПРАВДОЙ о
# прежней конституции и НЕИЗМЕРЕННОСТЬЮ о текущей; отличить одно от другого
# читателю было нечем. Возраст отчёта (5.1ч) на этот вопрос не отвечает: он
# меряет, давно ли сторож ходил, а не сменился ли под ним ПРЕДМЕТ.
#
# Ровно тот же класс, что #222 закрыл для `house_view_gap` (сверка судила по
# снимкам разных тактов) и #235 — для дом-вью (один бюджет на producers с
# тактами в два порядка). Правило класса: зелёный ответ сторожа на СВОЙ вопрос
# никогда не есть ответ на нужный.
#
# Объявлять сюда только то, что действительно измеримо и действительно является
# предметом: артефакт, «предмет» которого — живая система (`data/*`), сюда НЕ
# годится, иначе каждая запись цикла давала бы находку, и строка обесценится.
#
# Второй вход — замер цикла #471 (03.09), ADR-220. Отчёт моста, произведённый
# в 11:46:08Z, печатал по двум карточкам «перенести правку автоматически нечем;
# сделать это вручную из worktree на origin/main». В 16:04:31Z коммит 3425bd28
# (ADR-219) научил перенос везти ровно этот случай — перемерено в 17:2xZ:
# `rebase_card()` строит кандидата для ОБЕИХ. То есть обязательный шаг звал
# человека делать руками то, что машина уже умеет, и отличить «нечем» от «есть
# чем» читателю было НЕЧЕМ. Предмет здесь — не карточки (живое состояние, его
# объявлять сюда нельзя), а САМ РЕШАТЕЛЬ: `card_delivery` — единственный, кто
# отвечает «переносим» или «переносить нечем», и оба отказа отчёта (доставка
# карточек и доставка следа ответа владельца) приходят из него.
_SUBJECT: dict[str, tuple[str, ...]] = {
    "architecture_conformance.json": ("architecture/manifest.json",),
    "findings_bridge_report.json": ("spa_core/monitoring/card_delivery.py",),
}


def _basename(path) -> str:
    """Имя файла карточки для строки отчёта: путь целиком не читаем, а имя — адрес."""
    return os.path.basename(str(path or "")) or "(без имени)"


def _sha256(path: str) -> str | None:
    import hashlib
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


#: ЕЩЁ НЕ ДОЛЖЕН БЫЛ ПЕРЕМЕРИТЬ — третий исход смены предмета (#527).
#: Не «всё хорошо» и не находка: знание отстаёт, и это ОЖИДАЕМОЕ состояние,
#: которое снимет следующий такт производителя.
_NOT_DUE = "ЕЩЁ НЕ ДОЛЖЕН БЫЛ ПЕРЕМЕРИТЬ"


def _producer_tick_hours(name: str, root: str) -> tuple[float | None, str]:
    """Как часто производитель `data/<name>` ОБЯЗАН перемерять свой предмет.

    Возвращает `(часы, чем измерено)`. `None` — такт НЕ ИЗМЕРЕН, и вторым
    элементом идёт причина ИМЕННО та, что случилась: их четыре, и они разные
    (манифест не прочитан · артефакта нет в `artifacts[]` · его производителя
    нет в `agents[]` · расписание в такт не переводится). Одна общая причина
    «не смог» соврала бы читателю о том, где именно оборвалось объявление.

    Разбор строки расписания берётся у
    `architecture_conformance.producer_tick_hours` — второго определения того
    же понятия здесь заводить нельзя (правило «одно имя — один объект»).
    Признак ОБЪЯВЛЕННЫЙ, а не выведенный: и `artifacts[].producer`, и
    `agents[].schedule` пишет генератор конституции, а не эта проверка.
    """
    from spa_core.monitoring.architecture_conformance import producer_tick_hours

    mpath = os.path.join(root, "architecture", "manifest.json")
    try:
        with open(mpath, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        return None, f"конституция не прочитана ({type(exc).__name__})"
    if not isinstance(manifest, dict):
        return None, "конституция не разобрана как объект"
    rel = f"data/{name}"
    art = next((a for a in (manifest.get("artifacts") or [])
                if isinstance(a, dict) and a.get("path") == rel), None)
    if art is None:
        return None, f"{rel} не объявлен в `artifacts[]` конституции"
    label = art.get("producer")
    if not label:
        return None, f"у {rel} в конституции не объявлен производитель"
    agent = next((a for a in (manifest.get("agents") or [])
                  if isinstance(a, dict) and a.get("label") == label), None)
    if agent is None:
        return None, f"производителя {label} нет в `agents[]` конституции"
    tick = producer_tick_hours(agent.get("schedule"))
    if tick is None:
        return None, (f"расписание {label} ({agent.get('schedule')!r}) в такт "
                      f"не переводится")
    return tick, f"schedule {label} = {agent.get('schedule')}"


def _drift_is_a_finding(name: str, *, root: str, art_ts, now) -> tuple[bool, str]:
    """Предмет сменился — это находка (карточка) или ожидаемое отставание?

    Утверждение «про ТЕКУЩИЙ предмет не измерено ничего» ВЕРНО всегда, и
    строка о нём остаётся. Вопрос здесь ДРУГОЙ и решается отдельно: обязан ли
    читатель ДЕЙСТВОВАТЬ. До #527 ответ был один — «находка (карточка)» — при
    ЛЮБОМ расхождении, и 08.09 обязательный шаг говорил это об ИСПРАВНОМ
    контуре: отчёт `architecture_conformance` произведён 06:54Z (возраст 5.0ч)
    при такте производителя `interval:21600s` = 6ч, то есть он ещё не должен
    был отработать, и следующий такт снял бы строку сам.

    Ровно тот же класс, что ADR-261/262 закрыли для ОТСУТСТВИЯ артефакта
    («файла нет» — находка только после того, как производитель отработал).
    Форму контроля там применили к своему поводу и не перенесли на СМЕНУ
    ПРЕДМЕТА — третий случай урока #519 подряд, поэтому перенос сделан на ОБЕ
    ветки `_subject_drift` сразу, а не на ту, на которой нашлось.

    Три исхода:

    * такт объявлен и ещё НЕ прошёл ⇒ **не находка**, `⏳ ЕЩЁ НЕ ДОЛЖЕН БЫЛ
      ПЕРЕМЕРИТЬ`; исход не вечен — он закрывается следующим прогоном
      производителя САМ, без правки кода и без записи в базу;
    * такт объявлен и ПРОШЁЛ ⇒ **находка**: производитель просрочил перемер,
      сам строку уже не снимет;
    * такта нет или вердикт нечем датировать ⇒ **находка** с названной
      причиной. «Не смог измерить» не есть «всё хорошо» (fail-CLOSED,
      инвариант 2), и направление тут важнее: молчание здесь было бы
      fail-OPEN, тише красной строки и потому опаснее.
    """
    if art_ts is None:
        return True, (f"вердикт нечем датировать ({_UNMEASURED}), поэтому "
                      f"сказать, перемерит ли производитель предмет сам, НЕЧЕМ.")
    tick, why = _producer_tick_hours(name, root)
    if tick is None:
        return True, (f"такт производителя {_UNMEASURED} — {why}; перемерит "
                      f"ли он предмет сам, сказать нечем.")
    age_h = (now - art_ts).total_seconds() / 3600.0
    if age_h < tick:
        due = art_ts + dt.timedelta(hours=tick)
        return False, (f"такт {tick:.1f}ч ({why}), отчёту {age_h:.1f}ч — "
                       f"следующий такт ~{due:%Y-%m-%d %H:%M}Z перемерит "
                       f"предмет и снимет строку сам. Нужен ответ раньше — "
                       f"прогнать сторожа руками.")
    return True, (f"производитель ПРОСРОЧИЛ перемер — такт {tick:.1f}ч ({why}), "
                  f"отчёту {age_h:.1f}ч, сам он строку уже не снимет. "
                  f"Прогнать сторожа руками.")


def _finding_mark(is_finding: bool) -> str:
    """Значок красной строки — ОДИН дом на весь шаг.

    Значок и есть то, по чему читатель отличает «действовать» от «к сведению»
    (подпись шага: «Красные строки выше = действовать (карточки)»). Второй его
    копии не заводится намеренно: разойтись две копии могут молча, и цену этого
    #527 уже заплатил внутри одной функции (см. `_drift_words`).
    """
    return "⚠️" if is_finding else "⏳"


def _drift_words(is_finding: bool) -> tuple[str, str]:
    """Значок и слова классификации — ОДНО следствие одного вердикта.

    Первая редакция #527 держала их в двух местах: значок выводился из
    возвращённого `bool`, а слова «Это находка (карточка)» лежали внутри
    строки-причины. Батарея мутаций тут же нашла цену: подмена вердикта на
    `False` у ДВУХ дверей незнания (такт не измерен · вердикт нечем датировать)
    меняла только значок, текст продолжал звать заводить карточку, и ни один
    тест не краснел. Направление вреда — fail-OPEN («не измерено» → «безопасно»),
    то есть тише красной строки и потому опаснее.
    """
    if is_finding:
        return _finding_mark(True), "Это находка (карточка), а не деталь:"
    return _finding_mark(False), f"{_NOT_DUE} — это НЕ находка, карточка НЕ нужна:"


def _block_absent_is_a_finding(name: str, key: str, *, root: str,
                               art_ts, now) -> tuple[bool, str]:
    """Блока нет в отчёте — это находка или производитель ещё не отработал?

    ЧЕТВЁРТЫЙ случай урока #519 подряд, и на этот раз спрошенный обо ВСЁМ
    классе сразу, а не о поводе (заказ цикла #527). Форму контроля ставили
    ADR-261 (файла нет на диске), ADR-262 (второй читатель того же) и ADR-264
    (предмет сменился) — каждый раз ровно там, где нашлось. Перепись красных
    печатей шага 0-офис (49 штук) показала, что тем же свойством обладают ещё
    **тринадцать**: «в отчёте нет блока X (отчёт старого образца)». Ни одна из
    тринадцати не спрашивала производителя ни о чём — все печатали `⚠️`
    безусловно, и пять из них при этом ПРОТИВОРЕЧИЛИ соседней строке того же
    прогона (`_schema_drift` объявляет тот же ключ и отвечает о нём иначе).

    Утверждение «блока нет, значит про это НЕ ИЗМЕРЕНО ничего» верно всегда и
    остаётся. Вопрос здесь другой: обязан ли читатель ДЕЙСТВОВАТЬ.

    Четыре исхода, и различающий признак ОБЪЯВЛЕН, а не выведен:

    * ключа нет в исходнике производителя (`_PRODUCER` + разбор AST) ⇒
      **находка**: сколько бы производитель ни отработал, блок не появится —
      выжимка читает поле, которого никто не пишет;
    * ключ производитель пишет, а его такт (`artifacts[].producer` +
      `agents[].schedule` конституции) ещё НЕ прошёл ⇒ **не находка**:
      следующий прогон допишет блок сам. Исход не вечен — он закрывается
      прогоном производителя, без правки кода и без записи в базу;
    * ключ пишет, а такт ПРОШЁЛ ⇒ **находка**: производитель просрочил, сам
      он блок уже не допишет;
    * производитель не объявлен / исходник не разобран / такта нет / отчёт
      нечем датировать ⇒ **находка** с названной причиной (fail-CLOSED,
      инвариант 2). Молчание здесь было бы fail-OPEN — тише красной строки и
      потому опаснее.

    Второй копии понятия «такт производителя» не заводится: ответ на вопрос
    «отработал ли он» берётся у `_drift_is_a_finding` (ADR-264), который берёт
    его у `architecture_conformance.producer_tick_hours`.
    """
    rel = _PRODUCER.get(name)
    if rel is None:
        return True, (f"производитель артефакта не объявлен в `_PRODUCER` — "
                      f"допишет ли он блок сам, сказать НЕЧЕМ.")
    keys = _source_keys(os.path.join(root, rel))
    if keys is None:
        return True, (f"исходник производителя {rel} не прочитан/не разобран — "
                      f"пишет ли он этот ключ вообще, сказать НЕЧЕМ.")
    leaf = key.split(".")[-1]
    if leaf not in keys:
        return True, (f"производитель {rel} этот ключ НЕ ПИШЕТ (в исходнике его "
                      f"нет) — сколько бы он ни отработал, блок не появится: "
                      f"выжимка читает поле, которого никто не пишет.")
    # Отчёт МОЛОЖЕ кода ⇒ производитель уже отработал с этим кодом и блока не
    # написал; следующий такт его тоже не напишет, и ждать нечего. Форма —
    # ветка 3 ADR-261 («бегун отработал ПОСЛЕ прихода кода»), перенесённая
    # сюда, а не выдуманная заново. Без неё две строки ОДНОГО прогона
    # противоречили бы друг другу: `_schema_drift` называл бы это
    # расхождением, а строка ниже обещала бы, что «допишется само».
    src_ts = _mtime(os.path.join(root, rel))
    if art_ts is not None and src_ts is not None and art_ts >= src_ts:
        return True, (f"производитель {rel} ключ пишет (правлен "
                      f"{src_ts:%Y-%m-%d %H:%M}Z), а отчёт произведён ПОЗЖЕ "
                      f"({art_ts:%Y-%m-%d %H:%M}Z) и блока не несёт — значит "
                      f"производитель уже отработал с этим кодом и не написал "
                      f"его; следующий такт не изменит ничего.")
    is_finding, why = _drift_is_a_finding(name, root=root, art_ts=art_ts, now=now)
    if is_finding:
        return True, f"производитель {rel} ключ пишет, но {why}"
    return False, f"производитель {rel} ключ пишет; {why}"


def _absent_block(name: str, data, key: str, *, root: str | None,
                  now) -> tuple[str, str]:
    """Значок и хвост-причина строки «в отчёте нет блока <key>».

    ОДНО следствие одного вердикта (урок #527): значок берётся из
    `_finding_mark`, слова — из той же пары, и разойтись им негде.
    """
    is_finding, why = _block_absent_is_a_finding(
        name, key, root=root or REPO_ROOT,
        art_ts=_parse_ts(_produced_at(name, data)), now=now)
    return _finding_mark(is_finding), why


def _subject_drift(name: str, data, *, root: str | None = None,
                   now: dt.datetime | None = None) -> list[str]:
    """Менялся ли ПРЕДМЕТ проверки после того, как вердикт был вынесен.

    Четыре исхода, и они РАЗНЫЕ (четвёртый добавлен #527):
      * предмет с тех пор не менялся ⇒ молчим (вердикт актуален);
      * предмет изменился, а производитель ПРОСРОЧИЛ свой такт ⇒ находка:
        вердикт вынесен о ПРЕЖНЕЙ конституции, сам он уже не обновится;
      * предмет изменился, но такт производителя ЕЩЁ НЕ ПРОШЁЛ ⇒ строка
        остаётся (знание правда отстаёт), но это НЕ находка и карточка не
        нужна: следующий такт снимет её сам. Кто из двух — решает
        `_drift_is_a_finding` по ОБЪЯВЛЕННОМУ расписанию, а не по догадке;
      * предмет или отметка времени не читаются ⇒ «НЕ ИЗМЕРЕНО» вслух
        (fail-CLOSED, инвариант 2), а не молчание.

    Основание сравнения — СОДЕРЖИМОЕ (`sha256` из блока `inputs` отчёта), и
    только при его отсутствии — `mtime`. Перезапись файла байт-в-байт двигает
    mtime, а генератор манифеста идемпотентен по построению: судить по одному
    mtime значило бы печатать находку на каждой холостой перегенерации.
    Основание НАЗЫВАЕТСЯ в самой строке — иначе «сошлось по хэшу» и «сошлось,
    потому что мерить было нечем» выглядят одинаково.
    """
    subjects = _SUBJECT.get(name)
    if not subjects:
        return []
    root = root or REPO_ROOT
    art_ts = _parse_ts(_produced_at(name, data))
    recorded = {r.get("path"): r for r in (data.get("inputs") or [])
                if isinstance(r, dict)}
    lines: list[str] = []
    for rel in subjects:
        path = os.path.join(root, rel)
        prev = recorded.get(rel)
        now_sha = _sha256(path)
        if now_sha is None:
            lines.append(f"   ⚠️ предмет проверки {_UNMEASURED}: {rel} не прочитан — "
                         f"о чём именно вынесен вердикт, сказать нечем.")
            continue
        if isinstance(prev, dict) and prev.get("sha256"):
            if prev["sha256"] == now_sha:
                continue
            is_finding, why = _drift_is_a_finding(name, root=root,
                                                  art_ts=art_ts, now=now)
            mark, verdict = _drift_words(is_finding)
            lines.append(
                f"   {mark} ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ: "
                f"{rel} изменился ПОСЛЕ замера "
                f"(сверка по содержимому: отчёт мерил {prev['sha256'][:12]}, "
                f"сейчас {now_sha[:12]}) — про ТЕКУЩИЙ {rel} не измерено ничего. "
                f"{verdict} {why}")
            continue
        # Старый отчёт без `inputs` — судим по mtime и говорим это вслух.
        try:
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)
        except OSError:
            mtime = None
        if art_ts is None or mtime is None:
            why = ("у отчёта нет разобранного generated_at" if art_ts is None
                   else f"у {rel} не измерено время правки")
            lines.append(f"   ⚠️ предмет проверки {_UNMEASURED}: {why}; "
                         f"отчёт старого образца (без блока `inputs`) — "
                         f"сверить по содержимому нечем.")
        elif mtime > art_ts:
            # Тот же вопрос о такте, что и у сверки по содержимому: форма
            # контроля переносится на ВЕСЬ класс, а не на ту ветку, где нашлась
            # (урок #519). Собственный дефект ЭТОЙ ветки при этом остаётся и
            # назван вслух ниже: mtime меряет ДРУГОЙ признак, и свежий
            # worktree (все файлы датированы чекаутом) даёт её всегда.
            is_finding, why = _drift_is_a_finding(name, root=root,
                                                  art_ts=art_ts, now=now)
            mark, verdict = _drift_words(is_finding)
            lines.append(
                f"   {mark} ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ: "
                f"{rel} правлен "
                f"{mtime:%Y-%m-%d %H:%M}Z, отчёт произведён "
                f"{art_ts:%Y-%m-%d %H:%M}Z — про ТЕКУЩИЙ {rel} не измерено "
                f"ничего. Сверка по mtime (отчёт старого образца, без `inputs`): "
                f"холостая перегенерация тем же содержимым даёт ту же строку. "
                f"{verdict} {why}")
    return lines


def _has_path(data, path: str) -> bool:
    """Есть ли (возможно вложенное) поле `a.b.c` — именно ЕСТЬ, а не истинно."""
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


#: Heredoc с питоном внутри shell-производителя: `python3 - <<'PYEOF' … PYEOF`.
#: Метка произвольная, закрывающая строка — та же метка с начала строки.
_PY_HEREDOC_RE = re.compile(
    r"""^(?P<cmd>[^\n]*?)"""
    r"""<<[-]?\s*['"]?(?P<tag>[A-Za-z_][A-Za-z0-9_]*)['"]?\s*\n"""
    r"""(?P<body>.*?)\n(?P=tag)\s*$""",
    re.S | re.M)

#: `ИМЯ=значение` в shell — чтобы узнать питон, спрятанный за переменной.
_SH_ASSIGN_RE = re.compile(r"^\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)=(?P<val>\S+)",
                           re.M)
_PYTHON_RE = re.compile(r"\bpython[0-9.]*\b")


def _python_vars(text: str) -> set:
    """Переменные скрипта, значение которых — питон (`PYTHON=/…/python3`)."""
    return {m.group("var") for m in _SH_ASSIGN_RE.finditer(text)
            if _PYTHON_RE.search(m.group("val"))}


def _launches_python(cmd: str, pyvars: set) -> bool:
    """Зовёт ли эта команда питон — прямо или через переменную скрипта.

    Прямое имя (`python3 - <<'PY'`) и переменная (`"$PYTHON" - <<'PYEOF'`) —
    один и тот же способ запуска; различать их значило бы объявить настоящего
    производителя неизмеримым по форме записи. Живой замер: именно так и
    устроен `code_sync_from_origin.sh` (`PYTHON=/…/python3`, затем `"$PYTHON"`).
    """
    if _PYTHON_RE.search(cmd):
        return True
    return any(re.search(r"\$\{?" + re.escape(v) + r"\b", cmd) for v in pyvars)


def _embedded_python(text: str) -> list:
    """Куски питона внутри shell-исходника — те, что действительно разбираются.

    ЗАЧЕМ. `_source_keys` спрашивала у `ast` весь файл целиком, поэтому у
    производителя-СКРИПТА (`scripts/code_sync_from_origin.sh`) сверка схемы
    отвечала `SyntaxError` ⇒ `None` ⇒ громкое «не измерено» на КАЖДОМ прогоне.
    Это честно, но бесполезно: строка «не измерено», которая не может стать
    измеренной ни при каком состоянии системы, — шум, а не сторож (тот же урок,
    что у необратимого `UNCHECKED`, #267).

    Мерить тут ЕСТЬ что: артефакт `data/code_sync_status.json` пишет питон,
    встроенный в скрипт heredoc'ом, и имена ключей — обычные питоновские
    литералы. Разбираем именно их, а НЕ ищем имя ключа подстрокой по всему
    shell-тексту: подстрока зачла бы упоминание в комментарии за проводку —
    капкан #227, из-за которого объяснение «этого тут нет» молча снимало вопрос.

    Граница названа честно и меряется КОМАНДОЙ, а не разбором. Первая редакция
    брала любой heredoc, который питон сумел разобрать, — и это оказалось ложным
    признаком: тело обычного текстового heredoc'а вида ``retired_instructions``
    разбирается как валидное выражение-имя, то есть произвольный shell-текст
    выдавал бы себя за исходник производителя. Признаком служит СТРОКА ЗАПУСКА:
    heredoc берётся, только если его открывает команда, зовущая `python`.
    Разбор остаётся вторым ситом (не разобралось ⇒ не наш кусок). Если
    питоновских кусков не нашлось вовсе, вызывающий получает пустой список и
    обязан сказать «НЕ ИЗМЕРЕНО» — не «пусто».
    """
    out = []
    pyvars = _python_vars(text)
    for m in _PY_HEREDOC_RE.finditer(text):
        if not _launches_python(m.group("cmd"), pyvars):
            continue                # heredoc не питона — не наш кусок
        body = m.group("body")
        try:
            ast.parse(body)
        except (SyntaxError, ValueError):
            continue                # объявлен питоном, но не разбирается
        out.append(body)
    return out


def _source_keys(path: str):
    """Строковые литералы исходника — или None, если измерить нечем.

    Докстринги и голые строки-выражения ИСКЛЮЧЕНЫ намеренно: капкан #227 —
    там сканер зачёл упоминание в комментарии за проводку, и комментарий,
    объяснявший «этого тут нет», молча снимал вопрос навсегда. Здесь та же
    ошибка дала бы «производитель ключ пишет» по одному лишь абзацу докстринга,
    в котором ключ назван (а он назван — в `owner_answer_delivery.py` именно
    так). None ⇒ «не измерено», НИКОГДА не «в порядке».
    """
    try:
        text = _read_text(path)
    except OSError:
        return None
    sources = [text] if not path.endswith(".sh") else _embedded_python(text)
    if not sources:
        return None                 # bash без python-heredoc — измерять нечем
    keys: set = set()
    for src in sources:
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            return None             # разобрать не смогли ⇒ НЕ ИЗМЕРЕНО, а не «пусто»
        bare = {id(n.value) for n in ast.walk(tree)
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        keys |= {n.value for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and id(n) not in bare}
    return keys


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _mtime(path: str):
    """Время правки файла в UTC — или None, если спросить нечем (fail-CLOSED)."""
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)
    except OSError:
        return None


def _schema_drift(name: str, data, *, root: str | None = None) -> list[str]:
    """Поля, которые ветка читает, а производитель не пишет — вслух.

    Три РАЗНЫХ ответа вместо одного (см. комментарий к `_PRODUCER`):
      * ключа нет в исходнике производителя ⇒ РАСХОЖДЕНИЕ (находка, карточка);
      * ключ есть, отчёт произведён ПОЗЖЕ кода ⇒ тоже РАСХОЖДЕНИЕ, и раньше
        этот случай не отличался от следующего вовсе;
      * ключ есть, отчёт произведён РАНЬШЕ кода ⇒ отчёт старого образца, ждём
        такта производителя — печатается, но находкой НЕ объявляется;
      * производитель не объявлен / не найден / не разобран / у отчёта нет
        `generated_at` ⇒ «НЕ ИЗМЕРЕНО» громко, как и было (fail-CLOSED).
    Обе стороны сравнения НАЗЫВАЮТСЯ в самой строке (#222): судить о возрасте
    молча — то же самое, что не судить.
    """
    missing = [p for p in _READ_SCHEMA.get(name, ()) if not _has_path(data, p)]
    if not missing:
        return []
    root = root or REPO_ROOT
    rel = _PRODUCER.get(name)
    src = os.path.join(root, rel) if rel else None
    keys = _source_keys(src) if src else None
    mtime = _mtime(src) if src else None
    art_ts = _parse_ts(_produced_at(name, data))

    if rel is None:
        why = "производитель не объявлен в _PRODUCER"
    elif keys is None:
        why = f"исходник производителя {rel} не прочитан/не разобран"
    elif mtime is None:
        why = f"у исходника производителя {rel} не измерено время правки"
    else:
        why = None

    never: list[str] = []
    newer: list[str] = []
    old: list[str] = []
    unmeasured: list[str] = []
    for p in missing:
        leaf = p.split(".")[-1]
        if why is not None:
            unmeasured.append(p)
        elif leaf not in keys:
            never.append(p)
        elif art_ts is None:
            unmeasured.append(p)
        elif art_ts < mtime:
            old.append(p)
        else:
            newer.append(p)

    def _bits() -> str:
        bits = []
        if rel:
            bits.append(f"производитель {rel}")
        if mtime is not None:
            bits.append(f"правлен {mtime:%Y-%m-%d %H:%M}Z")
        if art_ts is not None:
            bits.append(f"отчёт {art_ts:%Y-%m-%d %H:%M}Z")
        return f" ({' · '.join(bits)})" if bits else ""

    lines: list[str] = []
    # ДВЕ разные причины расхождения — ДВА разных текста (цикл #528). Прежняя
    # редакция сливала их в один список и печатала обоим одну фразу
    # «производитель не пишет X». Для второй причины эта фраза — прямая
    # НЕПРАВДА, и неправда, которую тот же код только что измерил: ветка `else`
    # достижима ровно тогда, когда `leaf in keys`, то есть когда производитель
    # ключ ПИШЕТ. Замер 08.09 на живом `loop_retro.json` (ключ снят из копии
    # отчёта): строка обвиняла производителя в том, чего он не делал, при
    # литерале `"outcomes_completeness"` в его же исходнике на строке 272.
    # Тот же класс, что урок #527 (значок и слова из двух источников), только
    # здесь разошлись измеренная причина и названная.
    if never:
        lines.append("   ⚠️ СХЕМА РАЗОШЛАСЬ: производитель не пишет "
                     + ", ".join(never) + _bits()
                     + " — выжимка ниже читает НЕ ТОТ файл. Это находка (карточка), а не деталь.")
    if newer:
        lines.append("   ⚠️ СХЕМА РАЗОШЛАСЬ: производитель ПИШЕТ "
                     + ", ".join(newer) + _bits()
                     + ", но отчёт произведён ПОЗЖЕ его правки и этих полей не несёт —"
                     + " старым образцом это не объясняется. Это находка (карточка), а не деталь.")
    if old:
        lines.append("   ℹ️ отчёт СТАРОГО ОБРАЗЦА (не находка): " + ", ".join(old)
                     + f" — производитель {rel} их пишет (правлен "
                     + f"{mtime:%Y-%m-%d %H:%M}Z), а отчёт произведён РАНЬШЕ "
                     + f"({art_ts:%Y-%m-%d %H:%M}Z); ждём следующего такта производителя.")
    if unmeasured:
        reason = why or "у отчёта нет разобранного generated_at"
        lines.append(f"   ⚠️ расхождение схемы {_UNMEASURED}: " + ", ".join(unmeasured)
                     + f" — {reason}; отличить старый образец от расхождения нечем.")
    return lines


def _num(container, key):
    """Счётчик или явное «НЕ ИЗМЕРЕНО».

    Отсутствующий счётчик — это НЕ ноль, а неизмеренная величина (fail-CLOSED).
    """
    if not isinstance(container, dict) or key not in container:
        return _UNMEASURED
    v = container.get(key)
    return _UNMEASURED if v is None else v


def _parse_ts(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _age_line(ts_value, now: dt.datetime, *, field: str = "generated_at") -> str:
    """Возраст артефакта — безусловно, для КАЖДОГО артефакта.

    Отдельная строка, а не свойство generic-ветки: до #176 возраст печатался
    только тем артефактам, у которых не нашлось именованной ветки, и самый
    важный из них — house_view — ехал в контекст оркестратора без единого
    признака возраста (замер: 19.4 ч, и три «возможности» в нём были дофиксовые).
    """
    if ts_value is None:
        return f"   ⚠️ возраст НЕ ИЗМЕРЕН: производитель не пишет {field}"
    parsed = _parse_ts(ts_value)
    if parsed is None:
        return f"   ⚠️ возраст НЕ ИЗМЕРЕН: {field} не разобран ({ts_value!r})"
    hours = (now - parsed).total_seconds() / 3600.0
    mark = "  ⚠️ старше суток" if hours >= STALE_HOURS else ""
    return f"   {field}: {ts_value} (возраст {hours:.1f}ч){mark}"


def _summarize_json(path: str, data, *, now: dt.datetime | None = None,
                    root: str | None = None,
                    artifact_root: str | None = None) -> list[str]:
    """Компактная выжимка известных офисных файлов; generic — для остальных.

    Два разных корня, и это не педантизм. `root` — где искать ИСХОДНИК
    производителя (сверка схемы); `artifact_root` — дерево, ЧЕЙ артефакт мы
    сейчас читаем, и значит единственное место, где лежит ПРЕДМЕТ, о котором
    вынесен вердикт. В режиме `--data-dir` (читаем офис прода из worktree) они
    расходятся: сверить прод-отчёт с манифестом СВОЕГО дерева — значит выдумать
    расхождение там, где его нет, ровно тем же способом, каким #267 выдумывал
    «дрейф механики» из границы синхронизации. По умолчанию совпадают.
    """
    name = os.path.basename(path)
    if not isinstance(data, dict):
        return [f"   (не-dict JSON, {type(data).__name__})"]
    now = now or dt.datetime.now(dt.timezone.utc)
    head: list[str] = _schema_drift(name, data, root=root)
    head.append(_age_line(_produced_at(name, data), now, field=_TS_FIELD.get(name, "generated_at")))
    # ПОСЛЕ возраста и ДО вердикта: читатель должен узнать, что предмет сменился,
    # раньше, чем прочтёт вердикт о нём.
    head.extend(_subject_drift(name, data, root=(artifact_root or root), now=now))
    out: list[str] = []
    if name == "chief_investment.json":
        hv = data.get("house_view") or {}
        out.append(f"   постура: {hv.get('overall_posture')}")
        for c in (hv.get("conflicts") or [])[:3]:
            out.append(f"   конфликт: {c}")
        for o in (hv.get("top_opportunities") or [])[:3]:
            v = o.get("value") or {}
            out.append(f"   возможность: {v.get('protocol')} {v.get('apy_pct')}% "
                       f"(evidence {o.get('evidence_level')})")
    elif name == "_health.json":
        # Схема ВЫМЕРЕНА по производителю (`investment_os/health.py`): счётчики
        # лежат в `counts`, а строки аналитиков — в `analysts`. Прежняя ветка
        # читала `stale`/`failing`/`unknown` на верхнем уровне: ни одного такого
        # поля нет, поэтому «протух аналитик» шаг 0-офис не сказал бы НИКОГДА —
        # печаталась одна строка «статус офиса», и она читалась как весь ответ.
        c = data.get("counts") or {}
        out.append(f"   статус офиса: {data.get('overall') or data.get('status')}")
        out.append(f"   аналитики: всего {_num(c, 'total')} · здоровы {_num(c, 'healthy')} · "
                   f"протухли {_num(c, 'stale')} · нет файла {_num(c, 'missing')} · "
                   f"нечитаемы {_num(c, 'unknown_or_corrupt')}")
        # ДОМ-ВЬЮ отдельной строкой (#235): «здоровы 11» читалось как ответ про офис
        # целиком, тогда как судим мы каждый цикл именно по дом-вью. Поле НЕ внесено в
        # `_READ_SCHEMA` СОЗНАТЕЛЬНО: производитель дневной, и до его следующего такта
        # живой файл поля не имеет — требование обязательности выдало бы ложную находку
        # «СХЕМА РАЗОШЛАСЬ» на верном состоянии. Нет поля ⇒ честное «не измерено».
        hv = data.get("house_view")
        if isinstance(hv, dict):
            age_h = hv.get("age_s")
            age_txt = f"{age_h / 3600:.1f}ч" if isinstance(age_h, (int, float)) else _UNMEASURED
            max_h = hv.get("max_age_s")
            max_txt = f"{max_h / 3600:.0f}ч" if isinstance(max_h, (int, float)) else _UNMEASURED
            mark = "" if hv.get("status") == "FRESH" else "⚠️ "
            # ПРОИСХОЖДЕНИЕ срока годности (#340). Молчим, когда он ПРОЧИТАН из конституции
            # флота, и говорим вслух, когда это откат на литерал: до #340 срок был списан
            # рукой с такта 16.08, решение владельца ADR-104 сменило такт 21.08, и строка
            # «дом-вью FRESH при сроке 30ч» свидетельствовала В ПОЛЬЗУ здоровья артефакта,
            # который по действующей конституции протух. Число без источника неоспоримо.
            src = hv.get("budget_source")
            src_txt = ("" if src in ("manifest_slo", None)
                       else f" · срок НЕ из конституции ({src}: {hv.get('budget_why', '')})")
            out.append(f"   {mark}дом-вью ({hv.get('agent')}): {hv.get('status')} · "
                       f"возраст {age_txt} при сроке годности {max_txt}{src_txt}")
        else:
            out.append(f"   дом-вью: {_UNMEASURED} (поля `house_view` нет — "
                       f"производитель ещё не переписал файл)")
        for a in (data.get("analysts") or []):
            if not isinstance(a, dict):
                continue
            if a.get("present") and a.get("fresh") and a.get("status") == "ok":
                continue
            out.append(f"   ⚠️ аналитик {a.get('agent')}: present={a.get('present')} "
                       f"fresh={a.get('fresh')} status={a.get('status')}")
    elif name == "architecture_conformance.json":
        c = data.get("counts") or {}
        out.append(f"   вердикт: {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"aged={_num(c, 'aged')} unchecked={_num(c, 'unchecked')})")
        for f in (data.get("findings") or [])[:8]:
            out.append(f"   [{f.get('severity')}] {f.get('message')}")
        if (data.get("findings") or [])[8:]:
            out.append(f"   … ещё {len(data['findings']) - 8} наход(ок) в отчёте")
        # ПРИЧИНА «не измерено» — не декорация: до цикла #236 счётчик
        # `unchecked=1` печатался голым числом, и читателю шага 0 приходилось
        # лезть в JSON руками, чтобы узнать, ЧТО именно не измерено.
        for u in (data.get("unchecked") or [])[:4]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u.get('check')}: {u.get('reason')}")
        # Пробел в контракте, а не находка (ADR-158 · ADR-164 п.2): срок
        # годности назначают две роли, и «не сошлись» ⇒ поле пустое. В шаг 0
        # это выносится ОТДЕЛЬНОЙ строкой потому, что до цикла #426 состояние
        # было немым насквозь: ни находки, ни `unchecked`, ни счётчика — и
        # активный артефакт, протухший на сорок суток, читался как исправный.
        for u in (data.get("slo_unassigned") or [])[:6]:
            age = ("файла нет на диске" if not u.get("exists")
                   else f"наблюдённый возраст {u.get('observed_age_h')}ч")
            out.append(f"   [СРОК НЕ НАЗНАЧЕН] {u.get('path')} "
                       f"(производитель {u.get('producer')}): свежесть НЕ "
                       f"ИЗМЕРЕНА, {age} — назначить обязаны две роли (ADR-158)")
        for p in (data.get("mechanics_from_ref") or [])[:4]:
            out.append(f"   [измерено с {p.get('ref')}] {p.get('label')}: "
                       f"{p.get('plist')} — в прод-дереве файла нет, "
                       f"{'сошлось' if p.get('agrees') else 'РАСХОДИТСЯ'}")
    elif name == "code_sync_status.json":
        # ЗАЧЕМ ЭТА ВЕТКА. Поле `retired_instructions` (ADR-214, цикл #458)
        # писалось и не читалось НИКЕМ — писатель без потребителя, зеркало
        # ADR-209. Смысл поля прямой: `git checkout <ref> -- <путь>` НЕ удаляет,
        # поэтому правило, снятое владельцем на origin, продолжает лежать в
        # прод-дереве и управлять агентами, которые читают его ПЕРЕД работой
        # (CLAUDE.md §5). Молчание тут неотличимо от «всё в порядке».
        #
        # Население класса на день заведения читателя — НОЛЬ (03.09: `CLAUDE.md`
        # и все пять `.claude/rules/*.md` в прод-дереве побайтово совпадают с
        # origin). Сказано вслух намеренно: читатель заводится на предмет,
        # которого сейчас нет, и это не повод считать его лишним — он и нужен
        # ровно к тому дню, когда владелец правило снимет. Обратная сторона
        # (совпало ⇒ тишина) закреплена отдельным тестом, иначе «нечего
        # называть» неотличимо от «называть разучились».
        #
        # `_SUBJECT` здесь СОЗНАТЕЛЬНО не объявлен: предмет этого вердикта —
        # живое дерево, а не git-файл; объявить его значило бы давать находку
        # на каждую запись цикла (см. комментарий к `_SUBJECT`).
        result = data.get("result")
        out.append(f"   синхронизация кода с origin: {result}"
                     f" · origin_main {str(data.get('origin_main') or '?')[:9]}"
                     f" · файлов сменилось {_num(data, 'files_changed')}")
        if result not in (None, "SYNCED", "IN_SYNC"):
            out.append(f"   ⚠️  последняя синхронизация НЕ удалась: "
                         f"{data.get('detail') or 'причина не названа'} — дерево "
                         f"работает на ПРЕЖНЕМ коде")
        retired = data.get("retired_instructions")
        if retired is None:
            out.append(f"   [{_UNMEASURED}] снятые инструкции: поля нет в отчёте — "
                         f"сказать, не действует ли в дереве отменённое правило, НЕЧЕМ")
        elif retired:
            out.append(f"   🔴 ИНСТРУКЦИЙ, КОТОРЫХ НА origin БОЛЬШЕ НЕТ, а в дереве "
                         f"лежат: {len(retired)} — их продолжают читать ПЕРЕД работой, "
                         f"хотя владелец их снял (`git checkout` не удаляет):")
            for f in retired:
                out.append(f"      ! {f}")
            out.append(f"      удаление из прод-дерева — действие владельца "
                         f"(.claude/rules/deployment.md §6), сторож только НАЗЫВАЕТ")
        else:
            out.append("   снятых инструкций нет: состав `CLAUDE.md` + "
                         "`.claude/rules/` в дереве совпадает с origin")
        # Та же ветка про КОД (цикл #482). Отдельной строкой, а не припиской к
        # инструкциям, потому что это разные предметы и разная починка: снятое
        # правило продолжает УПРАВЛЯТЬ агентами, а снятый код лежит и числится
        # вечным дрейфом — из-за него синк каждые 10 минут снимал архив всего
        # кода (1300 архивов, 70 ГБ в /tmp на 04.09). Население класса в день
        # заведения строки — 13 (у инструкций тогда же было 0).
        retired_code = data.get("retired_code")
        if retired_code is None:
            out.append(f"   [{_UNMEASURED}] снятый код: поля нет в отчёте — сказать, "
                         f"не лежит ли в дереве код, удалённый на origin, НЕЧЕМ")
        elif retired_code:
            out.append(f"   🔴 КОДА, КОТОРОГО НА origin БОЛЬШЕ НЕТ, а в дереве лежит: "
                         f"{len(retired_code)} — чекаут его не удалит никогда, поэтому "
                         f"дрейфом он больше НЕ считается (иначе синк не сходится вечно):")
            for f in retired_code:
                out.append(f"      ! {f}")
            out.append(f"      удаление из прод-дерева — действие владельца "
                         f"(.claude/rules/deployment.md §6), сторож только НАЗЫВАЕТ")
        else:
            out.append("   снятого кода нет: всё, что расходится с origin, "
                         "чекаут способен свести")
    elif name == "adapter_feed_divergence.json":
        # Сверка ДВУХ артефактов адаптеров об одном протоколе (ADR-060 D6).
        # Рода расхождений печатаются РАЗНЫМИ словами намеренно: «оба фида
        # наблюдают и не сходятся» (инвариант 2, fail-CLOSED) и «одна сторона
        # подставила литерал, потому что не наблюдала» — разные аварии с разной
        # починкой, и одинаковая формулировка увела бы починку не туда.
        c = data.get("counts") or {}
        findings = data.get("findings") or []
        out.append(f"   сверка двух фидов адаптеров: {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')}); "
                   f"протоколов сверено: {len(data.get('compared_protocols') or [])}")
        # Слово «не измерено» у этого производителя живёт в ДВУХ контейнерах:
        # общий на всю сверку (`unchecked`, ниже) и ПОАГЕНТНЫЙ — находка с
        # `severity: UNCHECKED`. Счётчик `counts.unchecked` складывает оба, и
        # вердикт всей сверки поднимается до UNCHECKED от любого из них
        # (`adapter_feed_divergence.run`: `if counts["unchecked"]` — первым, то
        # есть ВЫШЕ CRITICAL). Печатался же только первый: фильтр находок стоял
        # на `("CRITICAL", "WARN")`. Замер 31.08 (цикл #445) на живом артефакте:
        # `overall: UNCHECKED`, `counts.unchecked: 1`, список `unchecked` ПУСТ,
        # и единственная причина вердикта — `pendle: доходность не измерена` —
        # не звучала в обязательном шаге ни словом. `pendle` — это 20 % книги и
        # дословно тот протокол, ради которого модуль написан (его docstring).
        # Класс — тот же, что чинили в #236 для `architecture_conformance`
        # (голое число вместо причины) и в #426 для `slo_unassigned`: починка
        # была сделана ОДИН раз для ОДНОГО контейнера и не доехала до второго.
        # Порядок печати повторяет ранжирование самого производителя: «не
        # измерено» идёт первым, потому что первым же поднимает вердикт.
        by_sev: dict[str, list] = {}
        for x in findings:
            if isinstance(x, dict):
                by_sev.setdefault(str(x.get("severity") or _UNMEASURED), []).append(x)
        unchecked_f = by_sev.pop("UNCHECKED", [])
        for f in unchecked_f[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {f.get('message')}")
        if unchecked_f[6:]:
            out.append(f"   … ещё {len(unchecked_f) - 6} находк(и) «не измерено» в отчёте")
        loud = by_sev.pop("CRITICAL", []) + by_sev.pop("WARN", [])
        for f in loud[:8]:
            out.append(f"   [{f.get('severity')}] {f.get('message')}")
        if loud[8:]:
            out.append(f"   … ещё {len(loud) - 8} наход(ок) CRITICAL/WARN в отчёте")
        # INFO-строки (расхождение ПРОВЕНАНСА TVL) не печатаются поимённо: их
        # шесть каждый день, состояние уже названо и решено (ADR-053), и вынос
        # их в обязательный шаг научил бы читателя пролистывать весь блок.
        # Это осознанная агрегация, а не пропуск: число звучит.
        info_n = len(by_sev.pop("INFO", []))
        if info_n:
            out.append(f"   … и {info_n} INFO-строк(и) о провенансе TVL "
                       f"(константа против живого — состояние названо, ADR-053)")
        # ПАМЯТЬ (ADR-206): один снимок отвечает «расходятся ли СЕЙЧАС», и до
        # 01.09 другого ответа не было вовсе — отчёт перезаписывался, и «мигает
        # или живёт» решалось тем, кто случайно посмотрел в нужную секунду
        # (замер карточки: 27.08 1.69 пп → через 4 ч сошлись → 31.08 6.04 пп со
        # СМЕНОЙ ЗНАКА). Здесь звучит рецидив, а не мгновение.
        # Блока `history` НЕТ — здесь молчим НАМЕРЕННО. Ответ на «почему его нет»
        # даёт `_schema_gap` по объявлению в `_READ_SCHEMA`, и только он умеет
        # отличить «производитель его не пишет» (расхождение) от «отчёт написан
        # ДО доставки ключа» (ждём такта). Собственная строка здесь повторила бы
        # аварию #248: находка о полностью здоровом контуре теми же словами, что
        # настоящая, — и читатель перестаёт верить обеим.
        hist = data.get("history")
        if isinstance(hist, dict) and hist.get("status") != "OK":
            out.append(f"   [НЕ ИЗМЕРЕНО] память расхождений: "
                       f"{hist.get('reason') or _UNMEASURED} — это НЕ «расхождений не было»")
        elif isinstance(hist, dict):
            rows = hist.get("by_key") or {}
            trunc = (" ⚠️ окно обрезано возрастом журнала: покрыто "
                     f"{hist.get('covered_days')} сут из {hist.get('window_days')}"
                     if hist.get("window_truncated") else "")
            if rows:
                out.append(f"   память за {hist.get('window_days')} сут: "
                           f"{len(rows)} род(а/ов) расхождений{trunc}")
                for row in sorted(rows.values(),
                                  key=lambda r: -(r.get("snapshots_diverged") or 0))[:4]:
                    out.append(f"      ↺ {row.get('protocol')}/{row.get('kind')}: "
                               f"разошлись на {row.get('snapshots_diverged')} снимк(е/ах), "
                               f"разница пп {row.get('delta_pp_min')}…{row.get('delta_pp_max')} "
                               f"(медиана {row.get('delta_pp_median')}), последний раз "
                               f"{row.get('last_seen')}")
            else:
                out.append(f"   память за {hist.get('window_days')} сут: расхождений не "
                           f"записано{trunc}")
            if hist.get("blind_snapshots"):
                out.append(f"   [НЕ ИЗМЕРЕНО] снимков, о которых сторож отказался судить: "
                           f"{hist.get('blind_snapshots')} — «расхождений нет» о них не "
                           f"сказано, сказано «судить было нечем»")
        # Остаток — тяжесть, о которой эта ветка не знает. Немой `continue`
        # здесь и был бы рецидивом: разбор обязан быть ИСЧЕРПЫВАЮЩИМ, иначе
        # новый род находки у производителя молча исчезнет из единственного
        # обязательного читателя (у этого артефакта другого нет — мост
        # `findings_bridge` его находки не собирает вовсе).
        for sev in sorted(by_sev):
            for f in by_sev[sev][:4]:
                out.append(f"   [{sev}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:4]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
    elif name == "apy_composition.json":
        # Из чего ставка СОСТОИТ (ADR-230). Два рода печатаются разными словами
        # намеренно: «ставка держится на раздаче токена» и «пул выбран сегодняшним
        # порядком TVL» — разные предметы с разной починкой, и одинаковая
        # формулировка увела бы её не туда. «Не измерено» идёт ПЕРВЫМ, потому что
        # первым же поднимает вердикт у производителя.
        c = data.get("counts") or {}
        out.append(f"   состав ставок адаптеров: {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"unchecked={_num(c, 'unchecked')}); ключей с наблюдением этого "
                   f"прогона: {len(data.get('observed_adapters') or [])}")
        for line in (data.get("unchecked") or []):
            out.append(f"   [НЕ ИЗМЕРЕНО] {line}")
        for f in (data.get("findings") or []):
            out.append(f"   [{f.get('severity') or _UNMEASURED}] "
                       f"{f.get('message') or _UNMEASURED}")
        if data.get("book_note"):
            out.append(f"   ℹ️ книга не прочитана ({data['book_note']}) — находки НЕ "
                       f"поднимались до CRITICAL; это ограничение, а не зачёт")
        hist = data.get("history") or {}
        if hist.get("status") != "OK":
            out.append(f"   память состава: {_UNMEASURED} — "
                       f"{hist.get('reason') or 'причина не названа'}")
        else:
            changed = {k: v for k, v in (hist.get("by_adapter") or {}).items()
                       if v.get("winner_changes")}
            trunc = (" ⚠️ окно обрезано возрастом журнала"
                     if hist.get("window_truncated") else "")
            if changed:
                out.append(f"   память: победитель хинта менялся у "
                           f"{len(changed)} ключ(а/ей) за {hist.get('covered_days')} сут"
                           f"{trunc}")
                for k, v in changed.items():
                    out.append(f"      ↺ {k}: смен {v['winner_changes']}, разных пулов "
                               f"{v['distinct_pools']}, ставка "
                               f"{v['apy_min']}…{v['apy_max']}")
            if hist.get("blind_snapshots"):
                out.append(f"   [СЛЕПОТА] снимков со строкой «не измерено»: "
                           f"{hist['blind_snapshots']} — это НЕ «состав сходился»")
    elif name == "decision_reproducibility.json":
        # Вопрос §49 ТЗ CIO: один снимок, N процессов — тот же ли ответ. Число
        # прогонов печатается ВСЕГДА и рядом с вердиктом: «воспроизводимо на 3»
        # и «воспроизводимо на 100» — разные утверждения, и умолчание 3 не смеет
        # читаться как дословный опыт владельца.
        c = data.get("counts") or {}
        out.append(f"   воспроизводимость расчёта: {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')}); "
                   f"прогонов на снимок: {data.get('runs') or _UNMEASURED}")
        for m in (data.get("measurements") or []):
            if not isinstance(m, dict):
                continue
            v = m.get("verdict") or _UNMEASURED
            if v == "UNCHECKED":
                out.append(f"   [НЕ ИЗМЕРЕНО] {m.get('key')}: {m.get('reason')}")
            elif v != "OK":
                out.append(f"   [{v}] {m.get('key')}: {m.get('distinct_outputs')} "
                           f"разных ответа(ов) на {m.get('runs_completed')} прогонах "
                           f"ОДНОГО снимка")
                for d in (m.get("differences") or [])[:3]:
                    out.append(f"      {d}")
        for f in (data.get("findings") or []):
            if isinstance(f, dict) and f.get("severity") in ("WARN", "INFO"):
                out.append(f"   [{f['severity']}] {f.get('message')}")
        out.append("   ADVISORY: капитал по этому вердикту НЕ двигается — замер идёт "
                   "в песочнице (копия снимка), живое data/ не меняется")
    elif name == "marginal_apy_at_size.json":
        # §12 ТЗ CIO: «если vault показывает 8% APY, это не означает, что $40k
        # можно разместить под 8%». Ответ «учитывается ли» — НЕТ, целевая функция
        # линейна по ставке. Печатаем не только сегодняшнюю ошибку (она мала), но
        # и ГРАНИЦУ, которую держит сама политика, и капитал, на котором граница
        # догоняет требуемую выгоду перекладки: сегодняшняя малость — свойство
        # масштаба, а не свойство расчёта, и читаться как «вопрос закрыт» она не
        # должна.
        c = data.get("counts") or {}
        out.append(f"   влияние нашего размера на ставку: "
                   f"{data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        upct = data.get("unmeasured_capital_pct")
        if upct:
            out.append(f"   [СЛЕПОТА] {upct} % развёрнутого капитала стоит в пулах с "
                       f"ЛИТЕРАЛЬНЫМ TVL — знаменателя разбавления там нет")
        b = data.get("policy_bound") or {}
        if b:
            out.append(f"   граница политики: позиция ${b.get('position_usd', 0):,.0f} "
                       f"в пуле на TVL-floor ${b.get('tvl_floor_usd', 0):,.0f} ⇒ доля "
                       f"{b.get('worst_case_share_pct')} %, приведённая ошибка "
                       f"{b.get('worst_case_error_pp_blended')} пп")
        sc = data.get("scale_ceiling") or {}
        if sc.get("capital_usd_at_crossing"):
            out.append(f"   потолок масштаба: приведённая ошибка догоняет требуемую "
                       f"выгоду {sc.get('min_gain_pp')} пп при капитале "
                       f"${sc['capital_usd_at_crossing']:,.0f}")
        elif sc.get("reason"):
            out.append(f"   потолок масштаба: {_UNMEASURED} — {sc['reason']}")
        for f in (data.get("findings") or []):
            if isinstance(f, dict) and f.get("severity") in ("CRITICAL", "WARN"):
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: целевая функция оптимизатора НЕ трогается — правка "
                   "ранжирующего числа money-path, решение владельца")
    elif name == "rebalance_cost_evidence.json":
        # §49 ТЗ CIO «Costs». Печатаем не только вердикт, но и РАЗЛОЖЕНИЕ и
        # СТОРОНУ ошибки: «стоимость учитывается» — правда, но она заряжается
        # тремя литералами, а газ при этом наблюдается живьём в той же единице.
        # Заряженная дороже наблюдённой означает ложные отказы перекладки, то
        # есть неподвижную книгу — ровно ту жалобу, с которой начато ТЗ.
        c = data.get("counts") or {}
        out.append(f"   стоимость перекладки в решении: "
                   f"{data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        ch = data.get("charged") or {}
        if ch:
            out.append(f"   заряжено ${ch.get('total_usd', 0):,.2f} = газ "
                       f"${ch.get('gas_usd', 0):,.2f} + слиппедж "
                       f"${ch.get('slippage_usd', 0):,.2f} + мост "
                       f"${ch.get('bridge_usd', 0):,.2f}"
                       + ("" if ch.get("consistent") else
                          "  ⚠️ разложение РАЗОШЛОСЬ с `_move_cost_usd`"))
        s = data.get("substitution") or {}
        if s:
            out.append(f"   газ: заряжено ${s.get('gas_usd_charged', 0):,.2f} против "
                       f"наблюдённых ${s.get('gas_usd_observed', 0):.4f} "
                       f"(×{s.get('gas_ratio_charged_over_observed')})")
            out.append(f"   payback {s.get('payback_days_charged')} → "
                       f"{s.get('payback_days_on_observed_gas')} дн. при горизонте "
                       f"{s.get('max_payback_days')}; зазор гейта "
                       f"×{s.get('gate_flip_margin')}; вердикт переворачивается: "
                       f"{s.get('verdict_would_flip')}")
            band = s.get("false_refusal_band_days")
            if band:
                out.append(f"   [СЛЕПОТА] полоса ложного отказа: при заряженном "
                           f"payback от {band[0]} до {band[1]} дн. решение говорит "
                           f"HOLD на стоимости, которой цепь не берёт")
        elif not (data.get("unchecked") or []):
            out.append(f"   подстановка наблюдённого газа: {_UNMEASURED}")
        for f in (data.get("findings") or []):
            if isinstance(f, dict) and f.get("severity") in ("CRITICAL", "WARN"):
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: `_move_cost_usd` и пороги демпфера НЕ трогаются — "
                   "подстановка наблюдённого газа меняет гейт, решающий о движении "
                   "капитала, это money-path и решение владельца")
    elif name == "apy_forecast_accuracy.json":
        # §49 ТЗ CIO «Forecast accuracy». Печатаем ТРИ разных ответа, потому что
        # это три разных утверждения и одно не заменяет другого: (1) на какой
        # популяции вообще снята калибровка, (2) насколько прогноз врёт по
        # величине и КУДА, (3) хватает ли этой ошибки, чтобы перевернуть гейт.
        # Один только вердикт читался бы как «прогноз проверен», тогда как
        # полностью сверенных дней может быть один на всю историю.
        c = data.get("counts") or {}
        out.append(f"   точность прогноза перекладки: "
                   f"{data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        pop = data.get("population") or {}
        if pop:
            out.append(f"   популяция: наблюдено {pop.get('days_observed')} дн., "
                       f"сверено {pop.get('scoreable')}, существенных "
                       f"{pop.get('band_material')}, ПОЛНОСТЬЮ сверено "
                       f"{pop.get('fully_checked')} (горизонт "
                       f"{pop.get('horizon_days')} дн.)")
        mag = data.get("magnitude") or {}
        if mag.get("n"):
            out.append(f"   обещано/вышло на {mag['n']} существенных дн.: "
                       f"{mag.get('min')}…{mag.get('max')} при медиане "
                       f"{mag.get('median')}")
        elif mag.get("reason"):
            out.append(f"   обещано/вышло: {_UNMEASURED} — {mag['reason']}")
        g = data.get("gate_relation") or {}
        if g.get("tightest_gate_margin"):
            out.append(f"   худшее завышение ×{g.get('worst_ratio_observed')} против "
                       f"самого узкого зазора гейта ×{g.get('tightest_gate_margin')} "
                       f"({g.get('margin_consumed_pct')} % зазора); гейт "
                       f"переворачивается: {g.get('error_exceeds_margin')}")
        for d in (data.get("sign_disagreements") or [])[:3]:
            out.append(f"   [СТОРОНА] {d.get('cycle_date')}: обещано "
                       f"{d.get('claimed_usd_per_day')} $/дн., вышло "
                       f"{d.get('realised_usd_per_day')} $/дн. — прогноз и факт "
                       f"разошлись ЗНАКОМ")
        for f in (data.get("findings") or []):
            if isinstance(f, dict) and f.get("severity") in ("CRITICAL", "WARN"):
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: прогноз и гейты `gain_above_band` / "
                   "`payback_within_horizon` НЕ трогаются — подстройка прогноза "
                   "меняет решение о движении капитала, это money-path")
    elif name == "cio_shadow_replay.json":
        # §38 ТЗ CIO «Historical replay». Печатаем ТРИ руки в ДВУХ колонках
        # стоимости, а не один «лучший» ответ: вопрос ТЗ — не «какая доходность
        # выше», а «улучшился ли risk-adjusted realized NET return», и разница
        # между валовой и чистой доходностью здесь и есть весь предмет.
        c = data.get("counts") or {}
        out.append(f"   исторический прогон CIO-тени: "
                   f"{data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        pop = data.get("population") or {}
        if pop:
            out.append(f"   популяция: наблюдено {pop.get('days_observed')} дн., "
                       f"общих сверенных {pop.get('common_scored_days')} из "
                       f"{pop.get('day_pairs')}; вердикты {pop.get('verdicts')}")
        for column, block in (data.get("comparison") or {}).items():
            if not isinstance(block, dict):
                continue
            if block.get("verdict"):
                out.append(f"   [{column}] {_UNMEASURED} — {block.get('reason')}")
                continue
            net = block.get("net_apy_pct") or {}
            out.append(f"   [{column}] чистая APY: книга {net.get('current')} % · "
                       f"тень {net.get('cio_hold')} % · оптимум {net.get('cio_opt')} % "
                       f"⇒ лучшая рука {block.get('best_net_arm')}; валовые "
                       f"расходятся на {block.get('gross_spread_pp')} пп")
        fr = data.get("false_rebalances") or {}
        if fr.get("checked"):
            out.append(f"   ложных перекладок {fr.get('false')} из "
                       f"{fr.get('checked')} проверяемых (не окупаются за "
                       f"{fr.get('max_payback_days')} дн.); не сверено "
                       f"{fr.get('unchecked')}")
        elif fr.get("verdict"):
            out.append(f"   ложные перекладки: {_UNMEASURED} — {fr.get('reason')}")
        for f in (data.get("findings") or []):
            if isinstance(f, dict) and f.get("severity") in ("CRITICAL", "WARN"):
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: прогон НИЧЕГО не двигает — порог оборота, "
                   "стоимость хода и гейты ADR-060 остаются как есть; правка по "
                   "его итогам money-path и решение владельца")
    elif name == "cio_failure_modes.json":
        # §47 ТЗ CIO «Failure modes». Печатаем ПОКРЫТИЕ, а не число находок:
        # вопрос ТЗ — «на скольких из десяти названных деградаций система НЕ
        # перекладывает книгу», и «отказывает на 3 из 10» с «5 находок»
        # читаются совершенно по-разному.
        c = data.get("counts") or {}
        t = data.get("tally") or {}
        total = data.get("conditions_total")
        out.append(f"   отказ пути решения на деградации входа: "
                   f"{data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        if t:
            out.append(f"   из {total} названных владельцем деградаций: "
                       f"отказывает {t.get('REFUSES')} · частично "
                       f"{t.get('PARTIAL')} · НЕ отказывает {t.get('PROCEEDS')} · "
                       f"не измерено {t.get('UNCHECKED')}")
        for pr in (data.get("probes") or []):
            if pr.get("outcome") in ("PROCEEDS", "PARTIAL"):
                out.append(f"   [{pr['outcome']}] «{pr.get('owner_wording')}» — "
                           f"{pr.get('detail')}")
        for f in (data.get("findings") or []):
            if f.get("severity") in ("CRITICAL", "WARN"):
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: ни одна дверь этим замером не строится — "
                   "добавить отказ в путь решения значит изменить путь, по "
                   "которому двигается капитал, это решение владельца")
    elif name == "cio_explainability.json":
        # §44 ТЗ CIO «Explainability». Печатаем СОСТАВ объяснения, а не число
        # находок: вопрос ТЗ — «сколько из восьми названных владельцем фактов
        # система произносит о своём решении», и «произносит 2 из 8» с «5
        # находок» читаются совершенно по-разному. Отдельной строкой — разрез
        # SILENT/ABSENT: «измерено, но молчим» чинится предложением, «не
        # считает никто» — измерителем, и путать их дорого.
        c = data.get("counts") or {}
        t = data.get("tally") or {}
        ctrl = data.get("control") or {}
        out.append(f"   состав объяснения владельцу: "
                   f"{data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        if not ctrl.get("passed"):
            out.append(f"   [НЕ ИЗМЕРЕНО] положительный контроль не пройден — "
                       f"{ctrl.get('reason') or 'причина не названа'}; счёт по "
                       f"фактам не читать")
        elif t:
            out.append(f"   книга «{data.get('subject_book')}»: из "
                       f"{data.get('facts_total')} фактов владельца "
                       f"произносится {t.get('SPOKEN')} · измерено, но молчим "
                       f"{t.get('SILENT')} · не считает никто {t.get('ABSENT')} "
                       f"· объяснять нечего {t.get('UNCHECKED')}")
        layer = data.get("explanation_layer") or {}
        if layer:
            out.append(f"   читатели объяснения: "
                       f"{', '.join(layer.get('consumers') or []) or 'НЕТ НИ ОДНОГО'}"
                       f" · в ежедневном отчёте: "
                       f"{'да' if layer.get('in_daily_channel') else 'НЕТ'}")
        for f in (data.get("findings") or []):
            if f.get("severity") in ("CRITICAL", "WARN"):
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: ни одно предложение во фразу владельцу этим "
                   "замером не дописывается — что система говорит о движении "
                   "денег, решает владелец")
    elif name == "cio_kill_switch_controls.json":
        # §42 ТЗ CIO «Kill switch». Печатаем СОСТАВ органов остановки, а не
        # число находок: вопрос ТЗ — «сколько из трёх названных владельцем
        # ручек у него есть и что каждая делает», и «есть 1 из 3, одна подменена»
        # с «4 находки» читаются совершенно по-разному. Отдельной строкой —
        # отделимость: это ВТОРОЕ требование §42, у него свой ответ.
        c = data.get("counts") or {}
        t = data.get("tally") or {}
        ctrl = data.get("control") or {}
        out.append(f"   органы остановки у владельца: "
                   f"{data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        if not ctrl.get("passed"):
            out.append(f"   [НЕ ИЗМЕРЕНО] положительный контроль не пройден — "
                       f"{ctrl.get('reason') or 'причина не названа'}; счёт по "
                       f"органам не читать")
        else:
            out.append(f"   из {data.get('controls_total')} названных владельцем: "
                       f"есть {t.get(_PRESENT)} · подменены другим эффектом "
                       f"{t.get(_CONFLATED)} · отсутствуют {t.get(_ABSENT)} · "
                       f"не измерено {t.get(_UNCHECKED_KEY)}")
            for ctl in (data.get("controls") or []):
                if ctl.get("outcome") in (_CONFLATED, _ABSENT):
                    out.append(f"   [{ctl['outcome']}] «{ctl.get('owner_wording')}» — "
                               f"{ctl.get('detail')}")
            sep = data.get("separability") or {}
            out.append(f"   остановка без остановки наблюдения: "
                       f"{sep.get('verdict') or _UNMEASURED} — {sep.get('reason')}")
        for f in (data.get("findings") or []):
            if f.get("severity") in ("CRITICAL", "WARN"):
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: ни один орган остановки этим замером не "
                   "строится — дать владельцу ручку, меняющую движение денег, "
                   "это решение владельца")
    elif name == "cio_auto_execution_limits.json":
        # §41 ТЗ CIO «Auto-execution limits». Печатаем СОСТАВ ограничений и
        # ПОВЕРХНОСТЬ, на которой каждое связывает, а не число находок: «нет 6
        # из 12, у 2 порог зашит в коде» и «12 находок» читаются совершенно
        # по-разному. Отдельной строкой — полусвязанные: ограничение, которое
        # работает у того, кто ПРЕДЛАГАЕТ, и молчит у того, кто ДОПУСКАЕТ, в
        # сводке «есть/нет» неотличимо от полностью работающего.
        c = data.get("counts") or {}
        t = data.get("tally") or {}
        ctrl = data.get("control") or {}
        out.append(f"   ограничения auto-execution: "
                   f"{data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        if not ctrl.get("passed"):
            out.append(f"   [НЕ ИЗМЕРЕНО] положительный контроль не пройден — "
                       f"{ctrl.get('reason') or 'причина не названа'}; счёт по "
                       f"ограничениям не читать")
        else:
            out.append(f"   из {data.get('limits_total')} названных владельцем: "
                       f"связывают с ручкой владельца {t.get(_BINDING)} · порог "
                       f"зашит в коде {t.get(_LITERAL)} · объявлены, но не "
                       f"спрашиваются {t.get(_DECLARED_INERT)} · отсутствуют "
                       f"{t.get(_ABSENT)} · не измерено {t.get(_UNCHECKED_KEY)}")
            for lim in (data.get("limits") or []):
                if lim.get("outcome") in (_DECLARED_INERT, _ABSENT, _LITERAL):
                    out.append(f"   [{lim['outcome']}] «{lim.get('owner_wording')}» "
                               f"— {lim.get('detail')}")
                for gap in (lim.get("gaps") or []):
                    out.append(f"   [ПОЛОВИНА] «{lim.get('owner_wording')}» на "
                               f"`{gap.get('surface')}`: {gap.get('gap')}")
        for f in (data.get("findings") or []):
            if f.get("severity") == "CRITICAL":
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: ни один порог этим замером не меняется и ни "
                   "одно недостающее ограничение не строится — это money-path "
                   "и решение владельца")
    elif name == "cio_target_producers.json":
        # Остаток ADR-250. Печатаем ПОИМЁННО производителей, у которых
        # ограничение не стои́т, и СОСТАВ живых книг — а не число находок:
        # «у двух производителей из пяти не стои́т ни одно из трёх» и «6 находок»
        # читаются совершенно по-разному. Живые книги идут отдельной строкой
        # потому, что именно они отличают теорию от сегодняшнего состояния.
        c = data.get("counts") or {}
        ctrl = data.get("control") or {}
        out.append(f"   производители цели: {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        if not ctrl.get("passed"):
            out.append(f"   [НЕ ИЗМЕРЕНО] положительный контроль не пройден — "
                       f"{ctrl.get('reason') or 'причина не названа'}; счёт по "
                       f"производителям не читать")
        else:
            silent: dict = {}
            for row in (data.get("matrix") or []):
                if row.get("outcome") == "SILENT":
                    silent.setdefault(row["producer"], []).append(
                        row.get("owner_wording"))
            out.append(f"   производителей цели {len(data.get('producers') or [])}; "
                       f"принимают нарушающую цель хотя бы по одному "
                       f"ограничению владельца: {len(silent)}")
            for producer, wordings in sorted(silent.items()):
                out.append(f"   [SILENT] {producer} — не стои́т: "
                           + "; ".join(f"«{w}»" for w in wordings))
        for book in (data.get("live_books") or []):
            if book.get("unchecked"):
                out.append(f"   [НЕ ИЗМЕРЕНО] книга {book.get('artifact')}: "
                           f"{book['unchecked']}")
            elif book.get("over_declared_cap"):
                out.append(f"   [СОСТОЯНИЕ] книга {book.get('artifact')} держит "
                           f"СЕГОДНЯ {book.get('t3_share'):.1%} в T3 при "
                           f"объявленном потолке "
                           f"{book.get('t3_declared_cap'):.0%} — разрыв не "
                           f"теоретический")
        for f in (data.get("findings") or []):
            if f.get("severity") == "CRITICAL":
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: недостающее ограничение этим замером НЕ "
                   "строится и ни один порог не меняется — это money-path и "
                   "решение владельца")
    elif name == "cio_component_map.json":
        # §46 ТЗ CIO. Два ответа порознь, потому что вопросов в §46 два:
        # «есть ли эквивалент» (чтобы не строить второй) и «несёт ли цепь ход».
        # Печатать только первое значило бы отчитаться «карта построена» о
        # ступени, чей продукт никто не читает.
        c = data.get("counts") or {}
        ctrl = data.get("positive_control") or {}
        out.append(f"   карта компонентов (§46): {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        if not ctrl.get("passed"):
            failed = [k for k, v in (ctrl.get("checks") or {}).items() if not v]
            out.append("   [НЕ ИЗМЕРЕНО] положительный контроль не пройден "
                       f"({', '.join(failed) or 'причина не названа'}) — счёт "
                       "по §46 не читать")
        else:
            out.append(f"   эквивалент есть у {data.get('stages_present')} из "
                       f"{data.get('stages_total')} ступеней владельца; "
                       f"стыков несут ход {data.get('edges_wired')} из "
                       f"{data.get('edges_total')}")
            for e in (data.get("edges") or []):
                if e.get("verdict") in ("ONE_WAY", "DEAD_END", "UNCHECKED"):
                    out.append(f"   [{e['verdict']}] {e.get('from_name')} → "
                               f"{e.get('to_name')}: {e.get('note') or ''}"[:400])
        for f in (data.get("findings") or [])[:6]:
            out.append(f"   [{(f.get('severity') or '').upper()}] {f.get('text')}"[:400])
        out.append("   ADVISORY: разорванный стык этим замером НЕ соединяется и "
                   "ни одна ступень не переносится — это money-path и решение "
                   "владельца")
    elif name == "cio_outcome_independence.json":
        # Заказ #517. Печатается СНАЧАЛА вердикт, потом ПОЧЕМУ: ответ «не
        # существует» верен, но его обоснование и есть содержание — оно говорит
        # владельцу, что ступень нельзя оживить правкой кода.
        c = data.get("counts") or {}
        ctrl = data.get("positive_control") or {}
        cands = data.get("candidates") or []
        per = data.get("per_candidate_verdict") or []
        ident = data.get("identity") or {}
        out.append(f"   независимое наблюдение исхода книги: "
                   f"{data.get('verdict') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"unchecked={_num(c, 'unchecked')})")
        if not ctrl.get("passed"):
            out.append("   [НЕ ИЗМЕРЕНО] положительный контроль не прошёл — "
                       "вердикту ниже верить нельзя")
        indep = sum(1 for v in per if v.get("independent"))
        out.append(f"   кандидатов {len(cands)}, независимых {indep}; личность "
                   f"нашего счёта задана: {'да' if ident.get('configured') else 'НЕТ'}")
        for f in (data.get("findings") or [])[:6]:
            out.append(f"   [{(f.get('severity') or '').upper()}] {f.get('text')}"[:400])
        out.append("   ADVISORY: ничего не соединено; оживить сверку нельзя правкой "
                   "кода — нужны наблюдатель вне `spa_core/execution/` и реальный "
                   "капитал на цепи, оба решения владельца")
    elif name == "shadow_blockade_attribution.json":
        # Заказ G5 (ADR-271). Порядок строк — порядок вопроса: сперва КОГО
        # назвала блокада, затем ЧЕЙ вход его связывает, и только потом причина
        # выше по течению. Владелец, увидев одно имя гейта, пошёл бы крутить
        # бюджет — ручку, которая на 11 из 21 дня не при чём.
        from spa_core.monitoring.shadow_blockade_attribution import format_report
        out.extend(format_report(data))
    elif name == "target_stability.json":
        # Заказ #534. Порядок строк — порядок вопроса: сперва ДЕТЕРМИНИЗМ
        # производителя и полнота возмущения (без них маржа не число, а
        # украшение), затем сколько КАПИТАЛА стои́т на марже меньше собственного
        # хода ставки, и только потом поимённые строки.
        from spa_core.monitoring.target_stability import format_report
        out.extend(format_report(data))
    elif name == "ranking_tie_census.json":
        # Заказ #535. Порядок строк — порядок вопроса: сперва КВАНТ ранжируемой
        # ставки и тай-брейк (перепись ничьих ничего не стои́т, если возмущение
        # идёт ниже кванта — так и вышло в первой редакции прибора), затем ДВА
        # ярлыка рядом, и только потом поимённые пары.
        from spa_core.monitoring.ranking_tie_census import format_report
        out.extend(format_report(data))
    elif name == "ranking_tie_persistence.json":
        # Заказ #536. Порядок строк — порядок вопроса: сперва ОПОРА («покрытие
        # журнала не меняет измеряемого») и КОНТРОЛЬ ОСИ ДНЕЙ, без которых
        # «серия» не число, а украшение; затем сама серия; и только в конце —
        # что замер НЕ мерил. Последнее стои́т в отчёте намеренно: владелец,
        # увидев одни серии, прочёл бы молчание про пару как «она не ничья».
        from spa_core.monitoring.ranking_tie_persistence import format_report
        out.extend(format_report(data))
    elif name == "decision_journal_coverage.json":
        # Заказ #539. Порядок строк — порядок вопроса: сперва ЩЕЛЬ («держит N,
        # пишет M») и ПРИЧИНА отсечения, затем поимённо каждый потребитель с
        # НАПРАВЛЕНИЕМ сдвига, и только потом находки. Направление стои́т в
        # отчёте намеренно: владелец, увидев «вердикт изменился» без счётчика
        # покрытия, прочёл бы цену потолка как поломку потребителя.
        from spa_core.monitoring.decision_journal_coverage import format_report
        out.extend(format_report(data))
    elif name == "decision_record_verdict_sensitivity.json":
        # Заказ #540. Порядок строк — порядок вопроса: сперва ДВЕ ПОВЕРХНОСТИ
        # (живой путь вердикта и путь реплея), затем КОНТРОЛЬ СПОСОБНОСТИ, и
        # только потом находки. Контроль стои́т ВЫШЕ находок намеренно: владелец,
        # увидев «ни один вердикт не перевернулся» без него, прочёл бы вакуум
        # как доказательство, что расширение записи безопасно.
        from spa_core.monitoring.decision_record_verdict_sensitivity import (
            format_report as _drvs_report,
        )
        out.extend(_drvs_report(data))
    elif name == "hit_rate_selection_bias.json":
        # Заказ #541. Порядок строк — порядок вопроса: сперва НАСЕЛЕНИЕ (на
        # каком подмножестве окна вообще посчитан hit_rate), затем ИНТЕРВАЛ и
        # положение порога взвода в нём, затем ТРИ ОСИ со своими контролями, и
        # только потом находки. Контроли стоят ВЫШЕ находок намеренно: владелец,
        # увидев «ось A не двигает ни одного исхода» без доказанной способности
        # перевернуть день, прочёл бы вакуум как доказательство отсутствия
        # смещения.
        from spa_core.monitoring.hit_rate_selection_bias import (
            format_report as _hrsb_report,
        )
        out.extend(_hrsb_report(data))
    elif name == "g1_verdict_recoverability.json":
        # Заказ #541. Порядок строк — порядок вопроса: сперва НАСЕЛЕНИЕ (сколько
        # дней журнала вообще без вердикта и сколько из них восстановимы в
        # принципе), затем ОТВЕТ В ДНЯХ по каждому чтению «G1 закрыт», затем
        # блокирующие ноги с их классом, и только потом контроли и находки.
        # Ключи печатаются рядом с днями намеренно: заказ прямо назвал подмену
        # «сколько ключей добавится» вместо «сколько дней получат вердикт».
        from spa_core.monitoring.g1_verdict_recoverability import (
            format_report as _g1vr_report,
        )
        out.extend(_g1vr_report(data))
    elif name == "unevidenced_leg_causes.json":
        # Заказ #543. Порядок строк — порядок вопроса: сперва НАСЕЛЕНИЕ (сколько
        # дней потеряли вердикт именно из-за неоценённой ноги), затем КЛАССЫ
        # причин, затем цена каждого класса В ДНЯХ и поимённый перечень дней, и
        # только потом контроли и находки. Доля печатается ПОСЛЕ перечня
        # намеренно: заказ прямо запретил отвечать одной долей.
        from spa_core.monitoring.unevidenced_leg_causes import (
            format_report as _ulc_report,
        )
        out.extend(_ulc_report(data))
    elif name == "leg_provenance_split.json":
        # Заказ #546. Порядок строк — порядок вопроса: сперва НАСЕЛЕНИЕ, потом
        # ОБА НОСИТЕЛЯ вместе с их границами (история git — про объявленную
        # дорогу; журнал расхождений — односторонний и с окном), и только потом
        # классы и дни. Носители идут ПЕРЕД числами намеренно: читатель,
        # увидевший «проводка не объясняет ничего» первой строкой, прочтёт это
        # как замер того, что исполнял флот, — чего прибор не утверждает.
        from spa_core.monitoring.leg_provenance_split import (
            format_report as _lps_report,
        )
        out.extend(_lps_report(data))
    elif name == "snapshot_minute_sensitivity.json":
        # Заказ #549. Порядок строк — порядок вопроса: сперва НАСЕЛЕНИЕ (сколько
        # пар вообще имеют два снимка), потом мигание, и только потом вердикт про
        # ЦЕЛЬ. Население идёт ПЕРВЫМ намеренно: читатель, увидевший «минута
        # решает цель» первой строкой, прочтёт это как замер всего портфеля, —
        # а носитель покрывает пять повторяющихся адаптеров, и его молчание об
        # остальных прибор называет третьим исходом, а не нулём.
        from spa_core.monitoring.snapshot_minute_sensitivity import (
            format_report as _sms_report,
        )
        out.extend(_sms_report(data))
    elif name == "decision_record_run_identity.json":
        # Заказ #550/#551. Порядок строк — порядок вопроса: сперва НАСЕЛЕНИЕ
        # (сколько дней вообще опознано по прогону), потом положение выжившего
        # прогона и знак отметки, и только потом ответы. Население идёт ПЕРВЫМ
        # намеренно: читатель, увидевший «в журнал не попало N прогонов» первой
        # строкой, прочтёт это как замер всего журнала, — а носитель прогонов
        # покрывает 19 дней из 36, и его молчание об остальных прибор называет
        # третьим исходом, а не нулём.
        from spa_core.monitoring.decision_record_run_identity import (
            format_report as _drri_report,
        )
        out.extend(_drri_report(data))
    elif name == "day_replacement_verdict_loss.json":
        # Заказ #552. Порядок строк — порядок вопроса: сперва ЭКСПОЗИЦИЯ
        # знаменателя hit_rate (на скольких прогонах стои́т каждый scored-день),
        # и только потом движение входа. Экспозиция идёт ПЕРВОЙ намеренно:
        # читатель, увидевший первой строкой «вход двигался на N днях», прочтёт
        # это как замер всего журнала, — а носитель прогонов покрывает часть дней,
        # и его молчание об остальных прибор называет третьим исходом, а не покоем.
        from spa_core.monitoring.day_replacement_verdict_loss import (
            format_report as _drvl_report,
        )
        out.extend(_drvl_report(data))
    elif name == "intraday_rate_input_movement.json":
        # Заказ #554. Порядок строк — порядок заказа дословно: сперва ПОКРЫТИЕ
        # («что носитель реально покрывает»), и только потом движение ставки.
        # Порядок не косметика: читатель, увидевший первой строкой «ставка
        # двигалась на N парах», прочтёт это как замер знаменателя hit_rate —
        # а население там ДРУГОЕ, и прибор говорит об этом раньше, чем называет
        # долю.
        from spa_core.monitoring.intraday_rate_input_movement import (
            format_report as _irim_report,
        )
        out.extend(_irim_report(data))
    elif name == "audit_trail_rate_input_coverage.json":
        # Заказ #555. Порядок строк — порядок вопроса: сперва ОСЬ ПРОГОНОВ (то,
        # что у трейла есть и чего не хватило предыдущему кандидату), и СРАЗУ за
        # ней ВЕЛИЧИНА. Порядок не косметика и закреплён тестом: читатель,
        # увидевший «трейл касается 7 дней знаменателя» и не увидевший следующей
        # строки, прочтёт это как «семь дней рассужены» — а рассужено ноль,
        # потому что ставки запись не несёт вовсе.
        from spa_core.monitoring.audit_trail_rate_input_coverage import (
            format_report as _atric_report,
        )
        out.extend(_atric_report(data))
    elif name == "run_axis_time_stitch.json":
        # Заказ #556. Порядок строк — порядок вопроса, и здесь он обязателен
        # дважды. Сперва ОСЬ (какое поле ею выбрано замером): ось, названная
        # числом, не названа вовсе, и без этой строки читатель не узнает, что
        # правило состоятельно на одном поле записи и пусто на другом. Затем —
        # ОГОВОРКА, и только потом ДОЛЯ: заказ прямо потребовал сказать, чего
        # сшивка не снимает, прежде чем называть долю, иначе «11 из 11
        # однозначных» прочтётся как «второй вход измерим», а переносит сшивка
        # на знаменатель ноль дней. Порядок закреплён тестом.
        from spa_core.monitoring.run_axis_time_stitch import (
            format_report as _rats_report,
        )
        out.extend(_rats_report(data))
    elif name == "rate_observation_census.json":
        # Заказ #557. Порядок строк — порядок вопроса, и здесь он обязателен
        # трижды. Сперва НЕЗАВИСИМОСТЬ источника: показание кандидата, который
        # оказался тем же писателем, не есть второе показание. Затем ОТВЕТ про
        # дни, которых носитель касается (третий исход заказа), и лишь потом —
        # ПРИГОДНОСТЬ к сравнению ПЕРЕД любой разницей: десять наблюдений дня и
        # ноль сравнимых пар совместимы, и читатель обязан узнать это раньше,
        # чем увидит размах. Контроль на несвязанном населении идёт последним:
        # «переписчик теряет прогоны» первой строкой прочлось бы как замер
        # знаменателя. Порядок закреплён тестом.
        from spa_core.monitoring.rate_observation_census import (
            format_report as _roc_report,
        )
        out.extend(_roc_report(data))
    elif name == "census_consumer_census.json":
        # Заказ #564. Порядок строк — порядок вопроса: сперва НАСЕЛЕНИЕ по
        # классам (заказ прямо потребовал его первым результатом), затем
        # согласие о значении `root`, и лишь потом — третий исход про зов
        # через переменную. Третий исход идёт ПОСЛЕ намеренно: «72 места не
        # измерены» первой строкой прочлось бы как замер потребителей, а это
        # прямо противоположное утверждение — что часть населения посмотреть
        # не удалось. Порядок закреплён тестом.
        from spa_core.monitoring.census_consumer_census import (
            format_report as _ccc_report,
        )
        out.extend(_ccc_report(data))
    elif name == "subject_population_census.json":
        # Заказ #565. Порядок строк — порядок вопроса: сперва НАСЕЛЕНИЕ (заказ
        # потребовал его первым результатом), потом РОЛЬ (список субъектов
        # против запрета — разные предметы), и лишь потом слепота. Слепота
        # первой строкой прочлась бы как доля от всего набора, а она — доля от
        # роли `coverage`. Порядок закреплён тестом.
        from spa_core.monitoring.subject_population_census import (
            format_report as _spc_report,
        )
        out.extend(_spc_report(data))
    elif name == "substring_structure_assertions.json":
        # Заказ #567. Порядок строк — порядок вопроса: сперва НАСЕЛЕНИЕ (заказ
        # потребовал его первым результатом), затем замер обрыва, и только потом
        # граница замера. Граница идёт ПОСЛЕ намеренно: читатель, увидевший «ещё
        # 91 утверждение» первой строкой, прочтёт это как население — чего замер
        # не утверждает и прямо называет неизмеренным.
        from spa_core.monitoring.substring_structure_assertions import (
            format_report as _ssa_report,
        )
        out.extend(_ssa_report(data))
    elif name == "haystack_origin_census.json":
        # Заказ #568. Порядок строк — порядок вопроса, и первая строка НЕ доля:
        # сперва утверждение «путь не свернулся ≠ соседа нет в репозитории»
        # (заказ потребовал сказать это ПРЕЖДЕ любой доли), затем разделение,
        # и только потом ловушка признака-по-имени.
        from spa_core.monitoring.haystack_origin_census import (
            format_report as _hoc_report,
        )
        out.extend(_hoc_report(data))
    elif name == "arming_wall_order.json":
        # Заказ #545. Порядок строк — порядок вопроса: сперва ОБА порядка снятия
        # стен с числами освобождённых дней, потом вердикт ветки, и только потом
        # потолок расширения. Потолок идёт ПОСЛЕ намеренно: читатель, увидевший
        # «внутри потолка N пар» первой строкой, прочтёт это как «расширение
        # починит» — чего замер не утверждает и прямо называет третьим исходом.
        from spa_core.monitoring.arming_wall_order import (
            format_report as _awo_report,
        )
        out.extend(_awo_report(data))
    elif name == "journal_backfill_material.json":
        # Заказ #544. Сперва НАЛИЧИЕ материала (по парам, поимённо), и только
        # потом его ПРОБА. Порядок не косметика: владелец, увидевший «40 из 41»
        # без следующей строки, прочёл бы «дыра закрывается задним числом» —
        # чего замер не утверждает и прямо говорит в `what_it_does_not_prove`.
        from spa_core.monitoring.journal_backfill_material import (
            format_report as _jbm_report,
        )
        out.extend(_jbm_report(data))
    elif name == "journal_population_backfill.json":
        # ADR-309. Порядок строк — порядок условия владельца: сперва ПЛАН с
        # меткой пробы, потом именованные отказы, и только потом строка о том,
        # что дописанное сегодня не читает никто. Метка идёт в ПЕРВОЙ строке
        # намеренно: читатель, увидевший «39 значений дописано» без неё,
        # прочтёт это как «ставки восстановлены», чего замер не утверждает.
        from spa_core.monitoring.journal_population_backfill import (
            format_report as _jpb_report,
        )
        out.extend(_jpb_report(data))
    elif name == "cio_substitution_census.json":
        # Заказ #518/#519. Порядок строк — порядок вопроса: сперва НАСЕЛЕНИЕ
        # (и прямо сказано, что оно не ответ), затем ДОСТИЖИМОСТЬ двумя
        # каналами, и только потом находки. Владелец, увидев одно население,
        # прочёл бы «в дереве 513 дефектов», чего замер не утверждает.
        c = data.get("counts") or {}
        ctrl = data.get("positive_control") or {}
        meas = data.get("measurement") or {}
        cen = meas.get("census") or {}
        clo = meas.get("closure") or {}
        reach = meas.get("reachable") or {}
        out.append(f"   подстановка вместо отказа: {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"unchecked={_num(c, 'unchecked')})")
        if not ctrl.get("passed"):
            out.append("   [НЕ ИЗМЕРЕНО] положительный контроль не прошёл — "
                       "числам ниже верить нельзя")
        out.append(f"   перепись: {cen.get('substitutions', _UNMEASURED)} подстановок "
                   f"в {cen.get('files', _UNMEASURED)} файлах, констант с объявляющим "
                   f"именем {cen.get('constants', _UNMEASURED)} — это НАСЕЛЕНИЕ, не находка")
        out.append(f"   достижимо от решения: {len(reach.get('substitutions') or [])} "
                   f"подстанов(ка/ки/ок) и {len(reach.get('constants') or [])} констант(а/ы) "
                   f"(замыкание {clo.get('import_modules', _UNMEASURED)} импортом + "
                   f"{clo.get('artifact_modules', _UNMEASURED)} артефактом)")
        for f in (data.get("findings") or []):
            sev = (f.get("severity") or "").upper()
            if sev in ("CRITICAL", "UNCHECKED"):
                out.append(f"   [{sev}] {f.get('text')}"[:400])
        out.append("   ADVISORY: ни одна подстановка этим замером НЕ удалена и ни один "
                   "вызов не изменён — правка любого найденного места это money-path "
                   "и решение владельца")
    elif name == "cio_post_trade_verification.json":
        # §5 ТЗ CIO, ступень `post-trade verification`. Печатаются ТРИ ответа
        # порознь, потому что они и есть три разных вопроса: есть ли предмет ·
        # подают ли ступени наблюдённый исход · про ту ли книгу её последнее
        # слово. Предмет идёт ПЕРВЫМ намеренно: «верифицировать нечего» —
        # полный и честный ответ, и остальные строки при нём не находки.
        c = data.get("counts") or {}
        ctrl = data.get("positive_control") or {}
        subj = data.get("subject") or {}
        inp = data.get("inputs") or {}
        icounts = inp.get("counts") or {}
        out.append(f"   сверка исполненного (§5): {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        if not ctrl.get("passed"):
            failed = [x.get("name") for x in (ctrl.get("checks") or [])
                      if not x.get("passed")]
            out.append("   [НЕ ИЗМЕРЕНО] положительный контроль не пройден "
                       f"({', '.join(filter(None, failed)) or 'причина не названа'}) "
                       "— счёт по §5 не читать")
        else:
            out.append(f"   предмет: {subj.get('verdict') or _UNMEASURED} — "
                       f"ходов книги {subj.get('moves')}, последний "
                       f"{subj.get('last_move') or 'нет'}")
            out.append(f"   вызовов сверки вне тестов {inp.get('sites_production')}: "
                       f"с наблюдённым исходом {icounts.get('OBSERVED')}, "
                       f"из своей же цели {icounts.get('DERIVED_FROM_TARGET')}, "
                       f"не разобрано {icounts.get('UNCHECKED')}")
        for f in (data.get("findings") or [])[:6]:
            out.append(f"   [{(f.get('severity') or '').upper()}] {f.get('text')}"[:400])
        out.append("   ADVISORY: ступени НЕ подаётся фактический исход этим "
                   "замером — соединение стыка это money-path и решение владельца")
    elif name == "cio_policy_change_procedure.json":
        # §48 ТЗ CIO. Печатаются ДВА ответа порознь, потому что требование
        # владельца из двух половин: «не ослаблять молча» (что изменилось и в
        # какую сторону) и «сформировать proposal» (находят ли решение по тому
        # пути, который называет инструкция). Ослабление с достижимым решением
        # находкой не является — иначе строка кричала бы о выполненной процедуре.
        c = data.get("counts") or {}
        ctrl = data.get("positive_control") or {}
        relaxed = data.get("knobs_relaxed") or []
        out.append(f"   правки Risk Policy (§48): {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        if not ctrl.get("passed"):
            failed = [x.get("name") for x in (ctrl.get("checks") or [])
                      if not x.get("passed")]
            out.append("   [НЕ ИЗМЕРЕНО] положительный контроль не пройден "
                       f"({', '.join(filter(None, failed)) or 'причина не названа'}) "
                       "— счёт по §48 не читать")
        else:
            out.append(f"   против снимка v1.0: ослаблено {len(relaxed)}"
                       f"{' (' + ', '.join(relaxed) + ')' if relaxed else ''}, "
                       f"добавлено {len(data.get('knobs_added') or [])}, "
                       f"не менялось {data.get('knobs_unchanged')} из "
                       f"{data.get('knobs_total')}")
        for f in (data.get("findings") or [])[:6]:
            out.append(f"   [{(f.get('severity') or '').upper()}] {f.get('text')}"[:400])
        out.append("   ADVISORY: ни один порог этим замером НЕ меняется и ни одно "
                   "решение не переносится — правка порога это money-path и "
                   "решение владельца")
    elif name == "cio_architecture_constraints.json":
        # §45 ТЗ CIO. Печатаем ДВА ответа порознь — концентрацию и LLM, — потому
        # что владелец назвал их в одном пункте, а нарушаются они независимо.
        # Достижимость LLM печатается ВМЕСТЕ с каналом: путь через уведомление
        # владельца это explanation layer, который владелец разрешает, и строка
        # без канала читалась бы как нарушение там, где его нет.
        c = data.get("counts") or {}
        ctrl = data.get("control") or {}
        out.append(f"   разделение слоёв (§45): {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        if not ctrl.get("passed"):
            out.append(f"   [НЕ ИЗМЕРЕНО] положительный контроль не пройден — "
                       f"{ctrl.get('reason') or 'причина не названа'}; счёт по "
                       f"§45 не читать")
        else:
            conc = data.get("concentration") or {}
            out.append(f"   концентрация: максимум {conc.get('max')} из "
                       f"{conc.get('of')} ответственностей в ОДНОМ модуле; "
                       f"совмещают чтение рынка и подпись "
                       f"{len(conc.get('market_and_sign') or [])}")
            for row in (conc.get("modules") or []):
                if (row.get("count") or 0) >= 4:
                    out.append(f"   [МОНОЛИТ] {row.get('module')} "
                               f"({row.get('layer') or '—'}): "
                               + ", ".join(row.get("responsibilities") or []))
            llm = data.get("llm") or {}
            doors = llm.get("doors") or []
            out.append(f"   дверей к LLM в дереве: {len(doors)} — "
                       + (", ".join(f"{d['module']} [{d['kind']}]" for d in doors)
                          or "ни одной"))
            if not llm.get("reach_measured"):
                out.append(f"   [НЕ ИЗМЕРЕНО] достижимость двери LLM: "
                           f"{llm.get('reach_reason')}")
            else:
                for layer, row in (llm.get("by_layer") or {}).items():
                    hits = row.get("modules_reaching") or 0
                    if not hits:
                        continue
                    channel = ("через канал объяснения владельцу"
                               if row.get("through_explanation_channel")
                               else "НЕ через канал объяснения")
                    out.append(f"   · {layer}: достижим у {hits} модул(я/ей), "
                               f"{channel}")
            guard = llm.get("guard") or {}
            if not guard.get("measured"):
                out.append(f"   [НЕ ИЗМЕРЕНО] слепота сторожа инварианта #3: "
                           f"{guard.get('reason')}")
        for f in (data.get("findings") or []):
            if f.get("severity") == "CRITICAL":
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: ответственности этим замером НЕ разносятся и "
                   "сторож НЕ расширяется — это money-path и решение владельца")
    elif name == "decision_audit_trail.json":
        # §43 ТЗ CIO «Audit trail». Печатаем ДЕВЯТЬ полей владельца поимённо, а
        # не одно число находок: вопрос ТЗ — «через месяц ответить ЧЕРЕЗ ДАННЫЕ»,
        # и «6 из 9 не восстановимы» и «6 находок» читаются совершенно по-разному.
        c = data.get("counts") or {}
        out.append(f"   объяснимость прошлой перекладки по данным: "
                   f"{data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')})")
        pop = data.get("population") or {}
        if pop:
            out.append(f"   перекладок в трейле {pop.get('moves')} "
                       f"({pop.get('oldest_move_date')}…{pop.get('newest_move_date')}); "
                       f"объяснимы ПОЛНОСТЬЮ {pop.get('fully_answerable')}; старше "
                       f"месяца {pop.get('moves_older_than_owner_horizon')}")
        fields = data.get("owner_fields") or {}
        if fields:
            answering = [v.get("owner_wording") for v in fields.values()
                         if isinstance(v, dict)
                         and (v.get("counts") or {}).get("present") == pop.get("moves")]
            out.append(f"   девять полей §43: отвечают данными {len(answering)} из "
                       f"{len(fields)} — " + (", ".join(answering) or "ни одного"))
            for key, v in fields.items():
                if not isinstance(v, dict):
                    continue
                cc = v.get("counts") or {}
                if cc.get("present"):
                    continue
                out.append(f"   · {v.get('owner_wording')}: нет вовсе {cc.get('absent')}, "
                           f"частично {cc.get('partial')}, не измерено "
                           f"{cc.get('unmeasured')} — {v.get('detail')}")
        ident = data.get("identity") or {}
        if ident.get("reused_ids"):
            out.append(f"   тождество хода: {ident.get('reused_ids')} из "
                       f"{ident.get('distinct_ids')} значений trade_id названы больше "
                       f"одного раза — join по имени хода отвечает не одним ходом")
        probe = data.get("snapshot_id_probe") or {}
        if probe.get("measured") and not probe.get("content_addressed"):
            out.append("   snapshot_id адресует ПРОГОН, а не содержимое снимка "
                       "(опыт: два вызова производителя на одном входе разошлись)")
        for f in (data.get("findings") or []):
            if isinstance(f, dict) and f.get("severity") == "CRITICAL":
                out.append(f"   [{f['severity']}] {f.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        out.append("   ADVISORY: схема трейла НЕ трогается — дописать поле в запись "
                   "решения значит изменить путь движения капитала, это money-path")
    elif name == "pool_identity_collision.json":
        # ДВА ключа — ОДИН контракт. Потолок концентрации считает ключи разными
        # предметами риска; если они ранжируются на одном пуле DeFiLlama, книга
        # берёт удвоенную долю одного контракта, а КАЖДЫЙ потолок при этом
        # честно доложит, что не нарушен. Пин («не запинен, потому что коллизия
        # известна») тождества не отменяет: незапиненный ключ по-прежнему
        # резолвится, ранжируется и финансируется — «не измерен», а не «не
        # подвержен».
        c = data.get("counts") or {}
        out.append(f"   тождество пулов: {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')}); "
                   f"ключей сверено: {len(data.get('keys_compared') or [])}")
        for col in (data.get("collisions") or []):
            if isinstance(col, dict):
                out.append(f"   [{col.get('severity')}] {col.get('message')}")
        # Отказ реестра, до которого не доходит исполнение. INFO-строки
        # («расходится, но ветка достижима — отказ состоится») поимённо не
        # печатаются: их восемь, вреда сегодня нет, и вынос их сюда научил бы
        # читателя пролистывать блок. Число звучит — это агрегация, не пропуск.
        loud = [u for u in (data.get("unreachable_refusals") or [])
                if isinstance(u, dict) and u.get("severity") in ("CRITICAL", "WARN")]
        for u in loud[:6]:
            out.append(f"   [{u.get('severity')}] {u.get('message')}")
        quiet = len(data.get("unreachable_refusals") or []) - len(loud)
        if quiet > 0:
            out.append(f"   … и {quiet} INFO-строк(и): реестр и класс адаптера объявляют "
                       f"отказ по-разному, но ключ не опрашивается ⇒ отказ состоится")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
    elif name == "evidence_staleness.json":
        # Лестница ADR-167 на ЖИВОЙ книге. Читается как «сколько наших денег
        # система ещё ВИДИТ». Три вещи звучат отдельно, потому что это три
        # разных события с разными правильными реакциями:
        #   MASS_BLINDNESS — ослепли ВСЕ разом ⇒ это НАША поломка, а не рынок:
        #     чинить фид, капитал не трогать (эвакуация по своей же аварии хуже);
        #   де-риск НАЗВАН — протокол невидим > 168 ч; исполнение money-path и
        #     owner-gated, поэтому строка зовёт к карточке, а не к правке;
        #   БЕЗ ЧАСОВ — у ключа нет отметки наблюдения вовсе, и лестница его не
        #     видит ПО ПОСТРОЕНИЮ (сокращать по незнанию возраста — угадывание).
        #     Эти деньги не станут видимы и после подключения money-path-ноги.
        c = data.get("counts") or {}
        u = data.get("usd") or {}
        out.append(f"   устаревание наблюдения (ADR-167): "
                   f"{data.get('overall') or _UNMEASURED} · действие "
                   f"{data.get('action') or _UNMEASURED} — свежих {_num(c, 'fresh')} "
                   f"мягких {_num(c, 'soft_stale')} жёстких {_num(c, 'hard_stale')} "
                   f"без часов {_num(c, 'unknown_age')}")
        if data.get("action") == "MASS_BLINDNESS":
            out.append(f"   [ТРЕВОГА] {data.get('reason')}")
            out.append("   капитал НЕ трогаем намеренно: ослепли все разом ⇒ "
                       "симптом НАШЕЙ поломки, чинить фид (ADR-167)")
        for r in (data.get("to_derisk") or [])[:6]:
            if isinstance(r, dict):
                out.append(f"   [ДЕ-РИСК НАЗВАН] {r.get('protocol')}: "
                           f"${r.get('held_usd', 0):,.0f} — {r.get('reason')}")
        if data.get("to_derisk"):
            out.append("   исполнение — money-path, owner-gated: карточка "
                       "`agent-derisk-po-slepote-podklyuchit-k-rebalansu`")
        if _num(c, "unknown_age"):
            names = ", ".join(sorted(
                str(r.get("protocol")) for r in (data.get("protocols") or [])
                if isinstance(r, dict) and r.get("stage") == "UNKNOWN_AGE"))
            out.append(f"   [БЕЗ ЧАСОВ] ${u.get('unknown_age', 0):,.0f} стоит на ключах "
                       f"без отметки наблюдения ({names}) — лестница их не видит "
                       f"ПО ПОСТРОЕНИЮ")
        for line in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {line}")
    elif name == "capital_evidence_coverage.json":
        # Приёмка §5 ТЗ владельца «Portfolio CIO»: какая доля НАШИХ ДЕНЕГ стоит
        # на наблюдении. До ADR-226 у числа не было производителя вовсе — его
        # выводили руками 02.08 (25 %), 19.08 и 04.09 (100 %), и приёмкой оно
        # быть не могло: то, что каждый раз считают заново, не краснеет.
        #
        # Число-ДВОЙНИК печатается рядом НАМЕРЕННО. `feed_coverage.live_pct`
        # читается как ответ и им не является: он считает АДАПТЕРЫ вселенной,
        # приёмка — ДОЛЛАРЫ развёрнутой книги. На 04.09 оба равны 100 %, и
        # именно поэтому подмену легко не заметить — расхождение в пп говорит
        # вслух, насколько два вопроса разошлись сегодня.
        usd = data.get("usd") or {}
        hist = data.get("history")
        out.append(f"   доля КАПИТАЛА, ранжированного по наблюдённым числам: "
                   f"{_num(data, 'capital_coverage_pct')}% (цель {_num(data, 'target_pct')}%, "
                   f"было {_num(data, 'baseline_pct')}% на 02.08) — вердикт "
                   f"{data.get('verdict_live_track') or data.get('verdict') or _UNMEASURED}"
                   f" · популяция: {data.get('population') or _UNMEASURED}")
        # ВСЕ книги (ADR-231). До цикла #490 строка выше была единственной, и
        # «100 %» читалось как ответ про весь капитал, будучи ответом про книгу
        # живого трека: рукава Balanced/Aggressive держали $200 778 на литералах
        # и в знаменатель не входили вовсе.
        agg = data.get("all_books") or {}
        if agg:
            measured = agg.get("books_measured") or []
            declared = agg.get("books_declared") or []
            out.append(f"   ВСЕ КНИГИ ({len(measured)} из {len(declared)} померены): "
                       f"покрытие {_num(agg, 'coverage_pct')}% — вердикт "
                       f"{agg.get('verdict') or _UNMEASURED}")
            for rec in (data.get("books") or []):
                if not isinstance(rec, dict):
                    continue
                busd = rec.get("usd") or {}
                out.append(f"   · {rec.get('book')}: {_num(rec, 'coverage_pct')}% из "
                           f"${_num(rec, 'deployed_usd')} (литералом ${_num(busd, 'literal')}"
                           f" · НЕ ИЗМЕРЕНО ${_num(busd, 'unmeasured')}) — "
                           f"{rec.get('verdict') or _UNMEASURED}")
                for row in (rec.get("by_protocol") or [])[:6]:
                    if isinstance(row, dict) and row.get("message"):
                        tag = _UNMEASURED if row.get("bucket") == "unmeasured" else "WARN"
                        out.append(f"       [{tag}] {row.get('message')}")
                for u in (rec.get("unchecked") or [])[:3]:
                    out.append(f"       [{_UNMEASURED}] {u}")
        out.append(f"   развёрнуто ${_num(data, 'deployed_usd')}: наблюдением "
                   f"${_num(usd, 'evidenced')} · помеченным литералом "
                   f"${_num(usd, 'literal')} · НЕ ИЗМЕРЕНО ${_num(usd, 'unmeasured')}")
        alp = data.get("adapters_live_pct")
        out.append(f"   рядом: живых АДАПТЕРОВ вселенной "
                   f"{alp if alp is not None else _UNMEASURED}% — это ДРУГОЙ вопрос "
                   f"(расхождение {_num(data, 'divergence_pp')} пп)")
        # Доллар без провенанса называется ПОИМЁННО и с причиной: «не 100 %» не
        # говорит, ЧТО чинить, а именно это и есть предмет гэпа G1.
        for row in (data.get("by_protocol") or []):
            if isinstance(row, dict) and row.get("message"):
                tag = _UNMEASURED if row.get("bucket") == "unmeasured" else "WARN"
                out.append(f"   [{tag}] {row.get('message')}")
        for u in (data.get("unchecked") or [])[:6]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
        # ТРЕНД, а не мгновение: ТЗ спрашивает «стало ли лучше и держится ли».
        # Окно считается по РАЗНЫМ книгам, а не по прогонам сторожа, и обрезка
        # окна возрастом журнала говорится вслух — «100 % за 30 суток» по
        # двухдневному журналу это ненаблюдение, а не хорошая новость.
        if isinstance(hist, dict) and hist.get("status") != "OK":
            out.append(f"   [НЕ ИЗМЕРЕНО] память покрытия: "
                       f"{hist.get('reason') or _UNMEASURED} — это НЕ «покрытие держалось»")
        elif isinstance(hist, dict):
            trunc = (" ⚠️ окно обрезано возрастом журнала: покрыто "
                     f"{hist.get('covered_days')} сут из {hist.get('window_days')}"
                     if hist.get("window_truncated") else "")
            out.append(f"   память: книг измерено {hist.get('books_measured')}, "
                       f"покрытие {hist.get('coverage_pct_min')}…"
                       f"{hist.get('coverage_pct_max')} %{trunc}")
            if hist.get("books_unmeasured"):
                out.append(f"   [НЕ ИЗМЕРЕНО] книг без числа покрытия: "
                           f"{hist.get('books_unmeasured')} — ряд с дырами и ряд без "
                           f"дыр это разные новости")
    elif name == "house_view_gap.json":
        # Схема ВЫМЕРЕНА по производителю (`monitoring/house_view_gap.py`):
        # расхождения лежат в `gaps`, счётчики — `warn`/`info`/`unchecked`.
        # Прежняя ветка читала `overall`/`counts.critical`/`findings` — ни одного
        # такого поля производитель не пишет, и обязательный шаг печатал
        # «вердикт: None (critical=None …)» при ДВУХ реальных расхождениях.
        # «None» глазом читается как «пусто, всё в порядке» — тот же fail-OPEN,
        # что уже разбирали соседней веткой в этом же файле.
        c = data.get("counts") or {}
        gaps = data.get("gaps") or []
        out.append(f"   расхождений house_view↔факт: {len(gaps)} "
                   f"(warn={_num(c, 'warn')} info={_num(c, 'info')} "
                   f"unchecked={_num(c, 'unchecked')})")
        for g in gaps[:8]:
            out.append(f"   [{g.get('severity')}] {g.get('message')}")
        if gaps[8:]:
            out.append(f"   … ещё {len(gaps) - 8} расхожден(ий) в отчёте")
        for u in (data.get("unchecked") or [])[:4]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u.get('check')}: {u.get('reason')}")
    elif name == "findings_bridge_report.json":
        # Имя и схема ВЫМЕРЕНЫ по производителю (`findings_bridge.REPORT_REL`),
        # а не по памяти: ветка звалась `findings_bridge.json` и читала поля
        # `counts.opened/pending` — такого файла нет ни у одного производителя,
        # такой схемы нет ни в одном отчёте. Ветка была мёртвой, и обязательный
        # шаг 0-офис печатал по мосту одну строку `generated_at`, хотя манифест
        # требует «deferred читать ОБЯЗАТЕЛЬНО». Тот же класс, что #144: правка
        # детали при мёртвой проводке зелёная и бесполезная.
        out.append(f"   мост находка→карточка: создано {len(data.get('created') or [])} · "
                   f"закрыто {len(data.get('closed') or [])} · отложено "
                   f"{len(data.get('deferred') or [])} · ждут гистерезиса "
                   f"{len(data.get('waiting_hysteresis') or [])} · "
                   f"открытых карточек {_num(data, 'open_cards')}")
        for f in (data.get("created") or [])[:5]:
            out.append(f"   + [{f.get('severity')}] карточка {f.get('card')}")
        for k in (data.get("deferred") or [])[:5]:
            out.append(f"   ⚠️ ОТЛОЖЕНО rate-limit'ом (карточки НЕТ): {k}")
        for k in (data.get("escalated") or [])[:5]:
            out.append(f"   ⬆️ эскалация WARN→CRITICAL: {k}")
        # Гистерезис ЗАКРЫТИЯ (ADR-161): находка пропала, но ряд молчаливых
        # прогонов ещё не набран. Печатать обязательно — иначе шаг 0-офис
        # показывает «мост ничего не закрыл» там, где мост ЖДЁТ подтверждения,
        # и это ровно та болезнь, которую ADR-161 лечит ВНУТРИ моста: молчаливый
        # порог неотличим от бездействия. Клауза дописывается ТОЛЬКО при >0 и
        # ключ НЕ внесён в `_READ_SCHEMA` намеренно — отчёты, написанные до
        # ADR-161, законно его не имеют, и требовать его значило бы поднять
        # «СХЕМА РАЗОШЛАСЬ» на собственной доставке.
        closing = data.get("closing_hysteresis") or []
        if closing:
            out.append(f"   ⏳ ждут ЗАКРЫТИЯ по гистерезису: {len(closing)} — находка пропала, "
                       f"но ряд молчаливых прогонов не набран (молчание одного прогона не есть починка)")
            for c in closing[:5]:
                out.append(f"      {os.path.basename(str(c.get('card') or '?'))}: "
                           f"{c.get('absent_count')}/{c.get('required')} прогон(а) подряд")
        for src in (data.get("sources_unread") or []):
            out.append(f"   [ИСТОЧНИК НЕ ПРОЧИТАН] {src}")
        # Доставка карточек на origin: `needs-owner` вне origin для очереди
        # владельца не существует, поэтому провал доставки — находка, а не деталь.
        d = data.get("delivery") or {}
        if d:
            st = d.get("status")
            if st in ("DELIVERED", "IDLE"):
                # «Наша правка уже на origin» названо ОТДЕЛЬНО от «доставлено»:
                # иначе прогон, где везти было нечего потому, что всё уже там,
                # читается как прогон, где везти было нечего вообще (#268).
                covered = len(d.get("covered_by_origin") or [])
                # «Origin пришёл к тому же исходу раньше нас» — ТРЕТЬЕ основание
                # «везти нечего», и названо оно отдельно от второго: там origin
                # содержит нашу запись, здесь он записал тот же переход СВОЕЙ
                # строкой (наше закрытие оказалось повторным). Схлопнув их, шаг
                # 0-офис перестал бы отличать «мы отстали» от «мы сделали дважды».
                outcome = len(d.get("same_outcome_on_origin") or [])
                out.append(f"   доставка карточек: {st} ({len(d.get('delivered') or [])} на origin"
                           + (f"; уже на origin, origin ушёл вперёд: {covered}" if covered else "")
                           + (f"; origin закрыл раньше нас (повторное закрытие): {outcome}"
                              if outcome else "")
                           + ")")
            else:
                out.append(f"   ⚠️ ДОСТАВКА КАРТОЧЕК {st}: {d.get('reason')} "
                           f"(пыталось {len(d.get('attempted') or [])})")
            # Долг доставки (ADR-081) — ОТДЕЛЬНАЯ строка, а не хвост статуса.
            # Статус говорит про ЭТОТ прогон, долг — про то, чего на origin нет
            # до сих пор; 12.08 схлопывание этих двух вопросов в один означало,
            # что через два часа `IDLE` покажет зелёную строку при трёх
            # недоставленных карточках, и потеря исчезнет из поля зрения.
            debt = d.get("debt")
            if debt is None:
                mark, why = _absent_block(name, data, "debt", root=root, now=now)
                out.append(f"   {mark} долг доставки НЕ ИЗМЕРЕН: в квитанции нет блока "
                           f"debt (ADR-081) — {why}")
            elif debt.get("unmeasured"):
                out.append(f"   ⚠️ долг доставки НЕ ИЗМЕРЕН: {debt['unmeasured']}")
            elif debt.get("count"):
                age = debt.get("oldest_hours")
                age_s = f"старшему {age}ч" if age is not None else "возраст не датируется"
                out.append(f"   ⚠️ ДОЛГ ДОСТАВКИ: {debt['count']} карточк(и) НЕ на origin "
                           f"({age_s}) — поедут следующим прогоном")
                after = debt.get("stale_after")
                for p in (debt.get("stale") or [])[:5]:
                    out.append(f"   ⛔ не рассасывается повтором "
                               f"(≥{after if after is not None else '?'} попыток), "
                               f"нужен человек: {p}")
                for dr in (debt.get("dropped") or [])[:5]:
                    out.append(f"   ⚠️ снято с долга: {dr.get('path')} — {dr.get('reason')}")
        else:
            mark, why = _absent_block(name, data, "delivery", root=root, now=now)
            out.append(f"   {mark} доставка карточек НЕ ИЗМЕРЕНА: в отчёте нет блока "
                       f"delivery — {why}")
        # Доставка СЛЕДА решения владельца (ADR-086) — отдельный вопрос от доставки
        # карточек: мост везёт то, что создал сам, а ответ владельца пишет БОТ, и
        # мост его не создавал никогда. Замер #247: 2 из 9 ответов не были в git
        # ни минуты (с 08.08). Молчание здесь читалось бы как «след на origin».
        oad = data.get("owner_answer_delivery")
        if oad is None:
            mark, why = _absent_block(name, data, "owner_answer_delivery",
                                      root=root, now=now)
            out.append(f"   {mark} след решения владельца НЕ ИЗМЕРЕН: в отчёте нет "
                       f"блока owner_answer_delivery (ADR-086) — {why}")
        else:
            ost = oad.get("status")
            if ost == "DELIVERED":
                out.append(f"   след решения владельца: доставлен "
                           f"{len(oad.get('delivered') or [])} → origin "
                           f"(коммит {oad.get('commit')})")
            elif ost == "IDLE":
                out.append(f"   след решения владельца: весь на origin "
                           f"({len(oad.get('already_on_origin') or [])} карточк(и))")
            else:
                out.append(f"   ⚠️ СЛЕД РЕШЕНИЯ ВЛАДЕЛЬЦА {ost}: {oad.get('reason')} "
                           f"(недоставлено {len(oad.get('pending') or [])})")
            for c in (oad.get("conflicts") or [])[:5]:
                out.append(f"   ⛔ ДВА РАЗНЫХ ОТВЕТА ВЛАДЕЛЬЦА, нужен человек: "
                           f"{c.get('card')} — {c.get('reason')}")
            # Третий исход (цикл #419): расходились, и владелец УЖЕ решил — origin
            # называет вытесненный ответ поимённо. Не ⛔ (звать некого) и не
            # молчание: невидимое вытеснение ничем не отличалось бы от того, что
            # сторож просто перестал смотреть на это поле.
            for s in (oad.get("superseded") or [])[:5]:
                out.append(f"   ↩︎ ответ ВЫТЕСНЕН более поздним, человек не нужен: "
                           f"{s.get('card')} — {s.get('reason')}")
            # Четвёртый исход (цикл #429): выбор владельца ОДИН, разошлись канал и
            # отметка. Не ⛔ — стороны выбирать не надо, спора о решении нет; но и
            # не молчание: 30.08 ровно половина «нужен человек» была об этом, и
            # настоящий спор тонул среди ложных.
            for pv in (oad.get("provenance") or [])[:5]:
                out.append(f"   ≈ тот же ВЫБОР владельца, разный провенанс "
                           f"(человек не нужен): {pv.get('card')} — {pv.get('reason')}")
            # Пятый исход (цикл #437): на origin `owner_choice` стоит, а автора у
            # него нет ни одного — его написал агент. Не ⛔ «два ответа владельца»:
            # ответ владельца ровно ОДИН, и звать его выбирать между собой и
            # агентской записью нельзя — этого он разрешить не может. Но и не
            # молчание: запись на origin НЕВЕРНА, чинить её надо.
            for ua in (oad.get("unattributed") or [])[:5]:
                out.append(f"   ✍︎ на origin owner_choice БЕЗ АВТОРА (не второй ответ "
                           f"владельца — запись без автора; чинить ЗАПИСЬ, не спрашивать "
                           f"владельца): {ua.get('card')} — {ua.get('reason')}")
            for u in (oad.get("unmeasured") or [])[:5]:
                out.append(f"   ⚠️ след НЕ ИЗМЕРЕН: {u.get('card')} — {u.get('reason')}")
    elif name == "loop_retro.json":
        # До этой ветки ретро печаталось как «(пусто)»: generic-ветка ищет
        # status/reason, а у ретро их нет — и ЕГО НАХОДКИ не показывались вовсе.
        # Мост их читает, но обязательный шаг цикла молчал о них, то есть
        # артефакт числился прочитанным, а прочитанного в нём не было ничего.
        fnd = data.get("findings")
        if not isinstance(fnd, list):
            mark, why = _absent_block(name, data, "findings", root=root, now=now)
            out.append(f"   {mark} находки ретро {_UNMEASURED}: в отчёте нет списка "
                       f"findings — {why}")
        else:
            out.append(f"   находок ретро: {len(fnd)}")
            for f in fnd[:5]:
                if isinstance(f, dict):
                    out.append(f"   [{f.get('severity') or _UNMEASURED}] "
                               f"{str(f.get('message') or f.get('key'))[:160]}")
            if len(fnd) > 5:
                out.append(f"   … ещё {len(fnd) - 5} (полный список — data/loop_retro.json)")
        # Полнота архива исходов — СУЖДЕНИЕ, а не возраст (#235: возраст решает
        # читатель, а суждение обязан вынести производитель). Возрастной бюджет
        # того же файла живёт в architecture_conformance и отвечает на свой вопрос.
        comp = data.get("outcomes_completeness")
        if not isinstance(comp, dict):
            mark, why = _absent_block(name, data, "outcomes_completeness",
                                      root=root, now=now)
            out.append(f"   {mark} полнота архива исходов {_UNMEASURED}: в отчёте нет "
                       f"блока outcomes_completeness — {why}")
        elif not comp.get("measured"):
            out.append(f"   ⚠️ полнота архива исходов {_UNMEASURED}: {comp.get('reason')}")
        elif comp.get("missing_days"):
            out.append(f"   🔴 архив исходов НЕПОЛОН: {comp.get('reason')}")
        else:
            out.append(f"   архив исходов полон: {_num(comp, 'expected_days')} закрыт(ых) "
                       f"evidenced-дн(я/ей) с якоря {comp.get('anchor_date')}, дыр нет")
    elif name == "loop_health.json":
        # СИБЛИНГ loop_retro.json, и та же авария — на файле, который её уже
        # объяснил. Ветка ретро заведена со словами «до неё ретро печаталось
        # как (пусто)»; пульс той же петли остался в generic-ветке, а она ищет
        # status/overall/posture/reason/summary, которых loop_health не пишет
        # ни одного. Живой замер 2026-08-28 03:2xZ: артефакт нёс recurrences
        # 3, cards_fate.unreadable 4 и card→close max 66.01ч, обязательный шаг
        # напечатал про него «(пусто)» и засчитал в «прочитано 22, не
        # прочитано 0». Артефакт объявлен в конституции с потребителем
        # `orchestrator` — то есть читать его ОБЯЗАНЫ, а прочитанного в нём не
        # было ничего.
        #
        # Что печатаем и почему именно это (порядок — по цене ошибки):
        #   * `unreadable` — статус карточки НЕ ИЗМЕРЕН: третий исход, который
        #     нельзя складывать ни с «взята», ни с «лежит» (иначе неизмеренное
        #     читается как благополучие);
        #   * `recurrences_total` — производитель сам называет рецидив
        #     СИСТЕМНОЙ причиной, а не случайностью;
        #   * `new` — карточки моста, которые никто не взял: это и есть пульс;
        #   * `note` производителя — его собственная оговорка «медианы по n<5
        #     не интерпретировать»; без неё числа читаются увереннее, чем их
        #     написал автор.
        fate = data.get("cards_fate")
        if not isinstance(fate, dict):
            mark, why = _absent_block(name, data, "cards_fate", root=root, now=now)
            out.append(f"   {mark} судьба карточек петли {_UNMEASURED}: в отчёте нет "
                       f"блока cards_fate — {why}")
        else:
            out.append(f"   петля ADR-066: открытых карточек {_num(data, 'open_cards')} · "
                       f"не взято {_num(fate, 'new')} · в работе {_num(fate, 'in_progress')} · "
                       f"закрыто человеком {_num(fate, 'done_by_human')} · "
                       f"автозакрыто {_num(fate, 'auto_closed')}")
            # Три строки — три РАЗНЫХ утверждения (#421). Раньше они были одной:
            # `unreadable` копил и «статуса не отдали», и «статус есть, но не из
            # перечисления», и живой замер 29.08 показал, что ВСЕ четыре карточки
            # были второго рода (`ingested`) — то есть шаг четвёртые сутки звал
            # разбирать слепое пятно, которого не было. Имена печатаются всегда:
            # число без имён — строка, по которой действовать нечем.
            if fate.get("other_status"):
                named = data.get("cards_other_status")
                tail = (" — " + " · ".join(f"{_basename(c.get('card'))} ({c.get('status')})"
                                           for c in named[:4])
                        if isinstance(named, list) and named else
                        f" — КАКИЕ именно, {_UNMEASURED}: в отчёте нет cards_other_status")
                out.append(f"   ℹ️ {fate['other_status']} карточк(и) моста живут в статусе "
                           f"ВНЕ перечисления петли (прочитаны, но это не new/in-progress/"
                           f"done){tail}")
            if fate.get("unreadable"):
                named = data.get("cards_unreadable")
                tail = (" — " + " · ".join(_basename(c.get("card")) for c in named[:4])
                        if isinstance(named, list) and named else
                        f" — КАКИЕ именно, {_UNMEASURED}: в отчёте нет cards_unreadable")
                out.append(f"   ⚠️ статус {fate['unreadable']} карточк(и) моста "
                           f"{_UNMEASURED}: статуса не отдали вовсе — это НЕ «взята», "
                           f"НЕ «лежит» и НЕ «закрыта»{tail}")
        rec = data.get("recurrences_total")
        if rec is None:
            mark, why = _absent_block(name, data, "recurrences_total", root=root, now=now)
            out.append(f"   {mark} рецидивы {_UNMEASURED}: в отчёте нет "
                       f"recurrences_total — {why}")
        elif rec:
            # Настоящее время — только для живых. Замер 29.08: из 4 рецидивов 2
            # закрыты и молчат с 25–26.08, а строка кричала о всех четырёх как о
            # сегодняшнем событии. Счётчик `recurrences` не стареет никогда, и
            # такая строка перестаёт быть сигналом ровно потому, что верна всегда.
            live = data.get("recurrence_liveness")
            if not isinstance(live, dict):
                out.append(f"   🔴 РЕЦИДИВ: {rec} находк(а/и) ВЕРНУЛИСЬ после закрытия — "
                           "по производителю это системная причина, а не случайность")
                mark, why = _absent_block(name, data, "recurrence_liveness",
                                          root=root, now=now)
                out.append(f"      {mark} живой рецидив от исторического {_UNMEASURED}: "
                           f"в отчёте нет recurrence_liveness — {why}")
            elif live.get("live"):
                hist = (f" · ещё {live['historical']} исторических (закрыты и молчат "
                        f"с {str(live.get('historical_last_seen') or '')[:10]})"
                        if live.get("historical") else "")
                out.append(f"   🔴 РЕЦИДИВ ЖИВОЙ: {live['live']} находк(а/и) вернулись и "
                           f"СЕЙЧАС на доске{hist} — по производителю это системная "
                           f"причина, а не случайность")
            else:
                out.append(f"   ℹ️ рецидивов на доске СЕЙЧАС нет; {live.get('historical')} "
                           f"исторических (последний раз "
                           f"{str(live.get('historical_last_seen') or 'НЕ ИЗМЕРЕНО')[:10]}) — "
                           f"запись остаётся, требования к действию сегодня нет")
            # Голое число объявляло причину системной и не называло НИ ОДНОЙ
            # находки: действовать по такой строке нечем, и она возвращалась
            # каждый цикл нетронутой. Производитель теперь называет класс и
            # ключи (loop_health._recurrence_detail) — печатаем их, а если полей
            # нет (отчёт старого образца), говорим это вслух, а не молчим.
            by_class = data.get("recurrences_by_class")
            recurring = data.get("recurring_findings")
            if not isinstance(by_class, dict) or not isinstance(recurring, list):
                absent = ("recurrences_by_class" if not isinstance(by_class, dict)
                          else "recurring_findings")
                mark, why = _absent_block(name, data, absent, root=root, now=now)
                out.append(f"      {mark} ЧТО именно вернулось {_UNMEASURED}: в отчёте "
                           f"нет recurring_findings/recurrences_by_class — "
                           f"действовать по этой строке нечем; {why}")
            else:
                if len(by_class) == 1:
                    cls, n = next(iter(by_class.items()))
                    out.append(f"      причина ОДНА, а не пять: весь рецидив из класса "
                               f"`{cls}` ({n}) — чинить класс, а не находки поштучно")
                else:
                    out.append("      по классам: " + " · ".join(
                        f"`{c}` {n}" for c, n in list(by_class.items())[:4]))
                uncarded = [r for r in recurring if not r.get("carded")]
                if uncarded:
                    out.append(f"      🔴 вернулись и карточки СЕЙЧАС НЕТ ({len(uncarded)}): "
                               + " · ".join(f"{r.get('key')} ×{r.get('recurrences')}"
                                            for r in uncarded[:4]))
                for r in recurring[:4]:
                    out.append(f"      - {r.get('key')} ×{r.get('recurrences')} "
                               f"(статус {r.get('status')}, карточка "
                               f"{'есть' if r.get('carded') else 'НЕТ'})")
        for key, label in (("latency_finding_to_card", "находка→карточка"),
                           ("latency_card_to_close", "карточка→закрытие")):
            lat = data.get(key)
            if not isinstance(lat, dict):
                mark, why = _absent_block(name, data, key, root=root, now=now)
                out.append(f"   {mark} латентность {label} {_UNMEASURED}: в отчёте нет "
                           f"{key} — {why}")
            elif not lat.get("n"):
                out.append(f"   латентность {label}: измерять нечего (n=0)")
            else:
                out.append(f"   латентность {label}: медиана {lat.get('median_h')}ч · "
                           f"максимум {lat.get('max_h')}ч (n={lat.get('n')})")
        if data.get("note"):
            out.append(f"   оговорка производителя: {str(data['note'])[:160]}")
        # Пятый исход судьбы карточки: мост закрыл её в ПРОДЕ, а на `origin/main`
        # она осталась открытой — и закрытие наверх не возвращается ничем
        # (bridge_closure_drift). `cards_fate` про это не знает по построению:
        # он читает диск ЭТОГО дерева, а очередь по протоколу §3.4 читается из
        # worktree на origin. Цена измерена #480: карточку, снятую 25 дней назад,
        # цикл взял как открытую работу и дошёл до правды только через два
        # gitignored-артефакта. Молчание тут читалось бы как «расхождений нет».
        #
        # Отсутствие блока эта ветка НЕ комментирует СОЗНАТЕЛЬНО. На него уже
        # отвечает объявленная схема (`_READ_SCHEMA` + `_PRODUCER`), и отвечает
        # точнее: она различает «производитель ключа не пишет» и «артефакт
        # произведён РАНЬШЕ доставки ключа». Своя строка здесь означала бы
        # красное на здоровом контуре в каждый цикл до следующего такта
        # производителя — ровно та ложная тревога, которую сняли в #248.
        drift = data.get("closure_drift")
        if isinstance(drift, dict) and drift.get("verdict") == "unmeasured":
            out.append(f"   ⚠️ закрытия моста против origin/main {_UNMEASURED}: "
                       f"{drift.get('unmeasured_reason')}")
        elif isinstance(drift, dict) and drift.get("open_on_origin"):
            rows = drift["open_on_origin"]
            out.append(f"   🔴 ЗАКРЫТО В ПРОДЕ, ОТКРЫТО НА origin/main: "
                       f"{len(rows)} карточк(и) моста — очередь предъявляет циклам "
                       f"работу, снятую ранее (сверено с {str(drift.get('ref_sha'))[:9]})")
            for row in rows[:4]:
                out.append(f"      - {row.get('card_id')} (`{row.get('origin_status')}` "
                           f"наверху, ключ {row.get('key')}, закрыта "
                           f"{str(row.get('closed_at') or _UNMEASURED)[:10]})")
        elif isinstance(drift, dict):
            absent = drift.get("absent_on_origin") or []
            tail = (f" · на origin/main нет вовсе: {len(absent)} (направление "
                    f"РОЖДЕНИЯ, своя карточка)" if absent else "")
            out.append(f"   закрытия моста сверены с origin/main "
                       f"({str(drift.get('ref_sha') or _UNMEASURED)[:9]}): "
                       f"{_num(drift, 'checked')} закрыт(ых), сошлось "
                       f"{_num(drift, 'agreed')}{tail}")
    elif name == "owner_decision_pending.json":
        out.append(f"   статус: {data.get('status')}")
        if data.get("reason"):
            out.append(f"   {str(data['reason'])[:160]}")
        # Полнота очереди: видит ли это дерево ВСЕ вопросы владельца (цикл #270).
        # Отдельной строкой и всегда, по той же причине, что и кнопки ниже: `reason`
        # обрезается до 160 символов, а именно в хвосте стоят идентификаторы карточек,
        # ради которых строка и написана. Молчание тут читалось бы как «очередь полна» —
        # 17.08 ровно так и потерялся `own-34` (needs-owner на origin, файла в проде нет).
        gap = data.get("origin_queue")
        if not isinstance(gap, dict):
            mark, why = _absent_block(name, data, "origin_queue", root=root, now=now)
            out.append(f"   {mark} полнота очереди НЕ ИЗМЕРЕНА: в отчёте нет блока "
                       f"origin_queue — {why}")
        elif not gap.get("measured"):
            out.append(f"   ⚠️ полнота очереди НЕ ИЗМЕРЕНА: {gap.get('reason')}")
        elif gap.get("count"):
            # Исход печатается ПОИМЁННО у каждой карточки (цикл #439). До него строка
            # говорила «файла в дереве нет» про любую находку — а с #439 их три, и
            # чинятся они по-разному: файла нет · в дереве ДРУГОЙ текст (кнопка
            # владельца ответит под чужим вопросом) · ответ пережил свой вопрос.
            _kind_words = {"absent": "файла в дереве нет",
                           "differs": "в дереве ДРУГОЙ текст",
                           "answer_outlived_question": "ответ пережил свой вопрос"}
            names = ", ".join(
                f"{c.get('card_id')} [{_kind_words.get(str(c.get('kind')), c.get('kind') or 'исход не назван')}]"
                for c in (gap.get("hidden") or []))
            out.append(f"   ⚠️ очередь дерева НЕПОЛНА: {gap['count']} вопрос(ов) владельцу "
                       f"есть на {gap.get('ref')} ({str(gap.get('ref_sha'))[:9]}) и до "
                       f"владельца из этого дерева НЕ доходят — {names}")
        else:
            out.append(f"   очередь полна: живые вопросы владельца достижимы из дерева "
                       f"({gap.get('ref')} {str(gap.get('ref_sha'))[:9]})")
        # Третье плечо той же полноты (#351): вопрос владельцу, живущий ТОЛЬКО на
        # ВЕТКЕ. Его не видит ни строка выше (сверяет дерево с `origin/main`), ни
        # отправитель. Печатаем ВСЕГДА и сразу после неё: рядом эти две строки
        # означают «очередь измерена с обеих сторон», а строка выше в одиночку
        # читалась как утверждение о полноте, замера под которым не было.
        bgap = data.get("branch_queue")
        if not isinstance(bgap, dict):
            mark, why = _absent_block(name, data, "branch_queue", root=root, now=now)
            out.append(f"   {mark} вопросы на ВЕТКАХ НЕ ИЗМЕРЕНЫ: в отчёте нет блока "
                       f"branch_queue — {why}")
        elif not bgap.get("measured"):
            out.append(f"   ⚠️ вопросы на ВЕТКАХ НЕ ИЗМЕРЕНЫ: {bgap.get('reason')}")
        else:
            unread = bgap.get("unreadable") or []
            tail = (f"; НЕ ПРОЧИТАНО веток: {len(unread)}" if unread else "")
            if bgap.get("count"):
                names = ", ".join(
                    f"{c.get('card_id')} ({', '.join(c.get('branches') or [])})"
                    for c in (bgap.get("cards") or [])[:3])
                more = (f" (и ещё {bgap['count'] - 3})" if bgap["count"] > 3 else "")
                out.append(f"   ⚠️ вопросов владельцу ТОЛЬКО НА ВЕТКЕ: {bgap['count']} "
                           f"— ни задать, ни закрыть (веток прочитано "
                           f"{bgap.get('branches_read')}){tail}: {names}{more}")
            else:
                out.append(f"   вопросов, живущих только на ветке, нет "
                           f"(веток прочитано {bgap.get('branches_read')}){tail}")
            # Третий исход рядом с «потеряно» и «убрано с базы»: карточку прочитали
            # при разборе ветки и осознанно решили не везти. Печатается ОТДЕЛЬНОЙ
            # строкой и с основанием — «решено не везти» без автора закрыло бы что
            # угодно, а невидимое основание проверить нечем (карточка
            # `inbox-storozh-voprosy-vladeltsa-na-vetke-ne-zn`).
            dropped = bgap.get("dropped") or []
            if dropped:
                names = "; ".join(
                    f"{d.get('card_id')} — {d.get('by')}, {d.get('date')}: {d.get('reason')}"
                    for d in dropped[:3] if isinstance(d, dict))
                more = (f" (и ещё {len(dropped) - 3})" if len(dropped) > 3 else "")
                out.append(f"   🚮 прочитано и осознанно НЕ везём: {len(dropped)} — "
                           f"это РЕШЕНИЕ, а не потеря: {names}{more}")
            # Брак реестра решений — находка о САМОМ реестре. Молчать нельзя: строка
            # с меткой, которую сторож не принял, означает, что автор решение записал,
            # а система его не увидела, и обе стороны считают, что всё в порядке.
            issues = bgap.get("declaration_issues") or []
            if issues:
                names = "; ".join(f"{i.get('where')} — {i.get('reason')}"
                                  for i in issues[:3] if isinstance(i, dict))
                more = (f" (и ещё {len(issues) - 3})" if len(issues) > 3 else "")
                out.append(f"   ⚠️ реестр «не везём» с браком: {len(issues)} — "
                           f"объявлением НЕ считается, карточка остаётся потерей: "
                           f"{names}{more}")
        # Дрейф прод↔origin (цикл #273): отправленная карточка закрыта на origin, а
        # файла в прод-дереве нет. НЕ находка — но и не молчание: до #273 такие
        # строки неделю держали сторожа в WARNING как «не измерено», и именно ради
        # объяснения они оттуда ушли. Объяснение, которого не видно, ничего не стоит.
        closed = data.get("closed_on_origin")
        if isinstance(closed, list) and closed:
            names = ", ".join(f"{c.get('card_id')} (`{c.get('origin_status')}`)"
                              for c in closed if isinstance(c, dict))
            out.append(f"   дрейф прод↔origin: {len(closed)} отправленн(ая/ых) карточк(а/и) "
                       f"ЗАКРЫТЫ на origin, файла в прод-дереве нет — {names}")
        # Принятые поручения (#350): владелец нажал «Принято — беру в работу», и
        # карточка ОСТАЛАСЬ открытой, потому что «принято» — это обещание, а не
        # исполнение. Читатель у обещания ровно один — этот шаг; молчание здесь
        # вернуло бы ровно ту потерю, ради которой статус и заведён.
        # Блока нет вовсе ⇒ говорим «НЕ ИЗМЕРЕНО»: отчёт старого образца не имеет
        # права выглядеть как «принятых поручений нет».
        if "accepted" not in data:
            mark, why = _absent_block(name, data, "accepted", root=root, now=now)
            out.append(f"   {mark} принятые поручения НЕ ИЗМЕРЕНЫ: в отчёте нет блока "
                       f"accepted — {why}")
        else:
            accepted = data.get("accepted")
            accepted = accepted if isinstance(accepted, list) else []
            if accepted:
                names = ", ".join(
                    f"{c.get('card_id')} (принято {str(c.get('accepted_at') or 'когда — не записано')[:19]})"
                    for c in accepted if isinstance(c, dict))
                out.append(f"   ⚠️ принято владельцем, НЕ ИСПОЛНЕНО: {len(accepted)} "
                           f"поручени(е/я) ждут агента — {names}")
            else:
                out.append("   принятых и неисполненных поручений нет")
        # Дрейф прод↔origin ВТОРОГО рода (#472): карточка ЗДЕСЬ открыта, а на origin
        # закрыта и закрыта позже нашего последнего движения. Печатаем ВСЕГДА — и
        # находку, и «не измерено»: молчание об этой оси и есть тот дефект, ради
        # которого строка заведена (шаг 0-офис 2.6 ч заказывал сделанную работу).
        drift_here = data.get("closed_on_origin_open_here")
        if not isinstance(drift_here, dict):
            mark, why = _absent_block(name, data, "closed_on_origin_open_here",
                                      root=root, now=now)
            out.append(f"   {mark} закрытые на origin, открытые здесь, НЕ ИЗМЕРЕНЫ: в "
                       f"отчёте нет блока closed_on_origin_open_here — {why}")
        elif not drift_here.get("measured"):
            out.append("   ⚠️ закрыты ли на origin открытые здесь карточки — НЕ ИЗМЕРЕНО: "
                       f"{drift_here.get('reason', 'причина не названа')}")
        else:
            drifted = drift_here.get("drift") or []
            if drifted:
                names = ", ".join(
                    f"{d.get('card_id')} (`{d.get('origin_status')}` на origin "
                    f"с {str(d.get('origin_change_at') or 'когда — не записано')[:19]})"
                    for d in drifted if isinstance(d, dict))
                out.append(
                    f"   дрейф прод↔origin: {len(drifted)} карточк(а/и) открыт(а/ы) в этом "
                    f"дереве, а на origin УЖЕ ЗАКРЫТ(а/ы) — {names}. Это НЕ поручение и НЕ "
                    f"вопрос владельцу: работа сделана, устарела прод-копия "
                    f"(`nimbalyst-local/` в прод не возит никто)")
            else:
                out.append("   открытых здесь карточек, закрытых на origin, нет")
        accepted_origin = data.get("accepted_on_origin")
        if isinstance(accepted_origin, list) and accepted_origin:
            names = ", ".join(str(c.get("card_id")) for c in accepted_origin
                              if isinstance(c, dict))
            out.append(f"   дрейф прод↔origin: {len(accepted_origin)} принят(ое/ых) "
                       f"поручени(е/я) есть на origin, файла в прод-дереве нет — {names}")
        # Канал: уезжали ли владельцу сообщения с вариантами БЕЗ кнопок (жалоба 14.08).
        # Печатаем ОТДЕЛЬНОЙ строкой и всегда: молчание про этот вопрос читалось бы как
        # «кнопки в порядке», а до цикла #229 он был неизмерим по построению.
        ch = data.get("channel_buttons")
        if not isinstance(ch, dict):
            mark, why = _absent_block(name, data, "channel_buttons", root=root, now=now)
            out.append(f"   {mark} кнопки в канале НЕ ИЗМЕРЕНЫ: в отчёте нет блока "
                       f"channel_buttons — {why}")
        elif not ch.get("measured"):
            out.append(f"   ⚠️ кнопки в канале НЕ ИЗМЕРЕНЫ: {ch.get('reason')}")
        else:
            # Импорт локальный и защищённый: обязательный шаг 0-офис не имеет права
            # упасть из-за строчки оформления — упавший шаг это НЕ прочитанный офис.
            try:
                from spa_core.telegram.buttonless_audit import summary_line

                line = summary_line(ch)
            except Exception as exc:  # noqa: BLE001
                line = (f"⚠️ кнопки в канале НЕ ИЗМЕРЕНЫ: строку не собрать ({exc})")
            out.append(f"   {line}")
    elif name == "rebalance_trigger.json":
        # ADR-240. Generic-ветка печатала бы отсюда ОДНО слово — и слова этого
        # у файла нет вовсе (`status`/`overall`/`posture` он не пишет), то есть
        # артефакт уходил бы в «пустую» строку. Но главное не оформление:
        # `should_rebalance: false` при непустом `unmeasured` означает «повода
        # не нашли ТАМ, ГДЕ СМОТРЕЛИ», и это НЕ «повода нет».
        verdict = data.get("verdict")
        fired = data.get("triggered") or []
        unmeasured = data.get("unmeasured")
        mark = {"REBALANCE": "🔁", "UNCHECKED": "❓"}.get(str(verdict), "✅")
        out.append(f"   {mark} триггеры ребаланса (ADR-031): {verdict or 'ПОЛЕ НЕ НАЙДЕНО'}"
                   f" · сработали: {', '.join(fired) or '—'}")
        if unmeasured is None:
            out.append("   [СЛЕПОТА] поля `unmeasured` нет — файл писан до ADR-240: "
                       "`should_rebalance` там не отличает «повода нет» от «не смотрели»")
        elif unmeasured:
            out.append(f"   [НЕ ИЗМЕРЕНО] {len(unmeasured)} проверк(и) из 5 без входа: "
                       f"{', '.join(str(x) for x in unmeasured)}")
        for key, entry in sorted((data.get("checks") or {}).items()):
            if not isinstance(entry, dict):
                continue
            if entry.get("measured") is False:
                out.append(f"   · {key.upper()}: НЕ ИЗМЕРЕНО — "
                           f"{entry.get('unmeasured_reason') or 'причина не названа'}")
            elif entry.get("triggered"):
                out.append(f"   · {key.upper()}: сработал")
        srcs = data.get("inputs")
        if isinstance(srcs, dict) and srcs:
            out.append("   входы названы: "
                       + " · ".join(f"{k}={v}" for k, v in sorted(srcs.items())))
        out.append("   ADVISORY: капитал по этому вердикту НЕ двигается — живой ход "
                   "решают аллокатор + ADR-060 + демпфер ADR-168")
    elif name == "shadow_trigger_evaluation.json":
        # До цикла #487 этот артефакт попадал в generic-ветку и говорил ровно одно
        # слово — `NOT_READY`. Слово верное и бесполезное: оно одинаково звучит на
        # «копим дни» и на «взвод недостижим никаким ожиданием», а это два разных
        # ответа, и второй требует решения владельца.
        out.append(f"   статус: {data.get('status')} (готов к взводу: "
                   f"{'да' if data.get('ready_to_arm') else 'нет'}) · "
                   f"дней наблюдения {data.get('observation_days')} · "
                   f"ACT {(data.get('counts') or {}).get('act')}")
        for c in (data.get("criteria") or []):
            if c.get("status") != "PASS":
                out.append(f"   [{c.get('status')}] критерий {c.get('criterion')} "
                           f"{c.get('threshold')} (факт: {c.get('actual')})")
        try:
            from spa_core.paper_trading.shadow_trigger_eval import format_blockade

            blockade_lines = format_blockade(data.get("arming_blockade"))
        except Exception as exc:  # noqa: BLE001
            # Тот же приём, что у кнопок ниже: обязательный шаг 0-офис не имеет
            # права упасть из-за строчки оформления — упавший шаг это НЕ
            # прочитанный офис.
            blockade_lines = [f"Достижимость взвода: ⚠️ НЕ ИЗМЕРЕНА ({exc})"]
        out.extend(f"   {line}" for line in blockade_lines)
    else:
        status = data.get("status") or data.get("overall") or data.get("posture")
        if status is not None:
            out.append(f"   статус: {status}")
        reason = data.get("reason") or data.get("summary")
        if reason:
            out.append(f"   {str(reason)[:160]}")
    return head + (out or [
        f"{_HOLLOW_MARK}: ни ветки в `_summarize_json`, ни строки в "
        "`_READ_SCHEMA`, а generic-ветка не нашла ни `status`/`overall`/"
        "`posture`, ни `reason`/`summary`. Прочитано НИЧЕГО — это НЕ «пусто, "
        "всё в порядке» и НЕ «в файле ничего нет»: файл разобран не был."])


# Пустой разбор — ТРЕТИЙ исход, а не «прочитано». Четвёртый рецидив класса в этом
# файле (findings_bridge · house_view_gap · _health · loop_retro) прожил дольше
# всех остальных именно потому, что «(пусто)» ЗАСЧИТЫВАЛОСЬ в «прочитано»: 28.08
# шаг напечатал про `data/loop_health.json` «(пусто)», написал за него КВИТАНЦИЮ
# потребления и подвёл итог «прочитано 22, не прочитано 0» — при том, что в
# артефакте лежали 3 рецидива и 4 карточки со статусом «не измерено». Квитанция —
# это утверждение «я это прочитал», и на ней стоит проверка B3 сторожа
# архитектуры; правило самого модуля квитанций сказано прямо: «ресит пишется
# ТОЛЬКО после фактического успешного чтения — иначе B3 превращается в театр».
# Разобрать было нечем ⇒ читать было нечего ⇒ квитанции нет, и в итоге стоит
# отдельное число. Молчаливым «прочитано» этот исход больше не притворяется.
_HOLLOW_MARK = "   ⚠️ РАЗОБРАТЬ НЕЧЕМ"


def _summarize_md(full: str, *, now: dt.datetime | None = None) -> list[str]:
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        with open(full, encoding="utf-8") as f:
            head = [ln.rstrip() for _, ln in zip(range(12), f)]
    except Exception as e:  # noqa: BLE001
        return [f"   (md не прочитан: {e})"]
    stamp = None
    for ln in head:
        m = _MD_TS_RE.search(ln)
        if m:
            stamp = f"{m.group(1)}T{m.group(2)}:00+00:00"
            break
    body = ["   " + ln for ln in head if ln.strip()][:6]
    return [_age_line(stamp, now)] + body


def _resolve(rel: str, *, root: str, data_dir: str | None) -> str:
    """Куда смотреть за артефактом `rel`.

    Без `--data-dir` — как раньше, относительно `--root`.

    С `--data-dir` читается офис ТОГО дерева — целиком, включая
    `docs/SYSTEM_BRIEFING.md`. Первая редакция оставляла брифинг при своём
    дереве («это разные вопросы»), и замер показал, чем это кончается: из
    worktree выходило «прочитано 21, не прочитано 0», где 20 артефактов свежие
    (прод, минуты-часы), а брифинг — git-копия возрастом **1047.7 ч**, и оба
    слагаемых лежали под одним итогом. Смешанная свежесть под одним вердиктом —
    ровно тот дефект, против которого заведена эта правка, только тише.

    Манифест НЕ отсюда: конституция принадлежит дереву, которое проверяем
    (`--root`), а не тому, чьи артефакты читаем.
    """
    if data_dir:
        return os.path.join(os.path.dirname(data_dir), rel)
    return os.path.join(root, rel)


def _main_worktree(root: str) -> str | None:
    """Главное рабочее дерево — ПЕРВАЯ запись `git worktree list` (правило #234).

    Guard'ится целиком: обязательный шаг 0-офис не имеет права упасть из-за
    подсказки в тексте ошибки. Нет git / не репозиторий / что угодно ⇒ None,
    и вызывающий честно скажет «не измерено» вместо выдуманного пути.
    """
    try:
        import subprocess

        out = subprocess.run(["git", "-C", root, "worktree", "list"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode != 0:
            return None
        first = (out.stdout.splitlines() or [""])[0].strip()
        path = first.split(" ")[0] if first else ""
        return path or None
    except Exception:  # noqa: BLE001
        return None


#: Кто ЗАПУСКАЕТ производителя. Отличается от `_PRODUCER` (кто пишет файл):
#: два десятка переписей не имеют своего launchd-агента — их ступенью прогоняет
#: мост находок, и вопрос «отработал ли производитель» адресуется именно ему.
#: Артефакт бегуна назван здесь, чтобы у вопроса был ОДИН ответ данными.
_RUNNER_REPORT = "findings_bridge_report.json"


def _absent_verdict(rel: str, *, root: str, data_dir: str | None,
                    now: dt.datetime) -> tuple[bool, list[str]]:
    """Артефакта нет на диске — это находка или производитель ещё не отработал?

    Два состояния, до #524 неразличимые и печатавшиеся ОДНИМ текстом
    «❌ НЕ ПРОЧИТАН · файла нет на диске» под подписью «красные строки выше =
    действовать (карточки)»:

    * производитель отработал и файла не оставил — **находка**;
    * производитель приехал в дерево ПОСЛЕ последнего прогона своего бегуна —
      исправный контур, ответ будет на следующем прогоне.

    Живой замер 2026-09-08 (цикл #524): `cio_substitution_census.py` доставлен
    пушем в 07:42 и лёг в прод-дерево синком в 09:51; `com.spa.decision_loop`,
    который его зовёт, последний раз отработал в **07:05:59Z**. Обязательный шаг
    напечатал находку об исправном модуле — в песочнице он отрабатывает,
    `positive_control.passed` истинно. Тот же класс, что #248: там его закрыли
    для ПОЛЕЙ схемы («артефакт, произведённый ДО доставки ключа, не может его
    содержать»), а для самого СУЩЕСТВОВАНИЯ артефакта — нет.

    Различающий признак — **объявленный**, а не выведенный: мост записывает
    состав ступени переписей в `censuses.attempted` своего отчёта
    (`findings_bridge.CENSUS_STAGE`). Дата файла нужна только там, где
    объявления ещё нет, и ровно затем, чтобы третий исход не стал вечным:

    1. перепись НАЗВАНА в `attempted`, артефакта нет ⇒ **находка** (и причина,
       если бегун её записал в `censuses.skipped`);
    2. не названа, а отчёт бегуна СТАРШЕ производителя в дереве ⇒ «ЕЩЁ НЕ
       ПРОИЗВОДИЛСЯ» — третий исход, закрываемый следующим прогоном;
    3. не названа, а отчёт бегуна МОЛОЖЕ производителя ⇒ **находка**: код в
       дереве лежит, бегун после его прихода отработал и ступени не позвал —
       ровно форма ADR-259 (объявленный артефакт без производящего вызова);
    4. бегуна спросить нечем (нет отчёта, нет производителя в карте, файл
       производителя не найден) ⇒ прежнее поведение, **находка**. Молчать здесь
       нельзя: «не смог измерить» не есть «всё хорошо».

    ПОПРАВКА ЦИКЛА #525 — решение вынесено в
    `spa_core/monitoring/artifact_absence.py`, ОДНО на обоих читателей вопроса.
    Здесь остаётся только огранка в строки офиса. Перенос был не копированием:
    он замерил прежнюю реализацию и нашёл в ней две дыры, обе — от приёма
    «вывести вместо того, чтобы спросить объявление»:

    * **имя ступени выводилось** из имени файла модуля, а мост её ОБЪЯВЛЯЕТ.
      Для `data/evidence_staleness.json` эти имена разные (`evidence_staleness`
      против `evidence_staleness_monitor`), и ветка 1 не срабатывала НИКОГДА:
      реально провалившаяся перепись с записанной причиной уходила в ветку дат
      и при недавно правленом модуле объявлялась «ещё не производился» —
      **fail-OPEN**, направление опаснее ложной находки. То же у `outcomes`;
    * **бегун подставлялся чужой:** отчёт МОСТА сравнивался с датой модуля для
      любого артефакта карты, включая пять, которых мост не запускает вовсе
      (`architecture_conformance.json`, `chief_investment.json`, `_health.json`,
      `code_sync_status.json`, `rebalance_trigger.json`). Теперь такой артефакт
      получает честное `НЕ ИЗМЕРЕНО` и остаётся находкой.

    Возвращает `(находка?, строки)`.
    """
    from spa_core.monitoring import artifact_absence as _aa

    v = _aa.verdict(rel, root=root, data_dir=data_dir, now=now)
    plain = ["   файла нет на диске"]

    if v.kind == _aa.NOT_YET:
        return False, [
            f"   ⏳ ЕЩЁ НЕ ПРОИЗВОДИЛСЯ (это НЕ находка): производитель "
            f"{v.module} лежит в дереве {v.module_age_h:.1f}ч, а его бегун "
            f"({_RUNNER_REPORT}) последний раз отработал "
            f"{v.runner_ran_at} — ДО его прихода.",
            f"   Ответ будет на следующем прогоне бегуна. Если и тогда файла "
            f"не появится, строка станет находкой сама.",
        ]
    if v.kind == _aa.ATTEMPTED_AND_ABSENT:
        tail = ([f"   причина пропуска (записана бегуном): {v.skip_reason}"]
                if v.skip_reason else
                [f"   бегун ступень звал и о пропуске НЕ сообщил — файла всё "
                 f"равно нет"])
        return True, plain + [f"   {v.reason}"] + tail
    return True, plain + [f"   {v.reason}"]


def _office_absent_wholesale(targets: list[str], *, root: str,
                             data_dir: str | None) -> list[str] | None:
    """НИ ОДНОГО артефакта офиса в этом дереве — это ОДНА находка, а не двадцать.

    Почему это отдельная ветка, а не «пусть каждый файл скажет за себя».
    Артефакты офиса пишет ЖИВОЙ флот в прод-дерево, и они в `.gitignore`;
    в git-worktree их нет ПО ПОСТРОЕНИЮ. Прежний вывод давал оттуда двадцать
    строк «❌ НЕ ПРОЧИТАН · файла нет на диске» и подпись «красные строки выше =
    действовать (карточки)». Форма — полноценная находка, текст — прямое
    требование действовать; добросовестная сессия, работающая по §3.4 в
    изолированном worktree, заводит двадцать карточек о мёртвом инвест-офисе,
    которого нет (замер цикла #207 — ровно этот вывод первым же прогоном).

    Разделяющий признак ИЗМЕРЕН, а не угадан: в worktree каталог `data/` есть
    (326 файлов, git-tracked), нет именно РАНТАЙМНЫХ артефактов офиса — поэтому
    признак «нет каталога data/» не годится, а годится «ни один из целевых
    артефактов под data/ не существует». Если хоть один есть — дерево
    производящее, и пропажа соседа это НАСТОЯЩАЯ находка, её печатаем как
    прежде, по одной строке на артефакт.

    Возвращает строки вердикта либо None (обычный ход).
    """
    data_targets = [t for t in targets if t.startswith("data/")]
    if not data_targets:
        return None
    present = [t for t in data_targets
               if os.path.exists(_resolve(t, root=root, data_dir=data_dir))]
    if present:
        return None
    where = data_dir or os.path.join(root, "data")
    main_tree = _main_worktree(root)
    # НЕ подставлять сюда REPO_ROOT: он вычисляется от расположения САМОГО
    # скрипта, то есть из worktree указывает на worktree — совет «гоняйте из
    # прод-дерева (<этот же worktree>)» это выдуманный путь. Либо называем
    # главное дерево по правилу #234 (первая запись `git worktree list`), либо
    # не называем никакого.
    how = (f"гонять шаг 0-офис из ПРОД-дерева ({main_tree}) либо передать "
           f"--data-dir {os.path.join(main_tree, 'data')}"
           if main_tree else
           "гонять шаг 0-офис из ПРОД-дерева (того, куда пишет флот) либо "
           "передать --data-dir <прод>/data; какое дерево главное — здесь НЕ "
           "измерено (`git worktree list` недоступен), путь не выдумываю")
    return [
        f"⚠️ ОФИС НЕ ИЗМЕРЕН: ни одного из {len(data_targets)} артефактов офиса нет "
        f"в этом дереве ({where}).",
        "   Это ОДНА находка, а не "
        f"{len(data_targets)}: артефакты пишет живой флот в прод-дерево, они в "
        "`.gitignore`, и в git-worktree их нет по построению.",
        "   Карточек о «мёртвом инвест-офисе» по этому выводу заводить НЕЛЬЗЯ — "
        "офис не опровергнут, он не измерен.",
        f"   Что сделать: {how}.",
    ]


def _mandate_lines(now: dt.datetime) -> list[str]:
    """Строки о действующем мандате автономии — или честное «не измерено».

    Fail-CLOSED: если модуль не читается (старое дерево, битый импорт), это НЕ
    повод молча продолжать широко. Печатаем УЗКИЙ протокол и называем причину —
    неизмеренная широта полномочий обязана читаться как отсутствие широты.
    """
    try:
        from spa_core.governance.autonomy_mandate import summary_lines
    except Exception as e:  # noqa: BLE001
        return [
            f"⏹ мандат автономии: НЕ ИЗМЕРЕН ({type(e).__name__}: {e})",
            "   режим цикла: ОДНА безопасная задача за цикл (базовый протокол) — "
            "неизмеренная широта полномочий читается как её отсутствие",
        ]
    return summary_lines(now=now)


def main(argv=None, *, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="читать артефакты офиса из ЧУЖОГО дерева (обычно прод): "
                         "<прод>/data. Квитанции потребления уезжают туда же — "
                         "иначе сторож B3 доложит «офис не читают» на прочитанный офис")
    ap.add_argument("--consumer", default=CONSUMER)
    ap.add_argument("--no-receipts", action="store_true",
                    help="только чтение/печать, без квитанций (для проверок)")
    args = ap.parse_args(argv)
    now = now or dt.datetime.now(dt.timezone.utc)

    # ── Ширина собственных полномочий — ПЕРВОЙ строкой шага (ADR-101) ────────
    # Печатается ДО манифеста намеренно: «как мне сегодня работать» не должно
    # зависеть от того, читаются ли артефакты офиса. При `return 1` (нет
    # манифеста) и `return 3` (офис не измерить из этого дерева) ответ всё
    # равно уже произнесён. До ADR-101 срок мандата не знал никто: ADR-078
    # истёк 19.08, и вопрос о продлении задал ЦИКЛ РУКАМИ в последний день.
    for _ln in _mandate_lines(now):
        print(_ln)
    print()

    from spa_core.monitoring.consumption_receipts import write_receipt

    manifest_path = os.path.join(args.root, "architecture", "manifest.json")
    try:
        manifest = json.load(open(manifest_path))
    except Exception as e:  # noqa: BLE001
        print(f"❌ манифест не прочитан ({manifest_path}): {e} — шаг НЕ выполнен")
        return 1

    targets = [a["path"] for a in manifest.get("artifacts", [])
               if a.get("status") == "active" and args.consumer in (a.get("consumers") or [])]
    if not targets:
        print(f"❌ в манифесте нет active-артефактов с потребителем {args.consumer!r} — "
              f"проверить конституцию")
        return 1

    # Куда пишутся квитанции: они отвечают на вопрос «офис ЧИТАЮТ?» (B3), поэтому
    # обязаны лечь в то дерево, чьи артефакты прочитаны. Квитанция о прод-офисе,
    # осевшая в одноразовом worktree, исчезнет вместе с ним, и сторож честно
    # доложит «не читают» про прочитанное — fail-OPEN наизнанку.
    data_dir = os.path.abspath(args.data_dir) if args.data_dir else None
    receipt_root = os.path.dirname(data_dir) if data_dir else args.root

    print(f"— офис и сторожа → контекст оркестратора ({len(targets)} артефактов) —")
    if data_dir:
        print(f"— артефакты офиса читаются ИЗ ЧУЖОГО ДЕРЕВА: {data_dir} "
              f"(квитанции туда же: {receipt_root}) —")

    absent = _office_absent_wholesale(targets, root=args.root, data_dir=data_dir)
    if absent is not None:
        for ln in absent:
            print(ln)
        print("— итог: офис НЕ ИЗМЕРЕН (0 прочитано). Это НЕ «всё хорошо» и НЕ "
              "находка о состоянии офиса — измерять нечем из этого дерева. —")
        return 3

    consumed = failed = hollow = 0
    not_yet = 0
    for rel in sorted(targets):
        full = _resolve(rel, root=args.root, data_dir=data_dir)
        lines: list[str]
        ok = False
        pending = False
        if not os.path.exists(full):
            # Пропажа соседа при живых соседях — НЕ автоматически находка
            # (#524). Различает `_absent_verdict`, и различает объявлением
            # бегуна, а не догадкой.
            is_finding, lines = _absent_verdict(rel, root=args.root,
                                                data_dir=data_dir, now=now)
            pending = not is_finding
        elif rel.endswith(".json"):
            try:
                lines = _summarize_json(rel, json.load(open(full)), now=now,
                                        artifact_root=receipt_root)
                ok = True
            except Exception as e:  # noqa: BLE001
                lines = [f"   JSON не прочитан: {e}"]
        else:
            lines = _summarize_md(full, now=now)
            ok = bool(lines) and not any(
                ln.startswith("   (md не прочитан") for ln in lines)
        if ok and any(ln.startswith(_HOLLOW_MARK) for ln in lines):
            # Ресит НЕ пишется: см. `_HOLLOW_MARK`. Файл открылся и разобрался
            # как JSON — но прочитано из него не было ничего, и утверждать
            # обратное значит кормить проверку B3 собственным эхом.
            mark = "⚠️ ПРОЧИТАН ВХОЛОСТУЮ (ресит НЕ пишется)"
            hollow += 1
        elif ok:
            receipted = True if args.no_receipts else write_receipt(
                rel, args.consumer, root=receipt_root)
            mark = "✅" if receipted else "⚠️ (ресит НЕ записан)"
            consumed += 1
        elif pending:
            # Третий исход, и он ОТДЕЛЬНОЕ слагаемое итога: складывать его с
            # «прочитано» значило бы объявить измеренным то, чего никто не
            # мерил, а с «не прочитано» — вернуть ту самую ложную находку.
            mark = "⏳ ЕЩЁ НЕ ПРОИЗВОДИЛСЯ"
            not_yet += 1
        else:
            mark = "❌ НЕ ПРОЧИТАН"
            failed += 1
        print(f"{mark} {rel}")
        for ln in lines:
            print(ln)
    # ── критерии открытых карточек (ADR-208) ────────────────────────────────
    # Печатается ДО итоговой строки намеренно: «красные строки выше = действовать»
    # обязано покрывать и эту находку. Карточка, чей собственный критерий уже
    # выполнен, — единственный класс, которого не видит НИ мост (у ручной карточки
    # нет `finding_key`), НИ петля: её находил только тот, кто случайно брал
    # карточку в работу и перемерял (замер #450: 3 из 6).
    print()
    try:
        from spa_core.monitoring import card_acceptance
        _tracker = os.path.join(receipt_root, "nimbalyst-local", "tracker")
        for _ln in card_acceptance.report_lines(card_acceptance.audit(_tracker)):
            print(_ln)
    except Exception as _exc:  # noqa: BLE001 — молчание здесь = fail-OPEN
        print("— критерии открытых карточек —")
        print(f"   [{_UNMEASURED}] сверка критериев не выполнена: "
              f"{type(_exc).__name__}: {_exc}")
    print()

    # ── пины против гейта финансирования (ADR-236) ──────────────────────────
    # Проводка при рождении. Состояние СТОЯЧЕЕ и молчаливое: запинённый ключ,
    # которого нет в снимке оркестратора, гейт отклоняет как
    # `TVL unverified (missing)` при любом пине и любом живом TVL, то есть
    # решение владельца о смысле ключа невидимо тому, кто решает о деньгах.
    # Дёшево — два файла, без сети и без прогона аллокатора.
    try:
        from scripts.measure_pin_placement_effect import (
            gate_visibility_report_lines as _pin_lines,
            pins_invisible_to_the_gate as _pins_vs_gate,
        )
        _pin_ddir = data_dir or os.path.join(receipt_root, "data")
        for _ln in _pin_lines(_pins_vs_gate(_pin_ddir)):
            print(_ln)
    except Exception as _exc:  # noqa: BLE001 — молчание здесь = fail-OPEN
        print("— пины против гейта финансирования (ADR-236) —")
        print(f"   [{_UNMEASURED}] сверка не выполнена: "
              f"{type(_exc).__name__}: {_exc}")
    print()

    # Клауза о вхолостую ДОПИСЫВАЕТСЯ, а не переписывает итог: в здоровом
    # состоянии (hollow=0) строка та же, что и была, — соседние тесты сверяют её
    # дословно, и ослаблять их ради нового счётчика было бы нечестно.
    hollow_clause = (f", ⚠️ ВХОЛОСТУЮ {hollow} (разобрать нечем, ресит не "
                     f"записан — артефакт объявлен читаемым, а прочитано "
                     f"ничего)" if hollow else "")
    # Ровно та же осторожность, что и с «вхолостую»: клауза ДОПИСЫВАЕТСЯ, в
    # здоровом состоянии (not_yet=0) итоговая строка побайтово прежняя.
    pending_clause = (f", ⏳ ЕЩЁ НЕ ПРОИЗВОДИЛСЯ {not_yet} (производитель в "
                      f"дереве новее последнего прогона своего бегуна — это НЕ "
                      f"находка и НЕ прочитанное)" if not_yet else "")
    print(f"— итог: прочитано {consumed}{hollow_clause}{pending_clause}, "
          f"не прочитано {failed}. "
          f"Красные строки выше = действовать (карточки), это не декорация. —")
    return 0


if __name__ == "__main__":
    sys.exit(main())
