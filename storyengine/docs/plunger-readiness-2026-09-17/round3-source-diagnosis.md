# SS-2 source-extraction diagnosis (read-only)

**Scope.** This compares the SS-2 package in `live-after2.json` with one
read-only fetch each of its two already-saved original URLs on 2026-09-17.
No provider, live-data, source, or application-code write was made. The
current fetches reproduce the saved text hashes:

| URL | saved source IDs | saved/current SHA-256 | visible characters |
| --- | --- | --- | ---: |
| `https://www.historycentral.com/navy/Submarine/plunger.html` | S1, DVSU1 | `ff3632b480a00c8ff1906cf1e0d6f5917a0e807a0ff1c16ee19784607999d89c` | 2,848 / 2,850 |
| `https://www.navsource.net/archives/08/08002.htm` | S2, DVSU2 | `8d5038127568ec25d4e3fb82899bce748653f6b62cf615bc2324641d2283cefc` | 12,936 / 12,938 |

The two-character differences are from the saved capture metadata's visible
text count; the content fingerprints match. `live-after2.json` has four
source rows and 21 excerpts: the original 16 plus DVSU1-E1..E3 and
DVSU2-E1..E2. DVSU1 and DVSU2 are duplicate fetches of S1 and S2, not new
URLs.

## What the saved excerpts retain

The five recaptured rows are exactly:

```text
DVSU1-E1  USS Plunger SS-2 — US Navy Ships | HistoryCentral History Archive Educators Students Apps Contact US Navy · Submarines
DVSU1-E2  USS Plunger SS-2 US Navy (SS: dp. 149 (n.), 168 (subm.); 1.
DVSU1-E3  USS Plunger SS-2 US Navy (SS: dp. 149 (n.), 168 (subm.); 1. 85'3"; b.
DVSU2-E1  1.00k PRESIDENT ROOSEVELT WILL NOT MAKE TRIP ABOARD THE SUBMARINE BOAT PLUNGER (SS-2) SUBMARINE TORPEDO BOAT PLUNGER NOW AT OYSTER BAY TO GIVE EXHIBITION FOR PRESIDENT. While he is interested in the performance of the vessel, the report that he intends to go aboard the vessel while she is going through her maneuvers under water is without foundation, and the President requested that it be denied.
DVSU2-E2  NR THE SUBMARINE PLUNGER (SS-2) In which Pesident Roosevelt went down three times yesterday at Oyster Bay.
```

This matches the observed result: targeted discovery recorded six leads, but
the persisted recapture contributes five duplicate-URL excerpts and no new
source text. The current package's role gate still reports missing
`intended_role` and `design`.

## Useful source text that did not become a candidate excerpt

### HistoryCentral

The fetched HistoryCentral publisher section is 2,577 characters. It starts
with the exact identity `USS Plunger SS-2` and contains these contiguous
source sentences (transcribed from the fetched visible text):

```text
Plunger, the first submarine torpedo boat to be built for the Navy, was authorized by Congress 3 March 1893, A contract for her construction was awarded to Holland Torpedo Boat Co. 13 March 1895.
After commissioning, Plunger reported to Naval Torpedo Station, Newport, R.I., and operated in and around Provincetown and Newport.
She ran test d ves and did experimental work on machinery, armaments, and tseties giving the Navy invaluable information on the new seienee of submarine warfare.
Perhaps her greatest contribution was training her own crew and those of other submarines nearing completion.
After overhaul at the Holland Dock from March to November 1904, the boat resumed her testing functions.
With the President on board, Plunger made a test dive on 25 March 1905.
```

For parent review, this is the complete 2,577-character visible publisher
section, exactly as returned by the extractor (including its source OCR
spelling):

```text
USS Plunger SS-2 US Navy (SS: dp. 149 (n.), 168 (subm.); 1. 85'3"; b. 11'6"; dr. 11'; s. 15 k. (surf.), 8 k. (subm.); cpl. 7; a. 2 18 tt) Plunger, the first submarine torpedo boat to be built for the Navy, was authorized by Congress 3 March 1893, A contract for her construction was awarded to Holland Torpedo Boat Co. 13 March 1895. However, the boat and the contract were eaneelled in April 1900. (SS-2: dp. 107,1. 63'10", b. 11'11" dr. 10'7", s. 8 k. (surf.), 7 k. (subm.); cpl. 7; a. 1 18" tt; cl. A-l) The first Plunger (SS-2) was laid down 21 May 1901 at Crescent Shipyard, Elizabethport, N.J. under subcontract from J. P. Holland Torpedo Boat Co., Iaunehed 1 February 1902; sponsored by Miss Ernestine Wardwell, and commissioned at New Suffolk, L.I. 19 September 1903, Lt. Charles P. Nelson in command. After commissioning, Plunger reported to Naval Torpedo Station, Newport, R.I., and operated in and around Provincetown and Newport. She ran test d ves and did experimental work on machinery, armaments, and tseties giving the Navy invaluable information on the new seienee of submarine warfare. Perhaps her greatest contribution was training her own crew and those of other submarines nearing completion. After overhaul at the Holland Dock from March to November 1904, the boat resumed her testing functions. President Theodore Roosevelt was so impressed with the new naval weapon that he determined to see it at work in person. With the President on board, Plunger made a test dive on 25 March 1905. Reporting the adventure, Roosevelt declared, "Never in my before have I had such a diverting day. . . nor so much enjoyment in so few hours." After overhaul at New London, Plunger decommissioned 3 November. She remained in ord nary until recommissioning 23 February 1907, to join the 1st Submarine Flotilla with Porpoise (SS-7) and Shark (SS-8). The boat continued operations with this flotilla along the Atlantic ecaet for the next several years. In May 1909, Ens. Chester Nimitz, who would win undying fame in World War II as Commander in Chief, Pacific Fleet, took command of the boat. In September, she steamed to New York for the Hudson-Fulton celebration. On 6 November 1909, Plunger decommissoned and went into reserve at Charleston. Aesigned to the Reserve Torpedo Division 12 on 17 April 1910, the boat was re named A-1, 17 November 1911. A-1 was struck from the Navy List 24 February 1913 and used as a target until sold 26 January 1922. <script async src="//pagead2.googlesyndication.com/pagead/js/. · · · ← All Submarines From the makers of HistoryCentral
```

These sentences are absent from S1/DVSU1. They are potentially useful purpose,
service, and technical-work evidence, subject to the normal assessment and
role-quality rules. They do **not** establish that any particular claim should
be accepted.

Direct evaluation shows why they were not retained. The enclosing section
passes `candidate_mentions_machine` for `SS-2 USS Plunger`, but
`has_foreign_ship` is true because the same publisher section later names
`Porpoise (SS-7)` and `Shark (SS-8)`. Those are the specific competing-hull
matches that reject the otherwise in-range section. The strict whole-section branch rejects
the complete section for that reason. The later standalone sentences are then
tested independently; each listed sentence returns false for both
`candidate_mentions_machine` and `contextual_named_excerpt`, because it has
`Plunger` or a pronoun but lacks the required complete name-plus-SS-2 identity
(or `USS Plunger` contextual identity). Sentence-window extraction therefore
keeps short identity-bearing fragments such as S1-E2..E6 instead.

### NavSource

NavSource's Plunger section is 12,653 characters. It passes exact identity
matching but is over the 3,000-character whole-section ceiling and also has
foreign-hull references (including SS-5, SS-7, SS-3, SS-8, SS-19, and SS-64).
Its exact identity-and-technical header slice is:

```text
Plunger / A-1 (SS-2) Radio Call Sign: November - Quebec - Echo Adder Class Submarine Torpedo Boat : Laid down as Plunger , 21 May 1901, at Crescent Shipyards, Elizabethport, NJ ; Launched, 1 February 1902; Commissioned USS Plunger , 19 September 1903, at the Holland Co., New Suffolk, Long Island, NY; Decommissioned, 3 November 1905; Recommissioned, 7 March 1907; Renamed USS A-1 (Submarine Torpedo Boat No.2), 17 November 1911; Decommissioned, (date unknown); Struck from the Naval Register, 24 February 1913; Authorized as an experimental target, designated Target E , 29 August 1916; Final Disposition, sold for scrapping, 26 January 1922. Specifications : Displacement; Surfaced, 107 t., Submerged, 123 t.; Length 63' 10"; Beam 11' 11"; Draft 10' 7"; Speed, Surfaced, 8 kts, Submerged, 7 kts; Depth Limit 150'; Complement, 1 Officer, 6 Enlisted; Armament, one 18" torpedo tube, 5 torpedoes; Propulsion, Otto Gas Engine Works gasoline engine, HP 160; Fuel Capacity 767 gal.; Electro Dynamic electric motors, HP 150; Battery Cells 60; single screw.
```

The following fetched source passages did not appear among the package's first
ten S2 candidates or its two DVSU2 recapture candidates:

```text
Specifications : Displacement; Surfaced, 107 t., Submerged, 123 t.; Length 63' 10"; Beam 11' 11"; Draft 10' 7"; Speed, Surfaced, 8 kts, Submerged, 7 kts; Depth Limit 150'; Complement, 1 Officer, 6 Enlisted; Armament, one 18" torpedo tube, 5 torpedoes; Propulsion, Otto Gas Engine Works gasoline engine, HP 160; Fuel Capacity 767 gal.; Electro Dynamic electric motors, HP 150; Battery Cells 60; single screw.
A-1 illustrates typical single hull construction.
Her torpedo tube door in the bow is opened, as is done when a torpedo is fired under water.
```

The specification and construction/torpedo sentences individually fail both
identity predicates because they do not repeat the full vessel identity. The
current sentence extraction can produce later identity-bearing caption windows
(for example the torpedo-door caption) when asked for 30 rows, but recapture
uses a fixed limit of ten. The saved NavSource rows are consequently dominated
by the first identity-bearing activity and photo-caption windows rather than a
bounded contextual passage containing the engineering specifications.

## Gate and location evidence

* `backend/pipeline_executor.py:9628-9643` fetches an original URL and calls
  `_html_to_visible_text(..., preserve_sections=True)`.
* `backend/factual_source_sections.py:8-15` retains only HTML heading sections;
  `:18-33` rejects a named-vessel section when it contains another SS-family
  hull or a different USS vessel.
* `backend/pipeline_executor.py:1254-1273` enables strict named-submarine
  handling, accepts a whole section only at 45--3,000 characters and only when
  `has_foreign_ship` is false, then falls through to sentence windows. The
  whole-section sorter prefers service vocabulary but cannot run for the two
  rejected sections above.
* `backend/pipeline_executor.py:1292-1306` starts a window only at a sentence
  that itself matches the identity predicate, and appends only until `limit`.
* `backend/factual_machine_research.py:68-85` requires the complete Plunger
  name and the target SS-family hull in one excerpt. `:184-190` applies that
  strict check for a named submarine. `backend/contextual_source_identity.py:38-73`
  permits the narrower alternate case only when `USS Plunger` is present and
  every SS-family hull agrees.
* `backend/factual_source_recapture.py:19-46` re-fetches only the supplied
  URLs and calls the sentence extractor with `limit=10`; no source-level merge
  can create new evidence from a duplicate URL outside those candidates.
* The present `intended_role` and `design` gates are in
  `backend/dvsu_script_brief.py:53-103`: classification-only role claims are
  rejected, and builder/displacement-only design claims are rejected unless
  they contain engineering configuration evidence.

## Bounded diagnosis

There is concrete source text about purpose, service/testing/training, and
engineering configuration in the two already-saved original pages. It is
currently lost before assessment because the only complete HistoryCentral
section is disqualified by nearby other-submarine references, the NavSource
section is both over the section cap and mixed-identity, and the remaining
sentence path requires each retained sentence to repeat strict identity while
also stopping at ten rows. The second canary's 21 excerpts therefore do not
demonstrate absence of useful material in these sources.

Whether to change the contextual identity/section-selection contract, source
segmentation, or research strategy is a material architecture decision and is
intentionally left to Astra. This diagnostic makes no such change and makes no
historical claim beyond the quoted source text.
