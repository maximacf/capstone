-- Migration tracking table (created first, before any other migrations)
-- Tracks which migrations have been applied
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT DEFAULT (datetime('now')),
  description TEXT
);
