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

(
    previous=$(cksum "$chain" "$key")
    while kill -0 "$server_pid" 2>/dev/null; do
        sleep 60
        current=$(cksum "$chain" "$key")
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
