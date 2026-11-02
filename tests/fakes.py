"""Minimal stand-ins for plexapi objects."""

import re
import xml.etree.ElementTree as ET
from types import SimpleNamespace


def guid(value):
    return SimpleNamespace(id=value)


def stream(stream_type, display="", extended="", **attrs):
    return SimpleNamespace(streamType=stream_type, displayTitle=display, extendedDisplayTitle=extended, **attrs)


def video(display="", extended="", **attrs):
    return stream(1, display, extended, **attrs)


def audio(display="", extended="", **attrs):
    return stream(2, display, extended, **attrs)


def media(resolution, file="/movies/Movie (2020).mkv", streams=()):
    return SimpleNamespace(videoResolution=resolution, parts=[SimpleNamespace(file=file, streams=list(streams))])


class FakeItem:
    """An item whose full data (guids, streams) only appears after reload()."""

    def __init__(self, TYPE="movie", title="Movie", lite=None, full=None, episodes=()):
        self.TYPE = TYPE
        self.title = title
        self.reloads = 0
        self.uploads = []
        self.fields = []
        self._full = full or {}
        self._episodes = list(episodes)
        for key, value in {"guids": [], "media": [], **(lite or {})}.items():
            setattr(self, key, value)

    def uploadPoster(self, url=None, filepath=None):
        self.uploads.append(filepath.read())
        self.fields = [SimpleNamespace(name="thumb", locked=True)]
        return self

    def reload(self):
        self.reloads += 1
        for key, value in self._full.items():
            setattr(self, key, value)

    def episodes(self):
        return self._episodes

    def seasons(self):
        """Seasons built from the episodes, like Plex."""
        numbers = sorted({e.seasonNumber for e in self._episodes})
        return [FakeItem(TYPE="season", lite={"index": n}, episodes=[e for e in self._episodes if e.seasonNumber == n])
                for n in numbers]


def title(key, name, TYPE="movie", imdb=None, tmdb=None, resolution=None, locked=False):
    guids = [guid(f"imdb://{imdb}")] if imdb else []
    guids += [guid(f"tmdb://{tmdb}")] if tmdb else []
    medias = [media(resolution, streams=[video()])] if resolution else []
    fields = [SimpleNamespace(name="thumb", locked=True)] if locked else []
    return FakeItem(TYPE=TYPE, title=name, lite={
        "ratingKey": key, "year": 2020, "thumb": f"/library/metadata/{key}/thumb/1", "guids": guids, "media": medias,
        "fields": fields,
    })


class FakeSection:
    def __init__(self, key, title, type="movie", items=(), collections=()):
        self.key, self.title, self.type = key, title, type
        self.items = list(items)
        self._collections = list(collections)
        self.totalSize = len(self.items)
        self.pages = []

    def search(self, container_start=0, container_size=None, maxresults=None, **kwargs):
        self.pages.append(container_start)
        return self.items[container_start:container_start + maxresults]

    def collections(self):
        return self._collections

    def createCollection(self, title, items):
        server = self.server
        key = 1000 + len(server._collections)
        collection = FakeCollection(key, title, items, section_key=self.key, server=server)
        server._collections[key] = collection
        return collection


class FakeHub:
    def __init__(self):
        self._promoted = False
        self.promotedToRecommended = self.promotedToOwnHome = self.promotedToSharedHome = False
        self.updates = []

    def updateVisibility(self, recommended=None, home=None, shared=None):
        self._promoted = True
        self.promotedToRecommended, self.promotedToOwnHome, self.promotedToSharedHome = recommended, home, shared
        self.updates.append((recommended, home, shared))
        return self


class FakeCollection:
    TYPE = "collection"

    def __init__(self, key, title, items, section_key=1, server=None):
        self.ratingKey, self.title, self._items = key, title, list(items)
        self.childCount = len(self._items)
        self.smart = False
        self.librarySectionID = section_key
        self.labels, self.sort, self.hub, self.deleted, self.moves = [], None, FakeHub(), False, 0
        self._server = server

    def items(self):
        return list(self._items)

    def addItems(self, items):
        self._items += items

    def removeItems(self, items):
        gone = {str(i.ratingKey) for i in items}
        self._items = [i for i in self._items if str(i.ratingKey) not in gone]

    def moveItem(self, item, after=None):
        self.moves += 1
        moved = next(i for i in self._items if str(i.ratingKey) == str(item.ratingKey))
        self._items.remove(moved)
        index = 0 if after is None else next(n for n, i in enumerate(self._items) if i.ratingKey == after.ratingKey) + 1
        self._items.insert(index, moved)

    def addLabel(self, labels):
        self.labels += labels if isinstance(labels, list) else [labels]

    def removeLabel(self, labels):
        self.labels = [label for label in self.labels if label not in labels]

    def sortUpdate(self, sort):
        self.sort = sort

    def editTitle(self, title):
        self.title = title

    def reload(self):
        return self

    def visibility(self):
        return self.hub

    def delete(self):
        self.deleted = True
        if self._server:
            self._server._collections.pop(self.ratingKey, None)


class FakeServer:
    def __init__(self, sections, collections=()):
        self._sections = sections
        self._collections = {c.ratingKey: c for c in collections}
        self.machineIdentifier = "machine-1"
        for section in sections:
            section.server = self
        self.library = SimpleNamespace(sections=lambda: self._sections,
                                       sectionByID=lambda key: next(s for s in sections if s.key == key))

    def query(self, path, headers=None, timeout=None):
        """/library/sections/{key}/all with guids, paged, optionally addedAt>>= filtered."""
        self.queries = getattr(self, "queries", []) + [path]
        key = int(re.search(r"/sections/(\d+)/", path).group(1))
        items = next(s for s in self._sections if s.key == key).items
        if since := re.search(r"addedAt>>=(\d+)", path):
            items = [i for i in items if getattr(i, "addedAt", 0) >= int(since.group(1))]
        start = int((headers or {}).get("X-Plex-Container-Start", 0))
        size = int((headers or {}).get("X-Plex-Container-Size", len(items) or 1))
        root = ET.Element("MediaContainer")
        for item in items[start:start + size]:
            element = ET.SubElement(root, "Video", ratingKey=str(item.ratingKey))
            for g in item.guids:
                ET.SubElement(element, "Guid", id=g.id)
        return root

    def fetchItem(self, key):
        from plexapi.exceptions import NotFound

        if key in self._collections:
            return self._collections[key]
        item = next((i for s in self._sections for i in s.items if i.ratingKey == key), None)
        if item is None:
            raise NotFound(key)
        return item

    def fetchItems(self, path):
        keys = path.rsplit("/", 1)[1].split(",")
        return [i for s in self._sections for i in s.items if str(i.ratingKey) in keys]
