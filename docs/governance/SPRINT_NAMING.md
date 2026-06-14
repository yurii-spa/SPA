# Sprint Naming Convention

> Источник истины: это правило закреплено в `KANBAN.json → sprint_naming_convention`

## Format

```
Sprint v{MAJOR}.{MINOR} — MP-{NNN}+{NNN}
```

## Examples

- `Sprint v7.21 — MP-966+967`
- `Sprint v7.22 — MP-968+969`
- `Sprint v7.23 — MP-970+971`

## Rules

- **MAJOR** — текущая мажорная версия (7 начиная с июня 2026)
- **MINOR** — порядковый номер пуша; должен совпадать с суффиксом push-скрипта (`push_v7NN.sh`)
- **MP numbers** — номера двух модулей, построенных в этом спринте (через `+`)
- **Запрещено** использовать буквенные коды (AAA6, BBBB7 и т.д.) — они не самодокументирующиеся
- Каждый спринт = 1 `git push` + 1 `scripts/push_vNNN.sh`

## Push Script Naming

```
scripts/push_v{MAJOR*100+MINOR}.sh
```

Пример: `v7.21` → `scripts/push_v721.sh`, `v7.22` → `scripts/push_v722.sh`

## KANBAN.json fields

| Поле | Значение | Пример |
|---|---|---|
| `sprint_current` | `"v{MAJOR}.{MINOR}"` | `"v7.22"` |
| `sprint_completed` | предыдущий спринт | `"v7.21"` |
| `sprint_naming_convention` | шаблон (не трогать) | `"Sprint v{MAJOR}.{MINOR} — MP-{NNN}+{NNN}"` |
| `updated_by` | `"orchestrator v{MAJOR}.{MINOR} (MP-NNN+MP-NNN)"` | `"orchestrator v7.21 (MP-966+MP-967)"` |

## Why This Matters

Стабильное именование позволяет:
1. Однозначно привязать каждый пуш к паре MP-задач
2. Найти push-скрипт по номеру версии без угадывания
3. Автоматически проверить continuity (нет пропущенных MINOR-номеров)
4. Отличить реальный production-спринт от demo/teardown пуша

## Enforcement

- `KANBAN.json → sprint_naming_convention` — машиночитаемый источник истины
- Ревью каждого PR должно проверять соответствие имени ветки и `sprint_current`
- `AI_ASSISTANT_RULES.md §4` — ИИ-агент обязан следовать этому соглашению

---

*Создано: 2026-06-14 (audit pass — поле отсутствовало в docs/governance/)*
