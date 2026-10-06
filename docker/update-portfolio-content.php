<?php

if (PHP_SAPI !== 'cli' || !defined('WP_CLI')) {
    fwrite(STDERR, "Run this script through WP-CLI.\n");
    exit(1);
}

if (getenv('WEBSITE_ALLOW_HOME_REPLACE') !== '1') {
    fwrite(STDERR, "Set WEBSITE_ALLOW_HOME_REPLACE=1 to explicitly replace the editable Home page content.\n");
    exit(1);
}

require_once __DIR__ . '/portfolio-pages.php';

$home_id = (int) get_option('page_on_front');
$home = $home_id ? get_post($home_id) : null;
if (!$home || $home->post_type !== 'page' || $home->post_name !== 'home' || $home->post_status !== 'publish') {
    fwrite(STDERR, "Refusing to update: the published Home page is not the current static homepage.\n");
    exit(1);
}

foreach (website_portfolio_pages() as $slug => $page) {
    if ($slug === 'home') {
        $result = wp_update_post(['ID' => $home_id, 'post_content' => $page['content']], true);
    } else {
        $existing = get_page_by_path($slug);
        if ($existing) {
            $result = wp_update_post(['ID' => $existing->ID, 'post_content' => $page['content'], 'post_status' => 'publish'], true);
        } else {
            $result = wp_insert_post([
                'post_type' => 'page',
                'post_status' => 'publish',
                'post_title' => $page['title'],
                'post_name' => $slug,
                'post_content' => $page['content'],
            ], true);
        }
    }
    if (is_wp_error($result)) {
        fwrite(STDERR, "Could not update the $slug page: " . $result->get_error_message() . "\n");
        exit(1);
    }
}

update_option('blogname', 'Fearghal Ó Floinn');

$menu_error = website_portfolio_apply_menu();
if ($menu_error !== null) {
    fwrite(STDERR, $menu_error . "\n");
    exit(1);
}

WP_CLI::success('Updated the portfolio pages and navigation from the reviewed portfolio profile.');