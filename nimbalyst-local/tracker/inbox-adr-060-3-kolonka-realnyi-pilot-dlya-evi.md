---
trackerStatus:
  type: inbox
title: "ADR-060 §3: колонка «реальный пилот» для EVIDENCE_MAX_AGE_H/HARD_STALE_H не подключена (в отличие от TriggerParams)"
status: new
source: nimbalyst
created: 2026-08-29
---

ADR-060 §3 задаёт две колонки для EVIDENCE_MAX_AGE_H (36ч paper / 12ч пилот) и EVIDENCE_HARD_AGE_H (168ч paper / 72ч пилот). TriggerParams.for_mode() (spa_core/allocator/rebalance_economics.py) получил обе колонки 2026-08-29 (test_capital_mode_thresholds.py). Но эти два порога живут в ДРУГИХ модулях без переключателя режима: spa_core/allocator/allocator.py::_EVIDENCE_MAX_AGE_H = 36.0 (константа) и spa_core/governance/evidence_staleness.py::HARD_STALE_H = 168.0 (константа) — оба зашиты только на paper-колонку, SPA_CAPITAL_MODE не читают. На реальном пилоте система будет ранжировать и держать позиции по бумажным окнам свежести, если никто не вспомнит подключить пилот-колонку явно — тот же класс дефекта, который закрыли для TriggerParams. Найдено при работе над CIO oversight phase E (Investment Policy Objective Contract, docs/ideas/2026-08-29-cio-oversight-layer.md) — вне её текущего скоупа (там речь только про TriggerParams), поэтому не чинил тут, а завожу карточкой.
