# RM-TRUTH-01 · записи изменений (ADR-537)

Значимые удаления этого эпика. Каждая запись проверяется `scripts/check_change_evidence.py` в пушере;
достаточность рассуждения — вопрос независимого ревьюера (`docs/rm_truth/REVIEW_*.md`).

```change-record
id: CR-RMT01-001
task: RM-TRUTH-01 Wave 0 (W5 APY truth + W4 publication) · role: integrator (interactive session)
component: годовая ставка книг Balanced/Aggressive — /api/live/books (spa_core/api/routers/live.py) и снимок сайта (scripts/generate_track_snapshot.py)
purpose: _annualized_pct + _accrual_anchor_date давали владельцу годовую ставку книги в /api/live/books и /admin/portfolio-summary (фаза B надзора CIO, 2ba5e4b3d), а якорь начисления — первый день реальной записи вместо номинального start_date (533739abd); _post_fix_track отделял дни исправленной модели издержек sleeve-econ-v2 от искажённых v1 (ADR-531, c673b3df3)
purpose_source: 2ba5e4b3d
defect: линейная аннуализация за всю жизнь книги, включая 39 искажённых v1-дней, без порога зрелости — тот же расчёт жил ТРЕМЯ копиями (live.py, books_summary.py, generate_track_snapshot.py) с разными формулами; итог — инвертированная лестница у владельца (Conservative 4.15 / Balanced −4.36 / Aggressive 1.36 при 4 валидных днях), docs/rm_truth/A3_product.md §2
decision: один читатель трека рукава spa_core/paper_trading/sleeve_track.sleeve_track_view (только v2, только текущий эксперимент ADR-533, compound через spa_core/reporting/compound_apy) + порог зрелости REPORTABLE_AFTER из канона spa_core/defi_engine/package_status (ADR-580 C1/C2); ниже порога ставка null и статус «копится история»
alternative: оставить три копии и только поправить формулу в каждой — отвергнуто: ровно так три копии и разошлись (C1 «один писатель на значение»)
preserved: якорь начисления по первому дню реальной записи (теперь внутри sleeve_track_view: первый v2-день текущего эксперимента); отделение v1 от v2 и пометка pre_fix_period; _post_fix_track ПЕРЕЕХАЛ в spa_core/paper_trading/sleeve_track.py без изменения логики (сырая аудиторская v2-ставка, типизирована reportable/reportable_after); return_pct, equity, NAV книг — без изменений
changed: annualized_apy_pct книг ниже 30 валидных дней = null (было линейное число); Conservative — compound по evidenced-барам (4.90 вместо линейных 4.10, равно публичному числу); появилось типизированное поле annualized_apy_pct_rate (metric_type REALIZED_PAPER, window_days, annualisation, as_of, source, reportable)
removes: py:scripts/generate_track_snapshot.py:_post_fix_track, py:spa_core/api/routers/live.py:_accrual_anchor_date, py:spa_core/api/routers/live.py:_annualized_pct
consumers: /api/live/books → landing/src/pages/admin/portfolio-summary.astro (рендерит null как «—»); spa_core/reporting/daily_telegram_report.py блок «📚 Пакеты» (печатает «статистика текущей версии накапливается»); public track_snapshot.json paper_tracks.*.post_fix (не читается ни одной страницей — замер W4)
owner_approval: not required (применяет уже принятые владельцем ADR-531/533/548: «копится» до 30 валидных дней; публичные поля, читаемые сайтом, заморожены отдельным сторожем test_landing_read_fields_frozen)
reversible: yes (git revert коммита доставки возвращает три прежние функции; данные книг не трогались — расчёт идёт при чтении)
rollback: git revert <sha доставки RM-TRUTH-01 Wave 0>; перезапуск apiserver владельцем для KeepAlive-процесса
```
