# Passage measuring run - 2026-09-24 (step 1 of the HANDOFF plan)

Video `7b6914b6` (battleship test vehicle). Script: `passage-measure.py` (run from a dir holding
`pk.json` = `research_payload.machine_raw_source_packages`). Raw rows: `passage-measure-results.json`.

## Fetch + locate
- 23 machines, 191 claims, 191 evidence quotes, 109 unique URLs.
- Pages load: 102/109 HTML (Mac and VPS agree; VPS also gets the 1 PDF, which the script skips).
  Fail: 5x history.navy.mil (connect refused from both Mac and VPS), 1x navygeneralboard.com
  (timeout), 1x PDF.
- Quote found on page: 178/178 of loaded-page quotes (169 exact, 9 by head/tail anchor).
  Quotes with no passage (page down): 13/191 = 7% -> would keep the model quote alone.
- Size: quote median 137 chars; passage median 415 (min 112, max 822).
  Per machine, all passages together: median 3,499 chars, max 4,403 - against the 6,000-byte
  `MAX_BRIEF_BYTES` cap. Tight: passages need a per-claim cap or the brief cap needs raising.

## The 34 audited bad claims (claim-audit-34.json)
Where does the wrong text live? In the model `answer`, not the quote, for all 34.

- Wrong text no longer reaches the writer if the writer sees quote/passage instead of `answer`:
  33/34. Risk case: #26 South Dakota dates - the passage holds the ambiguous "next pair approved
  FY1940" line the model misread, so a writer could misread it again.
- 16 are pure unsupported additions (no fix text). Dropping `answer` removes them. Nothing to gain
  from the passage.
- 18 have a correct replacement fact. That fact is inside the passage for 5 (#12, #18, #21, #27,
  #33). For 4 of those 5 (#12, #18, #21, #27) the fact is already inside the bare quote.
  Only #33 (Oklahoma: "two or three additional torpedo hits") needs the wider passage.
  For the other 13 the true fact came from a different page or general knowledge; the writer
  simply gets less detail, not wrong detail.

## What it means
- Nearly all the gain comes from step 3 (writer reads quote, not `answer`). Step 2 (server fetch)
  adds context (3x the text) but fixed only 1 of 34 audited errors on its own.
- Fetch cost: 7% of pages unreachable, history.navy.mil blocked from the VPS.
