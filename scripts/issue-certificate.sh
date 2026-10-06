#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: sh scripts/issue-certificate.sh your-acme-contact-email" >&2
    exit 1
fi

compose() {
    docker compose -f compose.production.yaml "$@"
}

trap 'compose stop acme-bootstrap' EXIT
compose --profile bootstrap up -d acme-bootstrap
compose run --rm --no-deps --entrypoint certbot certbot certonly \
    --webroot -w /var/www/acme \
    --cert-name fearghal.fnl.life -d fearghal.fnl.life \
    --email "$1" --agree-tos --non-interactive
