<?php get_header(); ?>
<main id="main">
    <section class="hero" aria-labelledby="page-title">
        <div class="hero-copy">
            <p class="eyebrow"><?php echo esc_html(get_bloginfo('description') ?: __('Professional profile', 'initial-website')); ?></p>
            <h1 id="page-title"><?php echo esc_html(get_bloginfo('name')); ?></h1>
            <a class="hero-link" href="#profile-content">
                <?php esc_html_e('Explore my profile', 'initial-website'); ?>
                <span aria-hidden="true">&darr;</span>
            </a>
            <a class="hero-link hero-download" href="<?php echo esc_url(get_theme_file_uri('assets/Fearghal-O-Floinn-CV.pdf')); ?>" download>
                <?php esc_html_e('Download CV (PDF)', 'initial-website'); ?>
            </a>
        </div>
        <div class="hero-card">
            <p class="eyebrow"><?php esc_html_e('How I work', 'initial-website'); ?></p>
            <p class="hero-note"><?php esc_html_e('Practical reliability engineering, shaped by years close to the systems and people behind the service.', 'initial-website'); ?></p>
            <ul class="hero-focus">
                <li><?php esc_html_e('Cloud and distributed systems', 'initial-website'); ?></li>
                <li><?php esc_html_e('Service health and incident response', 'initial-website'); ?></li>
                <li><?php esc_html_e('Operational improvement', 'initial-website'); ?></li>
            </ul>
        </div>
    </section>

    <article class="page-content" id="profile-content">
        <?php
        while (have_posts()) :
            the_post();
            the_content();
        endwhile;
        ?>
    </article>
</main>
<?php get_footer(); ?>
