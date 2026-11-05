# FluxLake field atlas

FluxLake starts this release as a working 14-view public GitHub observatory. The canonical Vercel deployment serves the FastAPI container from the FluxLake repository. It uses Python and pinned pip requirements, PostgreSQL, server-rendered HTML and native JavaScript/CSS. The previous release established 39 hosted checks, a live 200-event sample and a separate reproducible 20,000-event crash and recovery benchmark. [Repository](https://github.com/9059Rohith/fluxlake) · [Baseline release](archive-replay-benchmark.md) · [Production](https://rohith-fluxlake.vercel.app)

## Route and workflow inventory

| View | Existing working behavior to verify | Atmospheric direction |
|---|---|---|
| Overview | Actual event counts, count/share chart and drilldown, recent evidence drawer | A winding signal leads to an optical observatory |
| Sources | Fixed GitHub endpoint, receipt and provenance | Offset apertures and one incoming beam |
| Ingestion | Operator-only acquisition, atomic publication and polling | Packet paths converging on a small gate |
| Bronze | Filter, paginate, inspect raw JSON and fingerprints | Immutable layers in a vault |
| Silver | Search, sort, filter, CSV and typed evidence | A regular array emerging from scattered points |
| Gold | Live SQL aggregate groups and contributor links | A prism separating analytical bands |
| Schema | Observed fields and explicit contract | A branching canopy of fields |
| Drift | Compare two retained acquisitions | Intersecting distribution ridges |
| Replay | Select runs, reconstruct, inspect differences, download and review offline proof | Echo paths return to a verified trace |
| Quarantine | Actual rejection details or a truthful empty state | An isolated pocket outside the validation boundary |
| Runs | Source receipts, time and outcome detail | Layered receipt cadence |
| Lineage | Follow a real event through evidence layers | A continuous thread through a network |
| Lake analyst | Gemini prompt, bounded results, expandable sources and quotas | Inquiry rings around a single answer node |
| Operator access | Tab-local token entry, verification and clear-session flow | Nested threshold portals |

The previous layout put analytical controls close to the viewport edge and used the same short heading treatment throughout. It had responsive navigation, chart SVGs, a command palette, an evidence dialog, visible focus and reduced-motion CSS. Its full Inter file and procedural icons were the only visual asset families. The flat shared canvas gave little visual distinction between routes. The original density works well for tables and forms, so the additional art belongs at section boundaries and in navigation to evidence. The repo has no checkout, user-registration or payment UI.

## Security and integration inventory

The exact-host guard and strict CSP restrict resources to this origin and keep inline scripts and styles blocked. Read-only public queries use the public GitHub tables. Private CDC routes, acquisition and migrations keep bearer authorization. The hosted read-only replay caps two runs and 200 records, while the packaged offline report documents the larger local drill. Public inference uses the existing Gemini provider, same-origin guard and persistent per-client/shared limits. The redesign reuses those routes, keeps their request and response contracts, and adds only fixed local visual resources. Production data, provider keys, bearer tokens and deployment environment variables stay in their existing services.

## Reference patterns and design inventory

Trickee’s directional art guides attention from the opening statement into a usable primary action. Its chapters organize a technical workflow as a sequence. FluxLake applies that direction to the event trace, a Replay audit action, and six workflow cards beneath the live evidence. Shunya Chakra uses a clear image focal point before a quieter form, with section transitions that separate storytelling from decisions. FluxLake uses one strong overview scene and compact route artwork, while preserving calm table and form surfaces. Reference observations combine the coordinator's browser inspection with accessible page content. [Trickee](https://www.trickee.co.in/) · [Shunya Chakra](https://shunyachakra.com/#waitlist)

The original concept uses a violet terrain observatory, signal lines, mint actions and dark aubergine. Keep its “Follow the event.” headline and Replay audit action. Adapt the board's illustrative fields to the actual workspace names and real samples. The route shell, command search, recent-event records and archived report retain existing semantics. Type remains Inter with system mono for identifiers. The canvas is ink `#130f21`, primary text is warm lilac `#f4edff`, surfaces use `#211931`, rules use `#463755`, and actionable mint is `#86f7cd`. The compact route hero uses a lighter type scale than the overview. Art fades into ink at the text boundary and remains decorative.

The original hero background and nineteen authored vector compositions cover all fourteen routes and six overview workflow cards. Responsive hero encodings share one composition and count once. One critical image loads per route. Chapter images use native lazy loading. A first-view entrance, native section reveal, restrained hover zoom and CSS scroll progress use transform and opacity. Reduced motion removes the decorative transitions, and content is visible independently of animation initialization.

## Acceptance criteria

- All 14 routes render and retain their real data operations, dialogs and keyboard entry points.
- At least 20 different integrated compositions have traceable sources, hashes, destinations and optimization metadata. Static routes reject unlisted asset names.
- Hosted replay reconstructs an actual retained 100-event run and offers the unchanged 20,000-event benchmark report. Public writes remain denied.
- Mobile and desktop maintain readable art, visible focus and native scrolling. Reduced motion leaves static visible content.
- Existing PostgreSQL tests, client tests, live route and image checks, canonical deployment and browser captures provide the release evidence.
