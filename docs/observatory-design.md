# FluxLake observatory design

The redesign uses two built-in ImageGen concepts, inspected before implementation:

- `evidence/design/observatory-overview-concept.png`: complete Overview with open metric band, event composition, evidence lineage and recent-record table.
- `evidence/design/observatory-analyst-concept.png`: complete analyst ready state, question workspace, source context and free allowance.

## Locked design system

Ink canvas `#090d16`, navy rail `#0d1421`, surface `#101827`, fine rules `#263149`, near-white content `#eef2ff`, muted slate `#9aabc5`, violet `#a38bff`, ice blue `#83cfff`, pale lavender `#cfbdff`. Inter variable is self-hosted under its included SIL Open Font License; event identities use a system monospace stack and tabular numerals. Display 36–40 px, section headings 18–20 px, body 13–14 px, supporting chrome 11–12 px. Controls use 8 px corners; open canvases and fine dividing rules carry the main hierarchy.

The 216–228 px navigation rail uses a consistent 24 px thin-line SVG symbol family. The top bar contains the actual command palette, page breadcrumb and official GitHub source link. Main content has 32–40 px gutters; Overview uses one open four-value band and a 65/35 chart/lineage canvas, followed by a single purposeful table surface. Analyst uses an open question column and a factual context rail. Secondary pages reuse the same tables, controls, source disclosures, field lists and evidence drawer.

Primary copy: “Every event. A clearer signal.” / “A public GitHub sample, from original evidence to analytical insight.” Analyst copy: “Ask the lake. Follow the evidence.” / “A read-only analyst grounded in the public GitHub sample.” Primary actions are “Ask the lake analyst”, “Investigate public sample”, “Refresh” and existing real workflow actions. No decorative eyebrow or invented trend metric is added.

## Factual content and component inventory

All values come from existing public APIs: the current retained sample has 200 events, 198 repositories, 164 actors, four event types and two acquisitions. Chart values are 157 PushEvent, 22 CreateEvent, 15 DeleteEvent and six PullRequestEvent; shares derive from the actual total. Runtime values remain dynamic. Generated concept proportions and labels are design references rather than shipped data. The final implementation corrects any concept shorthand: actual UTC timestamps replace illustrative dates, source sizes are shown only when present in the API, and drift is described as event-type comparison rather than repository drift.

Component families: thin-line SVG icons; primary/secondary/icon buttons; open statistics; native SVG count/share and distribution charts; vertical source-to-layer lineage; sortable, filterable record tables; command-search dialog; right-side actual-record evidence drawer; bounded question composer; safely formatted answer; expandable real tool results; explicit cooldown/error states; provenance footer. Native application text and charts are rendered in HTML/CSS/SVG, not flattened into the generated images.

## Views and useful interactions

All 13 routes retain their existing API contracts. Overview is the entry point; Bronze and Silver support real filters, pagination, current-page sorting, export and event inspection; Gold supports actual aggregate dimensions; drift selects retained acquisitions; lineage traces a real ID; schema, quarantine, sources, runs and ingestion retain real evidence and operator boundaries. The command palette navigates all pages and searches actual retained records. Analyst preserves the anonymous Gemini-only endpoint, persistent free quotas, source disclosures and private-operation authorization.

Responsive navigation becomes a proper overlay on small screens; analytical columns stack without horizontal page overflow. Tables scroll inside their own region. Keyboard shortcuts, visible focus, dialog labels, Escape behavior and reduced-motion preferences remain supported. The coordinator verifies actual desktop/mobile screens in the built-in browser before final handoff, with concept-to-render comparison and a concise mismatch record.
