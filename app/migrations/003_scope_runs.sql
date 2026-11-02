ALTER TABLE poster_sources ADD COLUMN read_quality INTEGER NOT NULL DEFAULT 1;

CREATE TABLE scope (
    id INTEGER PRIMARY KEY,
    library_key TEXT NOT NULL,
    library_title TEXT NOT NULL,
    collection_key TEXT NOT NULL DEFAULT '', -- '' = the whole library
    collection_title TEXT NOT NULL DEFAULT '',
    source_id INTEGER REFERENCES poster_sources (id) ON DELETE SET NULL, -- NULL = default source
    UNIQUE (library_key, collection_key)
);

CREATE TABLE runs (
    id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL, -- 'test' or 'live'
    status TEXT NOT NULL DEFAULT 'running', -- running, done, failed, cancelled
    max_items INTEGER,
    fetch_images INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    total INTEGER NOT NULL DEFAULT 0,
    applied INTEGER NOT NULL DEFAULT 0,
    unchanged INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE run_items (
    run_id INTEGER NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    rating_key TEXT NOT NULL,
    title TEXT NOT NULL,
    year INTEGER,
    type TEXT NOT NULL,
    library TEXT NOT NULL,
    thumb TEXT,
    source_name TEXT,
    quality TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL, -- apply, unchanged, skipped, error
    reason TEXT,
    url TEXT, -- secrets masked
    PRIMARY KEY (run_id, rating_key)
);
