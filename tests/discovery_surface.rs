use std::{fs, path::Path};

fn read(path: &str) -> String {
    fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join(path)).unwrap()
}

#[test]
fn discovery_surfaces_keep_the_canonical_namespace_and_crawler_access() {
    let config = read("docs/_config.yml");
    assert!(config.contains("title: Clean Room Launcher (CLROOM)"));
    assert!(config.contains("url: \"https://y-sor.github.io\""));
    assert!(config.contains("baseurl: \"/clean-room-launcher\""));
    assert!(config.contains("repository: y-sor/clean-room-launcher"));

    let bing_verification = config
        .lines()
        .find_map(|line| line.strip_prefix("bing_site_verification:"))
        .expect("missing Bing site verification setting")
        .trim()
        .trim_matches('"')
        .trim_matches('\'');
    assert!(!bing_verification.is_empty(), "Bing verification value is empty");
    assert!(
        !bing_verification.to_ascii_lowercase().contains("placeholder"),
        "Bing verification value is a placeholder"
    );

    let head = read("docs/_includes/head.html");
    assert!(head.contains("name=\"msvalidate.01\""));
    assert!(head.contains("content=\"{{ site.bing_site_verification | escape }}\""));

    let sitemap = read("docs/sitemap.xml");
    assert!(sitemap.contains("permalink: /sitemap.xml"));
    assert!(sitemap.contains("page.url | absolute_url"));
    assert!(sitemap.contains("page.sitemap == false"));

    let robots = read("docs/robots.txt");
    for agent in ["Googlebot", "Bingbot", "OAI-SearchBot", "Claude-SearchBot", "Claude-User"] {
        assert!(robots.contains(&format!("User-agent: {agent}")), "missing crawler policy for {agent}");
    }
    assert!(robots.contains("Sitemap: https://y-sor.github.io/clean-room-launcher/sitemap.xml"));

    let llms = read("docs/llms.txt");
    assert!(llms.contains("# Clean Room Launcher (CLROOM)"));
    assert!(llms.contains("https://github.com/y-sor/clean-room-launcher"));
    assert!(llms.contains("CLROOM is the acronym for **Clean Room Launcher**"));

    let legacy_owner = format!("{}{}", "ewgenij87sn", "work");
    let legacy_pages = format!("{legacy_owner}.github.io/clean-room-launcher");
    let legacy_repo = format!("github.com/{legacy_owner}/clean-room-launcher");
    for surface in [&config, &head, &sitemap, &robots, &llms] {
        assert!(!surface.contains(&legacy_pages));
        assert!(!surface.contains(&legacy_repo));
    }
}


#[test]
fn discovery_descriptions_stay_concise_and_specific() {
    let config = read("docs/_config.yml");
    let home = read("docs/index.md");

    for (surface, text) in [("site", &config), ("homepage", &home)] {
        let description = text
            .lines()
            .find_map(|line| line.strip_prefix("description: "))
            .expect("missing discovery description")
            .trim()
            .trim_matches('"')
            .trim_matches('\'');

        assert!(
            description.chars().count() <= 160,
            "{surface} discovery description exceeds the project concise-snippet target"
        );
        for required in [
            "Clean Room Launcher (CLROOM)",
            "Codex",
            "Claude Code",
            "clean, selective launch",
            "project context",
            "normal setup",
        ] {
            assert!(
                description.contains(required),
                "{surface} discovery description lost required signal: {required}"
            );
        }
    }
}

#[test]
fn homepage_metadata_exposes_analytics_preview_and_free_app_facts() {
    let head = read("docs/_includes/head.html");
    assert!(head.contains("max-image-preview:large"));
    assert!(head.contains("\"@type\": \"SoftwareApplication\""));
    assert!(head.contains("\"price\": 0"));
    assert!(head.contains("static.cloudflareinsights.com/beacon.min.js"));
    assert!(head.contains("a18fd1827d4c48d2a22277f14eade9b2"));

    let home = read("docs/index.md");
    assert!(home.contains("title: Clean Room Launcher (CLROOM)"));
    assert!(home.contains("path: /assets/clean-room-launcher-hero.png"));
    assert!(home.contains("the intended public identity is **Clean Room Launcher (CLROOM)**"));
}
