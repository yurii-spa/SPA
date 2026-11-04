---
trackerStatus:
  type: inbox
title: Мост находок (decision_loop) не укладывается в 2 ч — перепись покрытия журнала решений гоняет вложенные симуляции окна на каждого читателя
status: new
created: 2026-11-02
twin_key: "sha256:e01301a5959a94215248a92e216088052afbcdc9d52bab33f153c11c815a16c4"
intake_kind: task
---

## Что случилось
Владелец решил включить `com.spa.decision_loop` (ADR-901 п. 5). Гейт перед деплоем (`check_agent_before_deploy.sh`)
отказал дважды: 180 с и затем 7800 с (штатный `RUN_TIMEOUT`) — прогон `findings_bridge --run` в песочнице держал ядро
на 99 % больше 2 ч 10 мин без единой записи в журнал и без дочерних процессов. Служба осталась ВЫКЛЮЧЕННОЙ.

## Где время (faulthandler, 3 снимка по 3 мин, песочница `SPA_DATA_DIR`)
`findings_bridge.main` → `decision_journal_coverage.run/measure/probe_readers/_reader_probe` →
`adapter_repair_price.run/measure/capacity_price/_capacity_of` → `judge_alone_price.capacity/_ask_judge` →
`shadow_trigger_eval.evaluate_window` → `trim_optimum.trim_optimum_census/compare_trim_optimum/search_admissible_optimum/
_largest_admissible_turnover/ok/_fill` → `risk.policy.check_portfolio_health`. Вложенные полные симуляции окна с
бинарным поиском оборота НА КАЖДОГО читателя — комбинаторная цена, не сеть и не блокировка.

## Что нужно
Ограничить цену ступени (такт / бюджет времени / кэш симуляций окна) так, чтобы прогон моста укладывался в разумный
срок; затем — гейт и включение по решению владельца (уже принято). Evidence:
`~/Documents/SPA_worktrees/arb_s4_evidence_2026-11-01/decision_loop_diag/` (стеки, вывод гейта).
Отдельно найден и исправлен в ветке `fix/deploy-gate-kills-the-group` дефект гейта: по тайм-ауту он оставлял python
агента сиротой (дважды снят вручную).

## Замер 2026-11-03 на коде r1 (`199e60ec8`, уже в `main`) — всё ещё НЕ укладывается

Изолированный полный `findings_bridge --run` (копия `data/`, `SPA_TRACKER_DIR` — ловушка, Keychain недоступен,
`timeout 7800`): старт 20:12:44Z, **код 124**. Пройдено: все переписи до `judge_alone_price`
(`run_identity_key_price` ≈ 40 мин, WARNING); не завершён `adapter_repair_price`. Пик RSS ≈ 664 МБ, одно ядро ~99 %.
Ускорение ×61 прибора цены адаптеров (perf/decision-loop) полную ступень не уложило. Служба `com.spa.decision_loop`
НЕ загружена (условие владельца 03.11 не выполнено). Evidence: `~/Documents/SPA_worktrees/release_evidence_2026-11-03b/dl_*`.
Следующий шаг: сэмплер ступеней на коде `main`, бюджет времени ступени переписей или вынос дорогих переписей из моста.
