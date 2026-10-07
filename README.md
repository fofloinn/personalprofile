# Personal profile website

A self-hosted WordPress site with a small custom theme for presenting professional experience, education, and a personal introduction. WordPress keeps page content editable in the browser; Docker Compose runs WordPress and MariaDB with persistent database, WordPress files, and uploads volumes.

## Run locally

1. Copy `.env.example` to `.env` and replace both example passwords with long, unique values. In PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Start the containers:

   ```sh
   docker compose up -d --build
   ```

3. Open `http://localhost:8080` (or the port set by `PORT` in `.env`) and complete WordPress's normal first-run setup to create a private administrator account. No account credentials or user records are stored in the repository.
4. On the first signed-in administrator request after setup, the site automatically activates **Initial Website**, creates the editable **Home** page with the approved portfolio content, sets it as the homepage, applies the site title/tagline, and creates its profile navigation. No manual content entry or database/volume backup transfer is needed for a new installation.

The homepage content remains editable in WordPress. Its version-controlled bootstrap runs only when the WordPress data volume was initially empty and the database still contains only WordPress's starter content; existing installations and content are left untouched. It runs once, and later rebuilds/restarts do not replace edits. The theme uses local system fonts, a light blue palette, and rounded buttons without external font or script dependencies. Update theme files and rebuild with `docker compose up -d --build` when changing the design. Page content and uploaded media are stored separately and survive container rebuilds.

For a deliberate profile refresh on a site that is already initialized, rebuild the image and use the guarded content updater described in [production setup](docker/PRODUCTION.md#refresh-the-reviewed-portfolio-on-an-existing-site). It replaces the Home, Experience, Projects, Skills and Education pages and recreates the navigation menu, so save desired edits first.

## Container updates and persistence

WordPress setup is a one-time step. The database stores accounts, page content, menus, and settings; `wordpress-data` keeps WordPress files and installed plugins, and `wordpress-uploads` keeps uploaded media. Normal container recreation and `docker compose down` preserve these named volumes. Never use `docker compose down -v` unless you intend to delete the site's data.

The custom entrypoint copies the bundled theme from `/opt/initial-website` into the WordPress data volume each time the container starts. This ensures rebuilt theme files take effect rather than being hidden by the data volume. Edit the theme in this repository, not inside WordPress: matching theme files are overwritten on startup. Stylesheet URLs use the file's modification time for cache invalidation.

To deploy repository changes, use `docker compose up -d --build`. To refresh the upstream WordPress image as well, use `docker compose build --pull` followed by `docker compose up -d`. The persistent WordPress installation still needs core and plugin updates through the WordPress dashboard; pulling the base image alone does not replace core files already in the data volume.

For an installation created before `wordpress-data` was added, migrate the old `/var/www/html` volume before recreating the container. Back up the database and site files, then copy the old container's WordPress files into the new named volume, leaving the separate uploads volume intact. Merely attaching a new empty volume would lose access to existing plugins and local configuration.

## Useful commands

```sh
docker compose ps
docker compose logs -f wordpress
docker compose down
docker compose up -d --build
docker compose exec wordpress php -l /var/www/html/wp-content/themes/initial-website/functions.php
```

The PHP lint command checks one file; replace `functions.php` with another PHP file under `theme/` to check that file. Production integration checks run with `node scripts/check-production.mjs`; prerequisites and optional authenticated checks are described in `docker/PRODUCTION.md`.

The bootstrap behavior has an isolated PHP test harness. Run it with the PHP image without mounting any site volumes or private data:

```sh
docker run --rm \
  --mount type=bind,source="$(pwd)/docker",target=/docker,readonly \
  --mount type=bind,source="$(pwd)/scripts/test-portfolio-bootstrap.php",target=/tmp/test-portfolio-bootstrap.php,readonly \
  wordpress:php8.3-apache php /tmp/test-portfolio-bootstrap.php
```

## Playwright MCP

`.github/mcp.json` configures Playwright MCP for Copilot CLI in this repository. It uses a pinned package version, runs Microsoft Edge headlessly, and keeps its browser profile isolated in memory rather than accessing your normal browser sessions.

Requirements: Node.js 18 or newer, npm, and Microsoft Edge installed on the development machine. MCP runs on the host, not inside WordPress, and is not needed to serve the website.

Start a new Copilot CLI session in this repository and approve folder trust when prompted. Use `/mcp show playwright` to confirm the server is available. For example, ask Copilot:

> Use Playwright MCP to open http://localhost:8080 and check the page at desktop and mobile sizes.

Until WordPress setup is complete, this URL shows the installation wizard rather than the portfolio. Browser checks should not create administrator accounts or change site content without explicit instructions. For a different development machine, change `--browser` in the MCP configuration to an installed supported browser.

## Home hosting

The hardened Linux deployment for **fearghal.fnl.life** uses `compose.production.yaml`, Nginx rate limiting, automatic Let's Encrypt certificates, and an SSH-only admin listener. See [production setup and migration](docker/PRODUCTION.md) before starting it. Use this file on its own, not merged with the development Compose file.

To intentionally restore an existing site to a new host, transfer its private `.env` and trusted backups, then run `bash setup-production.sh --email YOUR-ACME-CONTACT-EMAIL --backup-dir ./backups --accept-terms` from the repository root on Linux. For a site whose named volumes already exist on that host, omit `--backup-dir`.

For a **new host**, no WordPress/database/uploads backups are required: prepare a private `.env` with unique database passwords, configure DNS/port forwarding, and run `bash setup-production.sh --email YOUR-ACME-CONTACT-EMAIL --accept-terms`. The script starts a clean installation without creating an administrator account; complete WordPress's first-run setup through the private admin tunnel. The approved portfolio is then seeded on the first signed-in administrator request. Existing installations retain the backup/restore path below and are never reseeded.

The default `compose.yaml` is for development and binds WordPress to host loopback only.

Optional, no-subscription Home Assistant HTTPS on the same Linux host has separate
[privacy, network and HA UI gates](docker/HOME_ASSISTANT_HTTPS.md). It is disabled by
default. Use `python3 scripts/setup-ha-https.py prepare`, then complete the mandatory
UI stop before `enable`. Use `bash scripts/production-compose.sh` for production
lifecycle commands so the dedicated proxy interface survives redeployment.

Keep `.env` private. Back up the database and both WordPress volumes before updates or migration. For public access, put the site behind a reverse proxy that provides HTTPS and configure your domain and router accordingly. Do not expose the WordPress container directly to the public internet without HTTPS and appropriate host firewall rules.

## License

The code and configuration are released under the [MIT License](LICENSE). The personal profile content in `docker/portfolio-content.php` and the CV PDF in `theme/assets` are not covered by that licence and remain all rights reserved.
