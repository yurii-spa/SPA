# S3 — как воспроизвести другой сессией (без сети, на копиях)

Дерево: ветка `s3/research` (origin). Python stdlib. Рабочие базы НЕ открываются на запись.

1. **Согласованный снимок** (SQLite backup API; источник открыт `mode=ro`; WAL earn-defi включается в копию):
   ```python
   import sqlite3
   def snap(src, dst):
       s = sqlite3.connect(f"file:{src}?mode=ro", uri=True); d = sqlite3.connect(dst); s.backup(d); d.close(); s.close()
   ```
   Источники: `~/Documents/SPA_Claude/data/trading_research/{market,evidence}.db`, `~/Documents/earn-defi/data/earn_defi.db`.
   Эталон этой поставки — `SNAPSHOT_MANIFEST.json` (sha256 каждой копии, `PRAGMA integrity_check` = ok).
2. **SPA: пересчёт наблюдения** — `replay.replay_observation(market_copy, evidence_copy, candidate_id[, seq=])`;
   на эталонном снимке: последние наблюдения 138/138 OK (`spa_replay_latest_all.txt`), случайные 300/300 OK
   (`spa_replay_sample.txt`, seed 20261101). Отказы проверяет `spa_core/tests/test_trading_research_replay.py`.
3. **earn-defi: replay** собственным `replay.py` репозитория earn-defi на копии `earn_defi.db` (репозиторий не меняется):
   0 расхождений по signals/decisions/trades/nav (`earn_defi_replay.txt`).
4. **Контракты**: `python3 -c "import json;from spa_core.trading_research import research_contract as rc;
   c=json.load(open('docs/research_contracts/trp05-sizing-band-2026-11-01.json'));print(rc.validate(c))"` → `[]`;
   `rc.check_ledgers(c, {'evidence': <копия evidence.db>})` → `OK`; для earn-defi — `{'db': <копия earn_defi.db>}`.
5. **TRP-05**: бюджет исчерпан (2/2), повторный запуск ОТКАЖЕТ (`AttemptBudgetExceeded`) — это и есть учёт попыток
   между сессиями. Пересчёт чисел отчёта без новой попытки: `sizing_experiment.simulate_frac` + `execution.simulate`
   на копии `market.db` с sha256 `a679b8ac…` (контрольная сумма данных отчёта `data_ref 9ecd292dee28db04`).
6. **Forward-аудит**: `forward_audit.audit(evidence_copy, market_copy, as_of_ms=<время снимка>)` → `FORWARD_AUDIT.md`.
7. **Пульт**: `SPA_TRADING_DATA_DIR=… EARN_DEFI_DIR=… python3 studio_shell/build_mobile.py` → `studio_shell/trading.json`;
   вёрстка: `python3 studio_shell/check_trading_layout.py studio_shell/trading.json <каталог-скриншотов>` (код 0/1/2).
