"""Keep a Plex collection equal to the owned titles of a list, in the list's order."""

from collections.abc import Callable
from dataclasses import dataclass, field

from plexapi.exceptions import NotFound

from app.branding import APP_NAME
from app.lists.store import ListConfig
from app.plex.sharing import PRIVATE_PREFIX, private_label

LABEL = APP_NAME
FETCH_BATCH = 100

# (recommended, home, friends' home) for each placement.
VISIBILITY = {
    "home": (True, True, True),
    "recommended": (True, False, False),
    "library": (False, False, False),
}


@dataclass
class Plan:
    create: bool = False
    delete: bool = False
    rename: bool = False
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    reorder: bool = False

    @property
    def changed(self) -> bool:
        return self.create or self.delete or self.rename or bool(self.add or self.remove) or self.reorder

    def describe(self, wanted: int) -> str:
        if self.delete:
            return "no title in Plex: collection removed"
        if self.create:
            return f"created with {wanted} titles"
        parts = []
        if self.add:
            parts.append(f"{len(self.add)} added")
        if self.remove:
            parts.append(f"{len(self.remove)} removed")
        if self.reorder:
            parts.append("reordered")
        if self.rename:
            parts.append("renamed")
        return ", ".join(parts) or "unchanged"


def find_collection(server, config: ListConfig):
    """The list's collection if it still exists, in the list's library."""
    if not config.collection_key:
        return None
    try:
        collection = server.fetchItem(int(config.collection_key))
    except (NotFound, ValueError):
        return None
    if getattr(collection, "TYPE", None) != "collection":
        return None
    return collection


def plan(collection, config: ListConfig, wanted: list[str]) -> Plan:
    if collection is None:
        return Plan(create=bool(wanted))
    if str(collection.librarySectionID) != config.library_key:
        return Plan(create=bool(wanted), delete=True)
    if not wanted:
        return Plan(delete=True)
    current = [str(item.ratingKey) for item in collection.items()]
    kept = [key for key in current if key in set(wanted)]
    result = Plan(
        rename=collection.title != config.name,
        add=[key for key in wanted if key not in set(current)],
        remove=[key for key in current if key not in set(wanted)],
    )
    result.reorder = bool(result.add) or kept != wanted
    return result


def fetch_items(server, keys: list[str]) -> list:
    """Plex items for these rating keys, in this order; titles gone from Plex are left out."""
    found = {}
    for start in range(0, len(keys), FETCH_BATCH):
        batch = keys[start:start + FETCH_BATCH]
        for item in server.fetchItems(f"/library/metadata/{','.join(batch)}"):
            found[str(item.ratingKey)] = item
    return [found[key] for key in keys if key in found]


def apply(server, section, collection, config: ListConfig, wanted: list, steps: Plan,
          say: Callable[[str], None] = lambda message: None):
    """Carry out the plan with the wanted Plex items. Returns the collection (None once deleted).

    `say` reports the slow steps as they start.
    """
    if steps.delete and collection is not None:
        collection.delete()
        collection = None
    if not wanted:
        return None
    if collection is None:
        say(f"creating the collection with {len(wanted)} titles")
        collection = section.createCollection(config.name, items=wanted)
        collection.addLabel(LABEL)
        collection.sortUpdate("custom")
        collection = collection.reload()
    else:
        if steps.rename:
            collection.editTitle(config.name)
        if steps.add or steps.remove:
            say(f"adding {len(steps.add)} titles, removing {len(steps.remove)}")
        if steps.remove:
            collection.removeItems([_Key(key) for key in steps.remove])
        if steps.add:
            added = set(steps.add)
            collection.addItems([item for item in wanted if str(item.ratingKey) in added])
    if steps.create or steps.reorder:
        say("putting the titles in the list's order")
        _reorder(collection, wanted)
    set_private_label(collection, config)
    set_visibility(collection, config.placement, owner_only=config.audience == "owner")
    return collection


def labels(collection) -> set[str]:
    return {getattr(label, "tag", label) for label in collection.labels}


def made_by(collection, linked: bool) -> str | None:
    """Which tool made a collection, as far as its labels tell."""
    if linked:
        return APP_NAME
    names = labels(collection)
    if LABEL in names:
        return f"{APP_NAME}, no list"
    if any(name.lower().startswith("agregarr") for name in names):
        return "Agregarr"
    return None


def set_private_label(collection, config: ListConfig) -> None:
    """A collection for some people only carries a label their friends' restrictions exclude."""
    current = labels(collection)
    wanted = {private_label(config.id)} if config.private else set()
    stale = [label for label in current if label.startswith(PRIVATE_PREFIX) and label not in wanted]
    if stale:
        collection.removeLabel(stale)
    if wanted - current:
        collection.addLabel(sorted(wanted - current))


@dataclass(frozen=True)
class _Key:
    """plexapi only reads ratingKey to remove or move an item."""

    ratingKey: str


def _reorder(collection, wanted: list) -> None:
    """Move items until the collection follows the list, one request per misplaced item."""
    current = [str(item.ratingKey) for item in collection.items()]
    for index, item in enumerate(wanted):
        key = str(item.ratingKey)
        if index < len(current) and current[index] == key:
            continue
        after = wanted[index - 1] if index else None
        collection.moveItem(item, after=after)
        if key in current:
            current.remove(key)
        current.insert(index, key)


def set_visibility(collection, placement: str, owner_only: bool = False) -> None:
    recommended, home, shared = VISIBILITY[placement]
    shared = shared and not owner_only
    hub = collection.visibility()
    if not hub._promoted and not (recommended or home or shared):
        return
    if (hub.promotedToRecommended, hub.promotedToOwnHome, hub.promotedToSharedHome) == (recommended, home, shared):
        return
    hub.updateVisibility(recommended=recommended, home=home, shared=shared)


def delete_collection(server, config: ListConfig) -> bool:
    collection = find_collection(server, config)
    if collection is None:
        return False
    collection.delete()
    return True
