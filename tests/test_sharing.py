import json

import httpx

from app.plex.sharing import Friend, changed, friends, merge_filter, update, wanted_filters

OURS = {"curatarr-private-1", "curatarr-private-2"}


def test_merge_keeps_other_restrictions():
    assert merge_filter("", OURS) == "label!=curatarr-private-1,curatarr-private-2"
    assert merge_filter("", set()) == ""
    # Another tool's label stays, ours are added to the same exclusion.
    assert merge_filter("label!=AgregarrTargetUser_1", {"curatarr-private-1"}) == \
        "label!=AgregarrTargetUser_1,curatarr-private-1"
    # Stale labels of ours go, other groups and encoded commas survive.
    existing = "contentRating=G%2CPG&label!=curatarr-private-9%2Cmine"
    assert merge_filter(existing, {"curatarr-private-1"}) == "contentRating=G,PG&label!=mine,curatarr-private-1"
    assert merge_filter("contentRating=G&label!=curatarr-private-9", set()) == "contentRating=G"


def friend(**settings):
    return Friend("7", "bob", "Bob", {"filterMovies": "", "filterTelevision": "", **settings})


def test_wanted_and_changed():
    bob = friend(filterMovies="label!=keep")
    filters = wanted_filters(bob, {"7": {"curatarr-private-1"}})
    assert filters == {"filterMovies": "label!=keep,curatarr-private-1", "filterTelevision": "label!=curatarr-private-1"}
    assert changed(bob, filters)
    done = friend(filterMovies="label!=keep%2Ccuratarr-private-1", filterTelevision="label!=curatarr-private-1")
    assert not changed(done, wanted_filters(done, {"7": {"curatarr-private-1"}}))


XML = b"""<sharedServers>
  <sharedServer machineIdentifier="machine-1" invitedId="7" invitedEmail="bob">
    <invited id="7" username="bob" friendlyName="Bob"><sharingSettings filterMovies="label!=x" allowSync="1" allowTuners="0"/></invited>
  </sharedServer>
  <sharedServer machineIdentifier="other-server" invitedId="8"><invited id="8" username="eve"><sharingSettings/></invited></sharedServer>
</sharedServers>"""


def test_friends_of_this_server_only():
    def handler(request):
        assert request.headers["x-plex-token"] == "tok" and request.headers["x-plex-client-identifier"] == "cid"
        return httpx.Response(200, content=XML)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        [bob] = friends(http, "tok", "cid", "machine-1")
    assert (bob.id, bob.username, bob.name, bob.settings["filterMovies"]) == ("7", "bob", "Bob", "label!=x")


def test_update_sends_every_setting_back():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    bob = friend(allowSync="1", allowChannels="0", allowTuners="2", filterMusic="label!=m")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        update(http, "tok", "cid", bob, {"filterMovies": "label!=a", "filterTelevision": "label!=a"})
    settings = sent[0]["settings"]
    assert sent[0]["invitedEmail"] == "bob"
    assert (settings["allowSync"], settings["allowChannels"], settings["allowTuners"]) == (True, False, 2)
    assert (settings["filterMusic"], settings["filterMovies"], settings["filterAll"]) == ("label!=m", "label!=a", None)
