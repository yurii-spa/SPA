---
trackerStatus:
  type: inbox
title: Тест GSM Sky приколочен к до-ADR-065 состоянию
status: new
source: nimbalyst
created: 2026-08-07
---

test_sky_susds_gsm_gate_is_consulted требует allowed=False/gsm_not_confirmed, но ADR-065 легально повысил Sky до T1 (GSM 48ч наблюдён on-chain). Класс «тест приколочен к инциденту» (4-й случай). Обновить тест: обе стороны — при подтверждённом GSM allowed=True, при неподтверждённом False. Не моя правка — падение существует на чистом origin.
