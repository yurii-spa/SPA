---
trackerStatus:
  type: inbox
title: "Восемь блоков публикуют число отсутствия, и не читает его никто (ADR-856, замер #974)"
status: new
source: nimbalyst
created: 2026-10-29
priority: high
finding_adr: ADR-856
acceptance_probe: additive_field_reader_distinguishes
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
