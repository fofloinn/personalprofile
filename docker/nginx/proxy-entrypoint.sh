#!/bin/sh
set -eu

chain=/etc/letsencrypt/live/fearghal.fnl.life/fullchain.pem
key=/etc/letsencrypt/live/fearghal.fnl.life/privkey.pem
if [ ! -s "$chain" ] || [ ! -s "$key" ]; then
    echo 'ERROR: issue the certificate using the documented bootstrap steps first' >&2
    exit 1
fi

nginx -t
nginx -g 'daemon off;' &
server_pid=$!

certificate_checksum() {
    # Include every separate lineage (HA is optional). Follow certbot's symlinks.
    for certificate in /etc/letsencrypt/live/*/fullchain.pem /etc/letsencrypt/live/*/privkey.pem; do
        [ ! -f "$certificate" ] || cksum "$certificate"
    done
}

(
    previous=$(certificate_checksum)
    while kill -0 "$server_pid" 2>/dev/null; do
        sleep 60
        current=$(certificate_checksum)
        if [ "$current" != "$previous" ]; then
            if nginx -t && nginx -s reload; then
                previous=$current
            else
                echo 'ERROR: renewed certificate could not be reloaded; retrying' >&2
            fi
        fi
    done
) &
watcher_pid=$!

trap 'kill "$watcher_pid" "$server_pid" 2>/dev/null || true' TERM INT EXIT
wait "$server_pid"
