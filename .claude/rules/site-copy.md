# Rule · Site copy (`landing/`, публичные страницы, FAQ, blog)

**Читать перед любой правкой публичного текста earn-defi.com.**

> **🔒 Авто-шип + owner-gate (ADR-OWN-2026-07-autoship).** Автономный оркестратор пушит БЕЗОПАСНЫЕ
> правки сайта в live сам. Owner-gated классы этого правила (числа доходности · нейминг тиров ·
> расшифровка «SPA» · legal/disclaimer · solicitation · удаление honesty-токенов) НИКОГДА не уезжают
> автономно — `scripts/check_owner_gate.py` их ловит, `scripts/safe_site_push.py` заворачивает в
> карточку владельцу. Пуш `landing/**` из автономного контекста — ТОЛЬКО через `safe_site_push.py`.
> Гайд: `docs/OWNER_GATE.md`.

- **Никакого solicitation-языка.** Продукт на paper-стадии, внешний капитал закрыт до
  legal-clearance. Запрещены формулировки действующего фонда: «minimum investment»,
  «withdrawals within N days», «no lock-up», «fee after KYC» как активные условия.
  Честная рамка: «research paper-track; коммерческие условия — после go-live + legal review;
  не оферта».
- **APY-честность (evidence L0–L6, `docs/37`):** не выдавать paper/backtest за live. Всегда
  показывать источник доходности + risk-категорию + last-verified дату. Не выдумывать APY/TVL.
- **Хвост всегда виден:** для Balanced/Aggressive показывать drawdown/tail рядом с доходностью;
  research-paper тиры помечены «refused-for-live».
- **Бренд-нейминг и числа — OWNER-GATED.** Не менять расшифровку «SPA», отображаемые числа
  доходности, наименования тиров и legal-формулировки без карточки `board/owner/`.
- **RU-копия (`data-ru`) — натуральный русский:** без транслита, без смешанного алфавита
  («Йелд-десk» — запрещено), без непереведённого английского жаргона в оффере. Проверять
  `data-ru` на латиницу перед публикацией.
- Двуязычность EN|RU по всему сайту. Canonical дашборд — `/dashboard` (не `/app`).
- Деплой сайта — только `deploy-landing.yml` (CF Pages git-integration билдит `landing/` на push).
- Проверять деплой: `curl -L https://earn-defi.com/<page>/` (следовать 308, trailing slash, без query).
