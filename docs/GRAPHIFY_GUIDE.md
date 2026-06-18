# Graphify — Knowledge Graph для SPA

Graphify — это **Claude Code skill**, который строит граф знаний по кодовой базе.
Используется внутри Claude Code через команду `/graphify`.
Позволяет AI-агентам находить связи между модулями, не тратя токены на полное чтение файлов.

Источник: https://github.com/safishamsi/graphify

---

## Установка (один раз на Mac)

```bash
pip install graphifyy
graphify install
```

`graphify install` устанавливает SKILL.md в `~/.claude/skills/graphify/` и регистрирует
команду `/graphify` в Claude Code.

---

## Использование в Claude Code

После установки открой Claude Code в `~/Documents/SPA_Claude` и вызывай:

```
/graphify .
```

Graphify сам прочитает файлы, построит граф и вернёт структуру.

### Основные команды

```
# Индексация папок (запускать внутри Claude Code)
/graphify .                           # весь репо
/graphify ./spa_core                  # только Python-код
/graphify ./docs                      # только документация
/graphify . --mode deep               # агрессивное извлечение рёбер INFERRED
/graphify . --update                  # обновить только изменённые файлы

# Запросы к графу
/graphify query "what connects yield_quality to cycle_runner?"
/graphify path "alert_manager" "cycle_gap_monitor"
/graphify explain "SwinTransformer"

# Добавить внешний источник
/graphify add https://arxiv.org/abs/1706.03762
/graphify add https://defillama.com/

# Авто-обновление при изменениях
/graphify . --watch

# Экспорт
/graphify . --wiki      # wiki-статьи для навигации агентов
/graphify . --svg       # граф как SVG
/graphify . --graphml   # для Gephi/yEd
/graphify . --neo4j     # Cypher для Neo4j

# Git hook — автоматическое обновление после каждого коммита
graphify hook install
```

---

## Что создаётся в graphify-out/

```
graphify-out/
├── graph.html         — интерактивный граф (кликабельный, с поиском)
├── graph.json         — персистентный граф (для последующих запросов)
├── GRAPH_REPORT.md    — god nodes, surprising connections, suggested questions
├── obsidian/          — открывать как Obsidian vault
├── wiki/              — Wikipedia-статьи для навигации агентов (--wiki)
└── cache/             — SHA256 кэш изменений (--update ускоряет re-run)
```

---

## Что индексирует

| Тип | Расширения | Метод |
|-----|-----------|-------|
| Код | `.py .ts .js .go .rs` и др. | AST + call-graph (tree-sitter) |
| Документация | `.md .txt .rst` | Claude — концепты + отношения |
| PDF | `.pdf` | Citation mining + Claude |
| Изображения | `.png .jpg .webp` | Claude Vision (схемы, диаграммы) |

---

## Рекомендуемые сессии для SPA

```
# 1. Полный индекс (первый раз — долго, потом --update быстро)
/graphify . --mode deep

# 2. Только код + docs (без data/ и tests/)
/graphify ./spa_core ./docs ./SPA_Dev

# 3. Обновить после спринта
/graphify . --update

# 4. Найти связи между модулями
/graphify query "what connects drawdown to strategy promotion?"
/graphify query "which modules write to data/*.json?"
/graphify path "cycle_runner" "alert_manager"
```

---

## Важно

- **Нет файла конфигурации** — Graphify не использует `.graphify.yml` или подобное.
  Папки передаются прямо в команду.
- **Python 3.10+** required (Graphify сам это проверяет).
- **PyPI пакет называется `graphifyy`** (два y), но CLI команда — `graphify`.
- Каждое ребро помечено `EXTRACTED`, `INFERRED` или `AMBIGUOUS` — всегда ясно что найдено, что предположено.

---

*Обновлено: 2026-06-17 — переписано по реальному README репозитория*
