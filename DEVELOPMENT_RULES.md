# DEVELOPMENT_RULES.md — Правила разработки SPA
> **Версия:** 1.0 | **Дата:** 2026-06-13 | **Статус:** ОБЯЗАТЕЛЬНО к исполнению
> Читается каждым AI-агентом в начале каждой сессии. Без исключений.

---

## ⚡ ЧЕКЛИСТ ДО НАЧАЛА РАБОТЫ (Pre-Work Checklist)

Выполнять строго по порядку перед выбором任务 из backlog:

```
[ ] 1. Прочитать CURRENT_STATE.md — sprint_current, done_count, blockers, push_method
[ ] 2. Прочитать docs/governance/DEVELOPMENT_RULES.md (этот файл)
[ ] 3. Прочитать docs/governance/AI_ASSISTANT_RULES.md
[ ] 4. Прочитать docs/DECISIONS.md — последние 3 записи
[ ] 5. Прочитать KANBAN.json — sprint_current, columns.backlog, tasks
[ ] 6. Проверить дубликаты: ls spa_core/analytics/ | grep <module_name>
[ ] 7. Проверить скрипты: ls scripts/push_v*.sh | tail -5 (какой номер последний)
```

**Запрещено:** брать задачу без прохождения этого чеклиста.

---

## ✅ ЧЕКЛИСТ ПОСЛЕ ЗАВЕРШЕНИЯ РАБОТЫ (Post-Work Checklist / Definition of Done)

Задача считается DONE только если выполнены ВСЕ пункты:

```
[ ] 1. Код написан и тесты зелёные (python3 -m unittest discover -s spa_core/tests)
[ ] 2. KANBAN.json обновлён атомарно:
        - status: "done"
        - sprint_completed: "vX.YZ"
        - completed: "YYYY-MM-DD"
        - done_count увеличен на 1 (аддитивно — не перезаписывать!)
[ ] 3. docs/DECISIONS.md — добавлена запись о сессии
[ ] 4. CURRENT_STATE.md — обновлён sprint_current, done_count
[ ] 5. Push-скрипт создан: scripts/push_vNNN.sh (chmod +x)
[ ] 6. Пользователю сообщён финальный отчёт (только один раз, не промежуточные)
```

**Статусы доставки (delivery_status в KANBAN):**
- `shipped_local` — написан и протестирован, не запушен
- `shipped_remote` — в GitHub
- `in_prod` — работает в production (daily_cycle или launchd)

`shipped_local` — **не финальный статус**. Реальный done = `shipped_remote` или `in_prod`.

---

## 📋 DEFINITION OF DONE (для каждого типа задач)

### Analytics-модуль (MP-xxx):
- Файл создан в `spa_core/analytics/`
- ≥ 65 тестов в `spa_core/tests/test_<module>.py`
- Функция `analyze()` возвращает dict с ключами `status`, `verdict`, `details`
- Ring-buffer лог в `data/<module>_log.json` (≤ 100 записей)
- CLI: `python3 -m spa_core.analytics.<module> --check` работает без ошибок
- Нет внешних зависимостей (только stdlib)
- Нет импортов из `execution/`, `risk/`, `monitoring/`

### ADR-документ:
- Файл в `docs/adr/ADR-NNN-<name>.md`
- Разделы: Status, Context, Decision, Consequences, Rationale
- Обновлён KANBAN.json
- Упомянут в DECISIONS.md

### Infra-задача:
- Изменение протестировано локально
- Обновлён CURRENT_STATE.md (infra-блок)
- Если launchd — команда для проверки: `launchctl list | grep com.spa`

---

## 🔄 ПАРАЛЛЕЛЬНЫЕ СПРИНТЫ: ПРОТОКОЛ КОЛЛИЗИЙ

Когда несколько агентов работают одновременно (parallel pipeline):

### KANBAN.json — правило атомарного обновления:
1. **Перечитай файл с диска** непосредственно перед записью (не используй кэш из начала сессии)
2. Увеличь `done_count` аддитивно: `done_count = current_done_count + N` (не устанавливай фиксированное значение)
3. Запись только через `tmp + os.replace` (атомарная запись)
4. Если `scripts/push_vNNN.sh` уже существует — используй `push_vNNNb.sh`

### Конфликты push-скриптов:
```bash
# Проверить перед созданием:
ls scripts/push_vNNN.sh 2>/dev/null && SCRIPT="push_vNNNb.sh" || SCRIPT="push_vNNN.sh"
```

### Sprint_current и done_count могут расходиться:
- Допустимое расхождение done_count: ±5 (параллельные спринты)
- Если расхождение > 5 — добавь `_reconcile_note` в KANBAN и зафиксируй в DECISIONS.md

---

## 🚫 ANTI-HALT ПРОТОКОЛ

Если одна и та же проблема повторяется третий раз:

1. **НЕ писать тот же текст четвёртый раз** — это шум, не коммуникация
2. Создать задачу `[ESCAPE-XXX]` в KANBAN с планом выхода
3. Продолжить работу с незаблокированными задачами
4. Добавить запись в DECISIONS.md: блокер, что попробовано, ESCAPE-задача
5. Сообщить пользователю ОДИН РАЗ: что попробовано, что нужно от него

**Запрещено:** более 3 повторений одного и того же запроса к пользователю.

---

## 📊 ПРИОРИТИЗАЦИЯ ЗАДАЧ

```
P0 infrastructure → P0 process → P1 infrastructure → P1 analytics → P2+ analytics
```

**Запрещено:** брать P2+ analytics при наличии незаблокированных P1 infrastructure задач.

Исключение: если P0/P1 infra заблокированы USER ACTION — переходи к следующему приоритету, явно укажи причину в sprint log.

---

## 📝 ЯЗЫК И КОММУНИКАЦИЯ

- **Сообщения пользователю:** русский язык
- **Код, комментарии, коммиты:** английский
- **Отчёт:** один финальный, не промежуточные обновления
- **Формат финального отчёта:**
  ```
  ✅ Завершено: [список задач]
  📦 Тесты: N новых, всего M
  🔧 Файлы: [список созданных/изменённых файлов]
  📋 Push: scripts/push_vNNN.sh — запустить из Terminal
  ⚠️ Блокеры: [если есть]
  ```

---

## 🔐 SECRETS POLICY (инцидент 2026-06-10)

> ⚠️ **КРИТИЧНО:** В 2026-06-10 PAT утёк в 90+ сгенерированных файлов. Правила обязательны.

1. **НИКОГДА** не писать GitHub PAT, токены, ключи, пароли ни в один файл (включая CLAUDE.md, docs/*, .command, сгенерированные артефакты). **Без исключений.**
2. **ЗАПРЕЩЕНО** генерировать `push_*.html`-артефакты с встроенными кредами.
3. PAT читается **только** из macOS Keychain в runtime: `security find-generic-password -s GITHUB_PAT_SPA -w`
4. Секрет попал в файл → немедленно revoke на `github.com/settings/tokens`, зачистить файлы и историю, уведомить Owner.
5. Push-скрипты (`scripts/push_vNNN.sh`) читают PAT из Keychain/env — никаких хардкоднных значений.

Ротация PAT: `bash setup_pat.sh` → `docs/TOKEN_ROTATION_RUNBOOK.md`

---

## 🏷️ SPRINT NAMING CONVENTION

Формат: `Sprint v{MAJOR}.{MINOR} — MP-{NNN}+{NNN}`

Пример: `Sprint v7.21 — MP-966+967`

Детали: `docs/governance/SPRINT_NAMING.md`

---

*Источник правил: docs/governance/DEVELOPMENT_RULES.md v1.1 (2026-06-14 — добавлены SECRETS POLICY и SPRINT NAMING)*
*Следующие документы: GIT_WORKFLOW.md, AI_ASSISTANT_RULES.md, ANTI_PATTERNS.md, SPRINT_NAMING.md*
