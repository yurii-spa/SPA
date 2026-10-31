---
trackerStatus:
  type: inbox
title: "Три критерия go-live переписать на настоящую проводку: решение владельца 31.10, вариант 1 (шесть баллов из десяти — константа)"
status: done
source: nimbalyst
created: 2026-10-31
priority: high
twin_key: "sha256:eaa4f5c2753151da7aae93533cee76f8e768198d9c1407b69d4dcdc0d90b5a88"
claimed_by: cycle-50145
claimed_at: 2026-10-31T15:10:15Z
claimed_run_id: orchestrator-50145-F5765D1FF43C4AA6A35AC38D3AB00D8E
claimed_pid: 50145
claimed_pid_start: Sat Oct 31 16:01:15 2026
acceptance_probe: golive_criteria_ask_the_producer
status_trail:
  - "2026-10-31T15:21:54.244806+00:00 new -> in-progress · queue.set_status · cycle-50145"
  - "2026-10-31T15:50:15.241055+00:00 in-progress -> done · queue.set_status/closed_by:cycle-50145/evidence:проба golive_criteria_ask_the_producer = satisfied (6/6 баллов писателя против 0/6, PASS/approved против WARN/mark_without_signature, 4 PASS против 0 при одинаковом присутствии); ADR-879; батарея 20 p · cycle-50145"
---

## Что решено владельцем

**Вариант 1** (ответ 31.10, telegram, `owner_choice: 1`, ADR-878): переписать все три места на
НАСТОЯЩУЮ проводку. Владелец отвечал так же 23.07 («честная import-проверка для ВСЕХ
критериев-адаптеров») и 13.09 по C012 («переписать критерий на настоящую проводку»), и заранее
согласился с ценой: число готовности, скорее всего, УПАДЁТ до шести баллов в разделе «источники
данных».

## Что сделать (три правки, у каждой свой положительный контроль)

1. **`spa_core/analytics/golive_readiness_report.assess_data_sources`** — шесть баллов из десяти
   начисляются за присутствие четырёх git-tracked ИСХОДНИКОВ (`spa_core/utils/defillama.py`,
   `adapters/defillama_feed.py`, `analytics/t1_data_verifier.py`, `analytics/strategy_promoter.py`).
   Спрашивать вместо присутствия: у фида — свежую ЖИВУЮ ставку · у верификатора — свежий артефакт
   ЕГО прогона · у промоутера — запись о РЕАЛЬНОМ запуске.
2. **`spa_core/golive/checklist.check_wallet_ready`** — «wallet infrastructure confirmed by owner»
   по присутствию `data/wallet_ready.sentinel`. Спрашивать ЗАПИСАННУЮ подпись владельца
   (`wallet_ready_approved.json` с его ответом), а не файл-метку (инв. #14).
3. **`scripts/cycle_dry_run.check_files`** — `n_pass` за присутствие И РАЗМЕР обязательных
   `data/*.json`. Размер наблюдением не является так же, как присутствие.

## Как понять, что готово

У каждой правки контроль **В ОБЕ СТОРОНЫ**: зелено на живом производителе, КРАСНО, когда
производителя действительно нет (не «файла нет», а «писателя нет»). Падение числа готовности —
отдельной строкой журнала с ПРИЧИНОЙ, а не молча. Перепись ADR-876 на этих местах перестаёт
давать `presence_to_observed`:

```bash
python3 -m spa_core.monitoring.presence_as_observation_census   # находок должно стать меньше на 3
```

Пробу объявить ДО работы (`.claude/rules/acceptance.md`); подходящей в реестре сегодня нет —
значит её написание и есть первая работа по карточке.

## Чего НЕ делать

RiskPolicy v1.0, стоп-кран, живой трек — не трогать. Меняется ЧИСЛО ОТЧЁТА о готовности, а не
порог и не поведение гейта исполнения. Реальный капитал остаётся $0.
