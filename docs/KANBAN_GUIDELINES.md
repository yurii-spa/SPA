# KANBAN.json — Правила работы

> **Статус:** Обязательно для всех агентов и скриптов, работающих с KANBAN.json  
> **Введено:** Sprint v10.4 (CRIT-001)

---

## Зачем эти правила

Аудит Sprint v10.3 поймал живой баг: `sprint_completed: v10.0 > sprint_current: v9.94`.
Причина — несколько агентов параллельно читали KANBAN.json и писали его напрямую без блокировки,
что привело к гонке данных и несогласованному состоянию.

---

## Запрещено

- **НИКОГДА** не читать KANBAN.json + писать KANBAN.json без файловой блокировки (`fcntl.LOCK_EX`).
- **НИКОГДА** не хардкодить `done_count` напрямую — только инкрементально через `increment_done()`.
- **НИКОГДА** не делать `open("KANBAN.json", "w")` — только атомарную запись через `tmp + os.replace`.
- **НИКОГДА** не понижать `sprint_current` ниже значения `sprint_completed`.
- **НИКОГДА** не делать `json.dump(k, open("KANBAN.json", "w"))` без блокировки.

---

## Правильный способ — через `spa_core/utils/kanban.py`

### Инкремент done_count при завершении задачи

```python
from spa_core.utils.kanban import increment_done

new_count = increment_done(base_dir=".", n=1, sprint="v10.4")
print(f"done_count = {new_count}")
```

`increment_done()` делает:
1. Открывает файл в режиме `r+`
2. Берёт `fcntl.LOCK_EX` (эксклюзивная блокировка)
3. Читает JSON, инкрементирует `done_count`, опционально ставит `sprint_completed`
4. Перезаписывает файл, снимает блокировку

### Атомарное сохранение произвольных изменений

```python
import fcntl, json, os

def save_kanban_atomic(k: dict, path: str = "KANBAN.json") -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(k, f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, path)  # атомарная замена
```

### Обновление sprint_current

```python
# Правильно: используй save_kanban_atomic или kanban_health.save_kanban
# Неправильно: k["sprint_current"] = "v10.4" → json.dump(k, open(..., "w"))
```

---

## Проверка состояния

```bash
# Быстрая проверка
python3 scripts/kanban_health.py

# Автоматический ремонт
python3 scripts/kanban_health.py --fix

# Непрерывный мониторинг (каждые 30 сек)
python3 scripts/kanban_health.py --watch
```

### Ожидаемый вывод при здоровом KANBAN

```
✅ KANBAN OK: done_count=1109, sprint_current=v10.4, sprint_completed=v10.4
```

---

## При конфликте / инконсистентности

Симптомы:
- `sprint_completed > sprint_current` — регрессия спринта
- `done_count < len(done[])` — счётчик отстал
- `version != "10.0.0"` — версия не совпадает

Фикс:

```bash
python3 scripts/kanban_health.py --fix
```

Затем сверь результат:

```bash
python3 scripts/kanban_health.py
# должен выдать ✅
```

---

## Обнаружение нарушений (lint)

```bash
python3 scripts/lint_kanban_usage.py
```

Скрипт ищет в `.py` и `.sh` файлах прямую запись в KANBAN.json без использования
`kanban.py` или `save_kanban_atomic`. Возвращает список файлов-нарушителей.

---

## Инварианты KANBAN.json (период v10.x)

| Поле | Инвариант |
|---|---|
| `version` | Всегда `"10.0.0"` в период paper trading |
| `done_count` | `>= len(done[])` в любой момент |
| `sprint_current` | `>= sprint_completed` (нельзя регрессировать) |
| `current_sprint` | Равен `sprint_current` |
| `last_updated` | Присутствует, формат `YYYY-MM-DD` |

---

## История изменений

| Sprint | Изменение |
|---|---|
| v10.3 | CRIT-001: `kanban_health.py` — health checker + repair |
| v10.4 | CRIT-001: этот документ + `lint_kanban_usage.py` |
