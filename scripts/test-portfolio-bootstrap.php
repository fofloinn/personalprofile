<?php

define('WP_CONTENT_DIR', sys_get_temp_dir() . '/website-portfolio-bootstrap-test-' . getmypid());
if (!is_dir(WP_CONTENT_DIR) && !mkdir(WP_CONTENT_DIR, 0700, true) && !is_dir(WP_CONTENT_DIR)) {
    throw new RuntimeException('Could not create the bootstrap test directory.');
}

class TestWpError {
    public function get_error_message(): string {
        return 'test error';
    }
}

class WP_CLI {
    public static function success(string $message): void {
        $GLOBALS['test_cli_success'] = $message;
    }
}

define('WP_CLI', true);

function add_action(string $hook, callable $callback, int $priority = 10): void {
    $GLOBALS['test_actions'][$hook] = $callback;
}

function get_option(string $name, $default = false) {
    return $GLOBALS['test_options'][$name] ?? $default;
}

function flush_rewrite_rules(bool $hard = true): void {}

function update_option(string $name, $value): void {
    $GLOBALS['test_options'][$name] = $value;
}

function get_posts(array $args): array {
    return $GLOBALS['test_posts'];
}

function get_post(int $post_id) {
    foreach ($GLOBALS['test_posts'] as $post) {
        if ($post->ID === $post_id) {
            return $post;
        }
    }
    return null;
}

function wp_update_post(array $post, bool $wp_error = false) {
    $existing = get_post($post['ID']);
    if (!$existing) {
        return new TestWpError();
    }
    foreach ($post as $key => $value) {
        $existing->$key = $value;
    }
    return $existing->ID;
}

function get_page_by_path(string $path) {
    foreach ($GLOBALS['test_posts'] as $post) {
        if ($post->post_type === 'page' && $post->post_name === $path) {
            return $post;
        }
    }
    return null;
}

function current_user_can(string $capability): bool {
    return $GLOBALS['test_is_admin'];
}

function wp_insert_post(array $post, bool $wp_error = false) {
    $id = $GLOBALS['test_next_post_id']++;
    $post['ID'] = $id;
    $post['post_type'] = $post['post_type'] ?? 'post';
    $post['post_status'] = $post['post_status'] ?? 'publish';
    $GLOBALS['test_posts'][] = (object) $post;
    return $id;
}

function is_wp_error($value): bool {
    return $value instanceof TestWpError;
}

function switch_theme(string $stylesheet): void {
    $GLOBALS['test_active_theme'] = $stylesheet;
    $GLOBALS['test_options']['stylesheet'] = $stylesheet;
}

function wp_get_nav_menu_object(string $name) {
    return false;
}

function wp_delete_nav_menu(int $id): void {}

function wp_create_nav_menu(string $menu_name) {
    $GLOBALS['test_menu_name'] = $menu_name;
    return $GLOBALS['test_menu_id'];
}

function wp_update_nav_menu_item(int $menu_id, int $menu_item_db_id, array $args) {
    $GLOBALS['test_menu_items'][] = $args;
    return count($GLOBALS['test_menu_items']);
}

function get_theme_mod(string $name, $default = false) {
    return $GLOBALS['test_theme_mods'][$name] ?? $default;
}

function set_theme_mod(string $name, $value): void {
    $GLOBALS['test_theme_mods'][$name] = $value;
}

require __DIR__ . '/../docker/portfolio-bootstrap.php';

function check(bool $condition, string $message): void {
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

function reset_test_state(array $extra_posts = [], bool $is_admin = true, bool $pending = true): void {
    $GLOBALS['test_options'] = [
        'show_on_front' => 'posts',
        'page_on_front' => 0,
    ];
    $GLOBALS['test_posts'] = [
        (object) ['ID' => 1, 'post_type' => 'post', 'post_name' => 'hello-world', 'post_status' => 'publish'],
        (object) ['ID' => 2, 'post_type' => 'page', 'post_name' => 'sample-page', 'post_status' => 'publish'],
    ];
    $GLOBALS['test_posts'] = array_merge($GLOBALS['test_posts'], $extra_posts);
    $GLOBALS['test_is_admin'] = $is_admin;
    $GLOBALS['test_next_post_id'] = 10;
    $GLOBALS['test_menu_id'] = 20;
    $GLOBALS['test_menu_name'] = null;
    $GLOBALS['test_menu_items'] = [];
    $GLOBALS['test_theme_mods'] = [];
    $GLOBALS['test_active_theme'] = null;
    $pending_file = WP_CONTENT_DIR . '/.website-initial-content-pending';
    if ($pending) {
        file_put_contents($pending_file, '');
    } elseif (is_file($pending_file)) {
        unlink($pending_file);
    }
}

function run_bootstrap(): void {
    $GLOBALS['test_actions']['wp_loaded']();
}

check(
    ($GLOBALS['test_actions']['wp_loaded'] ?? null) === 'website_portfolio_bootstrap_initial_content',
    'The bootstrap should run from WordPress initialization.',
);
reset_test_state();
run_bootstrap();
$home = $GLOBALS['test_posts'][2];
check($home->post_title === 'Home', 'The homepage should be created.');
check(count($GLOBALS['test_posts']) === 7, 'The profile should be split into Home plus four sub-pages.');
foreach (['experience', 'projects', 'skills', 'education'] as $slug) {
    check(get_page_by_path($slug) !== null, "The $slug page should be created.");
}
check(!str_contains(get_page_by_path('experience')->post_content, '>Experience</h2>'), 'Sub-pages should not repeat their title as a heading.');
$home_only = $home->post_content;
$all_content = implode("\n", array_map(fn($p) => $p->post_content ?? '', $GLOBALS['test_posts']));
$home->post_content = $all_content;
check(str_contains($home->post_content, 'Senior Site Reliability Engineer'), 'The public profile content should be seeded.');
check(str_contains($home->post_content, 'large-scale cloud services used by customers around the world'), 'The Microsoft role should describe customer impact generically.');
check(!str_contains($home->post_content, 'Azure Resource Manager') && !str_contains($home->post_content, 'sovereign cloud'), 'The Microsoft profile must not expose internal product or environment details.');
check(str_contains($home->post_content, 'https://www.linkedin.com/in/fearghal-o-floinn-7b237939'), 'The approved LinkedIn link should be included.');
check(!str_contains($home->post_content, 'mailto:') && !str_contains($home->post_content, 'tel:'), 'Private contact links must not be included.');
check(!preg_match('/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i', $home->post_content), 'Email addresses must not be included.');
check($GLOBALS['test_options']['blogname'] === 'Fearghal Ó Floinn', 'The site title should match the current site.');
check($GLOBALS['test_options']['blogdescription'] === 'Senior Site Reliability Engineer', 'The tagline should match the current site.');
check($GLOBALS['test_options']['show_on_front'] === 'page' && $GLOBALS['test_options']['page_on_front'] === 10, 'The Home page should be the static homepage.');
$home->post_content = $home_only;
check($GLOBALS['test_options']['blog_public'] === 0, "Search engine visibility should retain the current site's setting.");
check($GLOBALS['test_active_theme'] === 'initial-website', 'The portfolio theme should be activated.');
check($GLOBALS['test_menu_name'] === 'Profile navigation' && count($GLOBALS['test_menu_items']) === 5, 'The profile navigation should be created.');
check(!is_file(WP_CONTENT_DIR . '/.website-initial-content-pending'), 'Successful bootstrap should remove its one-time marker.');

$snapshot = serialize([
    $GLOBALS['test_options'],
    $GLOBALS['test_posts'],
    $GLOBALS['test_menu_items'],
]);
run_bootstrap();
check($snapshot === serialize([
    $GLOBALS['test_options'],
    $GLOBALS['test_posts'],
    $GLOBALS['test_menu_items'],
]), 'A second run must not change or duplicate the site content.');

reset_test_state([
    (object) ['ID' => 3, 'post_type' => 'page', 'post_name' => 'home', 'post_status' => 'publish', 'post_content' => 'Existing page content'],
]);
run_bootstrap();
check(count($GLOBALS['test_posts']) === 3, 'Existing pages must not be modified or duplicated.');
check(!isset($GLOBALS['test_options']['website_portfolio_bootstrap_version']), 'An existing installation must not be marked as seeded.');
check(is_file(WP_CONTENT_DIR . '/.website-initial-content-pending'), 'Skipped existing content must retain the pending marker.');

reset_test_state([], false);
run_bootstrap();
check(count($GLOBALS['test_posts']) === 2, 'Unauthenticated requests must not seed site content.');
check(is_file(WP_CONTENT_DIR . '/.website-initial-content-pending'), 'Unauthenticated requests must retain the pending marker.');

reset_test_state([], true, false);
run_bootstrap();
check(count($GLOBALS['test_posts']) === 2, 'Existing WordPress data volumes must not be seeded.');

reset_test_state();
run_bootstrap();
$home_id = $GLOBALS['test_options']['page_on_front'];
$home = get_post($home_id);
$home->post_content = 'Older editable page content';
$sample_page = get_post(2);
$sample_page->post_content = 'Existing sample page content';
$sample_content = $sample_page->post_content;
putenv('WEBSITE_ALLOW_HOME_REPLACE=1');
require __DIR__ . '/../docker/update-portfolio-content.php';
check(
    get_post($home_id)->post_content === website_portfolio_pages()['home']['content'],
    'The explicitly invoked updater should replace only the selected Home page content.',
);
check(get_post(2)->post_content === $sample_content, 'The updater must leave other pages unchanged.');
check(str_contains(get_page_by_path('projects')->post_content, 'Rundeck'), 'The updater should keep the Projects page current.');
check(
    $GLOBALS['test_cli_success'] === 'Updated the portfolio pages and navigation from the reviewed portfolio profile.',
    'The updater should report a clear success.',
);
putenv('WEBSITE_ALLOW_HOME_REPLACE');

$pending_file = WP_CONTENT_DIR . '/.website-initial-content-pending';
if (is_file($pending_file)) {
    unlink($pending_file);
}
rmdir(WP_CONTENT_DIR);
echo "Portfolio bootstrap tests passed.\n";
