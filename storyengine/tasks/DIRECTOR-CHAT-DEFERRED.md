# Director Phase 1 - Post-Deploy Verification

Four items built and wired but not verifiable in this sandbox. Exact proof level reached and test recipes below.

## 1. `GET /api/custom-film/recipes` returning a live 200

**Proof level reached:** The route, its auth dependency, and import wiring were proven by a traceback showing the request reaching `routes/custom_film.py`, then `custom_film_contract.list_active_recipes`, then `database.fetch_all`, then `pool.acquire()`, failing only at the DB socket. The table was independently verified empty on production with `se db "SELECT count(*) FROM custom_film_recipes"` returning `{"count": 0}`.

**Not checkable here:** No valid local `DATABASE_URL` exists on this machine. The frontend points at the production backend, which does not have this route yet because nothing was deployed.

**Test recipe after deploy:**
```bash
curl -s -H "Authorization: Bearer $(cat /tmp/se_token)" http://76.13.119.181:8001/api/custom-film/recipes
```

**Expected result:** HTTP 200 with body `{"recipes": []}`.

## 2. The saved-styles empty state rendering on screen

**Proof level reached:** The error state was proven to render correctly when the endpoint 404s, so a failure does not masquerade as "you have no styles". The empty state's markup exists but has not been seen with a real 200 response.

**Not checkable here:** Same reason, the production backend does not have the route yet.

**Test recipe after deploy:** Load `/` signed in. Confirm the gold dashed card reads "You haven't saved a style yet" and the header count reads "0 saved", with no red error box.

## 3. The Build button end to end

**Proof level reached:** Wired to the existing `getVideoActions` and `runBuild`, rendered behind a confirm, and verified disabled on a nonexistent video id. Never clicked.

**Not checkable here:** Clicking it spends real money.

**Test recipe after deploy:** On a real video with work pending, click Build, confirm the dialog, and check the cost ledger moves by the amount the confirm dialog quoted.

## 4. A populated Scene altitude view

**Proof level reached:** The scene and shot list renders from `getVideoAssets` and `getVideoScript`. A real video was opened during verification. A full visual check against the mockup's scene rows was not completed.

**Not checkable here:** Visual verification against the mockup requires manual review of a populated state.

**Test recipe after deploy:** Open a video with several scenes and drawn shots. Compare the scene rows and shot tiles against the mockup's Scene view at `tasks/director-mockup/index.html`.
