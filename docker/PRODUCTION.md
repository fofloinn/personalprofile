# Production hosting: fearghal.fnl.life

## Exposure and administration

Use `compose.production.yaml` as a standalone Compose file, not an override merged with `compose.yaml`. Production publishes only the reverse proxy's HTTP/HTTPS ports and a loopback-only administration port. Neither WordPress nor MariaDB publishes a host port.

Public HTTPS is read-only: GET/HEAD requests are permitted, while WordPress admin/login routes, REST (both URL forms), XML-RPC, PHP paths, dotfiles, and backup/configuration files are blocked. A must-use plugin provides an additional public REST boundary. Public forms, frontend REST-dependent plugins, application passwords, and external XML-RPC clients are intentionally unsupported.

The private listener is HTTPS on host `127.0.0.1:8443`, available through SSH only. WordPress uses `https://fearghal.fnl.life:8443` for private admin and REST URLs while retaining `https://fearghal.fnl.life` as the public homepage. Incoming forwarded headers are overwritten by the proxy. Do not expose the WordPress backend or connect untrusted containers to its network.

## Before starting on Ubuntu

### Automated setup from the repository root

After installing Docker and configuring DNS/router forwarding, run the installer from the repository root:

```sh
bash setup-production.sh --email YOUR-ACME-CONTACT-EMAIL --accept-terms
```

With no existing site volumes, the script starts a clean WordPress installation and does not require database, WordPress-file, or uploads backups. It creates no administrator account. Complete WordPress's normal first-run setup through the private admin tunnel; on the first signed-in administrator request, the bundled bootstrap creates the approved portfolio page and site settings. No account credentials or user records are included in the image or repository.

When all site volumes already exist without a pending first-install marker, the script treats them as an existing installation, takes a private pre-update backup, keeps credentials intact, migrates stored localhost URLs, issues a certificate only when missing, and starts/checks the hardened services. An unfinished first install can be rerun without a backup while its one-time marker remains. Use `--old-url` if migrating an existing installation from a different origin. A partially present volume set is refused. Rerunning against an installed deployment preserves content and reuses its certificate.

### Refresh the reviewed portfolio on an existing site

The first-install bootstrap never overwrites an existing Home page. To deliberately replace that page with the latest reviewed, generic profile from the repository, pull and rebuild the WordPress image, activate the custom theme, then run:

```sh
docker compose -f compose.production.yaml up -d --build wordpress
docker compose -f compose.production.yaml exec -T wordpress wp --allow-root theme activate initial-website
docker compose -f compose.production.yaml exec -e WEBSITE_ALLOW_HOME_REPLACE=1 -T wordpress wp --allow-root eval-file /opt/website/update-portfolio-content.php
```

This updates the published Home page plus the Experience, Projects, Skills and Education pages (created if missing) and recreates the Profile navigation menu on the primary location. It replaces those pages' block content, so save any edits you want to keep first; WordPress normally stores the previous content as a revision. It does not change accounts, any other pages, uploads, or database credentials. The Microsoft description intentionally stays at a public, role-and-impact level and omits product names, internal tools, and internal operating processes.

Optional restoration of an existing installation still requires trusted database/WordPress/uploads backups and absent destination volumes; pass them explicitly with `--backup-dir`. Restore refuses to overwrite existing storage. A failed run reports an error; it does not delete volumes or automatically attempt a destructive rollback. If restore fails partway, follow an intentional recovery plan before retrying. Only restore archives you trust.

The script requires Python 3 and curl in addition to Docker Compose. It does not install Docker, change your firewall/router/DNS/SSH policy, edit your development computer's hosts file, or create WordPress admin accounts. `--accept-terms` explicitly accepts the Let's Encrypt subscriber agreement; without it, first issuance asks interactively. Existing certificates need no renewed acceptance.

On Linux, run mocked setup checks with `python3 scripts/test-setup-production.py`. A single check can be run with `python3 scripts/test-setup-production.py SetupTests.test_restore_refuses_existing_volumes`; these tests do not access real Docker storage or issue certificates.

Install Docker Engine and the Docker Compose plugin. From the repository root:

1. Point the domain's A record to your home public IPv4 address. Only publish an AAAA record if IPv6 routing and firewall rules work too. Use DNS-only records rather than a CDN proxy with this direct-client-IP rate-limit configuration.
2. Forward router TCP ports 80 and 443 to the Ubuntu host. Do not forward 8080, 8443, or MariaDB. If your ISP uses CGNAT or blocks these ports, this HTTP-01 deployment will need a different approach.
3. Keep SSH restricted to your trusted network/VPN where possible, use SSH keys, and leave remote root/password login disabled according to your host's policy. HTTPS administration still requires your WordPress account.
4. Copy the repository. For a new site, create `.env` from `.env.production.example`, replace both database password placeholders with unique values, and keep it private (`chmod 600 .env`). For an existing site, preserve its database credentials and follow the optional restore procedure below when moving its data.
5. If a development Compose stack is running on this Linux host, stop it with `docker compose down` first. Never run the development and production WordPress services against the same volumes simultaneously.

Docker-published ports can bypass ordinary UFW rules. Verify actual exposure from another machine rather than relying on UFW alone.

## Start a new site without data backups

After DNS, router forwarding, and the private `.env` are ready, run:

```sh
bash setup-production.sh --email YOUR-ACME-CONTACT-EMAIL --accept-terms
```

The installer creates fresh named volumes, builds the versioned theme/content bootstrap, obtains the certificate if needed, and starts the hardened services. It deliberately leaves WordPress account creation to the owner. Use the private SSH tunnel in [Use the private WordPress editor](#use-the-private-wordpress-editor) and complete the first-run WordPress setup, then load the admin dashboard. The initial-content bootstrap activates the theme, fills the editable Home page, sets the title/tagline and static homepage, and creates the profile navigation. It runs only when the WordPress files volume was new and the database has only WordPress's untouched starter content. It never updates or imports content into an existing installation. Subsequent container starts and image rebuilds preserve edits.

The public site is not complete until that one-time private WordPress setup and first administrator request have finished. The bootstrap does not create accounts or passwords.

## Preserve the populated site

This optional procedure is only for intentionally preserving an existing site's content, accounts, media, and settings. Those private records are not embedded in the Git repository. A clean installation uses the versioned bootstrap above and does not need a data transfer.

On the source machine, create a private `backups` directory. These commands work in PowerShell or a Linux shell:

```sh
docker compose exec -T database sh -c 'mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --single-transaction "$MARIADB_DATABASE" > /tmp/site.sql'
docker compose cp database:/tmp/site.sql backups/database.sql
docker compose stop wordpress
docker compose exec -T database sh -c 'test -s /tmp/site.sql'
```

Since WordPress is stopped, export its volumes with a temporary helper container. This PowerShell form uses the current repository's volume names:

```powershell
docker run --rm --mount "type=bind,source=$((Get-Location).Path)\backups,target=/backup" --mount type=volume,source=website_wordpress-data,target=/site,readonly --mount type=volume,source=website_wordpress-uploads,target=/uploads,readonly --entrypoint sh wordpress:php8.3-apache -c 'tar -czf /backup/wordpress.tgz --exclude=./wp-content/uploads -C /site . && tar -czf /backup/uploads.tgz -C /uploads .'
```

The brief stop avoids concurrent file changes. For a busy site, stop WordPress **before** the database dump as well. Copy the three backup files and `.env` to the Ubuntu host using a secure transfer. The backups contain private data and must not be committed. Restart the source only if it will not be used concurrently with the migrated deployment.

On Ubuntu, from the repository root, restore before WordPress starts:

```sh
docker compose -f compose.production.yaml build --pull
docker compose -f compose.production.yaml up -d database
docker compose -f compose.production.yaml create wordpress
docker compose -f compose.production.yaml cp backups/database.sql database:/tmp/site.sql
docker compose -f compose.production.yaml exec -T database sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" < /tmp/site.sql'

docker run --rm \
  --mount type=bind,source="$(pwd)/backups",target=/backup,readonly \
  --mount type=volume,source=website_wordpress-data,target=/site \
  --mount type=volume,source=website_wordpress-uploads,target=/uploads \
  --entrypoint sh wordpress:php8.3-apache \
  -c 'tar -xzf /backup/wordpress.tgz -C /site && tar -xzf /backup/uploads.tgz -C /uploads'
```

These restore commands assume the destination volumes are empty. Do not import over a populated site without an intentional restore plan. The explicit `website_*` volume names preserve identity regardless of checkout-directory name; if you use another `SITE_VOLUME_PREFIX`, adjust helper volume names to match.

The existing `wp-config.php` must support the official `WORDPRESS_CONFIG_EXTRA` environment hook. The entrypoint and must-use plugin reject unsupported production configuration rather than silently leaving an insecure site running.

## Issue the real certificate

Once DNS and router forwarding work, run:

```sh
sh scripts/issue-certificate.sh your-contact-email@example.com
docker compose -f compose.production.yaml up -d --build --wait
docker compose -f compose.production.yaml logs --tail 50 proxy certbot
```

The certificate script uses the supplied email for your ACME account and accepts Let's Encrypt's subscriber agreement. It temporarily serves only HTTP-01 challenges on port 80, issues a real certificate into the persistent `certificates` volume, then stops the bootstrap listener. Do not run it while the production proxy already owns port 80.

The production proxy deliberately refuses to start without a certificate. Certificates are not embedded in the image or committed to Git. Certbot checks for renewal every 12 hours; Nginx detects changed certificate files and reloads within approximately a minute. Monitor renewal errors and certificate expiry. Certificate private keys remain on the host in the certificate volume; only the proxy mounts them read-only.

## Use the private WordPress editor

On your **development computer**, add this temporary hosts-file entry:

```text
127.0.0.1 fearghal.fnl.life
```

Windows hosts file: `C:\Windows\System32\drivers\etc\hosts`. Linux/macOS: `/etc/hosts`.

Start the tunnel, using the Ubuntu machine's LAN IP or another SSH-reachable address, **not** the hostname now mapped to localhost:

```sh
ssh -N -L 127.0.0.1:8443:127.0.0.1:8443 your-user@YOUR-LINUX-HOST-IP
```

Open **https://fearghal.fnl.life:8443/wp-admin/**. The normal domain certificate remains valid on this alternate port. Do not bypass certificate warnings. Keep local port 8443; WordPress's private origin uses that port even if the server-side port mapping is customized.

The hosts entry redirects the public hostname locally too. To view public pages, remove it after editing or use a different device. Optionally forward local 443 to the server's public 443 listener as well, if you can bind that local port, so public previews work while the hosts entry remains active. Never use a global DNS record pointing this domain to 127.0.0.1.

After migration, use the bundled WP-CLI to update stored links, including serialized menu/media settings. First preview, then apply:

```sh
docker compose -f compose.production.yaml exec -T wordpress wp --allow-root search-replace 'http://localhost:8080' 'https://fearghal.fnl.life' --all-tables-with-prefix --skip-columns=guid --dry-run
docker compose -f compose.production.yaml exec -T wordpress wp --allow-root search-replace 'http://localhost:8080' 'https://fearghal.fnl.life' --all-tables-with-prefix --skip-columns=guid
```

Substitute the actual old origin if it differs. The `guid` column is deliberately preserved. Relative navigation targets such as `/#experience` avoid tying links to a specific hostname. Do not use raw SQL replacement on serialized WordPress data.

## Hardening and limitations

- Public requests are limited to 5 requests/second per direct client IP with a burst of 30 and a maximum of 20 active connections. Excess requests return 429. Private login is limited to 5 requests/minute with a burst of 5. The editor itself is not subjected to that login limit.
- TLS 1.2/1.3, HSTS for this hostname, MIME-sniffing protection, same-origin framing, and restrictive device permissions are configured. A blanket CSP is not imposed because it can break WordPress's editor and plugin assets.
- Proxy filesystems are read-only with temporary writable directories; capability sets are reduced, privilege escalation is disabled, and log rotation/memory limits are configured. WordPress must retain writable data volumes and limited startup capabilities for Apache and theme deployment.
- Apache denies PHP-family execution in uploads, uploaded `.htaccess` overrides, directory indexes, configuration files, and backup files. PHP hides its version and reports errors to logs, not responses.
- WordPress's theme/plugin code editor, XML-RPC, and application passwords are disabled. Keep WordPress core and plugins updated through the private dashboard. Rebuilding the image does not update core files already in the WordPress volume.
- HTTP-01 requires port 80 continuously for future renewals. Do not disable it after initial issuance.
- No container configuration makes an unpatched WordPress/plugin installation immune to compromise. Keep backups off-host, protect `.env` and SSH keys, and install only needed plugins.

## Updates and checks

```sh
docker compose -f compose.production.yaml pull
docker compose -f compose.production.yaml up -d --build --wait
docker compose -f compose.production.yaml ps
```

Back up first, especially before MariaDB/core updates. Never use `down -v`. The production file does not reuse the development port mapping.

From a development machine with Node.js 18+, run `node scripts/check-production.mjs` with the private tunnel active and hostname resolution set appropriately. Public checks connect to `TEST_HOST` (default: the public domain); private checks connect to `TEST_ADMIN_HOST` (default: `127.0.0.1`) through the tunnel, retaining the correct HTTPS hostname. The checker exercises public HTTPS, restricted paths, headers, private login-page reachability, and rate limiting. To test authenticated editing, provide `TEST_ADMIN_USER` and `TEST_ADMIN_PASSWORD` through your shell's environment, not the repository or command history. The checker opens an unsaved editor page but does not publish content.

Because the hosts-file entry changes DNS, use `TEST_HOST=YOUR-LINUX-HOST-IP` for checks when the server is directly reachable; the checker retains the correct TLS hostname. Set `TEST_ADMIN_PORT` only if connecting to a differently mapped test listener. Public-only external route checks can also be made with `curl -I https://fearghal.fnl.life/wp-admin/` (expect 403) from a device without the hosts override.

## Public CV download

The hero's "Download CV (PDF)" button serves 	heme/assets/Fearghal-O-Floinn-CV.pdf, generated from the reviewed public profile content so it excludes address, phone, email, and date of birth. After editing docker/portfolio-content.php, regenerate it with python scripts/build-cv.py (requires eportlab) and commit the PDF.
