#!/usr/bin/env bash
# Use for ALL production lifecycle commands so the optional proxy interface survives.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
umask 077
if [[ -L .local || -L .local/ha-nginx || -L .local/ha-compose.json ]]; then
    printf 'ERROR: optional production configuration must not be symlinked.\n' >&2
    exit 1
fi
mkdir -p .local/ha-nginx
# nginx has no DAC_OVERRIDE capability; .local (unmounted) keeps host privacy.
chmod 755 .local/ha-nginx
args=(-f compose.production.yaml)
if [[ -f .local/ha-compose.json ]]; then
    args+=(-f .local/ha-compose.json)
fi
exec docker compose "${args[@]}" "$@"
