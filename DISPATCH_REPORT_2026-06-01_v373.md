# Dispatch Report — 2026-06-01 — SPA-V373 (LOCAL ONLY, NOT PUSHED)

## Резюме
Автономный dev-оркестратор отработал спринт **SPA-V373** (персист истории APY-gap +
sparkline `current_weighted_apy` на дашборде). Код и тесты легли **локально**. Пуш в живой
репозиторий `yurii-spa/SPA` **сознательно не выполнен** — причина ниже (утёкший PAT).

## 🔴 САМОЕ СРОЧНОЕ — утёкший GitHub PAT (требует действия СЕГОДНЯ)
Живой токен `ghp_REVOKED_LEAKED_N31r` лежит в plaintext в теле
scheduled-task (`SKILL.md`) и в **92 файлах `push_v*.html`** в папке репозитория. Это активная
утечка учётных данных, отмеченная уже в нескольких прошлых прогонах (v370, v372) и **до сих пор
не устранённая**.

1. **Отзови токен в GitHub прямо сейчас:** Settings → Developer settings → Personal access
   tokens → Revoke.
2. Перевыпусти новый и положи в секрет-хранилище (GitHub Secrets / keychain), а **не** в текст
   задачи или HTML.
3. После ротации — удали/очисти 92 файла `push_v*.html`, содержащие старый токен.

Именно из-за этого пуш этого спринта не делался: единственный санкционированный метод
(`push_v*.html → localhost:8765 → Chrome navigate`) потребовал бы встроить этот же утёкший
токен в новый файл и снова передать его. Повторно экспонировать заведомо утёкший секрет
автономно — недопустимо.

## Что сделано в SPA-V373 (локально, протестировано)
- **`apy_gap_report.py`** — новая `append_apy_gap_history(doc, data_dir)`: компактная запись
  `{generated_at, current_weighted_apy, gap, on_track}`, дедуп по `generated_at`, trim до 180,
  never-raise. Зеркало проверенного паттерна v3.63/v3.65/v3.68.
- **`export_data.py`** — guarded-вызов истории сразу после записи `apy_gap_report.json`;
  `apy_gap_report_history.json` зарегистрирован в манифесте.
- **`index.html`** — 9-й фетч `apy_gap_report_history.json`, новый sparkline
  «Weighted APY trend (toward 7.30% target)» (`renderApyGapTrend` через существующий
  `renderTrendSparkline`).
- **Тесты:** `test_apy_gap_export.py` 21 passed (+`TestAppendApyGapHistory` 7 + wiring);
  регрессия 74 passed/0 failed; `py_compile` OK; `node --check` JS OK; smoke round-trip OK.
- НЕ money-moving (eth_signer/mev_protection/адаптеры не тронуты), НЕ новый feed-health монитор
  (SPA-BL-011 freeze соблюдён).

## Замеченный пред-существующий баг (НЕ чинил — вне scope)
Контейнер `#apy-gap-widget` из спринта **v3.72** так и не был добавлен в `index.html` →
`renderApyGapWidget()` всегда no-op (getElementById → null). Тот виджет фактически не
отображается. Кандидат на 1-строчный фикс в SPA-V374. Новый sparkline v3.73 использует
собственный контейнер и монтируется независимо.

## Почему очереди реальной код-работы по-прежнему нет
Незаблокированной содержательной HIGH код-работы не осталось с ~v3.52. Стартовый список
задания (SPA-V326..V332) полностью `done`. Спринты v3.61–v3.73 — это presentation-слой
(тренды/спарклайны/виджеты). Критический путь к go-live (2026-07-15) держат **user-action
блокеры**, не баги:

- **SPA-BL-007** — RPC-ключи (Alchemy/Infura) в GitHub Secrets.
- **SPA-BL-008** — Telegram bot токен в Secrets.
- **SPA-BL-009** — Gnosis Safe + wallet address в Secrets.
- **BL-004/005/006** — GitHub Pages / Telegram bot / workflow-scope token.
- **FEAT-001/002** — live capital execution (money-moving, вне автономного режима по дизайну).

## Рекомендации (по приоритету)
1. 🔴 **Отозвать и ротировать GitHub PAT** (см. выше) — самое срочное.
2. Закрыть user-action блокеры SPA-BL-012 → это разблокирует реальный go-live путь.
3. **Пересмотреть правило «status pass запрещён».** Без разблокировки секретов автономный цикл
   может производить только косметику + коммиты в живой репо. Разумнее: «работай только при
   наличии реальной незаблокированной задачи, иначе — отчёт».
4. По подтверждению — housekeeping: ~100 `.bak.*` + 92 `push_v*.html` + `httpserver.log` (~7 МБ).
5. Обновить тело scheduled-task: стартовый список кандидатов устарел; путь к eth_signer —
   `spa_core/execution/eth_signer.py`.

## После того как PAT ротирован — как запушить v3.73
Изменённые файлы: `spa_core/data_pipeline/apy_gap_report.py`, `spa_core/export_data.py`,
`index.html`, `spa_core/tests/test_apy_gap_export.py`, `KANBAN.json`, `SPA_sprint_log.md`.
Бэкапы `.bak.v373` рядом. Запушить новым токеном из секрет-хранилища (не plaintext).
