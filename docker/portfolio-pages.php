<?php

function website_portfolio_source_dir(): string {
    return is_file(__DIR__ . '/portfolio-content.php') ? __DIR__ : '/opt/website';
}

function website_portfolio_strip_heading(string $section): string {
    return preg_replace('/^<!-- wp:heading \{"anchor":"[a-z]+"\} -->\s*<h2[^>]*>.*?<\/h2>\s*<!-- \/wp:heading -->\s*/s', '', $section, 1);
}

function website_portfolio_cards(string $content): string {
    $marker = '<!-- wp:heading {"level":3} -->';
    $parts = explode($marker, $content);
    $out = array_shift($parts);
    foreach ($parts as $part) {
        $tail = '';
        $split = preg_split('/(?=<!-- wp:heading \{"level":4\} -->)/', $part, 2);
        if (count($split) === 2) {
            [$part, $tail] = $split;
        }
        $out .= "<!-- wp:group {\"className\":\"profile-card\"} -->\n<div class=\"wp-block-group profile-card\">\n" . $marker . rtrim($part) . "\n</div>\n<!-- /wp:group -->\n" . $tail;
    }
    return $out;
}

function website_portfolio_pages(): array {
    $full = require website_portfolio_source_dir() . '/portfolio-content.php';
    $parts = preg_split('/(?=<!-- wp:heading \{"anchor":")/', $full);
    $sections = ['intro' => array_shift($parts)];
    foreach ($parts as $part) {
        if (preg_match('/"anchor":"([a-z]+)"/', $part, $match)) {
            $sections[$match[1]] = $part;
        }
    }

    $explore = <<<'HTML'
<!-- wp:heading {"anchor":"explore"} -->
<h2 class="wp-block-heading" id="explore">Explore</h2>
<!-- /wp:heading -->
<!-- wp:list -->
<ul class="wp-block-list">
<!-- wp:list-item -->
<li><a href="/experience/">Experience</a> - where I have worked and what I did there.</li>
<!-- /wp:list-item -->
<!-- wp:list-item -->
<li><a href="/projects/">Projects</a> - reliability, observability, and migration work.</li>
<!-- /wp:list-item -->
<!-- wp:list-item -->
<li><a href="/skills/">Skills</a> - the tools and platforms I use.</li>
<!-- /wp:list-item -->
<!-- wp:list-item -->
<li><a href="/education/">Education</a> - degree and certifications.</li>
<!-- /wp:list-item -->
</ul>
<!-- /wp:list -->

HTML;

    return [
        'home' => ['title' => 'Home', 'menu' => 'Home', 'url' => '/', 'content' => $sections['intro'] . $sections['about'] . $explore . $sections['connect']],
        'experience' => ['title' => 'Experience', 'menu' => 'Experience', 'url' => '/experience/', 'content' => website_portfolio_cards(website_portfolio_strip_heading($sections['experience']))],
        'projects' => ['title' => 'Projects', 'menu' => 'Projects', 'url' => '/projects/', 'content' => website_portfolio_cards(website_portfolio_strip_heading($sections['projects']))],
        'skills' => ['title' => 'Skills', 'menu' => 'Skills', 'url' => '/skills/', 'content' => website_portfolio_cards(website_portfolio_strip_heading($sections['skills']))],
        'education' => ['title' => 'Education', 'menu' => 'Education', 'url' => '/education/', 'content' => website_portfolio_cards(website_portfolio_strip_heading($sections['education']) . $sections['certifications'])],
    ];
}

function website_portfolio_apply_menu(): ?string {
    if (get_option('permalink_structure') === '' && function_exists('update_option')) {
        update_option('permalink_structure', '/%postname%/');
        if (function_exists('flush_rewrite_rules')) {
            flush_rewrite_rules(true);
        }
    }
    $existing = wp_get_nav_menu_object('Profile navigation');
    if ($existing) {
        wp_delete_nav_menu($existing->term_id);
    }
    $menu_id = wp_create_nav_menu('Profile navigation');
    if (is_wp_error($menu_id)) {
        return 'Could not create the navigation menu: ' . $menu_id->get_error_message();
    }

    foreach (website_portfolio_pages() as $page) {
        $item_id = wp_update_nav_menu_item($menu_id, 0, [
            'menu-item-title' => $page['menu'],
            'menu-item-url' => $page['url'],
            'menu-item-status' => 'publish',
            'menu-item-type' => 'custom',
        ]);
        if (is_wp_error($item_id)) {
            return 'Could not add navigation item ' . $page['menu'] . ': ' . $item_id->get_error_message();
        }
    }

    $locations = get_theme_mod('nav_menu_locations', []);
    $locations['primary'] = $menu_id;
    set_theme_mod('nav_menu_locations', $locations);
    $saved = get_theme_mod('nav_menu_locations', []);
    if (!is_array($saved) || (int) ($saved['primary'] ?? 0) !== (int) $menu_id) {
        return 'Could not assign the profile navigation.';
    }
    return null;
}