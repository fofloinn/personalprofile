FROM wordpress:php8.3-apache

COPY --from=wordpress:cli-php8.3 /usr/local/bin/wp /usr/local/bin/wp
COPY theme/ /opt/initial-website/
COPY docker/website-entrypoint.sh /usr/local/bin/website-entrypoint.sh
COPY docker/production-config.php docker/private-admin.php docker/portfolio-bootstrap.php docker/portfolio-content.php docker/portfolio-pages.php docker/update-portfolio-content.php /opt/website/
COPY docker/apache-hardening.conf /etc/apache2/conf-enabled/website-hardening.conf
COPY docker/php-hardening.ini /usr/local/etc/php/conf.d/website-hardening.ini

ENTRYPOINT ["sh", "/usr/local/bin/website-entrypoint.sh"]
CMD ["apache2-foreground"]
