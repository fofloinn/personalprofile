<?php

function initial_website_setup(): void {
    add_theme_support('title-tag');
    add_theme_support('post-thumbnails');
    add_theme_support('editor-styles');
    add_theme_support('align-wide');
    add_theme_support('responsive-embeds');
    add_theme_support('wp-block-styles');
    add_editor_style('style.css');

    register_nav_menus([
        'primary' => __('Primary navigation', 'initial-website'),
    ]);
}
add_action('after_setup_theme', 'initial_website_setup');

function initial_website_enqueue_styles(): void {
    wp_enqueue_style(
        'initial-website-style',
        get_stylesheet_uri(),
        [],
        (string) filemtime(get_stylesheet_directory() . '/style.css')
    );
}
add_action('wp_enqueue_scripts', 'initial_website_enqueue_styles');
