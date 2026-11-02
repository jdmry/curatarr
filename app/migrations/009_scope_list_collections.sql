-- Posters are only for the collections made by lists: drop whole libraries and other collections.
DELETE FROM scope WHERE collection_key NOT IN (SELECT collection_key FROM lists WHERE collection_key IS NOT NULL);
