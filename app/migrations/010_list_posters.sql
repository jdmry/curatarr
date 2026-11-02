-- Posters are a setting of each list: the service its collection's posters come from
-- (NULL = the default service), sent after each sync of the list.
ALTER TABLE lists ADD COLUMN posters INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lists ADD COLUMN poster_source_id INTEGER REFERENCES poster_sources (id) ON DELETE SET NULL;
UPDATE lists SET posters = 1,
    poster_source_id = (SELECT source_id FROM scope WHERE scope.collection_key = lists.collection_key)
WHERE collection_key IN (SELECT collection_key FROM scope);
DROP TABLE scope;
-- The lists' schedule now sends posters too: the posters' own schedule goes.
DELETE FROM settings WHERE key LIKE 'schedule.%';
