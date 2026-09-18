# Package D receipt

Added a selected-machine factual inspector block in `frontend/src/components/production/ResearchTab.tsx`.

It displays the saved research paragraph and source links, labels only a current passed card as `Saved and passed`, labels rejected/stale summaries `Needs review`, and tells factual legacy cards when no summary has been saved. Links render only for `http(s)` URLs; summary text remains ordinary React text.

Validation: `npm run build` completed after the final inspector changes (webpack compile, TypeScript, and static route generation). No browser, API, provider, or production action was run.
