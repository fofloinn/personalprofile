<?php

require_once (is_file(__DIR__ . '/portfolio-pages.php') ? __DIR__ : '/opt/website') . '/portfolio-pages.php';

function website_portfolio_is_fresh_install(): bool {
    if (get_option('show_on_front') !== 'posts' || (int) get_option('page_on_front') !== 0) {
        return false;
    }

    $posts = get_posts([
        'post_type' => ['page', 'post'],
        'post_status' => ['publish', 'future', 'draft', 'pending', 'private', 'auto-draft', 'trash'],
        'posts_per_page' => -1,
        'orderby' => 'ID',
        'order' => 'ASC',
    ]);

    $found = [];
    foreach ($posts as $post) {
        $key = $post->post_type . ':' . $post->post_name . ':' . $post->post_status;
        $allowed = [
            'post:hello-world:publish',
            'page:sample-page:publish',
            'page:privacy-policy:draft',
        ];
        if (!in_array($key, $allowed, true)) {
            return false;
        }
        $found[] = $key;
    }

    return in_array('post:hello-world:publish', $found, true)
        && in_array('page:sample-page:publish', $found, true);
}

function website_portfolio_initial_content(): string {
    return website_portfolio_pages()['home']['content'];
}

function website_portfolio_bootstrap_initial_content(): void {
    $pending_file = WP_CONTENT_DIR . '/.website-initial-content-pending';
    if (!is_file($pending_file)
        || get_option('website_portfolio_bootstrap_version')
        || !current_user_can('manage_options')
        || !website_portfolio_is_fresh_install()) {
        return;
    }

    $page_id = wp_insert_post([
        'post_type' => 'page',
        'post_status' => 'publish',
        'post_title' => 'Home',
        'post_name' => 'home',
        'post_content' => website_portfolio_initial_content(),
    ], true);
    if (is_wp_error($page_id)) {
        error_log('Portfolio bootstrap could not create the homepage: ' . $page_id->get_error_message());
        return;
    }

    foreach ([
        'blogname' => 'Fearghal Ó Floinn',
        'blogdescription' => 'Senior Site Reliability Engineer',
        'blog_public' => 0,
        'show_on_front' => 'page',
        'page_on_front' => $page_id,
        'page_for_posts' => 0,
    ] as $option => $value) {
        update_option($option, $value);
        if (get_option($option) !== $value) {
            error_log('Portfolio bootstrap could not update the ' . $option . ' setting.');
            return;
        }
    }

    switch_theme('initial-website');
    if (get_option('stylesheet') !== 'initial-website') {
        error_log('Portfolio bootstrap could not activate the Initial Website theme.');
        return;
    }

    foreach (website_portfolio_pages() as $slug => $page) {
        if ($slug === 'home') {
            continue;
        }
        $extra_id = wp_insert_post([
            'post_type' => 'page',
            'post_status' => 'publish',
            'post_title' => $page['title'],
            'post_name' => $slug,
            'post_content' => $page['content'],
        ], true);
        if (is_wp_error($extra_id)) {
            error_log('Portfolio bootstrap could not create the ' . $slug . ' page: ' . $extra_id->get_error_message());
            return;
        }
    }

    $menu_error = website_portfolio_apply_menu();
    if ($menu_error !== null) {
        error_log('Portfolio bootstrap: ' . $menu_error);
        return;
    }
    update_option('website_portfolio_bootstrap_version', '1');
    if (get_option('website_portfolio_bootstrap_version') !== '1') {
        error_log('Portfolio bootstrap could not save its completion marker.');
        return;
    }

    if (!unlink($pending_file)) {
        error_log('Portfolio bootstrap completed but could not remove its pending marker.');
    }
}
add_action('wp_loaded', 'website_portfolio_bootstrap_initial_content', 100);
