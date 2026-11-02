<div align="center">

# Curatarr

**Posters and collections for your Plex server, from one small web app.**

Apply posters from PostersPlus, RPDB or any image service to your whole library,
and turn MDBList, TMDB or Stremio addon lists into Plex collections that stay up to date.

[![Tests and image](https://github.com/jdmry/curatarr/actions/workflows/docker.yml/badge.svg)](https://github.com/jdmry/curatarr/actions/workflows/docker.yml)
[![Image](https://img.shields.io/badge/image-ghcr.io%2Fjdmry%2Fcuratarr-blue?logo=docker&logoColor=white)](https://github.com/jdmry/curatarr/pkgs/container/curatarr)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

---

## Features

**Posters**
- Use **PostersPlus**, **RPDB**, or any service that returns an image for a movie or show id.
- Pick whole libraries or single collections, each with its own service.
- Quality badges (4K, DV, ATMOS…) come from your actual files, never guessed.
- Only what changed is sent again; posters replaced in Plex (Fix Match) are put back.
- Do one title by hand, or sync everything on a schedule.

**Collections**
- Lists from **MDBList** (yours, private ones too, or popular ones), **TMDB** (trending, popular, any list)
  or a **Stremio addon** catalog (Netflix, Prime Video…).
- Kept in the list's order, on your Home, in Recommended, or only in the library.
- For everyone, only you, or one friend.
- Reorder your Home rows, and clean up old collections made by other tools.

**Built to be safe and light**
- **A test mode for everything**: see what would change before anything is sent to Plex.
- Everything is set up in the web UI. No YAML.
- One container, one SQLite file. No image is ever stored on disk.
- Keys and tokens are hidden in the interface and the logs; your Plex token never reaches the browser.

## Quick start

```yaml
# docker-compose.yml
services:
  curatarr:
    image: ghcr.io/jdmry/curatarr:latest
    container_name: curatarr
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      PUID: "1000"
      PGID: "1000"
    restart: unless-stopped
```

```sh
docker compose up -d
```

Open `http://<your-server>:8080` and follow the banner at the top.

Or with `docker run`:

```sh
docker run -d --name curatarr -p 8080:8080 -v ./data:/data \
  -e PUID=1000 -e PGID=1000 --restart unless-stopped ghcr.io/jdmry/curatarr:latest
```

> [!WARNING]
> **There is no login.** Anyone who can open the app can change your Plex posters and collections.
> Keep it on your local network, or put it behind your reverse proxy's authentication
> (basic auth, Authelia, Authentik…). Don't expose port 8080 to the internet.

### Unraid

Add a container with the repository `ghcr.io/jdmry/curatarr:latest`, port `8080`, a path mapped to `/data`
(for example `/mnt/user/appdata/curatarr`), and the variables `PUID=99` and `PGID=100`.

### CapRover

1. Create an app with **Has Persistent Data** checked, and add a persistent directory with path in app `/data`.
2. In **HTTP Settings**: set **Container HTTP Port** to `8080`, enable HTTPS, and enable **HTTP Basic Auth**.
3. In **Deployment**, deploy the image `ghcr.io/jdmry/curatarr:latest`. Deploy it again to update.

## Getting started

1. **Settings → Plex**: the URL the app uses to reach Plex (often `http://<server-ip>:32400`) and your
   [Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).
2. **Settings → Poster services**: add one (see below).
3. **Posters → Libraries**: tick what gets posters.
4. **Posters → Auto sync**: **Run test** on a few titles, check, then **Sync to Plex**.
5. **Collections → Lists**: add a list, **Preview** it, save, then **Sync to Plex**.

## Posters

### Poster services

Add a service by picking its type first.

| Type | What you give |
|---|---|
| **PostersPlus** | The URL from its configurator (**Copy config**). It's adapted for Plex: the client is set to Plex and the quality is read from your files (`NONE` when nothing is detected, so PostersPlus never guesses it). |
| **RPDB** | Your API key, a style, a size and a language. The URL is built for you; titles are looked up by IMDb id. |
| **Other image URL** | A URL with placeholders such as `{imdb_id}`, `{tmdb_id}`, `{type}` or `{quality}` (same syntax as AIOMetadata poster patterns, including optional `{name?}`). |

Search any title of your library to preview its poster before saving; nothing is sent to Plex.
If your posters don't show quality badges, untick **Read quality from files**: syncs get much faster.

### Tabs

| Tab | What it does |
|---|---|
| **Libraries** | Tick whole libraries or only some collections, each with the default service or another one. A collection's own service wins over its library's. |
| **Auto sync** | **Run test** shows what would change, live, without touching Plex. **Sync to Plex** sends the new posters. Set a schedule (every 1 to 24 hours) to keep them up to date. |
| **Manual** | Find any movie or show, compare its current poster with the new one, and apply it. |
| **History** | Every sync, with what was (or would be) changed for each title. |

A title is only sent again when its poster would change (other quality, edited URL, other service) or when
Plex replaced it: uploaded posters are locked in Plex, and an unlocked one is sent again. Plex keeps the
previous posters, so you can always switch back in Plex.

## Collections

### Adding a list

**1. Pick where the list comes from**

| Source | How |
|---|---|
| **MDBList** | Pick one of your lists or a popular one (needs a free MDBList API key in **Settings → MDBList**, which also unlocks private lists), or paste a public list URL. |
| **TMDB** | Pick trending, popular, top rated… or paste a TMDB list or collection URL. Needs a free TMDB key in **Settings → TMDB**. |
| **Stremio addon** | Paste the addon's manifest URL (its install link), load its catalogs and pick one. The addon's configuration, which can hold tokens, stays hidden. |

**2. Choose where it goes in Plex**: the library, the name, how many titles, where it shows
(**Home and Recommended**, **Recommended only**, **Library only**) and who sees it.

**Preview** shows which titles of the list you have and which are missing.

### Tabs

| Tab | What it does |
|---|---|
| **Lists** | Your lists. **Run test** shows what each collection would get; **Sync to Plex** (or **Sync** on one list) creates or updates them, in the list's order. Schedule it to keep them fresh. |
| **Home order** | The rows of each library, top first, as in Plex's *Manage Recommendations*. Move them with the arrows. |
| **Clean up** | Every collection in your libraries and who made it. Delete the ones no list keeps, like old Agregarr ones; their titles stay in Plex. |

Collections made by Curatarr carry the `Curatarr` label. Syncs never touch other collections, and deleting a
list deletes its collection.

### Who sees a collection

Plex has no per-person collections. For **Only me** or **Only &lt;a friend&gt;**, the collection gets a
`curatarr-private-…` label and every other friend's sharing restrictions (on plex.tv) exclude it. Their
other restrictions, including labels set by hand or by other tools, are kept, and only friends whose
restrictions actually change are updated. A test sync lists those changes without making them.
Rows on the Home need Plex Pass on the server.

## How it works

- **Finding list titles in Plex.** Lists give IMDb, TMDB or TVDB ids, and Plex can't search by id. So
  Curatarr reads the ids of a library once (about a minute for 50,000 movies) and keeps them in its
  database. Then it only reads titles added since, every 10 minutes, and rebuilds the index once a day in
  the background.
- **Plex images in the UI** go through the app, so the Plex token stays on the server. Nothing is cached on
  disk.
- **Everything lives in `/data/curatarr.db`.** To move an install, stop it and copy that file to the new
  `/data`.

## Configuration

Everything is set up in the web UI. Environment variables are optional.

| Variable | Default | Purpose |
|---|---|---|
| `PUID` / `PGID` | `1000` / `1000` | User and group owning the files in `/data`. |
| `PLEX_URL` | – | Initial Plex URL, e.g. `http://192.168.1.10:32400`. Only used until it's set in the UI. |
| `PLEX_TOKEN` | – | Initial Plex token. Only used until it's set in the UI. |
| `PORT` | `8080` | HTTP port inside the container. |
| `DATA_DIR` | `/data` | Where the database is stored. |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning` or `error`. |

### Image tags

| Tag | What it is |
|---|---|
| `latest` | The latest release. |
| `0.1.0`, `0.1` | A given release. |
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
GitHub Actions runs the tests and publishes the image.

## License

[MIT](LICENSE). Curatarr is not affiliated with Plex, PostersPlus, RPDB, MDBList, TMDB or Stremio.
