<?php
/**
 * Plugin Name: Private administration boundary
 */

if (getenv('WEBSITE_PRODUCTION') !== '1') {
    return;
}

if (!defined('WP_HOME') || WP_HOME !== 'https://fearghal.fnl.life' || !defined('FORCE_SSL_ADMIN') || !FORCE_SSL_ADMIN) {
    http_response_code(503);
    error_log('Production WordPress configuration was not loaded; check wp-config.php WORDPRESS_CONFIG_EXTRA support.');
    exit('Production configuration error');
}

add_filter('xmlrpc_enabled', '__return_false');
add_filter('wp_is_application_passwords_available', '__return_false');
add_filter('rest_url', function ($url) {
    if (($_SERVER['HTTP_X_WEBSITE_ADMIN'] ?? '') === '1') {
        return preg_replace('~^https://fearghal\.fnl\.life(?=/|$)~', 'https://fearghal.fnl.life:8443', $url);
    }
    return $url;
});
add_filter('rest_authentication_errors', function ($result) {
    if (($_SERVER['HTTP_X_WEBSITE_ADMIN'] ?? '') !== '1') {
        return new WP_Error('private_rest_only', 'REST access is private.', ['status' => 403]);
    }
    return $result;
}, 100);
