<?php

define('DISALLOW_FILE_EDIT', true);
define('FORCE_SSL_ADMIN', true);
define('WP_HOME', 'https://fearghal.fnl.life');

// Only the private proxy listener sets this; WordPress has no published port.
$private_admin = ($_SERVER['HTTP_X_WEBSITE_ADMIN'] ?? '') === '1';
define('WP_SITEURL', $private_admin ? 'https://fearghal.fnl.life:8443' : WP_HOME);
define('COOKIE_DOMAIN', 'fearghal.fnl.life');

if (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https') {
    $_SERVER['HTTPS'] = 'on';
}

if (!$private_admin) {
    $path = rawurldecode(explode('?', $_SERVER['REQUEST_URI'] ?? '/', 2)[0]);
    if (preg_match('~/(wp-admin|wp-login\.php|xmlrpc\.php)(/|$)~i', $path)) {
        http_response_code(403);
        exit('Forbidden');
    }
}
