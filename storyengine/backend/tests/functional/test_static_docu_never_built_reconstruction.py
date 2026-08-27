"""Never-built machines use verified design references to make honest photos.

Every external boundary is replaced: database, source search, downloads,
storage, image generation, vision QA, budget checks, and ledger writes.
"""
import json
import os
import sys
import uuid

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402
import pipeline_executor as pe  # noqa: E402
import shared.clients.image_client as image_client_mod  # noqa: E402,F401
from static_docu_contract import NEVER_BUILT_VIEW_PLANS, STATIC_VIEW_PLANS  # noqa: E402
from test_static_docu_qa_park import _ClientCM, _FakeDownloadResp  # noqa: E402
from test_static_docu_roster_reference_layer import (  # noqa: E402
    _CVA01_CLASS,
    _cache_key_for,
    _video_row,
)


def _environment(
    monkeypatch,
    *,
    generated_urls=(),
    design_url="https://storage.example/cva01-design.png",
    design_candidate="https://source.example/cva01-three-view.png",
    cached_kind=None,
    cached_url=None,
    design_verified=True,
    design_candidates=None,
    design_verdicts=(),
    geometry_verdicts=(),
    photoreal_verdicts=(),
    role_verdicts_by_url=None,
    existing_assets=(),
):
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    video = _video_row(video_id, [
        _CVA01_CLASS,
        {"name": "Boeing XB-15"},
        {"name": "Northrop XB-35"},
    ])
    env = {
        "video_id": video_id,
        "tenant_id": tenant_id,
        "assets": {row["id"]: dict(row) for row in existing_assets},
        "queries": [],
        "gen_calls": [],
        "design_checks": [],
        "geometry_checks": [],
        "photoreal_checks": [],
        "role_checks": [],
        "uploads": [],
        "ledger": [],
        "stored_reference": None,
    }

    cache_row = None
    if cached_kind and cached_url:
        cache_row = {
            "hosted_url": cached_url,
            "source_url": "https://source.example/cached",
            "reference_kind": cached_kind,
        }

    async def fake_fetch_one(query, *args):
        env["queries"].append(query)
        if "FROM videos" in query:
            return dict(video)
        if "FROM static_reference_cache" in query:
            requested_kind = "photo" if "reference_kind='photo'" in query else (
                "design" if "reference_kind='design'" in query else None
            )
            if cache_row and requested_kind == cache_row["reference_kind"]:
                return dict(cache_row)
            if env["stored_reference"] and requested_kind is None:
                return dict(env["stored_reference"])
            return None
        return None

    async def fake_fetch_all(query, *args):
        env["queries"].append(query)
        if "FROM scripts" in query:
            return [{
                "scene": 1,
                "scene_text": "CVA-01 was cancelled before construction.",
            }]
        if "FROM machine_research_cards" in query:
            return [{
                "roster_index": 1,
                "card": json.dumps({
                    "unit": "CVA-01 class",
                    "visual_identity": "angled flight deck, island set well aft",
                    "evidence_segments": [],
                }),
            }]
        if "FROM assets" in query:
            return list(env["assets"].values())
        return []

    async def fake_execute(query, *args):
        env["queries"].append(query)
        if "INSERT INTO assets" in query:
            env["assets"][args[0]] = {
                "id": args[0], "status": "generating", "image_url": None,
                "drive_image_url": args[12], "image_prompt": args[14],
                "caption": args[11],
            }
        elif "INSERT INTO static_reference_cache" in query:
            env["stored_reference"] = {
                "reference_kind": "design",
                "hosted_url": args[3],
                "source_url": args[4],
            }
        elif "UPDATE assets SET drive_image_url" in query:
            env["assets"].setdefault(args[0], {})["drive_image_url"] = args[1]
        elif "UPDATE assets SET caption=$2" in query:
            env["assets"].setdefault(args[0], {})["caption"] = args[1]
        elif "UPDATE assets SET image_url=$2" in query:
            row = env["assets"].setdefault(args[0], {})
            row.update(status="done", image_url=args[1], drive_image_url=args[1],
                       image_prompt=args[2])
        elif "UPDATE assets SET status='qa_rejected'" in query:
            row = env["assets"].setdefault(args[0], {})
            row.update(status="qa_rejected", image_url=None,
                       drive_image_url=args[1], image_prompt=args[2])
        elif "UPDATE assets SET status='blocked_no_reference'" in query:
            row = env["assets"].setdefault(args[0], {})
            row.update(status="blocked_no_reference", image_url=None,
                       drive_image_url=None)
        elif "DELETE FROM assets WHERE video_id=" in query:
            env["assets"].clear()
        elif "DELETE FROM assets WHERE id=" in query:
            env["assets"].pop(args[0], None)
        return None

    class FakeTextClient:
        async def generate(self, **kwargs):
            return json.dumps([{
                "scene": 1,
                "machine": "CVA-01 class",
                "aliases": ["CVA-01"],
                "caption_title": "CVA-01 class",
                "caption_sub": "Royal Navy • Designed 1963-1966",
                "caption_specs": ["Angled flight deck", "Island set well aft"],
                "detail_focus": "deck and island geometry",
                "search_query": "CVA-01 carrier design",
            }])

    async def fake_get_text_client_for_tenant(_tenant_id):
        return FakeTextClient()

    async def fake_secret(name, *args, **kwargs):
        return "fake-key" if name == "kie_ai_api_key" else None

    async def fake_design_candidates(machine, aliases, search_query):
        if design_candidates is not None:
            return list(design_candidates)
        return [(design_candidate, "File:CVA-01 three-view design.png")] if design_candidate else []

    remaining_design_verdicts = list(design_verdicts)

    async def fake_host_reference(url, video_arg, tenant_arg, tag):
        return design_url if design_candidates is None else f"https://storage.example/{tag}.png"

    async def fake_design_confirms(tenant_arg, image_url, machine, aliases=None,
                                   facts=None, source_label=None):
        env["design_checks"].append((image_url, machine, source_label))
        if remaining_design_verdicts:
            return remaining_design_verdicts.pop(0)
        return design_verified

    remaining_urls = list(generated_urls)

    async def fake_generate(self, prompt, ref_url, aspect_ratio="16:9",
                            allow_fallback=False, resolution="1K"):
        env["gen_calls"].append((prompt, ref_url))
        url = remaining_urls.pop(0) if remaining_urls else None
        return {"url": url} if url else {}

    geometry = list(geometry_verdicts)
    photoreal = list(photoreal_verdicts)

    async def fake_geometry(tenant_arg, source_url, render_url, machine,
                            facts=None, *, reason_out=None):
        env["geometry_checks"].append((source_url, render_url))
        verdict = geometry.pop(0) if geometry else True
        if reason_out is not None:
            reason_out.append("geometry matches" if verdict else "geometry drifted")
        return verdict

    async def fake_photoreal(tenant_arg, render_url, machine, *, reason_out=None):
        env["photoreal_checks"].append(render_url)
        verdict = photoreal.pop(0) if photoreal else True
        if reason_out is not None:
            reason_out.append("full-size photograph" if verdict else "flat CGI model")
        return verdict

    async def fake_role(tenant_arg, image_url, machine, view_plan,
                        reason_out=None, **kwargs):
        env["role_checks"].append(image_url)
        verdict = (role_verdicts_by_url or {}).get(image_url, True)
        if reason_out is not None:
            reason_out.append("correct angle" if verdict else "wrong angle")
        return verdict

    class FakeHttp:
        async def get(self, url, **kwargs):
            return _FakeDownloadResp(b"\x89PNG" + b"x" * 40)

    async def fake_upload(data, path, mime, tenant_arg):
        env["uploads"].append(path)
        return f"https://storage.example/{path.rsplit('/', 1)[-1]}"

    async def fake_budget(*args, **kwargs):
        return None

    async def fake_ledger(**kwargs):
        env["ledger"].append(kwargs)

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "_gather_design_reference_candidates", fake_design_candidates,
                        raising=False)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host_reference)
    monkeypatch.setattr(static_docu, "_design_reference_confirms", fake_design_confirms,
                        raising=False)
    monkeypatch.setattr(static_docu, "_reconstruction_matches_design_reference", fake_geometry,
                        raising=False)
    monkeypatch.setattr(static_docu, "_photoreal_render_confirms", fake_photoreal,
                        raising=False)
    monkeypatch.setattr(static_docu, "_view_role_confirms", fake_role)
    monkeypatch.setattr(static_docu, "upload_bytes", fake_upload)
    monkeypatch.setattr(static_docu.httpx, "AsyncClient", lambda *a, **k: _ClientCM(FakeHttp()))
    monkeypatch.setattr(image_client_mod.ImageClient, "generate_scene_image_gpt", fake_generate)

    import actions
    import generation_ledger
    import kie_unified
    import vault
    monkeypatch.setattr(actions, "budget_refusal", fake_budget)
    monkeypatch.setattr(generation_ledger, "record_ledger_entry", fake_ledger)
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant", fake_get_text_client_for_tenant)
    monkeypatch.setattr(vault, "get_secret", fake_secret)
    env["fake_fetch_one"] = fake_fetch_one
    return env


def _rows_by_role(env):
    rows = {}
    for row in env["assets"].values():
        caption = row.get("caption")
        if isinstance(caption, str):
            caption = json.loads(caption)
        if isinstance(caption, dict) and caption.get("view_role"):
            rows[caption["view_role"]] = (row, caption)
    return rows


def test_never_built_contract_uses_standard_three_roles():
    assert tuple(plan["role"] for plan in NEVER_BUILT_VIEW_PLANS) == (
        "three_quarter", "side_profile", "top_planform")


def test_reconstruction_prompt_requires_full_size_photo_and_excludes_flat_media():
    plan = STATIC_VIEW_PLANS[0]
    prompt = static_docu._never_built_reconstruction_prompt(
        "CVA-01 class", plan, ["angled flight deck"])
    lowered = prompt.lower()
    assert "full-size" in lowered and "professionally photographed" in lowered
    for preserved in ("proportions", "components", "planform", "control surfaces",
                      "engines", "armament", "distinctive geometry"):
        assert preserved in lowered
    for excluded in ("blueprint", "schematic", "line drawing", "orthographic plate",
                     "cad", "technical illustration", "miniature", "model", "toy",
                     "labels", "dimensions", "watermarks", "text"):
        assert excluded in lowered


@pytest.mark.asyncio
async def test_never_built_generates_three_grounded_photoreal_reconstructions(monkeypatch):
    env = _environment(monkeypatch, generated_urls=("gen://a", "gen://b", "gen://c"))
    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    rows = _rows_by_role(env)
    assert set(rows) == {"three_quarter", "side_profile", "top_planform"}
    assert len(env["gen_calls"]) == 3
    assert env["gen_calls"][0][1] == "https://storage.example/cva01-design.png"
    assert env["gen_calls"][1][1] == rows["three_quarter"][0]["image_url"]
    assert env["gen_calls"][2][1] == rows["three_quarter"][0]["image_url"]
    assert all(ref for _, ref in env["gen_calls"])
    assert len(env["geometry_checks"]) == 3
    assert len(env["photoreal_checks"]) == 3
    assert all(source == "https://storage.example/cva01-design.png"
               for source, _render in env["geometry_checks"])
    for row, caption in rows.values():
        assert row["image_url"] != "https://storage.example/cva01-design.png"
        assert caption["design_study"] is True
        assert caption["reconstruction_style"] == "photorealistic"
        assert caption["sub"].startswith("Design study — never built")
        assert "[never-built: photoreal-reconstruction]" in row["image_prompt"]


@pytest.mark.parametrize("design_candidate,design_verified", [
    (None, True),
    ("https://source.example/wrong-design.png", False),
])
@pytest.mark.asyncio
async def test_missing_or_unverified_design_blocks_before_generation(
    monkeypatch, design_candidate, design_verified,
):
    env = _environment(
        monkeypatch, design_candidate=design_candidate,
        design_verified=design_verified, generated_urls=("gen://unused",))
    result = await static_docu.generate_static_images_for_video(env["video_id"], env["tenant_id"])
    assert result["status"] == "failed"
    assert env["gen_calls"] == []
    assert any(row.get("status") == "blocked_no_reference" for row in env["assets"].values())


@pytest.mark.asyncio
async def test_photoreal_qa_gets_one_retry_then_parks_paid_result(monkeypatch):
    env = _environment(
        monkeypatch,
        generated_urls=("gen://bad-1", "gen://bad-2", "gen://good-remaining", "gen://good-last"),
        photoreal_verdicts=(False, False, True, True),
    )
    result = await static_docu.generate_static_images_for_video(env["video_id"], env["tenant_id"])
    # Generic scene recovery still accepts two approved views; later batch
    # readiness enforces the three-view target.
    assert result["status"] == "completed"
    assert len(env["gen_calls"]) == 4
    parked = [row for row in env["assets"].values() if row.get("status") == "qa_rejected"]
    assert len(parked) == 1
    assert parked[0]["image_url"] is None
    assert parked[0]["drive_image_url"] is not None
    assert not any("DELETE FROM assets WHERE id=" in q for q in env["queries"])


@pytest.mark.asyncio
async def test_old_blueprint_captions_are_stale_and_regenerated(monkeypatch):
    old = []
    for index, role in enumerate(("three_quarter", "side_profile", "top_planform"), 1):
        old.append({
            "id": f"old-{index}", "status": "done", "image_url": f"old://{role}",
            "caption": json.dumps({"view_role": role, "design_study": True}),
        })
    env = _environment(
        monkeypatch, existing_assets=old,
        generated_urls=("gen://new-a", "gen://new-b", "gen://new-c"),
    )
    result = await static_docu.generate_static_images_for_video(env["video_id"], env["tenant_id"])
    assert result["status"] == "completed"
    assert len(env["gen_calls"]) == 3


@pytest.mark.asyncio
async def test_verified_cached_photo_vetoes_never_built_classifier(monkeypatch):
    photo = "https://storage.example/verified-historical-photo.jpg"
    env = _environment(
        monkeypatch, cached_kind="photo", cached_url=photo,
        generated_urls=("gen://a", "gen://b", "gen://c"),
    )

    async def photo_identity(*args, **kwargs):
        return True

    async def photo_render(*args, reason_out=None, **kwargs):
        if reason_out is not None:
            reason_out.append("same machine")
        return True

    monkeypatch.setattr(static_docu, "_vision_confirms", photo_identity)
    monkeypatch.setattr(static_docu, "_render_matches_reference", photo_render)
    result = await static_docu.generate_static_images_for_video(env["video_id"], env["tenant_id"])
    assert result["status"] == "completed"
    assert env["design_checks"] == []
    assert env["gen_calls"][0][1] == photo
    for _, caption in _rows_by_role(env).values():
        assert "design_study" not in caption


def test_design_upsert_is_guarded_from_replacing_photo():
    sql = static_docu._reference_cache_upsert_sql("design")
    assert "reference_kind = 'design'" in sql
    assert "WHERE static_reference_cache.reference_kind = 'design'" in sql


def test_photo_upsert_may_replace_stale_design():
    sql = static_docu._reference_cache_upsert_sql("photo")
    assert "reference_kind = 'photo'" in sql
    assert "WHERE static_reference_cache.reference_kind = 'design'" not in sql


async def _install_photo_race(monkeypatch, env, interleaving):
    photo = {
        "reference_kind": "photo",
        "hosted_url": "https://storage.example/race-winning-photo.jpg",
        "source_url": "https://source.example/race-winning-photo",
    }
    original_fetch_one = env["fake_fetch_one"]
    photo_reads = 0

    async def racing_fetch_one(query, *args):
        nonlocal photo_reads
        if "FROM static_reference_cache" in query:
            if "reference_kind='photo'" in query:
                photo_reads += 1
                # Direct key, roster key, then the pre-upsert re-read.
                if interleaving == "before_upsert" and photo_reads == 3:
                    return dict(photo)
            elif "SELECT reference_kind, hosted_url, source_url" in query:
                assert interleaving == "during_upsert"
                return dict(photo)
        return await original_fetch_one(query, *args)

    async def photo_render_matches(*args, reason_out=None, **kwargs):
        if reason_out is not None:
            reason_out.append("same machine")
        return True

    monkeypatch.setattr(static_docu, "fetch_one", racing_fetch_one)
    monkeypatch.setattr(static_docu, "_render_matches_reference", photo_render_matches)
    return photo


@pytest.mark.parametrize("interleaving", ["before_upsert", "during_upsert"])
@pytest.mark.asyncio
async def test_photo_winner_during_design_verification_routes_to_photo_path(
    monkeypatch, interleaving,
):
    env = _environment(monkeypatch, generated_urls=("gen://a", "gen://b", "gen://c"))
    photo = await _install_photo_race(monkeypatch, env, interleaving)

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert len(env["gen_calls"]) == 3
    assert env["gen_calls"][0][1] == photo["hosted_url"]
    assert env["gen_calls"][0][1] != "https://storage.example/cva01-design.png"
    for _row, caption in _rows_by_role(env).values():
        assert "design_study" not in caption
        assert "reconstruction_style" not in caption


@pytest.mark.asyncio
async def test_all_qa_shares_one_paid_retry_ceiling(monkeypatch):
    env = _environment(
        monkeypatch,
        generated_urls=(
            "gen://bad-quality", "gen://bad-angle", "gen://good-two",
            "gen://good-three", "gen://must-not-run",
        ),
        photoreal_verdicts=(False, True, True, True),
        role_verdicts_by_url={"gen://bad-quality": True, "gen://bad-angle": False},
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"  # generic 2-view recovery
    assert len(env["gen_calls"]) == 4
    assert len(env["ledger"]) == 4
    parked = [row for row in env["assets"].values() if row.get("status") == "qa_rejected"]
    assert len(parked) == 1
    assert "wrong angle" in parked[0]["image_prompt"]


@pytest.mark.asyncio
async def test_unusable_article_design_falls_back_to_valid_commons_design(monkeypatch):
    article = ("https://article.example/unusable.png", "article concept")
    commons = ("https://commons.example/exact-three-view.png", "exact three-view")
    env = _environment(
        monkeypatch,
        design_candidates=(article, commons),
        design_verdicts=(False, True),
        generated_urls=("gen://a", "gen://b", "gen://c"),
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert [call[2] for call in env["design_checks"]] == [article[1], commons[1]]
    assert len(env["gen_calls"]) == 3


@pytest.mark.asyncio
async def test_design_candidate_gather_keeps_commons_after_article_sources(monkeypatch):
    async def lead(_names):
        return [{"url": "article://lead", "page": "CVA-01"}]

    async def article(_names):
        return [{"url": "article://three-view", "file_title": "CVA-01 drawing"}]

    async def commons(_query):
        return [{"url": "commons://exact", "title": "CVA-01 exact three-view"}]

    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", lead)
    monkeypatch.setattr(static_docu, "find_article_images", article)
    monkeypatch.setattr(static_docu, "find_commons_photos", commons)

    candidates = await static_docu._gather_design_reference_candidates(
        "CVA-01 class", ["CVA-01"], "CVA-01 design")
    assert candidates == [
        ("article://lead", "CVA-01"),
        ("article://three-view", "CVA-01 drawing"),
        ("commons://exact", "CVA-01 exact three-view"),
    ]


@pytest.mark.parametrize("design_source", ["cached", "fresh"])
@pytest.mark.asyncio
async def test_late_roster_key_photo_wins_over_design(monkeypatch, design_source):
    kwargs = {
        "generated_urls": ("gen://a", "gen://b", "gen://c"),
    }
    if design_source == "cached":
        kwargs.update(
            cached_kind="design",
            cached_url="https://storage.example/cached-design.png",
        )
    env = _environment(monkeypatch, **kwargs)
    original_fetch_one = env["fake_fetch_one"]
    roster_key = _cache_key_for(_CVA01_CLASS)
    roster_photo_reads = 0
    photo = {
        "hosted_url": "https://storage.example/late-roster-photo.jpg",
        "source_url": "https://source.example/late-roster-photo",
    }

    async def racing_fetch_one(query, *args):
        nonlocal roster_photo_reads
        if ("FROM static_reference_cache" in query
                and "reference_kind='photo'" in query
                and len(args) > 1 and args[1] == roster_key):
            roster_photo_reads += 1
            if roster_photo_reads == 2:
                return dict(photo)
        return await original_fetch_one(query, *args)

    async def photo_render_matches(*args, reason_out=None, **kwargs):
        if reason_out is not None:
            reason_out.append("same machine")
        return True

    identity_calls = []

    async def photo_identity(tenant_arg, image_url, machine, aliases=None,
                             trusted_source=False, facts=None, source_label=None):
        identity_calls.append({
            "image_url": image_url,
            "machine": machine,
            "aliases": aliases,
            "trusted_source": trusted_source,
            "facts": facts,
            "source_label": source_label,
        })
        return True

    monkeypatch.setattr(static_docu, "fetch_one", racing_fetch_one)
    monkeypatch.setattr(static_docu, "_render_matches_reference", photo_render_matches)
    monkeypatch.setattr(static_docu, "_vision_confirms", photo_identity)

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert env["gen_calls"][0][1] == photo["hosted_url"]
    assert len(identity_calls) == 1
    assert identity_calls[0]["trusted_source"] is True
    assert identity_calls[0]["source_label"] == pe._unit_display_name(_CVA01_CLASS)
    assert identity_calls[0]["facts"]
    for _row, caption in _rows_by_role(env).values():
        assert "design_study" not in caption


@pytest.mark.asyncio
async def test_rejected_late_roster_photo_keeps_verified_design(monkeypatch):
    design = "https://storage.example/cached-design.png"
    env = _environment(
        monkeypatch,
        cached_kind="design",
        cached_url=design,
        generated_urls=("gen://a", "gen://b", "gen://c"),
    )
    original_fetch_one = env["fake_fetch_one"]
    roster_key = _cache_key_for(_CVA01_CLASS)
    roster_photo_reads = 0
    late_photo = "https://storage.example/wrong-variant.jpg"

    async def racing_fetch_one(query, *args):
        nonlocal roster_photo_reads
        if ("FROM static_reference_cache" in query
                and "reference_kind='photo'" in query
                and len(args) > 1 and args[1] == roster_key):
            roster_photo_reads += 1
            if roster_photo_reads == 2:
                return {
                    "hosted_url": late_photo,
                    "source_url": "https://source.example/wrong-variant",
                }
        return await original_fetch_one(query, *args)

    identity_calls = []

    async def reject_identity(tenant_arg, image_url, machine, aliases=None,
                              trusted_source=False, facts=None, source_label=None):
        identity_calls.append({
            "image_url": image_url,
            "machine": machine,
            "aliases": aliases,
            "trusted_source": trusted_source,
            "facts": facts,
            "source_label": source_label,
        })
        return False

    monkeypatch.setattr(static_docu, "fetch_one", racing_fetch_one)
    monkeypatch.setattr(static_docu, "_vision_confirms", reject_identity)

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert env["gen_calls"][0][1] == design
    assert all(ref != late_photo for _prompt, ref in env["gen_calls"])
    assert len(identity_calls) == 1
    call = identity_calls[0]
    assert call["trusted_source"] is True
    assert call["source_label"] == pe._unit_display_name(_CVA01_CLASS)
    assert call["facts"]
    for _row, caption in _rows_by_role(env).values():
        assert caption["design_study"] is True
