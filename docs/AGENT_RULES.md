# Agent Coordination Rules

> Этот документ обязателен для всех агентов работающих над SPA.  
> Нарушение правил → broken builds, merge conflicts, потеря данных.

---

## Цикл волны агентов

```
PRE-GATE → [Агенты работают] → POST-GATE → kanban-update
```

Без прохождения pre-gate агенты **не стартуют**.  
Без прохождения post-gate изменения **не пушатся**.

---

## Обязательно перед стартом волны агентов

```bash
python3 -m spa_core.coordinator.sprint_coordinator pre-gate
```

Пример успешного вывода:
```json
{
  "passed": true,
  "checks": {
    "kanban_valid": true,
    "git_clean": true,
    "imports_ok": true,
    "import_ok_count": 847,
    "import_fail_count": 0
  },
  "errors": []
}
```

Если `"passed": false` — **сначала починить**, потом стартовать агентов.  
Смотри секцию "Устранение проблем" ниже.

---

## Обязательно после завершения волны

```bash
python3 -m spa_core.coordinator.sprint_coordinator post-gate
```

post-gate делает всё что pre-gate + запускает pytest:
- `pytest spa_core/tests/ -x -q --timeout=30`

Если тесты красные — **не пушить**, откатить или дочинить.

---

## Обновление KANBAN (только через координатор)

```bash
# +4 задачи, переход на новый спринт
python3 -m spa_core.coordinator.sprint_coordinator kanban-update --done 4 --sprint v12.04

# только счётчик
python3 -m spa_core.coordinator.sprint_coordinator kanban-update --done 1
```

Координатор использует `fcntl.LOCK_EX` — параллельные вызовы безопасны.

---

## Отчёт после волны

```bash
python3 -m spa_core.coordinator.sprint_coordinator wave-report --wave 12
```

Вывод содержит:
- Сколько модулей импортируется (ok/fail)
- Состояние KANBAN (done_count, sprint_current)
- Чистота git
- Новые файлы в HEAD
- Ошибки push_scripts

---

## Что ЗАПРЕЩЕНО агентам

| Запрет | Почему |
|--------|--------|
| Писать напрямую в `KANBAN.json` через `json.dump` | Только через `coordinator kanban-update` — иначе race condition |
| Создавать `from X import Y` без проверки что `X` существует | Ломает import smoke-test |
| Пушить с `[skip ci]` при красных тестах | CI должен работать |
| Запускать параллельные волны без pre-gate pass | Агрессивный параллелизм рвёт файлы |
| Импортировать `spa_core/execution/` из read-only кода | Нарушает domain isolation |
| Создавать файлы с секретами / PAT | SECRETS POLICY (инцидент 2026-06-10) |
| Прямой `open(..., "w")` на state-файлы | Только атомарные `tmp + os.replace` |

---

## Устранение проблем

### `kanban_valid: false` — KANBAN.json невалиден

```bash
# Проверить conflict markers
grep -n "<<<<<<\|>>>>>>>" KANBAN.json

# Проверить JSON
python3 -c "import json; json.load(open('KANBAN.json'))"
```

### `git_clean: false` — merge conflicts или stale lock

```bash
# Найти конфликтующие файлы
git diff --name-only --diff-filter=U

# Удалить stale lock
rm -f .git/index.lock
```

### `imports_ok: false` — broken imports

```bash
# Посмотреть полный список ошибок
python3 -m spa_core.coordinator.sprint_coordinator pre-gate 2>&1 | python3 -c "
import sys, json
d = json.load(sys.stdin)
for e in d['errors']:
    print(e)
"
```

### `tests_passed: false` — красные тесты

```bash
# Запустить только упавшие тесты подробно
python3 -m pytest spa_core/tests/ -x -v --tb=long 2>&1 | tail -50
```

---

## Интеграция в git_autopush.sh

`scripts/git_autopush.sh` автоматически вызывает pre-gate перед каждым пушем.  
Если pre-gate падает — push пропускается, в лог пишется wave-report.

---

## Ссылки

- Исходник: `spa_core/coordinator/sprint_coordinator.py`
- Тесты: `spa_core/tests/test_coordinator.py`
- KANBAN: `KANBAN.json`
- Политика секретов: `CLAUDE.md → SECRETS POLICY`
- RiskPolicy: `spa_core/risk/policy.py`
