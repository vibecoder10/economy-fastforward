# Holland: source-backed local brief

Status: human-reviewed local research/example. Not saved to StoryEngine or passed through its provider review.

| Field | Writer fact |
|---|---|
| intended_role | Holland’s commander advocated her use as a war vessel for coast and harbor defense. |
| design | Holland combined dual propulsion, separate main and auxiliary ballast systems, and a hydrodynamic hull shape. |
| actual_use | Holland served at the U.S. Naval Academy as a training submarine. |
| outcome | Improved Holland-type submarines became the Navy’s A-class. |

The first field is explicitly the operational role advocated by Holland’s commander; it is not proof of the original procurement requirement. This supported framing avoids inventing intent or a combat failure.

Sources: [Congressional Record, printed page3089 / PDF page77](https://www.govinfo.gov/content/pkg/GPO-CRECB-1901-pt4-v34/pdf/GPO-CRECB-1901-pt4-v34-2.pdf#page=77), [Naval Undersea Museum](https://navalunderseamuseum.org/undersea-pioneers2/). Exact extracted quotations, attribution and limits are in evidence.json. Original congressional page visually verified; OCR errors retained separately from the visual reading. Failed Smithsonian403/Navy TLS captures excluded.

## Manual editorial example (99 words)

USS Holland was promoted as a weapon for coast and harbor defense. Dual propulsion, separate ballast systems and a hydrodynamic hull brought the design together. But in service, that underwater weapon also became a classroom. At the U.S. Naval Academy, Holland served as a training submarine. Improved Holland-type boats followed as the A-class. The payoff was larger than one boat defending one harbor: Holland gave the Navy a working submarine to learn from, and a design to improve. Her importance lay in what came next—training people to operate underwater and helping establish the pattern for the boats that followed.

## Deterministic check and limits

Four claims contain 47 words. The real build_dvsu_brief function produces all four fields in 931 UTF-8 bytes, with identical output on repeat and reversed fact order. Sources and quotations stay in evidence.json, outside the writer payload. This demonstrates that 2,000 research words are unnecessary for this example.

This is local research and an editorial example, not a generated production preview. No paid calls, live card updates, code changes or deployment occurred. The next app step is explicit page-targeted ingestion and normal source assessment before preview: the Congressional evidence is on page77, beyond the current first8page PDF extractor. Do not silently truncate the PDF, forge an assessment, or call this end-to-end verification.
