# Obsidian как база знаний поверх репо (ENV_SETUP_BRIEF_v3 · Этап 7)

Obsidian — это просто редактор над папкой markdown. **Хранилище (vault) = корень репо.**
Ты пишешь в Obsidian, агенты читают те же файлы напрямую. Плагины-интеграции не нужны.

## Где что живёт

| Папка | Что | Действуют ли агенты |
|---|---|---|
| `docs/ideas/` | свободные идеи, мысли, «а что если» | ❌ НЕТ (идея ≠ инструкция) |
| `docs/rules-draft/` | черновики правил | ❌ НЕТ, пока не промоутнуто |
| `.claude/rules/`, `CLAUDE.md` | **действующие** правила | ✅ да |
| `docs/decisions/` | решения (ADR) | ✅ да |
| `inbox/`, `nimbalyst-local/tracker/` | задания и карточки | ✅ да |

## Промоушен: как идея становится инструкцией

Напиши в заметке (в `docs/ideas/` или `docs/rules-draft/`) тег **`#promote`** — и оркестратор в
следующем цикле превратит её в правило (`.claude/rules/` / `CLAUDE.md`), ADR или задачу-карточку,
а в исходнике заменит `#promote` → `#promoted-<дата>` со ссылкой на созданное. Без `#promote`
заметки остаются просто идеями — никто по ним не действует. (Скан: `scripts/orchestrator_queue.py promotions`.)

## Настройка Obsidian (один раз, на Mac)

1. Открой корень репо `~/Documents/SPA_Claude` как vault (уже сделано).
2. **Settings → Files and links → Excluded files** — добавь пути ниже, чтобы vault был быстрым и
   чистым (это только визуальное скрытие в Obsidian, файлы в репо не трогаются):

```
.git
.claude
node_modules
landing/node_modules
cabinet/node_modules
landing/dist
landing/.astro
data
logs
.venv_test
.mypy_cache
.pytest_cache
__pycache__
inbox/.ingested
```

3. `.obsidian/` (конфиг Obsidian) добавлен в `.gitignore` — он пер-девайсный, в git не попадает.

## Захват с телефона

Не настраивай синк Obsidian на телефоне (на iOS неудобно). С телефона идеи и задания шли через:
- **Telegram-бот** — `/task <текст>` или **голосовое** (расшифрую офлайн);
- **карточку в Nimbalyst** (мобильное приложение).

Obsidian — рабочее место на Mac. _(Платная опция `Obsidian Sync` могла бы синхронизировать vault на
телефон, но не требуется — мобильный захват уже закрыт Telegram/Nimbalyst.)_
