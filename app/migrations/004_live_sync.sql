-- The poster last sent to each title, so a sync only sends what changed.
CREATE TABLE poster_state (
    rating_key TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE runs ADD COLUMN scheduled INTEGER NOT NULL DEFAULT 0;
