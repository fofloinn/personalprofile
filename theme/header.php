<!doctype html>
<html <?php language_attributes(); ?>>
<head>
    <meta charset="<?php bloginfo('charset'); ?>">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<a class="screen-reader-text" href="#main"><?php esc_html_e('Skip to content', 'initial-website'); ?></a>
<div class="site-shell">
    <header class="site-header">
        <a class="site-brand" href="<?php echo esc_url(home_url('/')); ?>">
            <?php echo esc_html(get_bloginfo('name')); ?>
        </a>
        <nav class="site-navigation" aria-label="<?php esc_attr_e('Primary navigation', 'initial-website'); ?>">
            <?php
            wp_nav_menu([
                'theme_location' => 'primary',
                'container' => false,
                'fallback_cb' => false,
                'depth' => 1,
            ]);
            ?>
        </nav>
    </header>
