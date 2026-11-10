---
trackerStatus:
  type: inbox
title: "Исполнить ответ владельца 10.11 (вариант 1): окно свежести 36 ч — и к снимку оркестратора, второму источнику доказательности (money-path, ADR-975)"
status: done
source: nimbalyst
created: 2026-11-10
priority: high
intake_kind: task
acceptance_probe: snapshot_evidence_ages_out
twin_key: "sha256:a2cee09da828fcc8bf7478a80b3c2f7c677e71bb1812c804049cb7d9a69fd22d"
status_trail:
  - "2026-11-10T13:07:28.985430+00:00 new -> done · queue.set_status/closed_by:cycle-63852/evidence:ADR-976: окно 36 ч применено к снимку оркестратора через ту же дверь _within_window; проба snapshot_evidence_ages_out на прод-данных = satisfied; прибор §26 без evidence_that_never_ages; pre_cutover_g · cycle-63852"
---

## Что случилось и почему это важно

10.11 владелец ответил на вопрос «Проверка свежести данных не применяется к нашему
собственному снимку» (карточка `owner-decision-proverka-svezhesti-dannyh-ne-primenyaets`,
ответ записан ADR-975): **вариант 1 — применить к снимку оркестратора то же окно 36 часов,
что и ко второму источнику.** Замер 09.11 (ADR-969, прибор
`spa_core/analytics/determinism_census.py`, ось C): ветка снимка `adapter_orchestrator_status.json`
в `_load_evidenced_apy` (`spa_core/allocator/allocator.py`) окна свежести не применяет — на
сдвиге часов на год десять протоколов остаются «с подтверждёнными данными», и гейт `_fundable`
на них никогда не скажет `unevidenced`. Утверждение `CLAUDE.md` «stale-фид → unevidenced»
верно про второй источник и неверно про этот.

## Что нужно сделать

Это задача агента — решение владелец уже принял, переспрашивать нельзя (ADR-285). Это
денежный путь (`spa_core/allocator/`, гейт допуска протокола к капиталу) —
`.claude/rules/risk-engine.md`: читать ADR-061/ADR-303 (окно 36 ч), ADR-969, ADR-975.

1. В ветке снимка оркестратора `_load_evidenced_apy` применить то же окно `_EVIDENCE_MAX_AGE_H`
   (36 ч) через ту же дверь `_within_window(as_of, fallback_ts)` с тем же входом `now`: возраст
   — от момента наблюдения записи адаптера (поле `as_of`/`updated_at` снимка, если есть), иначе
   от `generated_at` снимка. Неразбираемая отметка ⇒ не доказательство (fail-CLOSED, как у
   второго источника). Одно правило — одна дверь; второй копии окна не заводить.
2. Симметрично проверить `_load_evidenced_tvl` (ADR-969 ось C уже сверяет TVL на сдвиге —
   прибор скажет, остался ли там нестареющий источник).
3. Тесты в обе стороны с инъекцией `now` (правило deployment.md «время — вход»): снимок
   внутри окна ⇒ протокол `orchestrator_live`; за окном ⇒ отсутствует; второй источник
   не изменил поведения. Прогон `spa_core/paper_trading/pre_cutover_gate.py`.
4. Новый ADR исполнения (правило до → после → ответ владельца → проверка, форма ADR-839);
   строка `CLAUDE.md` «stale-фид → `allocator._fundable()` `unevidenced`» — дополнить «оба
   источника» с датой проверки.
5. Прибор §26 после правки: `python3 -m spa_core.analytics.determinism_census --data-dir
   <прод>/data --no-write` — находка `evidence_that_never_ages` обязана исчезнуть.

## Как понять, что готово

Проба `snapshot_evidence_ages_out` (реестр `card_acceptance.PROBES`) отвечает `satisfied`:
на дальнем сдвиге часов годных по APY протоколов нет ни у одного источника. Сегодня —
`not_satisfied` (на сдвиге 8760 ч остаются протоколы источника `orchestrator_live`).

## Что будет после

Прибор §26 перестаёт печатать `evidence_that_never_ages`; строка `CLAUDE.md` описывает оба
источника; карточка владельца `…proverka-svezhesti…` (уже `ingested`) получает ссылку на ADR
исполнения в реестре ответов.
