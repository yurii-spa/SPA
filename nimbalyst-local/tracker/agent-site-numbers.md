---
trackerStatus:
  type: agent-task
title: Q4/Q5: числа/нейминг сайта
status: done
source: session-2026-07-16
created: 2026-07-16
---

Q4: убрать расшифровку «SPA» с сайта. Q5: свести число Conservative к «до 6%» + ~3.3% реализовано рядом. Owner-gated, owner-decided.

## Сделано 2026-07-16
**Q4 (расшифровка «SPA»):** на рендерящихся .astro-страницах расшифровки «Smart Passive Aggregator»
НЕ было («SPA —» там = «SPA это…», не расшифровка букв). Литеральная расшифровка жила в публично
отдаваемых `robots.txt` + `llms.txt` + метаданных `package.json` + внутреннем build-status — убрал
везде, теперь просто «SPA». Запушено (CF Pages деплоит). own-08 ingested.

**Q5 (Conservative «до 6%» + ~3.3% рядом):** ПРОВЕРЕНО — уже реализовано консистентно (прежние работы:
tier_bands.json единый источник, UX-14 удаление волатильного LIVE-бейджа, 6mo-M1 #7). Заголовок
«up to 6% / до 6%» + «~3.3% realized» рядом на index, packages, SiteHeader-nav (из единого источника),
strategies/conservative. Оставшиеся «2-6%» = комментарии про УЖЕ исправленный баг + BTC-утилизация
(не Conservative APY). Числа НЕ выдумывал — расхождений заголовка Conservative нет. own-14 ingested.
