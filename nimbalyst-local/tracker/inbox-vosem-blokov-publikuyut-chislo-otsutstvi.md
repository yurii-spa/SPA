---
trackerStatus:
  type: inbox
title: "Восемь блоков публикуют число отсутствия, и не читает его никто (ADR-856, замер #974)"
status: done
source: nimbalyst
created: 2026-10-29
priority: high
finding_adr: ADR-856
acceptance_probe: additive_field_reader_distinguishes
status_trail:
  - "2026-11-17T23:12:27.692758+00:00 new -> done · queue.set_status/closed_by:оркестратор, цикл #1185/evidence:своя проба карточки additive_field_reader_distinguishes = satisfied (перемерена руками из worktree на origin/main c45ba398a: эталон различает unmeasured против measured_zero; население класса НАЗВАНО  · cycle-30620"
---

## Что измерено (цикл #974, ADR-856)

У **8 из 18** блоков, публикующих два населения одного набора записей, число
отсутствия публикуется и **не читает его НИКТО** в дереве (non-test). Это тот
же дефект ADR-851 на шаг РАНЬШЕ: различение «шага не звали» от «замера нуля» не
теряется у читателя — его там никогда и не было.

«Ключ не читают нигде» здесь ЗАМЕР, а не подозрение: имя числа отсутствия
различающее, и значения, которого код не читает ни разу, в вердикте нет по
построению.

| блок | ключ отсутствия |
|---|---|
| `spa_core/monitoring/claim_release_census.py:520 build_report` | `records_without_card` |
| `spa_core/monitoring/empty_release_causes.py:415 build_report` | `records_without_card` |
| `spa_core/monitoring/foreign_done_cost.py:531 build_report` | `records_without_card` |
| `spa_core/monitoring/failure_cause_census.py:537 as_json` | `stream_absent_for` |
| `spa_core/monitoring/rule_second_copy_census.py:19392` | `absent_sample`, `declared_absent_but_entered_truncated` |
| `spa_core/monitoring/slo_keepability.py:2669 measure` | `produces_without_slo` |
| `spa_core/monitoring/substring_structure_assertions.py:875 measure` | `text_without_neighbour` |
| `spa_core/monitoring/substring_structure_assertions.py:879 measure` | `text_without_neighbour` |

## Почему это не закрыто тем же циклом

Починка каждого есть правка ЧУЖОГО прибора, и делать её прицепом к замеру
значило бы менять предмет на ходу. Важно другое: у ТРЁХ из восьми ключ один и
тот же (`records_without_card`, карточки освобождения) — то есть это ОДНА
правка на три места, а не три разных.

## Что нужно сделать

1. Для каждого блока спросить, ЕСТЬ ли у его числа отсутствия читатель, которому
   оно нужно, — и если вердикт блока вообще выносится, провести число до него.
2. Число отсутствия, которому читатель НЕ нужен, — это кандидат на удаление, а
   не на проводку; решение назвать явно, а не оставить «пусть лежит».
3. Контроль в обе стороны: сцена «поля не несёт ни одна запись» обязана давать
   третий исход, сцена, отличающаяся РОВНО одним полем, — замер нуля.

## Как понять, что готово

`additive_field_reader_census.blocks_with_no_reader` короче восьми, и у каждого
ушедшего блока названо, что с его числом стало: проведено до вердикта либо
снято решением. Проба — `additive_field_reader_distinguishes`.

## Расхождение «проба ↔ предмет» (назвал цикл #1141, 2026-11-15)

Машинная проба карточки (`additive_field_reader_distinguishes`) по замеру шага 0-офис
**ВЫПОЛНЕНА**: эталон различает «unmeasured» против «measured_zero» на сценах, отличающихся
РОВНО полем, и население класса НАЗВАНО (блоков 26, читателей числа отсутствия 23 — оба
населения 11, только отсутствие 12).

**Но предмет заголовка жив.** Тот же прогон печатает **11** блоков, чьё число отсутствия
публикуется и НЕ ЧИТАЕТ НИКТО (`daily_report_census._ledger_shape`, `paper_apy_census._bar_shape`,
`card_acceptance._probe_ci_cause_axis_names_a_session_death`, `claim_release_census.build_report`,
`empty_release_causes.build_report`, `failure_cause_census.as_json`, `foreign_done_cost.build_report`,
`rule_second_copy_census.the_verdict_form_outside_the_closed_list`, `slo_keepability.measure`,
`substring_structure_assertions.measure` ×2) — то есть на 29-10 было 8, сегодня 11.

Поэтому карточка НЕ закрыта: проба меряет «население НАЗВАНО», а заголовок обещает «читателя
ПОЯВИЛИ». Закрыть по непокрывающей пробе значило бы похоронить живую находку, а править пробу
делающей сессии запрещено (`.claude/rules/acceptance.md` п. 2). Карточка остаётся `new`;
следующая берущая её сессия обязана вернуть её в `new` с НОВОЙ пробой по исходу «блоков без
читателя стало меньше» либо расписать предмет отдельной карточкой.
