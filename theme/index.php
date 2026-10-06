<?php get_header(); ?>
<?php
$taglines = [
    'experience' => 'Where I have worked and the impact I have had along the way.',
    'projects' => 'Reliability, observability and migration work that I am proud of.',
    'skills' => 'The platforms, languages and tooling I use every day.',
    'education' => 'Formal education and professional certifications.',
];
$slug = is_page() ? get_post_field('post_name', get_the_ID()) : '';
?>
<main id="main">
    <?php if (have_posts()) : ?>
        <?php while (have_posts()) : the_post(); ?>
            <header class="page-hero">
                <p class="eyebrow"><?php echo esc_html(get_bloginfo('name')); ?></p>
                <h1 id="page-title"><?php the_title(); ?></h1>
                <?php if (isset($taglines[$slug])) : ?>
                    <p class="page-hero-lead"><?php echo esc_html($taglines[$slug]); ?></p>
                <?php endif; ?>
            </header>
            <article <?php post_class('page-content'); ?>>
                <?php the_content(); ?>
            </article>
        <?php endwhile; ?>
    <?php else : ?>
        <div class="page-content"><h1><?php esc_html_e('Nothing found', 'initial-website'); ?></h1></div>
    <?php endif; ?>
</main>
<?php get_footer(); ?>