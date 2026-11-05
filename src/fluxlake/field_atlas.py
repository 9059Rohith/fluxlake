"""Fixed artwork inventory and semantic editorial navigation for the public observatory."""

ROUTE_ART = {
    "overview": "observatory-terrain.webp",
    "sources": "source-apertures.svg",
    "ingestion": "packet-funnel.svg",
    "bronze": "strata-vault.svg",
    "silver": "normalized-grid.svg",
    "gold": "aggregate-prism.svg",
    "schema": "contract-canopy.svg",
    "drift": "distribution-ridges.svg",
    "replay": "replay-echo.svg",
    "quarantine": "isolated-pocket.svg",
    "runs": "receipt-cadence.svg",
    "lineage": "evidence-thread.svg",
    "agent": "signal-inquiry.svg",
    "access": "gated-threshold.svg",
}

CHAPTERS = (
    (
        "sources",
        "Find the source",
        "Inspect the GitHub endpoint and its acquisition boundaries.",
        "entry-corridor.svg",
    ),
    (
        "bronze",
        "Read the original",
        "Open immutable JSON and check its canonical fingerprint.",
        "immutable-core.svg",
    ),
    (
        "silver",
        "Explore typed events",
        "Filter by event type, repository, actor or identity.",
        "observed-fields.svg",
    ),
    (
        "drift",
        "Compare two runs",
        "See how the event mix changes across retained acquisitions.",
        "pattern-ridges.svg",
    ),
    (
        "replay",
        "Reconstruct a run",
        "Inspect the live audit and the offline archive recovery drill.",
        "recovery-resonance.svg",
    ),
    (
        "agent",
        "Ask the lake",
        "Follow a read-only answer back to actual public evidence.",
        "inspectable-answer.svg",
    ),
)

HERO_MOBILE = "observatory-terrain-mobile.webp"
ASSETS = frozenset([*ROUTE_ART.values(), HERO_MOBILE, *(chapter[3] for chapter in CHAPTERS)])


def route_art(page):
    src = f"/assets/atlas/{ROUTE_ART[page]}"
    if page == "overview":
        return (
            '<picture class="field-art" aria-hidden="true">'
            f'<source media="(max-width: 760px)" srcset="/assets/atlas/{HERO_MOBILE}">'
            f'<img src="{src}" alt="" width="1600" height="667" decoding="async" fetchpriority="high">'
            "</picture>"
        )
    return f'<img class="field-art" src="{src}" alt="" width="900" height="420" decoding="async">'


def chapters_html():
    cards = []
    for index, (page, title, description, image) in enumerate(CHAPTERS, 1):
        cards.append(
            f'<li class="field-chapter" data-reveal><a href="/workspace/{page}">'
            f'<img src="/assets/atlas/{image}" alt="" width="900" height="420" loading="lazy" decoding="async">'
            f'<span class="chapter-number" aria-hidden="true">{index:02}</span>'
            f'<div class="chapter-copy"><h3>{title}</h3><p>{description}</p></div>'
            '<span class="chapter-arrow" aria-hidden="true">↗</span></a></li>'
        )
    return (
        '<section class="field-chapters" aria-labelledby="field-chapters-title">'
        '<div class="field-section-head" data-reveal><h2 id="field-chapters-title">Explore the evidence</h2>'
        "<p>Six ways to follow a public event through the lake.</p></div>"
        f'<ol class="field-chapter-grid">{"".join(cards)}</ol></section>'
    )
