-- Send a list collection's posters right after each sync of the list.
ALTER TABLE scope ADD COLUMN refresh_posters INTEGER NOT NULL DEFAULT 0;
