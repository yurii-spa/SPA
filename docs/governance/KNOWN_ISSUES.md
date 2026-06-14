# KNOWN_ISSUES.md — Известные проблемы SPA
> **Версия:** 1.0 | **Дата:** 2026-06-13
> Обновлять при обнаружении новых проблем. Читать в начале сессии если нужен контекст.

---

## 🔴 P0 — Критические (блокируют production)

### KI-001: com.spa.autopush НЕ установлен
```
Статус: ОТКРЫТ с 2026-06-10 (MP-313, USER ACTION)
Симптом: GitHub репо не получает автоматические пуши (90-мин цикл не работает)
Причина: plist содержит заглушку PYTHON_PATH вместо реального пути
Диагностика: launchctl list | grep com.spa.autopush (отсутствует в списке)
Обходной путь: bash ~/Documents/SPA_Claude/run_all_pushes.sh (ручной пуш)
Фикс: USER ACTION — bash ~/Documents/SPA_Claude/mp009_fix_launchd.command
Блокирует: Автономная публикация данных трека на GitHub
```

---

### KI-002: ~/.github_pat содержит INVALID_PLACEHOLDER
```
Статус: ОТКРЫТ
Симптом: Push-скрипты падают если читают ~/.github_pat как fallback
Причина: Файл был создан как шаблон, реальный PAT не добавлен
Диагностика: cat ~/.github_pat → видим "INVALID_PLACEHOLDER"
Реальный PAT: security find-generic-password -s GITHUB_PAT_SPA -w (Keychain)
Обходной путь: push-скрипты проверяют значение и игнорируют INVALID_PLACEHOLDER
Фикс: Либо добавить реальный PAT в ~/.github_pat, либо оставить как есть (Keychain достаточно)
```

---

## 🟡 P1 — Важные (влияют на track record)

### KI-003: Memory-файлы рассинхронизированы — множество источников истины
```
Статус: ОТКРЫТ (выявлен аудитом 2026-06-13)
Симптом: Разные файлы дают разные значения done_count и sprint_current:
  MEMORY.md:      done=183, sprint=v4.70 (данные от ~2026-06-12 Wave 10)
  RULES.md:       done=91,  sprint=v4.47
  CURRENT_STATE:  done=252, sprint=v4.87/v4.88
  KANBAN.json:    done=553, sprint=v6.80  ← SOURCE OF TRUTH
Причина: Memory-файлы обновлялись непоследовательно, KANBAN обновлялся агрессивнее
Риск: Новый агент читает MEMORY.md и думает что сделано 183 задачи вместо 553
Фикс: Удалить или заморозить MEMORY.md; синхронизировать CURRENT_STATE.md с KANBAN
Приоритет: SYS-002 (в KANBAN backlog)
```

---

### KI-004: Duplicate modules в spa_core/analytics/
```
Статус: ОТКРЫТ
Симптом: 15+ групп файлов с похожими именами (yield_curve: 5 файлов, apy_forecast: 3, etc.)
Группы с высоким риском дублирования:
  yield_curve_*.py     (5 файлов)
  capital_efficiency_*.py  (4 файла)
  cross_chain_*.py     (4 файла)
  defi_portfolio_*.py  (4 файла)
  impermanent_loss_*.py    (4 файла)
  protocol_revenue_*.py    (4 файла)
  yield_farming_*.py   (4 файла)
Риск: Агент создаёт 6-й yield_curve файл вместо расширения существующего
Фикс: Аудит analytics/ — объединить дубли; правило pre-work check (уже в DEVELOPMENT_RULES.md)
```

---

### KI-005: Push backlog — GitHub не синхронизирован
```
Статус: ОТКРЫТ
Симптом: Последние push-скрипты (v668-v680) могут быть не запущены
Диагностика: 
  cat scripts/.push_log | tail -5  (какой последний успешный)
  ls scripts/push_v*.sh | tail -10  (список всех скриптов)
Фикс: bash ~/Documents/SPA_Claude/scripts/run_all_pushes.sh
```

---

### KI-006: Sprint log в KANBAN неполный
```
Статус: ОТКРЫТ (SYS-009 в backlog)
Симптом: sprint_log массив содержит только 5 записей (v5.60, v5.65, v6.28, v6.35, v6.75)
  Пропущены: v4.31–v4.47 (9 записей) + множество других
Причина: Sprint log не заполнялся в параллельных спринтах, перетирался
Риск: Невозможно восстановить историю работы
Фикс: Восстановить по dispatch_notes в KANBAN.json (задача SYS-009)
```

---

## 🟢 P2 — Известные ограничения (приняты)

### KI-007: KANBAN.json засорён dispatch_notes
```
Статус: ПРИНЯТО (технический долг)
Симптом: KANBAN.json содержит 80+ ключей вида _vNNN_dispatch_note
  Пример: _v680_dispatch_note, _v675_dispatch_note, ...
Причина: Каждый спринт добавляет dispatch note в корень JSON (не в sprint_log)
Последствие: Файл трудно читать, JSON parsing медленнее
Расхождение: done_count=553, но columns.done=371 (+tasks 24 = 395, не 553)
Фикс (долгосрочный): Мигрировать dispatch_notes в отдельный файл data/sprint_notes.json
Текущий workaround: При чтении KANBAN — читать только нужные поля, игнорировать _vNNN_ ключи
```

---

### KI-008: Параллельный done_count может быть off ±5
```
Статус: ПРИНЯТО (по дизайну)
Симптом: При 2 параллельных агентах done_count может увеличиться на +2 когда добавлена 1 задача
Причина: Read-increment-write без locking (атомарно на уровне файла, но не транзакционно)
Последствие: done_count=553 может быть 550 или 556 в реальности
Фикс: Принять расхождение ±5 как норму; не тратить время на reconcile при малом расхождении
```

---

### KI-009: GoLiveChecker 16/26 pass (NOT READY)
```
Статус: В РАБОТЕ (цель: 26/26 к 2026-07-15)
Симптом: 10 критериев не пройдены
Ключевые блокеры:
  - trades_real: нет реальных трейдов (is_demo:false) — нужно 30 дней трека
  - gap_monitor: менее 30 дней непрерывности (старт 2026-06-10)
  - autopush: com.spa.autopush не установлен (USER ACTION, KI-001)
  - Telegram daily alerts: не активированы (dry_run режим)
Go-live target: 2026-08-01 (ADR-002)
```

---

### KI-010: Telegram daily report в dry_run режиме
```
Статус: ОТКРЫТ (MP-314, USER ACTION)
Симптом: Telegram alerts настроены но не активированы
Причина: Токены в Keychain, но dry_run=True
Фикс: MP-314 — снять dry_run флаг (требует USER ACTION: подтвердить токены)
```

---

### KI-011: com.spa.httpserver статус неизвестен
```
Статус: ТРЕБУЕТ ПРОВЕРКИ
Диагностика: launchctl list | grep com.spa.httpserver
  Если нет в списке → установить: launchctl load ~/Library/LaunchAgents/com.spa.httpserver.plist
Сервис: Family Fund portal (localhost:8765)
```

---

## 📊 СВОДНАЯ ТАБЛИЦА

| ID | Приоритет | Статус | USER ACTION? | Фикс |
|----|-----------|--------|--------------|------|
| KI-001 | P0 | ОТКРЫТ | ✅ ДА | bash mp009_fix_launchd.command |
| KI-002 | P0 | ОТКРЫТ | Нет | Игнорировать ~/.github_pat |
| KI-003 | P1 | ОТКРЫТ | Нет | Заморозить MEMORY.md, синк CURRENT_STATE |
| KI-004 | P1 | ОТКРЫТ | Нет | Аудит analytics/ дублей |
| KI-005 | P1 | ОТКРЫТ | ✅ ДА | bash run_all_pushes.sh |
| KI-006 | P1 | ОТКРЫТ | Нет | SYS-009 восстановление sprint log |
| KI-007 | P2 | ПРИНЯТО | Нет | Долгосрочный: мигрировать dispatch_notes |
| KI-008 | P2 | ПРИНЯТО | Нет | done_count расхождение ±5 — норма |
| KI-009 | P2 | В РАБОТЕ | Частично | 30 дней трека (авто) + KI-001 фикс |
| KI-010 | P2 | ОТКРЫТ | ✅ ДА | MP-314 снять dry_run |
| KI-011 | P2 | НЕИЗВЕСТНО | Возможно | launchctl list | grep httpserver |

---

*Источник: docs/governance/KNOWN_ISSUES.md v1.0 (2026-06-13)*
*Основан на аудите проекта 2026-06-13*
