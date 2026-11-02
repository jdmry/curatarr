CREATE TABLE poster_sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url_template TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'generic', -- 'postersplus' or 'generic'
    type_movie TEXT NOT NULL DEFAULT 'movie',
    type_show TEXT NOT NULL DEFAULT 'series',
    no_quality TEXT NOT NULL DEFAULT '',
    headers TEXT NOT NULL DEFAULT '{}', -- JSON object
    timeout INTEGER NOT NULL DEFAULT 120,
    revision INTEGER NOT NULL DEFAULT 1, -- bumped when the rendered poster may change
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
