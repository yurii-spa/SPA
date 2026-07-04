-- Academy DB — initial schema
-- PRAGMA journal_mode=WAL и foreign_keys=ON применяются в db.py при каждом соединении

CREATE TABLE IF NOT EXISTS schema_migrations (
  version     INTEGER PRIMARY KEY,
  applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  email            TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash    TEXT NOT NULL,
  invite_code_used TEXT REFERENCES invite_codes(code),
  is_owner         INTEGER NOT NULL DEFAULT 0 CHECK (is_owner IN (0,1)),
  created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invite_codes (
  code        TEXT PRIMARY KEY,
  created_by  INTEGER REFERENCES users(id),
  max_uses    INTEGER NOT NULL DEFAULT 1 CHECK (max_uses >= 1),
  used_count  INTEGER NOT NULL DEFAULT 0,
  used_by     TEXT DEFAULT '[]',
  used_at     TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id  TEXT PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token  TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at  TEXT NOT NULL,
  ip          TEXT,
  user_agent  TEXT,
  revoked_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS progress (
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lesson_id     INTEGER NOT NULL CHECK (lesson_id BETWEEN 0 AND 8),
  status        TEXT NOT NULL DEFAULT 'not_started'
                CHECK (status IN ('not_started','in_progress','submitted','verified','failed')),
  started_at    TEXT,
  completed_at  TEXT,
  evidence_json TEXT,
  PRIMARY KEY (user_id, lesson_id)
);

CREATE TABLE IF NOT EXISTS wallets (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  address     TEXT NOT NULL COLLATE NOCASE,
  chain       TEXT NOT NULL DEFAULT 'base' CHECK (chain IN ('base','base_sepolia')),
  label       TEXT,
  verified_at TEXT,
  UNIQUE (user_id, address, chain)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wallets_verified_unique
  ON wallets(address, chain) WHERE verified_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS siwe_nonces (
  nonce      TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at TEXT NOT NULL,
  used       INTEGER NOT NULL DEFAULT 0 CHECK (used IN (0,1))
);

CREATE TABLE IF NOT EXISTS quiz_results (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lesson_id   INTEGER NOT NULL CHECK (lesson_id BETWEEN 0 AND 8),
  score       REAL NOT NULL,
  answers_json TEXT NOT NULL,
  attempt_n   INTEGER NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (user_id, lesson_id, attempt_n)
);

CREATE TABLE IF NOT EXISTS notes (
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lesson_id  INTEGER NOT NULL CHECK (lesson_id BETWEEN 0 AND 8),
  text       TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (user_id, lesson_id)
);

CREATE TABLE IF NOT EXISTS events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER REFERENCES users(id),
  action       TEXT NOT NULL,
  payload_json TEXT,
  ip           TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;

CREATE TABLE IF NOT EXISTS used_tx_hashes (
  tx_hash    TEXT NOT NULL COLLATE NOCASE,
  chain      TEXT NOT NULL,
  user_id    INTEGER NOT NULL REFERENCES users(id),
  lesson_id  INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (tx_hash, chain)
);
