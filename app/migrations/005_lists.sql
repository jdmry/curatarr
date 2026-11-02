-- External ids of each Plex library: Plex can't search by IMDb/TMDB/TVDB id.
CREATE TABLE plex_guids (
    library_key TEXT NOT NULL,
    guid TEXT NOT NULL,
    rating_key TEXT NOT NULL,
    PRIMARY KEY (library_key, guid)
) WITHOUT ROWID;

CREATE TABLE plex_index (
    library_key TEXT PRIMARY KEY,
    built_at INTEGER NOT NULL,
    checked_at INTEGER NOT NULL,
    size INTEGER NOT NULL
);

-- A list (MDBList, TMDB…) kept as a Plex collection.
CREATE TABLE lists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    library_key TEXT NOT NULL,
    library_title TEXT NOT NULL,
    placement TEXT NOT NULL DEFAULT 'home',
    max_items INTEGER NOT NULL DEFAULT 50,
    position INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    collection_key TEXT,
    synced_at TEXT,
    last_total INTEGER,
    last_matched INTEGER,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
