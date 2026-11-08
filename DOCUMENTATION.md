# Curatarr documentation

- [Install](#install)
- [Getting started](#getting-started)
- [Collections](#collections)
- [Posters](#posters)
- [How it works](#how-it-works)
- [Configuration](#configuration)
- [Development](#development)

## Install

Curatarr is one container. It listens on port **8080** and keeps everything in **`/data`**.

### Docker Compose

```yaml
services:
  curatarr:
    image: ghcr.io/jdmry/curatarr:latest
    container_name: curatarr
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      ADMIN_USERNAME: admin
      ADMIN_PASSWORD: change-me-please
      PUID: "1000"
      PGID: "1000"
    restart: unless-stopped
```

### Docker run

```sh
docker run -d --name curatarr -p 8080:8080 -v ./data:/data \
  -e ADMIN_USERNAME=admin -e ADMIN_PASSWORD=change-me-please \
  -e PUID=1000 -e PGID=1000 --restart unless-stopped ghcr.io/jdmry/curatarr:latest
```

### Unraid

Add a container with the repository `ghcr.io/jdmry/curatarr:latest`, port `8080`, a path mapped to `/data`
(for example `/mnt/user/appdata/curatarr`), and the variables `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `PUID=99` and
`PGID=100`.

### Login

Every page needs a login, except `/health` (for Docker health checks).

- **The admin account is made at the first start** from `ADMIN_USERNAME` and `ADMIN_PASSWORD` (8 characters at
  least). Without them, the app only shows which variables are missing.
- **After that, change it in Settings → Account.** The variables are then ignored: changing them does nothing.
  You can remove `ADMIN_PASSWORD` from your compose file.
- **Forgot the password?** Run `docker exec -it curatarr python -m app.reset_password`.
- A login lasts 30 days. Changing the password logs out every other browser. After 5 wrong passwords, an
  address has to wait 15 minutes.

Put the app behind HTTPS (your reverse proxy) when it is reachable from the internet, so the password and the
session cookie are never sent in clear.

### Updating

Pull the new image and recreate the container (`docker compose pull && docker compose up -d`). Your data
stays in `/data`.

## Getting started

Open the app: a banner at the top tells you what is missing.

Log in with the admin account (see [Login](#login)), then:

1. **Settings → Plex**: the URL the app uses to reach Plex (often `http://<server-ip>:32400`) and your
   [Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).
   **Test connection** checks them without saving.
2. **Settings → Poster services**: add one (see below).
3. **Collections → Lists**: add a list and pick its poster service, **Preview** it, save, then **Sync to
   Plex**. Its posters are sent right after.

In **Settings → Plex**, untick the libraries you don't use: they disappear from the app (lists, searches,
dashboard). Nothing changes in Plex.

## Collections

### Adding a list

**1. Pick where the list comes from**

| Source | How |
|---|---|
| **MDBList** | Pick one of your lists or a popular one (needs a free API key in **Settings → MDBList**, which also unlocks private lists), or paste a public list URL. |
| **TMDB** | Pick trending, popular, top rated… or paste a TMDB list or collection URL. Needs a free key in **Settings → TMDB** (API key or read access token). |
| **Stremio addon** | Paste the addon's manifest URL (its install link), load its catalogs and pick one. The addon's configuration, which can hold tokens, stays hidden. Catalogs that need a search or a genre aren't offered. |

**2. Choose where it goes in Plex**

- **Library** and **Name** (the list's name by default).
- **Show it in**: **Home and Recommended** (a row on your Home, your friends' Home and the library's
  Recommended tab), **Recommended only**, or **Library only**. Rows on the Home need Plex Pass on the server.
- **Who sees it**: everyone, only you, or one friend (see below).
- **Max titles**: the collection keeps the first titles of the list that you have, up to this number.

**3. Posters**

- **Poster service**: none, the default service or another one. Its titles get their posters right after each
  sync of the list, the first one included. A title in several collections is processed once.

**Preview** shows the collection in list order, up to its last title. Missing titles are greyed at the spot
they will take once added, with their posters (from the list, or from TMDB when a TMDB key is set). With your Seerr address in **Settings → Seerr** (Overseerr and Jellyseerr
work too), each missing title gets a **Request** button that opens its page in Seerr.

### Tabs

| Tab | What it does |
|---|---|
| **Lists** | Your lists. A saved list is only created in Plex by its first sync. **Run test** shows what each collection would get; **Sync to Plex** (or **Sync** on one list) creates or updates them, in the list's order, then sends their posters, with each step shown in Activity. Schedule it (every 1 to 24 hours) to keep collections and posters fresh. |
| **Home order** | The rows of each library, top first, as in Plex's *Manage Recommendations*. Move them with the arrows. |
| **Clean up** | Every collection in your libraries and who made it. Delete the ones no list keeps, like old Agregarr ones; their titles stay in Plex. |

Collections made by Curatarr carry the `Curatarr` label. Syncs never touch other collections, and deleting a
list deletes its collection.

### Who sees a collection

Plex has no per-person collections. For **Only me** or **Only &lt;a friend&gt;**, the collection gets a
`curatarr-private-…` label and every other friend's sharing restrictions (on plex.tv) exclude it. Their
other restrictions, including labels set by hand or by other tools, are kept, and only friends whose
restrictions actually change are updated. A test sync lists those changes without making them. You always
see everything.

## Posters

Posters go to the collections made by your lists: pick a poster service in a list (see
[Adding a list](#adding-a-list)), and its titles get their posters right after each sync of the list.
Whole libraries are left alone: a sync would have to read every title of the library each time.

### Poster services

Add a service in **Settings → Poster services** by picking its type first.

| Type | What you give |
|---|---|
| **PostersPlus** | The URL from its configurator (**Copy config**). It's adapted for Plex: the client is set to Plex and the quality is read from your files (`NONE` when nothing is detected, so PostersPlus never guesses it). |
| **RPDB** | Your API key, a style, a size and a language. The URL is built for you; titles are looked up by IMDb id. |
| **Other image URL** | A URL with placeholders such as `{imdb_id}`, `{tmdb_id}`, `{type}` or `{quality}` (same syntax as AIOMetadata poster patterns, including optional `{name?}`). |

Search any title of your library to preview its poster before saving; nothing is sent to Plex. Keys in
URLs and header values are hidden in the interface and the logs.

If your posters don't show quality badges, untick **Read quality from files**: reading it costs one Plex
request per title, so syncs get much faster without it.

Each list picks its poster service: the default one or another.

### Tabs

| Tab | What it does |
|---|---|
| **Sync** | Posters are sent after each sync of a list, so this is for checking or catching up: **Run test** shows what would change, live, without touching Plex; **Sync to Plex** sends the new posters of every list that has a service. Both only process the number of titles you enter (0 = all). |
| **Manual** | Find any movie or show, compare its current poster with the new one, and apply it. |
| **History** | Every sync, with what was (or would be) changed for each title. |

A title is only sent again when its poster would change (other quality, edited URL, other service) or when
Plex replaced it (Fix Match, poster reset): uploaded posters are locked in Plex, and an unlocked one is sent
again. Plex keeps the previous posters, so you can always switch back in Plex.

## How it works

- **Finding list titles in Plex.** Lists give IMDb, TMDB or TVDB ids, and Plex can't search by id. So
  Curatarr reads the ids of a library once (about a minute for 50,000 movies) and keeps them in its
  database. Then it only reads titles added since, every 10 minutes, and rebuilds the index once a day in
  the background. The first preview of a list on a big library shows "Indexing…" while this runs.
- **Plex images in the UI** go through the app, so the Plex token stays on the server. Nothing is cached on
  disk.
- **Everything lives in `/data/curatarr.db`.** To move an install, stop it and copy that file to the new
  `/data` before the first start.

## Configuration

Everything is set up in the web UI. Only the admin account variables are needed, at the first start.

| Variable | Default | Purpose |
|---|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | – | The admin account, made at the first start. Ignored once it exists. |
| `PUID` / `PGID` | `1000` / `1000` | User and group owning the files in `/data`. |
| `PLEX_URL` | – | Initial Plex URL, e.g. `http://192.168.1.10:32400`. Only used until it's set in the UI. |
| `PLEX_TOKEN` | – | Initial Plex token. Only used until it's set in the UI. |
| `PORT` | `8080` | HTTP port inside the container. |
| `DATA_DIR` | `/data` | Where the database is stored. |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning` or `error`. |
| `UPDATE_CHECK` | `true` | Once a day, ask GitHub for the latest release and show **Update available** in the sidebar. `false` turns it off. |

### Image tags

| Tag | What it is |
|---|---|
| `latest` | The latest release. |
| `0.5.1`, `0.5` | A given release. |
| `edge` | The latest commit on `main`. May break. |

Images are built for `linux/amd64` and `linux/arm64`.

## Development

Python 3.12, FastAPI, Jinja2 and HTMX. No front-end build step.

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
DATA_DIR=./data python -m app
```

To build the image yourself, use `build: .` instead of `image:` in `docker-compose.example.yml`.

**Releasing**: bump `APP_VERSION` in `app/branding.py`, then tag the commit `vX.Y.Z` and push the tag.
GitHub Actions runs the tests, publishes the image and creates the GitHub release.
