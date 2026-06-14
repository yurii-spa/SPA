# AI_ASSISTANT_RULES.md — Строгие правила поведения Claude-агентов
> **Версия:** 1.0 | **Дата:** 2026-06-13 | **Статус:** АБСОЛЮТНЫЕ ПРАВИЛА — нарушение недопустимо
> Этот файл адресован непосредственно AI-агентам (Claude). Читай первым в сессии.

---

## 🔴 АБСОЛЮТНЫЕ ЗАПРЕТЫ (нарушение = немедленный стоп)

### §1. PAT (Personal Access Token)
```
НИКОГДА не встраивать PAT/токены/пароли ни в один файл.
Это включает: .sh скрипты, .html, .md, .json, .py, .command, .env, README.
Без исключений, даже "для удобства", даже "временно".

ПРИЧИНА: Инцидент 2026-06-10 — PAT утёк в 90+ сгенерированных файлов.
         Revoke потребовал ручной работы и поставил проект под угрозу.
```

**Правило:** PAT читается ТОЛЬКО через fallback chain в момент выполнения скрипта:
```bash
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
```

### §2. Push из sandbox
```
НИКОГДА не пушить в GitHub напрямую из sandbox/shell агента.
Sandbox не имеет доступа к macOS Keychain. Это физическое ограничение.
```

**Правило:** Агент ВСЕГДА:
1. Создаёт `scripts/push_vNNN.sh`
2. Делает `chmod +x scripts/push_vNNN.sh`
3. Сообщает пользователю: "Запустить `bash ~/Documents/SPA_Claude/scripts/push_vNNN.sh` из Terminal"

### §3. pytest
```
НИКОГДА не использовать pytest. Только unittest из stdlib.
```

Правильно:
```bash
python3 -m unittest discover -s spa_core/tests -p "test_*.py"
python3 -m unittest spa_core.tests.test_my_module -v
```

Неправильно:
```bash
pytest spa_core/tests/  # ❌ ЗАПРЕЩЕНО
```

### §4. Внешние зависимости
```
НИКОГДА не использовать pip/третьи стороны в production/runtime коде.
Только Python stdlib.
```

Запрещены: `requests`, `pandas`, `numpy`, `httpx`, `aiohttp`, `pydantic` и любые `pip install`.
Разрешены: `json`, `http.client`, `urllib.request`, `datetime`, `collections`, `statistics`, `math`, и весь stdlib.

### §5. Прямая запись JSON/KANBAN
```
НИКОГДА не писать JSON-файлы через прямой open(..., "w").
Всегда атомарная запись: tmp-файл + os.replace.
```

Правильно:
```python
import json, os, tempfile

def atomic_write(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
```

### §6. Импорты из запрещённых доменов
```
НИКОГДА не импортировать из: execution/, risk/, monitoring/
в код из доменов: adapters/, analytics/, paper_trading/, family_fund/
```

### §7. LLM в критических компонентах
```
LLM-вызовы запрещены в: risk/, execution/, monitoring/
Причина: prompt injection в capital management — критический вектор атаки.
```

---

## 🟡 ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА ПОВЕДЕНИЯ

### §8. Чтение документов перед работой

Агент ОБЯЗАН прочитать в начале каждой сессии (в порядке):
1. `CURRENT_STATE.md`
2. `docs/governance/AI_ASSISTANT_RULES.md` (этот файл)
3. `docs/governance/DEVELOPMENT_RULES.md`
4. `docs/DECISIONS.md` (последние 3 записи)
5. `KANBAN.json` (sprint_current, backlog, done_count)

**Не полагаться на память о предыдущих сессиях.** Всегда читать с диска.

### §9. Проверка дубликатов

Перед созданием ЛЮБОГО нового модуля:
```bash
# Проверить существование похожих файлов
ls spa_core/analytics/ | grep -i "<ключевое_слово>"
ls spa_core/tests/ | grep -i "<ключевое_слово>"
```

Если найден похожий файл — проверить, что новый модуль не дублирует функциональность.
Если дублирует — расширить существующий, не создавать новый.

### §10. Атомарное обновление KANBAN

Правило обновления `done_count`:
```python
# ПРАВИЛЬНО:
with open("KANBAN.json") as f:
    kanban = json.load(f)  # перечитать с диска прямо сейчас!
kanban["done_count"] = kanban.get("done_count", 0) + N_new_tasks
# ... обновить другие поля ...
atomic_write("KANBAN.json", kanban)

# НЕПРАВИЛЬНО:
kanban["done_count"] = 553  # фиксированное значение — затирает параллельные изменения!
```

### §11. Ring-buffer ограничение логов

Все JSON-логи в `data/` — ring-buffer с лимитом:
- Analytics logs: ≤ 100 записей
- equity_curve_daily.json: ≤ 365 записей
- trades.json: ≤ 500 записей
- risk_policy_blocks.json: ≤ 100 записей

Реализация:
```python
LOG_LIMIT = 100
entries = data.get("entries", [])
entries.append(new_entry)
if len(entries) > LOG_LIMIT:
    entries = entries[-LOG_LIMIT:]
data["entries"] = entries
```

### §12. Минимум тестов

Каждый analytics-модуль: ≥ 65 тестов.
Инфраструктурные модули: ≥ 20 тестов.
Без тестов — задача не считается done.

### §13. Нейминг push-скриптов при коллизии

```bash
# Перед созданием скрипта:
NEXT_NUM=$(ls scripts/push_v*.sh 2>/dev/null | grep -oP 'v\K[0-9]+' | sort -n | tail -1)
NEXT_NUM=$((NEXT_NUM + 1))

if [ -f "scripts/push_v${NEXT_NUM}.sh" ]; then
    SCRIPT_NAME="push_v${NEXT_NUM}b.sh"
else
    SCRIPT_NAME="push_v${NEXT_NUM}.sh"
fi
```

---

## 📋 ОБЯЗАТЕЛЬНАЯ СТРУКТУРА ФИНАЛЬНОГО ОТЧЁТА

Агент сообщает пользователю ОДИН РАЗ в конце работы. Формат:

```
✅ Спринт vX.YZ завершён

Выполнено:
- MP-NNN: <название> (<N> тестов)
- MP-NNN: <название> (<N> тестов)

Файлы созданы:
- spa_core/analytics/<module>.py
- spa_core/tests/test_<module>.py
- data/<module>_log.json
- scripts/push_vNNN.sh ← ЗАПУСТИТЬ ИЗ TERMINAL

KANBAN: done_count = <число>, sprint_current = vX.YZ

Запустить пуш:
  bash ~/Documents/SPA_Claude/scripts/push_vNNN.sh

⚠️ Блокеры (если есть):
- [блокер]: требуется действие пользователя
```

**НЕ отправлять** промежуточные сообщения ("начинаю писать тест...", "вот черновик...").
**НЕ спрашивать** одобрения для стандартных действий (создать файл, написать тест).

---

## 🟢 РАЗРЕШЁННЫЕ ДЕЙСТВИЯ БЕЗ ПОДТВЕРЖДЕНИЯ

- Создавать файлы в `spa_core/`, `data/`, `docs/`, `scripts/`
- Обновлять `KANBAN.json`, `CURRENT_STATE.md`, `docs/DECISIONS.md`
- Запускать тесты через bash (sandbox)
- Выбирать следующую задачу из backlog
- Создавать новые ADR-документы
- Обновлять `index.html` (dashboard)

---

## 🔴 ДЕЙСТВИЯ ТОЛЬКО С ЯВНЫМ ЗАПРОСОМ ПОЛЬЗОВАТЕЛЯ

- Удалять файлы
- Изменять `spa_core/risk/policy.py` (RiskPolicy — только через ADR)
- Изменять `spa_core/golive/activate.py`
- Менять `version` в RiskPolicy (остаётся `"v1.0"` весь paper-period)
- Отключать/включать production launchd daemon'ы
- Активировать live trading (`spa_core/golive/activate.py`)

---

## 📊 КРАТКАЯ СПРАВКА: ЧТО ЧИТАТЬ ЕСЛИ НУЖНО БОЛЬШЕ

| Тема | Файл |
|------|------|
| Git workflow, пуш | `docs/governance/GIT_WORKFLOW.md` |
| Anti-patterns | `docs/governance/ANTI_PATTERNS.md` |
| Архитектура модулей | `docs/governance/ARCHITECTURE.md` |
| Текущие блокеры | `docs/governance/KNOWN_ISSUES.md` |
| История решений | `docs/DECISIONS.md` |
| Текущий статус | `CURRENT_STATE.md` |
| Backlog задач | `KANBAN.json` → `columns.backlog` |

---

*Источник: docs/governance/AI_ASSISTANT_RULES.md v1.0 (2026-06-13)*
