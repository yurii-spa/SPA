# ADR-2026-003: Provider stack для Data & Signals

Дата: 2026-05-02
Статус: Accepted
Owner: Юра
Связанные документы: Data & Signals v0.3 (раздел 4.4)

---

## Контекст

Без конкретного provider stack реализация в Claude Code / Codex невозможна.

Требования к stack:
- минимум 2 независимых источника для каждого критичного слоя;
- бюджет ориентир $50–150/месяц на старте;
- free tier допустим, paid tier обязателен после 4 недель live;
- все провайдеры должны иметь публичные API и историю работы ≥ 12 месяцев.

---

## Решение

### RPC (on-chain доступ)

| Роль | Провайдер | Тип |
|------|-----------|-----|
| Primary | Alchemy | Платный (free tier для старта) |
| Backup | Ankr | Freemium |
| Emergency | публичный node (ethereum.org) | Бесплатный |

Переход на paid tier Alchemy: после 4 недель live или при превышении rate limits.

### Oracle (цены)

| Роль | Провайдер |
|------|-----------|
| Primary | Chainlink price feeds (on-chain) |
| Confirmation | Pyth Network (on-chain) |
| Cross-check | RedStone |

Все три читаются on-chain — без API-затрат.

### Данные протоколов (TVL, APY)

| Роль | Провайдер | Тип |
|------|-----------|-----|
| Primary | DeFiLlama Pro API | ~$25/m |
| Backup | прямые on-chain reads | Бесплатно |

### Индексация

| Роль | Провайдер | Тип |
|------|-----------|-----|
| Primary | The Graph (subgraphs для Aave, Compound) | Freemium |
| Backup | Etherscan API | Freemium |

### Security feeds

| Роль | Провайдер | Тип |
|------|-----------|-----|
| Primary | BlockSec X/Twitter feed | Бесплатно |
| Secondary | PeckShield X/Twitter feed | Бесплатно |
| Tertiary | Cyvers | Бесплатно |

*Off-chain signals — не являются прямым триггером автоматических действий. Только через preprocessing и structured data (Agent Architecture 6.1).*

### Compliance

| Роль | Провайдер | Тип |
|------|-----------|-----|
| Primary | OFAC SDN list (прямой download) | Бесплатно |
| Secondary | EU restrictive measures list | Бесплатно |

Обновление: ежедневно автоматически. При росте до Fund этапа — рассмотреть Chainalysis или TRM Labs.

---

## Бюджет

**Total: ~$110–125/месяц** (в пределах $50–150 диапазона).

---

## Альтернативы

- Только публичные RPC — отклонено: rate limits и надёжность.
- Платные tier с старта — отклонено: free tier хватает на первые 4 недели paper trading.
- Single oracle (только Chainlink) — отклонено: нужен cross-check для critical feeds.

---

## Последствия

- Реализация в Claude Code / Codex разблокирована
- ADR-004 (paper trading) может стартовать с этим stack
- Через 4 недели — review consumption, переход на paid tier при необходимости

---

## Подпись Owner

Дата: 2026-05-02
Owner: Юра
