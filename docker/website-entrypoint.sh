#!/bin/sh
set -eu

# WordPress's data volume masks image files, so deploy the bundled theme at startup.
theme_path=/var/www/html/wp-content/themes/initial-website
mkdir -p "$theme_path"
cp -a /opt/initial-website/. "$theme_path/"
chown -R www-data:www-data "$theme_path"

mkdir -p /var/www/html/wp-content/mu-plugins
cp /opt/website/private-admin.php /var/www/html/wp-content/mu-plugins/website-private-admin.php
cp /opt/website/portfolio-bootstrap.php /var/www/html/wp-content/mu-plugins/website-portfolio-bootstrap.php
chown www-data:www-data \
    /var/www/html/wp-content/mu-plugins/website-private-admin.php \
    /var/www/html/wp-content/mu-plugins/website-portfolio-bootstrap.php

# The official entrypoint creates wp-config.php after this runs; existing installations already have it.
if [ ! -e /var/www/html/wp-config.php ]; then
    : > /var/www/html/wp-content/.website-initial-content-pending
    chown www-data:www-data /var/www/html/wp-content/.website-initial-content-pending
fi

if [ "${WEBSITE_PRODUCTION:-0}" = "1" ] && [ -f /var/www/html/wp-config.php ]; then
    if ! grep -q WORDPRESS_CONFIG_EXTRA /var/www/html/wp-config.php; then
        echo 'ERROR: wp-config.php must support WORDPRESS_CONFIG_EXTRA before production startup' >&2
        exit 1
    fi
fi

exec docker-entrypoint.sh "$@"
