# ANTI_PATTERNS.md — Что НИКОГДА не делать в SPA
> **Версия:** 1.0 | **Дата:** 2026-06-13 | **Статус:** ОБЯЗАТЕЛЬНО к прочтению

Этот документ — аудит реальных ошибок, повторявшихся в проекте.
Каждый пункт основан на инциденте или паттерне, наблюдавшемся в истории проекта.

---

## 🔴 КАТЕГОРИЯ 1: Безопасность (критические)

### ❌ AP-001: Встраивать PAT в файлы

```bash
# ПЛОХО — PAT в скрипте
PAT="ghp_<REDACTED-EXAMPLE-revoked-2026-06-10>"
python3 push_to_github.py --pat "$PAT" ...
```

```python
# ПЛОХО — PAT в Python
PAT = "ghp_<REDACTED-EXAMPLE-revoked-2026-06-10>"
headers = {"Authorization": f"token {PAT}"}
```

**Что случилось:** Инцидент 2026-06-10 — PAT утёк в 90+ сгенерированных файлов. Полный revoke + зачистка истории.

**Правильно:** Всегда fallback chain: Keychain → env `GITHUB_PAT_SPA` → env `SPA_GITHUB_PAT` → `~/.github_pat` (если не INVALID_PLACEHOLDER).

---

### ❌ AP-002: Создавать push_*.html с кредами

```html
<!-- ПЛОХО -->
<script>
const PAT = "ghp_...";  // Критически опасно
fetch(`https://api.github.com/...`, {headers: {Authorization: `token ${PAT}`}})
</script>
```

**Правильно:** Никаких HTML-пушеров. Только `.sh` скрипты с fallback chain.

---

### ❌ AP-003: Читать PAT из ~/.github_pat без проверки на заглушку

```bash
# ПЛОХО
PAT=$(cat ~/.github_pat)  # Может содержать "INVALID_PLACEHOLDER"
```

```bash
# ПРАВИЛЬНО
PAT=$(cat ~/.github_pat)
[ "$PAT" = "INVALID_PLACEHOLDER" ] && PAT=""  # Игнорировать заглушку
```

**Известная проблема:** `~/.github_pat` содержит строку `INVALID_PLACEHOLDER`. Реальный PAT только в Keychain.

---

## 🔴 КАТЕГОРИЯ 2: Архитектура (критические)

### ❌ AP-004: Пушить из sandbox

```python
# ПЛОХО — агент пытается пушить сам
import subprocess
subprocess.run(["python3", "push_to_github.py", "--pat", pat, ...])
```

**Причина:** Sandbox не имеет macOS Keychain. PAT недоступен. Это физическое ограничение.

**Правильно:** Создать `scripts/push_vNNN.sh`, сообщить пользователю запустить его из Terminal.

---

### ❌ AP-005: Использовать внешние библиотеки в runtime

```python
# ПЛОХО
import requests  # pip install requests
import pandas as pd  # pip install pandas
import aiohttp  # pip install aiohttp
from pydantic import BaseModel  # pip install pydantic
```

**Правильно:** Только stdlib:
```python
import urllib.request  # вместо requests
import json            # вместо pandas для simple JSON
import statistics      # вместо numpy для базовой статистики
```

---

### ❌ AP-006: Импортировать execution/ из read-only кода

```python
# ПЛОХО — в analytics/adapters/paper_trading
from spa_core.execution.live_adapter import execute_trade  # ❌
from spa_core.risk.policy import RiskPolicy  # ❌ (только через API)
```

**Правильно:** `analytics/` и `adapters/` работают автономно. Если нужна информация из risk — читать из файла `data/risk_policy_blocks.json`, не импортировать напрямую.

---

### ❌ AP-007: Прямая (неатомарная) запись JSON

```python
# ПЛОХО — если процесс упадёт в середине, файл будет corrupted
with open("data/trades.json", "w") as f:
    json.dump(data, f)
```

```python
# ПРАВИЛЬНО — атомарная запись
import os, json
def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # Атомарная операция на POSIX
```

---

### ❌ AP-008: Устанавливать done_count как фиксированное значение

```python
# ПЛОХО — при параллельном спринте перезатирает чужие изменения
kanban["done_count"] = 553  # Захардкоженное значение
```

```python
# ПРАВИЛЬНО — перечитать и инкрементировать
with open("KANBAN.json") as f:
    kanban = json.load(f)  # Читаем с диска прямо сейчас
kanban["done_count"] = kanban.get("done_count", 0) + new_tasks_count
```

---

### ❌ AP-009: Создавать дубликат модуля с похожим названием

```
# Примеры реальных дублей в проекте:
apy_forecaster.py         ─┐
apy_forecast_v2.py         ├ три версии одного функционала
apy_volatility_forecaster.py─┘

yield_curve_*.py  (5 файлов с "yield_curve" в имени)
capital_efficiency_*.py  (4 файла)
```

**Правило перед созданием:** `ls spa_core/analytics/ | grep -i <keyword>` → если есть — расширить существующий, не создавать новый.

---

## 🟡 КАТЕГОРИЯ 3: Процесс (важные)

### ❌ AP-010: Использовать pytest

```bash
# ПЛОХО
pytest spa_core/tests/  # pytest не в stdlib
pytest -v --cov  # тем более
```

```bash
# ПРАВИЛЬНО
python3 -m unittest discover -s spa_core/tests -p "test_*.py" -v
python3 -m unittest spa_core.tests.test_my_module -v
```

---

### ❌ AP-011: Отправлять промежуточные сообщения пользователю

```
# ПЛОХО — шум вместо информации
"Начинаю создавать модуль..."
"Теперь пишу тесты..."
"Тест 1 пройден..."
"Тест 2 пройден..."
"Обновляю KANBAN..."
"Создаю push-скрипт..."
```

```
# ПРАВИЛЬНО — один финальный отчёт после завершения всей работы
✅ Спринт v6.81 завершён: MP-885 AnalyticsModule, 72 теста
📋 Push: bash ~/Documents/SPA_Claude/scripts/push_v681.sh
```

---

### ❌ AP-012: Просить пользователя сделать то, что агент может сделать сам

```
# ПЛОХО
"Пожалуйста, создайте файл spa_core/analytics/new_module.py"
"Напишите тесты для этого модуля"
"Обновите KANBAN.json"
```

Агент сам создаёт файлы, тесты, обновляет KANBAN. Пользователя просим только о том,
что физически невозможно в sandbox: **пуш в GitHub** и **действия в Keychain/launchd**.

---

### ❌ AP-013: Повторять один и тот же запрос пользователю более 3 раз

```
Сессия 1: "Запустите mp009_fix_launchd.command"
Сессия 2: "Запустите mp009_fix_launchd.command"
Сессия 3: "Запустите mp009_fix_launchd.command"
Сессия 4: ... (СТОП — это не коммуникация, это шум)
```

**Правило:** После 3 повторений — создать `ESCAPE-xxx` задачу в KANBAN с альтернативным планом и продолжить с незаблокированными задачами.

---

### ❌ AP-014: Полагаться на память чата без чтения файлов

```
# ПЛОХО — агент помнит из прошлой сессии:
"Я помню, что done_count был 540..."
"По памяти sprint_current = v6.70..."
```

**Правило:** Всегда читать с диска. `CURRENT_STATE.md` → `KANBAN.json` → `DECISIONS.md`.
Память чата не может быть source of truth — между сессиями файлы меняются параллельными агентами.

---

### ❌ AP-015: Создавать файлы без check на существование

```python
# ПЛОХО — перезаписывает существующий модуль
with open("spa_core/analytics/apy_tracker.py", "w") as f:
    f.write(...)
```

```python
# ПРАВИЛЬНО — проверить сначала
import os
path = "spa_core/analytics/apy_tracker.py"
if os.path.exists(path):
    raise FileExistsError(f"Module already exists: {path}. Extend it, don't recreate.")
```

---

### ❌ AP-016: Игнорировать ring-buffer ограничение логов

```python
# ПЛОХО — лог растёт неограниченно
log["entries"].append(new_entry)
# Через 6 месяцев: 50000 записей, 200MB файл
```

```python
# ПРАВИЛЬНО — ring-buffer
LOG_LIMIT = 100
entries = log.get("entries", [])
entries.append(new_entry)
entries = entries[-LOG_LIMIT:]  # Только последние 100
log["entries"] = entries
```

---

### ❌ AP-017: Изменять RiskPolicy без ADR

```python
# ПЛОХО — прямое изменение порогов
risk_config.TVL_FLOOR = 3_000_000  # Было 5M, стало 3M без ADR
risk_config.VERSION = "v1.1"        # Изменение версии без ADR
```

**Правило:** RiskPolicy `version` остаётся `"v1.0"` весь paper-period. Любое изменение → новый ADR + snapshot в `spa_core/risk/versions/`.

---

### ❌ AP-018: Не синхронизировать memory-файлы между собой

**Симптом:** Видно в текущем проекте:
- `MEMORY.md` говорит: done_count = 183, sprint = v4.70 (от 2026-06-12)
- `RULES.md` говорит: done = 91 задача, sprint = v4.47
- `CURRENT_STATE.md` говорит: sprint = v4.87, done = 252
- `KANBAN.json` говорит: sprint_current = v6.80, done_count = 553

Четыре источника истины дают четыре разных ответа.

**Правило:** Единственный source of truth — `KANBAN.json`. После каждого спринта синхронизировать `CURRENT_STATE.md` (и только его, не MEMORY.md — он устарел).

---

## 📊 МАТРИЦА ANTI-PATTERNS ПО ПРИОРИТЕТУ

| ID | Категория | Серьёзность | Последний инцидент |
|----|-----------|-------------|-------------------|
| AP-001 | Безопасность | КРИТИЧЕСКИЙ | 2026-06-10 (PAT leak) |
| AP-002 | Безопасность | КРИТИЧЕСКИЙ | 2026-06-10 |
| AP-004 | Архитектура | КРИТИЧЕСКИЙ | Постоянно |
| AP-007 | Архитектура | ВЫСОКИЙ | Постоянно |
| AP-008 | Процесс | ВЫСОКИЙ | Параллельные спринты |
| AP-009 | Архитектура | ВЫСОКИЙ | 313 модулей, 15+ групп дублей |
| AP-018 | Процесс | ВЫСОКИЙ | MEMORY.md vs KANBAN разрыв 300+ задач |
| AP-011 | Процесс | СРЕДНИЙ | Постоянно |
| AP-013 | Процесс | СРЕДНИЙ | MP-313 autopush (повторялся 10+ сессий) |
| AP-014 | Процесс | СРЕДНИЙ | Постоянно |
| AP-010 | Инструменты | НИЗКИЙ | Периодически |
| AP-016 | Архитектура | НИЗКИЙ | Потенциальный риск |

---

*Источник: docs/governance/ANTI_PATTERNS.md v1.0 (2026-06-13)*
*Основан на аудите 2026-06-13 — SPA Project Governance Overhaul*
