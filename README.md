<div align="center">

# Curatarr

**Posters and collections for your Plex server, from one small web app.**

[![Tests and image](https://github.com/jdmry/curatarr/actions/workflows/docker.yml/badge.svg)](https://github.com/jdmry/curatarr/actions/workflows/docker.yml)
[![Image](https://img.shields.io/badge/image-ghcr.io%2Fjdmry%2Fcuratarr-blue?logo=docker&logoColor=white)](https://github.com/jdmry/curatarr/pkgs/container/curatarr)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

- **Collections**: turn MDBList, TMDB or Stremio addon lists into Plex collections, on your Home or in
  Recommended, for everyone, only you, or one friend. Keep them fresh on a schedule, request what's missing in
  Seerr, reorder your Home rows and clean up old collections.
- **Posters**: give each collection posters from PostersPlus, RPDB or any image service, with quality badges
  read from your files, sent after each sync. Or do one title by hand.
- **Safe**: a login protects every page, and a test mode shows what would change before anything is sent to Plex.
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
    environment:
      ADMIN_USERNAME: admin
      ADMIN_PASSWORD: change-me-please
    restart: unless-stopped
```

Run `docker compose up -d`, open `http://<your-server>:8080` and log in. The admin account is made from
`ADMIN_USERNAME` and `ADMIN_PASSWORD` at the first start; change it later in **Settings → Account**.

## Getting started

1. **Settings → Plex**: your Plex URL and token.
2. **Settings → Poster services**: add PostersPlus, RPDB or another service.
3. **Collections**: add a list, pick its poster service, **Preview** it, then **Sync to Plex**. Its posters
   are sent right after.

Everything else, from each tab to the environment variables, is in the [documentation](DOCUMENTATION.md).

## License

[MIT](LICENSE). Not affiliated with Plex, PostersPlus, RPDB, MDBList, TMDB or Stremio.
