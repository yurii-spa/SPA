# Release CI v5 — run 40469786128 on `release/task-prep-20261027` = `d8baff308b75712e1a9e70b80f1b7b3cb22db4be` — INCOMPLETE

- v5 = current server main `15ba1c054` + the same 24 package paths as `4a326236b` (byte-identical package content;
  built from integ `7973da2a9` by `build_release_v4` = v3 + scanner delta). New branch (the old one cannot fast-forward).
- Result: **INCOMPLETE** — 11/12 shards; shard 11 (10 709 tests) has no artifact. GitHub annotation: «The hosted runner lost
  communication with the server» (step «Run shard» never finished, 07:56→09:05). Job log: BlobNotFound.
- On the 11 shards that reported: 125 078 passed · 57 failed · 0 error · 705 skipped.
  Against today's scheduled main CI 40454032149 (`908015739`): **new 0 · pre-existing 57 · fixed 9** (on the reported shards).
  The 4 «new» against v4 are pre-existing on today's main (main moved); the board-date failure does not appear here.
- NOT a verification: a run with 10 709 tests without outcome cannot serve as the delivery gate. One full re-run on the
  SAME SHA is started because of this new uncertainty (runner loss), not to obtain green.
