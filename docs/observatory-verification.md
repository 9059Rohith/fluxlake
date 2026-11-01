# Observatory verification

Production: https://rohith-fluxlake.vercel.app. Runtime commit `107ec05` is published in Ready deployment `dpl_6RDSHwtommMsH4fAuDLoKnLDNMGU`, with the unique URL https://fluxlake-bk782oufg-rohiths-projects-5e14931b.vercel.app. Verification ran on 2 November 2026 IST (1 November UTC).

## Source and deployed checks

- Python suite: **144 passed, 32 skipped**, no failures. The skipped cases require a disposable PostgreSQL database; Docker remained stopped for this frontend-only change. `evidence/observatory-junit.xml` records all 176 cases. The pre-redesign PostgreSQL-enabled baseline passed all 174 cases earlier in this session, recorded separately in `evidence/public-analyst-junit.xml`; the subsequent Gemini-only public-provider guard passed 36 targeted tests in `evidence/public-analyst-targeted-junit.xml`. Those older integration runs are not presented as a fresh PostgreSQL run of this frontend revision.
- Client safety and data-rendering suite: **5 passed**, no failures. Checks cover escaped model markup, restricted evidence links, stable large-ID sorting, actual-derived chart proportions and escaped dimension labels. See `evidence/observatory-client-tests.txt`.
- Ruff check and format check passed across the repository (46 Python files); both JavaScript files passed Node syntax validation.
- Production HTTP smoke: **38 checks passed across all 13 pages**. It verifies actual source counts, filters, schema, original-event fingerprints, CSV, drift, provenance, retired synthetic endpoint and anonymous denial of private operations. See `evidence/observatory-http.json`.
- Production CSS, JavaScript, SVG symbols and the actual self-hosted Inter font returned HTTP 200 with correct MIME types and same-origin font CSP. The final desktop-navigation and mobile-chart refinements are present in deployed CSS. See `evidence/observatory-assets.json`.

These checks do not consume inference quota or mutate retained evidence. The API/provider contracts, origin checks, persistent public limits, private bearer boundary and database migrations are unchanged by the redesign. The sole CSP addition is `font-src 'self'` for the packaged font; no inline-script/style exception was introduced.

## Concept and implementation comparison

The inspected ImageGen concepts are stored in `evidence/design/`, and their tokens and components are specified in `docs/observatory-design.md`. The rendered Overview preserves the navy canvas, violet/ice palette, Inter hierarchy, open four-value metric band, count/share chart, vertical source-to-layer lineage, recent-evidence table and thin-line navigation. Analyst preserves the open composer, actual source context, exact distribution, visible limits and inspectable evidence treatment.

Generated visual shorthand is corrected in the implementation: records use actual API timestamps; chart shares are calculated from observations; lineage distinguishes raw evidence from typed silver and SQL aggregates; event-type drift uses retained acquisitions; no illustrative answer or reasoning transcript is presented as a real model result. Small screens stack the analytical regions and use an accessible navigation overlay. The first browser review identified desktop-only mobile-navigation controls; the final CSS hides those controls above 760 px and improves small-screen SVG label legibility.

The coordinator's actual browser review confirmed Count → Share changes the axis to 100% and reports the retained PushEvent share of 78.5%. Selecting that bar opens the Silver explorer with its real PushEvent filter (157 matches). Selecting event `25855852067` loads its actual `LCahst/quiet-space` evidence drawer, canonical fingerprint and 579-byte original JSON. At a 390 px viewport, the Silver page's measured document and scroll widths were both 383 px: the table scrolls within its own surface without widening the page. Mobile navigation open/close and focus return to `menu-toggle` passed. I inspected the rendered mobile capture in `evidence/design/observatory-mobile-live.jpg`; it preserves the intended type hierarchy, native icons, dark surfaces and functional table controls.

Final production browser review passed all 13 rendered routes with their real headings and no document overflow. Command-palette search for “Lake analyst” followed by Enter reached the correct route. The Original JSON tab and record digest were inspected. A fresh anonymous Gemini investigation returned a real answer through one actual tool call in 2,260 ms, reporting 157/200 PushEvent records, the exact 78.5% share, the source API path, acquisition time and honest freshness limitations. The implementation agent made no inference probes; the coordinator used the real public UI. `evidence/observatory-browser.json` records this review, and an independent HTTP check verifies that the drawer's public record matches canonical SHA-256 `b479b4b61c1869d3b91a6e7abb4e541057af94b7d4a552fbfa13ff433de3fbdb`.

Final inspected browser captures:

| View | Evidence |
|---|---|
| Overview | `evidence/design/observatory-overview-live-final.jpg` |
| Actual analyst answer | `evidence/design/observatory-agent-live.jpg` |
| Original-record drawer | `evidence/design/observatory-record-live.jpg` |
| Mobile Silver explorer | `evidence/design/observatory-mobile-live.jpg` |

I viewed both concept images again alongside the final Overview, analyst answer, record drawer and mobile captures. The five defining relationships remain intact: rail and content separation; display title and open metric hierarchy; proportional chart beside the evidence chain; consistent thin-line icon/control treatment; and the analyst's open composer beside factual source context. The final desktop capture is shorter than the concept, so recent records continue below the fold rather than being compressed. Flat native chart fills replace the image concept's highlights, and real observations correct its illustrative proportions and copy. The initial stray navigation controls are absent from the final desktop image. These are intentional implementation differences, not a claim of pixel identity or a project ranking.

## Practical limits

The current source is a retained, operator-acquired sample of **200 public GitHub events**, covering **198 repositories**, **164 actors**, **4 event types** and **2 acquisitions**. It is not a complete or continuously refreshed GitHub stream. Empty quarantine and schema/drift limitations reflect the real store. Sorting explicitly applies to the current returned page; filters, pagination and bounded CSV export remain real API operations.

Anonymous Gemini remains subject to 3 attempts per client per 10 minutes and shared capacity of 2 per minute / 30 per UTC day, plus provider availability. A real quota response displays its server cooldown. There is no paid fallback, fabricated answer or automatic inference on page load. Public questions and selected public evidence are sent to the provider; the interface warns against entering secrets or private records.
