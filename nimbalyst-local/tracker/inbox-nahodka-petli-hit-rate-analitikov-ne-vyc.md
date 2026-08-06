---
trackerStatus:
  type: inbox
title: "Находка петли: hit-rate аналитиков не вычислим: proof.jsonl хранит только хэши, содер"
status: new
source: nimbalyst
created: 2026-08-05
finding_key: "retro:verdict_archive_missing"
---

Находка петли ADR-066 (loop_retro, WARN, подтверждена 2 прогонами подряд):

hit-rate аналитиков не вычислим: proof.jsonl хранит только хэши, содержимое вердиктов не архивируется — завести append-only архив вердиктов (постура/сигналы по дням), иначе «говорит ли офис дело» останется вечным UNCHECKED

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `retro:verdict_archive_missing` · ADR-066_
