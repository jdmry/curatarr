-- Who sees a list's collection: 'all', 'owner', or a Plex user id.
ALTER TABLE lists ADD COLUMN audience TEXT NOT NULL DEFAULT 'all';
ALTER TABLE lists ADD COLUMN audience_name TEXT NOT NULL DEFAULT '';
