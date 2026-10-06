#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
trap 'printf "ERROR: setup failed at line %s. Data volumes were retained; inspect the error before retrying.\n" "$LINENO" >&2' ERR

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

usage() {
    cat <<'EOF'
Usage: bash setup-production.sh --email EMAIL [--backup-dir DIRECTORY]
                                [--old-url URL] [--accept-terms]

Configure fearghal.fnl.life on a fresh host or from an existing installation.
Requires Docker Compose, Python 3, curl, and a private .env file.
Optional restore backups must contain database.sql, wordpress.tgz, and uploads.tgz.
DNS and inbound ports 80/443 must already be configured.
--accept-terms explicitly accepts the Let's Encrypt subscriber agreement.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
compose() { docker compose -f compose.production.yaml "$@"; }

email=''
backup_dir=''
old_url='http://localhost:8080'
accept_terms=false
while (($#)); do
    case "$1" in
        --email|--backup-dir|--old-url)
            (($# >= 2)) || die "Missing value for $1"
            case "$1" in
                --email) email=$2 ;;
                --backup-dir) backup_dir=$2 ;;
                --old-url) old_url=$2 ;;
            esac
            shift 2 ;;
        --accept-terms) accept_terms=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; die "Unknown argument: $1" ;;
    esac
done

[[ $(uname -s) == Linux ]] || die 'Run this script on the Linux hosting machine.'
for tool in docker python3 curl; do
    command -v "$tool" >/dev/null || die "Install $tool first."
done
docker info >/dev/null || die 'Docker is unavailable to this user.'
docker compose version >/dev/null || die 'Install the Docker Compose plugin.'
[[ -f .env && ! -L .env ]] || die 'Copy the existing private .env here; this script never invents replacement database credentials.'
chmod 600 .env
compose config --quiet
compose config --format json | python3 -c '
import json, sys
ports = json.load(sys.stdin)["services"]["proxy"]["ports"]
expected = {"8080": "80", "8443": "443", "8444": "8443"}
if any(str(p["published"]) != expected.get(str(p["target"])) for p in ports):
    sys.exit("ERROR: automated setup requires standard HTTP_PORT=80, HTTPS_PORT=443, ADMIN_PORT=8443.")
'

# Read resolved configuration without sourcing .env as executable shell code.
mapfile -t volumes < <(compose config --format json | python3 -c '
import json, sys
c = json.load(sys.stdin)
for key in ("database-data", "wordpress-data", "wordpress-uploads"):
    print(c["volumes"][key]["name"])
')
[[ ${#volumes[@]} == 3 ]] || die 'Unable to resolve storage volume names.'
wordpress_volume=${volumes[1]}
uploads_volume=${volumes[2]}
fresh_install=false

if [[ -n $backup_dir ]]; then
    backup_dir=$(cd -- "$backup_dir" && pwd)
    for file in database.sql wordpress.tgz uploads.tgz; do
        [[ -s "$backup_dir/$file" ]] || die "Missing or empty backup: $file"
    done
    for volume in "${volumes[@]}"; do
        if docker volume inspect "$volume" >/dev/null 2>&1; then
            die "Restore requires absent destination volumes; $volume already exists. No data was overwritten."
        fi
    done
else
    existing_volume_count=0
    for volume in "${volumes[@]}"; do
        if docker volume inspect "$volume" >/dev/null 2>&1; then
            ((existing_volume_count += 1))
        fi
    done
    if ((existing_volume_count == 0)); then
        fresh_install=true
    elif ((existing_volume_count != ${#volumes[@]})); then
        die 'Only some site volumes exist. Refusing to initialize or back up a partial installation.'
    elif docker run --rm \
        --mount "type=volume,source=$wordpress_volume,target=/site,readonly" \
        --entrypoint sh wordpress:php8.3-apache \
        -c 'test -f /site/wp-content/.website-initial-content-pending' >/dev/null 2>&1; then
        fresh_install=true
    fi
fi

# Reject a second deployment sharing our database/files.
own_ids=$(compose ps -q)
for volume in "${volumes[@]}"; do
    while IFS= read -r container; do
        [[ -z $container ]] && continue
        grep -Fxq "$container" <<< "$own_ids" ||
            die "Another running container uses $volume. Stop that deployment without deleting volumes first."
    done < <(docker ps --no-trunc -q --filter "volume=$volume")
done

compose build --pull
compose pull proxy certbot acme-bootstrap
has_certificate=false
if compose run --rm --no-deps --entrypoint sh certbot -c \
    'test -s /etc/letsencrypt/live/fearghal.fnl.life/fullchain.pem && test -s /etc/letsencrypt/live/fearghal.fnl.life/privkey.pem'; then
    has_certificate=true
fi
if ! $has_certificate; then
    [[ $email == *@*.* && $email != -* ]] || die 'Supply --email with your ACME contact address.'
    if ! $accept_terms; then
        [[ -t 0 ]] || die 'Certificate issuance requires --accept-terms or interactive approval.'
        read -r -p "Accept Let's Encrypt's subscriber agreement and issue the certificate? [y/N] " answer
        [[ $answer == y || $answer == Y ]] || die 'Certificate issuance cancelled.'
    fi
fi

if [[ -n $backup_dir ]]; then
    compose up -d --wait --wait-timeout 180 database
    compose create wordpress
    docker run --rm \
        --mount "type=bind,source=$backup_dir,target=/backup,readonly" \
        --mount "type=volume,source=$wordpress_volume,target=/site" \
        --mount "type=volume,source=$uploads_volume,target=/uploads" \
        --entrypoint sh wordpress:php8.3-apache \
        -c 'set -eu; tar -xzf /backup/wordpress.tgz -C /site; tar -xzf /backup/uploads.tgz -C /uploads'
    compose cp "$backup_dir/database.sql" database:/tmp/site-restore.sql
    # shellcheck disable=SC2016
    compose exec -T database sh -c \
        'set -eu; mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" < /tmp/site-restore.sql; rm /tmp/site-restore.sql'
elif ! $fresh_install; then
    # Take a consistent, private snapshot before rebuilding the running site.
    snapshot="backups/pre-production-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mkdir -p "$snapshot"
    compose stop wordpress
    compose up -d --wait --wait-timeout 180 database
    # shellcheck disable=SC2016
    compose exec -T database sh -c \
        'mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --single-transaction "$MARIADB_DATABASE" > /tmp/site-backup.sql'
    compose cp database:/tmp/site-backup.sql "$snapshot/database.sql"
    compose exec -T database rm /tmp/site-backup.sql
    docker run --rm \
        --mount "type=bind,source=$PWD/$snapshot,target=/backup" \
        --mount "type=volume,source=$wordpress_volume,target=/site,readonly" \
        --mount "type=volume,source=$uploads_volume,target=/uploads,readonly" \
        --entrypoint sh wordpress:php8.3-apache \
        -c 'set -eu; tar -czf /backup/wordpress.tgz --exclude=./wp-content/uploads -C /site .; tar -czf /backup/uploads.tgz -C /uploads .'
    printf 'Private pre-update backup: %s\n' "$snapshot"
fi

compose up -d --wait --wait-timeout 180 wordpress
if compose exec -T wordpress wp --allow-root core is-installed >/dev/null 2>&1; then
    installed=true
else
    # shellcheck disable=SC2016
    compose exec -T wordpress php -r '
$hostParts = explode(":", getenv("WORDPRESS_DB_HOST"), 2);
$host = $hostParts[0];
$port = isset($hostParts[1]) ? (int) $hostParts[1] : 3306;
$connection = mysqli_init();
if (!$connection->real_connect(
    $host,
    getenv("WORDPRESS_DB_USER"),
    getenv("WORDPRESS_DB_PASSWORD"),
    getenv("WORDPRESS_DB_NAME"),
    $port
)) {
    fwrite(STDERR, "Database connection failed: " . $connection->connect_error . PHP_EOL);
    exit(1);
}
$connection->close();
' || die 'WordPress cannot connect to its database.'
    $fresh_install ||
        die 'WordPress is not installed in the existing volumes. No admin account or content was created.'
    installed=false
fi
if $installed; then
    compose exec -T wordpress wp --allow-root search-replace \
        "$old_url" 'https://fearghal.fnl.life' --all-tables-with-prefix --skip-columns=guid
fi

if ! $has_certificate; then
    compose stop proxy
    bash scripts/issue-certificate.sh "$email"
fi
compose up -d --wait --wait-timeout 180

# Check the real certificate and routing locally without depending on router hairpin NAT.
if $installed; then
    curl --fail --silent --show-error --resolve fearghal.fnl.life:443:127.0.0.1 \
        https://fearghal.fnl.life/ >/dev/null
fi
status=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --resolve fearghal.fnl.life:443:127.0.0.1 https://fearghal.fnl.life/wp-admin/)
[[ $status == 403 ]] || die "Public administration check failed: HTTP $status"
curl --fail --silent --show-error --resolve fearghal.fnl.life:8443:127.0.0.1 \
    https://fearghal.fnl.life:8443/wp-login.php >/dev/null

if $installed; then
    printf '\nProduction is ready: https://fearghal.fnl.life\n'
else
    printf '\nProduction containers are ready for the first WordPress setup: https://fearghal.fnl.life\n'
    printf 'Complete WordPress setup through the private admin tunnel; the approved portfolio is seeded on the first administrator visit.\n'
fi
printf 'Admin: SSH tunnel + https://fearghal.fnl.life:8443/wp-admin/\n'
printf 'See docker/PRODUCTION.md for the client hosts entry and SSH command.\n'
