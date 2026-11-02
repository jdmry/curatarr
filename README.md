<div align="center">

# Curatarr

**Posters and collections for your Plex server, from one small web app.**

[![Tests and image](https://github.com/jdmry/curatarr/actions/workflows/docker.yml/badge.svg)](https://github.com/jdmry/curatarr/actions/workflows/docker.yml)
[![Image](https://img.shields.io/badge/image-ghcr.io%2Fjdmry%2Fcuratarr-blue?logo=docker&logoColor=white)](https://github.com/jdmry/curatarr/pkgs/container/curatarr)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

- **Posters**: apply posters from PostersPlus, RPDB or any image service to your libraries, with quality
  badges read from your files. Keep them up to date on a schedule, or do one title by hand.
- **Collections**: turn MDBList, TMDB or Stremio addon lists into Plex collections, on your Home or in
  Recommended, for everyone, only you, or one friend. Reorder your Home rows and clean up old collections.
- **Safe**: a test mode shows what would change before anything is sent to Plex.
- **Simple**: one container, set up in the web UI. No YAML.

## Install

```yaml
services:
  curatarr:
    image: ghcr.io/jdmry/curatarr:latest
    container_name: curatarr
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

Run `docker compose up -d`, then open `http://<your-server>:8080`.

> [!WARNING]
> **There is no login.** Keep the app on your local network, or put it behind your reverse proxy's
> authentication. Don't expose port 8080 to the internet.

## Getting started

1. **Settings → Plex**: your Plex URL and token.
2. **Settings → Poster services**: add PostersPlus, RPDB or another service.
3. **Posters**: tick your libraries, **Run test**, then **Sync to Plex**.
4. **Collections**: add a list, **Preview** it, then **Sync to Plex**.

Everything else, from each tab to the environment variables, is in the [documentation](DOCUMENTATION.md).

## License

[MIT](LICENSE). Not affiliated with Plex, PostersPlus, RPDB, MDBList, TMDB or Stremio.
