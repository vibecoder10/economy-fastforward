import asyncio
import copy
import json

import pytest

import custom_film_contract as contract
import custom_film_orchestration as orchestration
import custom_film_planner as planner
import routes.chat as chat_route


def _profiles():
    rows = {
        "bilingual_character_animation": {
            "render_mode": "coverage",
            "script_profile": "neutral_v1",
            "visual_profile": "neutral_v1",
            "image_density": {"mode": "dialogue_shape", "target_per_minute": 8},
            "animation": {"enabled": True, "mode": "grok_native"},
            "language": {"mode": "bilingual"},
            "dubbing": {"enabled": True, "mode": "speech_to_speech"},
            "segmentation": {"mode": "speaker_turn"},
            "camera": {"mode": "dialogue_coverage"},
            "quality_laws": [
                "character_continuity",
                "lip_sync",
                "translation_fidelity",
            ],
            "image_source": "generate",
        },
        "simple_language_animation": {
            "render_mode": "coverage",
            "script_profile": "neutral_v1",
            "visual_profile": "neutral_v1",
            "image_density": {"mode": "dialogue_shape", "target_per_minute": 8},
            "animation": {"enabled": True, "mode": "grok_native"},
            "language": {"mode": "simple_single_language"},
            "dubbing": {"enabled": False, "mode": "none"},
            "segmentation": {"mode": "speaker_turn"},
            "camera": {"mode": "dialogue_coverage"},
            "quality_laws": [
                "character_continuity",
                "clear_language",
                "lip_sync",
            ],
            "image_source": "generate",
        },
        "photo_documentary": {
            "render_mode": "static_docu",
            "script_profile": "neutral_v1",
            "visual_profile": "neutral_v1",
            "image_density": {"mode": "per_item", "target": 3, "minimum": 2},
            "animation": {"enabled": False, "mode": "ken_burns"},
            "language": {"mode": "narrator"},
            "dubbing": {"enabled": False, "mode": "none"},
            "segmentation": {"mode": "item"},
            "camera": {"mode": "three_complementary_views"},
            "quality_laws": [
                "verified_reference",
                "variant_accuracy",
                "caption_grounding",
            ],
            "image_source": "generate",
        },
        "animated_investigative_documentary": {
            "render_mode": "coverage",
            "script_profile": "power_doctrine_v2",
            "visual_profile": "cinematic_illustration",
            "image_density": {"mode": "visual_cue", "target_per_minute": 10},
            "animation": {"enabled": True, "mode": "grok_native"},
            "language": {"mode": "narrator"},
            "dubbing": {"enabled": False, "mode": "none"},
            "segmentation": {"mode": "visual_cue"},
            "camera": {"mode": "investigative_coverage"},
            "quality_laws": [
                "source_grounding",
                "visual_cue_fidelity",
                "motion_prompt_presence",
            ],
            "image_source": "generate",
        },
    }
    return [
        {
            "id": style_id,
            "version": 1,
            "label": style_id.replace("_", " ").title(),
            "description": style_id,
            "knobs": knobs,
            "estimate": {},
            "requires_byok": True,
            "sort": index,
        }
        for index, (style_id, knobs) in enumerate(rows.items())
    ]


@pytest.fixture
def manifest():
    return contract.build_capability_manifest(_profiles())


def _proposal(focus="steel"):
    return {
        "sections": [
            {
                "role": "opening",
                "focus": focus,
                "duration_weight": 1,
                "structure_source": "photo_documentary",
                "writing_source": "animated_investigative_documentary",
                "visual_source": "animated_investigative_documentary",
            },
            {
                "role": "explanation",
                "focus": focus,
                "duration_weight": 2,
                "structure_source": "animated_investigative_documentary",
                "writing_source": "animated_investigative_documentary",
                "visual_source": "animated_investigative_documentary",
            },
        ]
    }


def _beat(*capabilities, dialogue=False, captions=False, intents=None):
    return {
        "narrative_function": "humanize" if dialogue else "investigate",
        "duration_weight": 1,
        "capability_ids": [
            "media.approved_primary",
            *capabilities,
            "audio.motion_system",
        ],
        "media_kind": "video",
        "dialogue": dialogue,
        "captions": captions,
        "intents": intents or ["evidence"],
        "energy": 2,
        "handoff": "waveform" if dialogue else "route",
    }


def _flagship_proposal():
    specs = [
        ("opening", "internet outage", 45, _beat(
            "motion.signal_pulse", "motion.outage_map",
            intents=["cinematic", "outage", "map"],
        )),
        ("evidence", "evidence investigation", 105, _beat(
            "motion.evidence_board", "motion.incident_timeline",
            intents=["evidence", "documents", "timeline"],
        )),
        ("case_study", "bilingual witness", 90, _beat(
            "motion.radio_waveform", "motion.bilingual_captions",
            dialogue=True, captions=True, intents=["witness", "radio"],
        )),
        ("explanation", "network recovery by StoryEngine", 60, _beat(
            "motion.network_explainer", "motion.storyengine_reveal",
            intents=["network", "recovery", "product"],
        )),
    ]
    return {
        "sections": [
            {
                "role": role,
                "focus": focus,
                "duration_weight": duration,
                "structure_source": (
                    "bilingual_character_animation"
                    if role == "case_study"
                    else "animated_investigative_documentary"
                ),
                "writing_source": "animated_investigative_documentary",
                "visual_source": "animated_investigative_documentary",
                "beats": [beat],
            }
            for role, focus, duration, beat in specs
        ]
    }


def _quote_for_compiled(compiled):
    durations = (45, 105, 90, 60)
    quote = {
        "sections": [],
        "totals": {
            "duration_seconds": 300,
            "still_images": 4,
            "animation_clips": 4,
            "voice_tracks": 4,
            "estimated_cost": 4.0,
        },
        "max_spend": 15.0,
    }
    for index, (section, duration) in enumerate(
        zip(compiled.internal_plan["sections"], durations)
    ):
        section["estimated_media"] = {
            "still_images": 1,
            "animation_clips": 1,
            "voice_tracks": 1,
            "duration_seconds": str(duration),
        }
        quote["sections"].append(
            {
                "section_id": section["section_id"],
                "order_index": index,
                "duration_seconds": duration,
                "still_images": 1,
                "animation_clips": 1,
                "voice_tracks": 1,
                "estimated_cost": 1.0,
            }
        )
    return quote


def test_planner_capability_beats_resolve_exact_approval_bound_reference(manifest):
    proposal = _flagship_proposal()
    request = (
        "Make a film about an internet outage, evidence investigation, a "
        "bilingual witness, and network recovery by StoryEngine."
    )
    compiled = planner.compile_planner_proposal(
        request, proposal, manifest, total_duration_seconds=300
    )
    quote = _quote_for_compiled(compiled)
    first = orchestration.compile_approved_orchestration(
        compiled.internal_plan, quote, compiled.planner_proposal
    )
    second = orchestration.compile_approved_orchestration(
        compiled.internal_plan, quote, compiled.planner_proposal
    )
    assert first == second
    assert first["reference_compatible"] is True
    assert first["resolved_plan"] == first["approved_beat_plan"]
    assert first["resolved_plan"]["total_frames"] == 7200
    assert first["resolved_plan"]["recipes"][0]["from"] == 0
    assert first["resolved_plan"]["recipes"][-1]["to"] == 7199
    assert first["approved_beat_plan_hash"]
    assert first["resolved_plan_hash"]
    assert first["contract_hash"] == contract.canonical_hash(
        {key: value for key, value in first.items() if key != "contract_hash"}
    )
    quote["orchestration"] = first
    quote["finishing_canvas"] = {
        **copy.deepcopy(chat_route._CUSTOM_FILM_REMOTION_FINISHING_CANVAS),
        "orchestration_contract_hash": first["contract_hash"],
        "story_identity": first["story_identity"],
        "recipe_hash": first["recipe_hash"],
    }
    card = chat_route._custom_film_approval_card(
        quote, compiled.display_plan
    )
    assert card["finishing_engine"] == "remotion"
    assert len(card["custom_film_orchestration_beats"]) == 4
    assert card["custom_film_orchestration_beats"][2]["captions_summary"] == (
        "bilingual word emphasis"
    )
    assert "Radio Waveform" in card[
        "custom_film_orchestration_beats"
    ][2]["capability_labels"]
    assert orchestration.validate_approved_orchestration(
        first, compiled.internal_plan, quote
    ) == first
    compiler_owned_mutations = {
        "decision_rules_version": "tampered-rules-v1",
        "reference_compatible": False,
        "story_identity": "tampered-story",
        "signals_hash": "f" * 64,
        "reference_plan_version": None,
    }
    for field, replacement in compiler_owned_mutations.items():
        tampered = copy.deepcopy(first)
        tampered[field] = replacement
        tampered["contract_hash"] = contract.canonical_hash(
            {
                key: value
                for key, value in tampered.items()
                if key != "contract_hash"
            }
        )
        with pytest.raises(
            contract.CustomFilmContractError,
            match="approved orchestration identity changed",
        ):
            orchestration.validate_approved_orchestration(
                tampered, compiled.internal_plan, quote
            )
    semantic_version_mutations = {
        "capability_catalog_version": "tampered-catalog-v1",
        "compatibility_version": "tampered-compatibility-v1",
    }
    for field, replacement in semantic_version_mutations.items():
        tampered_semantic = copy.deepcopy(first["semantic_input"])
        tampered_semantic[field] = replacement
        tampered = orchestration._contract_from_semantic_input(
            tampered_semantic
        )
        with pytest.raises(
            contract.CustomFilmContractError,
            match="approved orchestration semantic input changed",
        ):
            orchestration.validate_approved_orchestration(
                tampered, compiled.internal_plan, quote
            )

    mutated_proposal = copy.deepcopy(compiled.planner_proposal)
    mutated_proposal["sections"][0]["beats"][0]["energy"] = 3
    mutated = orchestration.compile_approved_orchestration(
        compiled.internal_plan, quote, mutated_proposal
    )
    assert mutated["contract_hash"] != first["contract_hash"]
    assert mutated["approved_beat_plan_hash"] != first["approved_beat_plan_hash"]


def test_same_timing_unrelated_story_cannot_receive_outage_reference(manifest):
    proposal = _flagship_proposal()
    for section in proposal["sections"]:
        section["focus"] = "steel manufacturing"
    compiled = planner.compile_planner_proposal(
        "Make a film about steel manufacturing",
        proposal,
        manifest,
        total_duration_seconds=300,
    )
    quote = _quote_for_compiled(compiled)
    result = orchestration.compile_approved_orchestration(
        compiled.internal_plan, quote, compiled.planner_proposal
    )
    assert result["reference_compatible"] is False
    assert result["resolved_plan"] == result["approved_beat_plan"]


def test_media_plus_motion_audio_only_still_compiles_executable_visual_layers(
    manifest,
):
    proposal = _proposal("ceramic glazing")
    for section in proposal["sections"]:
        section["beats"] = [
            {
                **_beat(intents=["cinematic"]),
                "capability_ids": [
                    "media.approved_primary",
                    "audio.motion_system",
                ],
            }
        ]
    compiled = planner.compile_planner_proposal(
        "Make a 30 second film about ceramic glazing",
        proposal,
        manifest,
        total_duration_seconds=30,
    )
    quote = _quote_for_compiled(compiled)
    quote["totals"]["duration_seconds"] = 30
    for duration, quote_section, plan_section in zip(
        (10, 20), quote["sections"], compiled.internal_plan["sections"]
    ):
        quote_section["duration_seconds"] = duration
        plan_section["estimated_media"]["duration_seconds"] = str(duration)
    approved = orchestration.compile_approved_orchestration(
        compiled.internal_plan,
        quote,
        compiled.planner_proposal,
    )
    for recipe in approved["resolved_plan"]["recipes"]:
        visual = {
            layer["primitive"]
            for layer in recipe["motionLayers"]
            if layer["primitive"]
            not in {"MotionAudioSystem", "BilingualCaptions"}
        }
        assert visual == {"SignalPulse", "MediaKinetics"}
    orchestration.validate_executable_orchestration(
        approved,
        total_duration_seconds=30,
        section_duration_seconds=[
            row["duration_seconds"] for row in quote["sections"]
        ],
    )


def test_orchestration_capability_catalog_is_strict_and_provider_opaque():
    serialized = json.dumps(planner.PUBLIC_ORCHESTRATION_CAPABILITIES).lower()
    assert "provider" not in serialized
    assert "model" not in serialized
    invalid = _flagship_proposal()
    invalid["sections"][0]["beats"][0]["capability_ids"].append(
        "motion.unknown"
    )
    with pytest.raises(planner.CustomFilmPlannerError):
        planner.compile_planner_proposal(
            (
                "Make a film about an internet outage, evidence investigation, "
                "a bilingual witness, and network recovery by StoryEngine."
            ),
            invalid,
            contract.build_capability_manifest(_profiles()),
            total_duration_seconds=300,
        )


class FakePlannerClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps(self.payload)


def test_fake_planner_fixture_compiles_to_stable_hidden_plan(manifest):
    first_client = FakePlannerClient(_proposal("hidden cost of fast fashion"))
    second_client = FakePlannerClient(
        copy.deepcopy(_proposal("hidden cost of fast fashion"))
    )

    first = asyncio.run(
        planner.plan_custom_film(
            "Make a custom film about the hidden cost of fast fashion",
            manifest,
            first_client,
        )
    )
    second = asyncio.run(
        planner.plan_custom_film(
            "Make a custom film about the hidden cost of fast fashion",
            manifest,
            second_client,
        )
    )

    assert first.internal_plan == second.internal_plan
    assert first.plan_hash == second.plan_hash
    assert first.recipe_signature == second.recipe_signature
    assert first.internal_plan["sections"][0]["knobs"]["render_mode"] == "static_docu"
    assert first.internal_plan["sections"][0]["knobs"]["script_profile"] == (
        "power_doctrine_v2"
    )
    assert first.internal_plan["sections"][0]["knobs"]["visual_profile"] == (
        "cinematic_illustration"
    )
    assert first.internal_plan["sections"][0]["estimated_media"]["duration_seconds"] == (
        "0"
    )
    assert first.display_plan["kind"] == "custom_film"
    assert first.display_plan["sections"][0]["purpose"] == (
        planner.ROLE_PURPOSES["opening"].format(
            focus="hidden cost of fast fashion"
        )
    )
    assert "purpose" not in first.planner_proposal["sections"][0]
    display_text = json.dumps(first.display_plan)
    assert "photo_documentary" not in display_text
    assert "animated_investigative_documentary" not in display_text
    assert "render_mode" not in display_text
    assert "provider" not in display_text.lower()
    assert "generation has not started" in display_text.lower()
    assert first_client.calls[0]["temperature"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["sections"][0].update(
            {"provider_id": "storyengine-funded"}
        ),
        lambda payload: payload["sections"][0].update(
            {"knobs": {"render_mode": "invented"}}
        ),
        lambda payload: payload["sections"][0].update(
            {"structure_source": "hidden_profile"}
        ),
        lambda payload: payload["sections"][0].update({"model": "paid-model"}),
        lambda payload: payload["sections"][0].update({"api_key": "secret"}),
        lambda payload: payload["sections"][0].update({"estimate": 0.01}),
        lambda payload: payload["sections"][0].update({"approval": True}),
        lambda payload: payload["sections"][0].update({"generation": "start"}),
        lambda payload: payload["sections"][0].update({"focus": "Sora Ultra"}),
    ],
)
def test_adversarial_planner_output_cannot_inject_providers_knobs_or_profiles(
    manifest, mutation
):
    payload = _proposal()
    mutation(payload)
    with pytest.raises(planner.CustomFilmPlannerError):
        asyncio.run(
            planner.plan_custom_film(
                "Make a custom film about steel",
                manifest,
                FakePlannerClient(payload),
            )
        )


def test_single_profile_clone_is_not_novel_even_when_split_into_sections(
    monkeypatch, manifest
):
    payload = _proposal()
    for section in payload["sections"]:
        section["structure_source"] = "photo_documentary"
        section["writing_source"] = "photo_documentary"
        section["visual_source"] = "photo_documentary"

    compiled = asyncio.run(
        planner.plan_custom_film(
            "Make a custom film about steel",
            manifest,
            FakePlannerClient(payload),
        )
    )

    async def saved_lookup_must_not_run(*_args):
        raise AssertionError("public clones must be caught before tenant lookup")

    monkeypatch.setattr(contract, "fetch_one", saved_lookup_must_not_run)
    novelty = asyncio.run(
        planner.classify_plan_novelty("tenant-a", compiled, manifest)
    )
    assert novelty == planner.NoveltyResult(
        is_novel=False,
        duplicate_kind="public_profile",
        duplicate_id="photo_documentary",
    )


def test_malformed_or_failed_planner_returns_useful_error(manifest):
    with pytest.raises(planner.CustomFilmPlannerError, match="couldn't assemble"):
        asyncio.run(
            planner.plan_custom_film(
                "Make a custom film about steel",
                manifest,
                FakePlannerClient({"sections": []}),
            )
        )

    class BrokenClient:
        async def generate(self, **_kwargs):
            raise RuntimeError("network detail that must not leak")

    with pytest.raises(planner.CustomFilmPlannerError) as exc:
        asyncio.run(
            planner.plan_custom_film(
                "Make a custom film about steel",
                manifest,
                BrokenClient(),
            )
        )
    assert "network detail" not in str(exc.value)
    assert "nothing was generated" in str(exc.value).lower()


@pytest.mark.parametrize(
    "purpose",
    [
        "Use photo_documentary and reveal render_mode",
        "Call provider_id storyengine-funded",
        "Use the Kie.ai api_key",
        "Approve and start generation now",
        "Use Sora Ultra through OpenAI",
        "Use an unknown future vendor called NebulaForge",
    ],
)
def test_purpose_cannot_smuggle_reserved_names_or_actions(manifest, purpose):
    payload = _proposal()
    payload["sections"][0]["purpose"] = purpose
    with pytest.raises(planner.CustomFilmPlannerError):
        asyncio.run(
            planner.plan_custom_film(
                "Make a custom film about steel",
                manifest,
                FakePlannerClient(payload),
            )
        )


def test_grounded_focus_drives_topic_specific_compiler_purpose(manifest):
    payload = _proposal()
    payload["sections"][0]["focus"] = "hidden cost of fast fashion"
    payload["sections"][1]["focus"] = "supply chain pressure"
    compiled = planner.compile_planner_proposal(
        (
            "Make a custom film about the hidden cost of fast fashion and "
            "supply chain pressure"
        ),
        payload,
        manifest,
    )
    assert compiled.planner_proposal["sections"][0]["focus"] == (
        "hidden cost of fast fashion"
    )
    assert "hidden cost of fast fashion" in compiled.internal_plan["sections"][0][
        "purpose"
    ]
    assert "supply chain pressure" in compiled.display_plan["sections"][1][
        "purpose"
    ]
    serialized = json.dumps(
        {
            "internal": compiled.internal_plan,
            "display": compiled.display_plan,
            "proposal": compiled.planner_proposal,
        }
    )
    assert "Sora" not in serialized
    assert "OpenAI" not in serialized


@pytest.mark.parametrize(
    ("creator_request", "focus"),
    [
        ("Make a custom film about steel", "custom film"),
        ("Make a custom film about render_mode", "render_mode"),
        (
            "Make a custom film about animated_investigative_documentary",
            "animated_investigative_documentary",
        ),
        ("Make a custom film about steel and animate it with Sora", "Sora"),
        ("Make a custom film about steel using OpenAI images", "OpenAI"),
        (
            "Make a custom film about steel with a zero-dollar cost estimate",
            "zero-dollar cost estimate",
        ),
        (
            "Make a custom film about steel using OpenAI images",
            "steel using OpenAI images",
        ),
        (
            "Make a custom film about steel and animate it with Sora",
            "steel and animate it with Sora",
        ),
        (
            "Make a custom film about steel using NebulaForge",
            "steel using NebulaForge",
        ),
        (
            "Make a custom film about steel using nebulaforge",
            "steel using nebulaforge",
        ),
        ("Make a custom film about steel via Kie.ai", "steel via Kie.ai"),
        ("Make a custom film about steel using Veo3", "steel using Veo3"),
        (
            "Make a custom film about steel through Google Veo",
            "steel through Google Veo",
        ),
    ],
)
def test_focus_must_be_topical_content_not_planner_boilerplate_or_internal_ids(
    manifest, creator_request, focus
):
    payload = _proposal(focus)
    with pytest.raises(planner.CustomFilmPlannerError):
        planner.compile_planner_proposal(creator_request, payload, manifest)


@pytest.mark.parametrize(
    "focus",
    [
        "OpenAI partnership with Apple",
        "companies using OpenAI in classrooms",
        "artists using Sora for criticism",
        "movies powered by friendship",
        "films powered by Friendship as a theme",
        "artists using found footage",
        "healing through music",
        "learning via play",
        "history through oral tradition",
        "journeys through Ancient Rome",
        "companies using recycled steel",
        "trade via the Silk Road",
        "history of animation",
        "language barriers",
        "nuclear power generation",
    ],
)
def test_grounded_content_focus_allows_named_companies_and_ordinary_topics(
    manifest, focus
):
    compiled = planner.compile_planner_proposal(
        f"Make a custom film about {focus}",
        _proposal(focus),
        manifest,
    )
    assert compiled.planner_proposal["sections"][0]["focus"] == focus
    assert focus in compiled.display_plan["sections"][0]["purpose"]


def test_editing_section_content_preserves_stable_ordered_section_ids(manifest):
    first = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _proposal(),
        manifest,
    )
    edited_payload = _proposal()
    edited_payload["sections"][1]["visual_source"] = "photo_documentary"
    prior_ids = [
        section["section_id"] for section in first.internal_plan["sections"]
    ]
    edited = planner.compile_planner_proposal(
        "Make the second section of that steel film more human",
        edited_payload,
        manifest,
        prior_section_ids=prior_ids,
        prior_focuses=[
            section["focus"] for section in first.planner_proposal["sections"]
        ],
    )
    assert prior_ids == [
        section["section_id"] for section in edited.internal_plan["sections"]
    ]
    assert first.plan_hash != edited.plan_hash
    with pytest.raises(planner.CustomFilmPlannerError):
        planner.compile_planner_proposal(
            "Change the steel film",
            edited_payload,
            manifest,
            prior_section_ids=prior_ids[:1],
            prior_focuses=[
                section["focus"] for section in first.planner_proposal["sections"]
            ],
        )


def test_followup_may_replace_focus_with_new_exact_user_topic(manifest):
    first = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _proposal(),
        manifest,
    )
    revised_payload = _proposal()
    revised_payload["sections"][1]["focus"] = "human consequence"
    revised = planner.compile_planner_proposal(
        "Make the second section focus on the human consequence",
        revised_payload,
        manifest,
        prior_section_ids=[
            section["section_id"] for section in first.internal_plan["sections"]
        ],
        prior_focuses=[
            section["focus"] for section in first.planner_proposal["sections"]
        ],
    )
    assert revised.planner_proposal["sections"][1]["focus"] == "human consequence"
    assert "human consequence" in revised.display_plan["sections"][1]["purpose"]


def test_custom_film_intent_is_explicit_and_does_not_capture_generic_films():
    assert planner.is_custom_film_intent("Make me a custom film about steel")
    assert planner.is_custom_film_intent(
        "Mix animation and documentary styles section by section"
    )
    assert planner.is_custom_film_intent(
        "Open with still photographs, then switch to animated investigation, "
        "and finish with bilingual characters"
    )
    assert planner.is_custom_film_intent(
        "Use static photos in the opening section and simple-language character "
        "dialogue in the closing section"
    )
    assert planner.is_custom_film_intent(
        "Use a photo-documentary opening, an animated explanation, and a "
        "bilingual ending."
    )
    assert not planner.is_custom_film_intent("Make me a film about steel")
    assert not planner.is_custom_film_intent("Make a photo documentary")
    assert not planner.is_custom_film_intent("What is a custom film?")
    assert not planner.is_custom_film_intent("I don't want a custom film")
    assert not planner.is_custom_film_intent(
        "I made a custom film yesterday; explain it"
    )
    assert not planner.is_custom_film_intent(
        "Start with a mystery, then reveal the answer"
    )
    assert not planner.is_custom_film_intent(
        "Open with photographs of the city and then explain its history"
    )
    assert not planner.is_custom_film_intent(
        "Make an animated film with character dialogue"
    )
    assert planner.is_custom_film_exit_intent(
        "Cancel Custom Film; make a normal Photo Documentary instead"
    )
    assert planner.is_custom_film_exit_intent(
        "I don't want to continue this custom film"
    )
    for shorthand in ("cancel", "never mind", "stop", "exit", "go back to Producer"):
        assert planner.is_custom_film_exit_intent(shorthand)
    assert planner.is_custom_film_ordinary_video_request(
        "Cancel Custom Film; make a normal Photo Documentary instead"
    )
    assert not planner.is_custom_film_ordinary_video_request("never mind")
    assert not planner.is_custom_film_exit_intent(
        "Keep the Custom Film but make the ending calmer"
    )


def test_chat_custom_film_handler_persists_distinct_pending_plan_without_approval(
    monkeypatch, manifest
):
    compiled = asyncio.run(
        planner.plan_custom_film(
            "Make a custom film about steel",
            manifest,
            FakePlannerClient(_proposal()),
        )
    )
    persisted = {}

    async def fake_resolve(_tenant_id):
        return object()

    async def fake_load_manifest():
        return manifest

    async def fake_plan(*_args, **_kwargs):
        return compiled

    async def fake_novelty(*_args, **_kwargs):
        return planner.NoveltyResult(is_novel=True)

    async def fake_persist(conversation_id, tenant_id, transcript, state, phase):
        persisted.update(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            transcript=copy.deepcopy(transcript),
            state=copy.deepcopy(state),
            phase=phase,
        )

    monkeypatch.setattr(chat_route, "_resolve_producer_client", fake_resolve)
    monkeypatch.setattr(planner, "load_capability_manifest", fake_load_manifest)
    monkeypatch.setattr(planner, "plan_custom_film", fake_plan)
    monkeypatch.setattr(planner, "classify_plan_novelty", fake_novelty)
    monkeypatch.setattr(chat_route, "_persist", fake_persist)

    state = {
        "last_spec": {"legacy": "must be cleared"},
        "pending_action": {"verb": "build", "paid": True},
        "selections": {"production_style": "photo_documentary"},
        "pending_style_draft": {"name": "stale"},
        "pending_quality_rules_draft": {"rules": ["stale"]},
        "pending_dna_digest": True,
        "pending_reference_url": "https://example.invalid/stale",
        "pending_assets": ["stale-asset"],
    }
    response = asyncio.run(
        chat_route._handle_custom_film_plan(
            "conversation-a",
            "tenant-a",
            [],
            state,
            "Make a custom film about steel",
        )
    )

    assert response.ready_to_create is False
    assert response.phase == "plan"
    assert response.plan is None
    assert "last_spec" not in persisted["state"]
    assert "pending_action" not in persisted["state"]
    assert "selections" not in persisted["state"]
    for stale_key in (
        "pending_style_draft",
        "pending_quality_rules_draft",
        "pending_dna_digest",
        "pending_reference_url",
        "pending_assets",
    ):
        assert stale_key not in persisted["state"]
    pending = persisted["state"]["pending_custom_film_plan"]
    from custom_film_contract import approval_binding_hash, plan_hash
    assert pending["plan_hash"] == plan_hash(compiled.internal_plan)
    assert pending["approval_hash"] == approval_binding_hash(
        pending["plan_hash"], pending["quote_inputs"]
    )
    revision_input = contract.revision_input_from_normalized_plan(
        pending["internal_plan"], manifest
    )
    assert contract.normalize_plan(revision_input, manifest) == pending["internal_plan"]
    assert pending["status"] == "awaiting_approval"
    assert pending["internal_plan"] == compiled.internal_plan
    assert pending["display_plan"] == compiled.display_plan
    assert pending["planner_proposal"] == compiled.planner_proposal
    assert pending["novelty"] == {"is_novel": True}
    assert "plan" not in json.loads(persisted["transcript"][-1]["content"])
    assert "1. **Opening**" in response.assistant_text
    assert "BYOK estimate" in response.assistant_text
    assert response.cards and response.cards[0]["id"] == "custom_film_approval"
    blueprint = response.cards[0]
    assert blueprint["label"] == "Your Custom Film production blueprint"
    assert len(blueprint["custom_film_sections"]) == 2
    assert blueprint["custom_film_totals"] == {
        "duration_seconds": 300,
        "still_images": sum(
            row["still_images"] for row in pending["quote_inputs"]["sections"]
        ),
        "animation_clips": sum(
            row["animation_clips"] for row in pending["quote_inputs"]["sections"]
        ),
        "voice_tracks": sum(
            row["voice_tracks"] for row in pending["quote_inputs"]["sections"]
        ),
        "estimated_cost": pending["quote_inputs"]["totals"]["estimated_cost"],
        "max_spend": pending["quote_inputs"]["max_spend"],
        "headroom": 0.0,
    }
    blueprint_text = json.dumps(blueprint).lower()
    for hidden_internal in (
        "provider_id",
        "model_id",
        "render_mode",
        "photo_documentary",
        "animated_investigative_documentary",
    ):
        assert hidden_internal not in blueprint_text
    assert blueprint["options"][0]["value"] == "yes"
    assert "paid production" in blueprint["options"][0]["label"].lower()
    assert "any edit clears approval" in blueprint["approval_notice"].lower()
    assert "render_mode" not in response.assistant_text
    assert "photo_documentary" not in response.assistant_text


def test_custom_film_blueprint_blocks_approval_when_cap_is_below_estimate():
    quote = {
        "sections": [
            {
                "section_id": "section-a",
                "order_index": 0,
                "duration_seconds": 60,
                "still_images": 3,
                "animation_clips": 3,
                "voice_tracks": 1,
                "estimated_cost": 0.72,
            }
        ],
        "totals": {
            "duration_seconds": 60,
            "still_images": 3,
            "animation_clips": 3,
            "voice_tracks": 1,
            "estimated_cost": 0.72,
        },
        "max_spend": 0.50,
    }
    display_plan = {
        "sections": [
            {
                "order": 1,
                "role": "Opening",
                "purpose": "Open the story",
                "feel": "Focused",
                "share_percent": 100,
            }
        ]
    }
    assert chat_route._custom_film_approval_cards(quote, display_plan) is None
    quote["max_spend"] = 0.72
    cards = chat_route._custom_film_approval_cards(quote, display_plan)
    assert cards and cards[0]["id"] == "custom_film_approval"
    assert cards[0]["options"][0]["label"].endswith("$0.72")
    assert cards[0]["finishing_engine"] == "ffmpeg"
    assert "ffmpeg" in cards[0]["finishing_notice"].lower()


def test_custom_film_blueprint_locks_remotion_only_for_exact_showcase_contract():
    durations = (45, 105, 90, 60)
    roles = ("Opening", "Evidence", "Case Study", "Explanation")
    quote = {
        "sections": [
            {
                "section_id": f"section-{index}",
                "order_index": index,
                "duration_seconds": duration,
                "still_images": 1,
                "animation_clips": 1,
                "voice_tracks": 1,
                "estimated_cost": 1.0,
            }
            for index, duration in enumerate(durations)
        ],
        "totals": {
            "duration_seconds": 300,
            "still_images": 4,
            "animation_clips": 4,
            "voice_tracks": 4,
            "estimated_cost": 4.0,
        },
        "max_spend": 15.0,
    }
    display_plan = {
        "sections": [
            {
                "order": index + 1,
                "role": role,
                "purpose": f"Purpose {index + 1}",
                "feel": "Cinematic",
                "share_percent": duration / 3,
            }
            for index, (role, duration) in enumerate(zip(roles, durations))
        ]
    }

    unrelated = chat_route._custom_film_approval_card(quote, display_plan)
    assert unrelated["finishing_engine"] == "ffmpeg"

    frame = 0
    recipes = []
    for index, duration in enumerate(durations):
        section_frames = duration * 24
        recipes.append(
            orchestration.resolve_layered_recipe(
                {
                    "id": f"section-{index}:beat:0",
                    "section_index": index,
                    "from": frame,
                    "to": frame + section_frames - 1,
                    "signals": {
                        "media_kind": "video",
                        "dialogue": False,
                        "captions": False,
                        "intents": ["cinematic"],
                        "energy": 2,
                        "handoff": "pulse",
                    },
                }
            )
        )
        frame += section_frames
    semantic_input = {
        "capability_catalog_version": orchestration.CAPABILITY_CATALOG_VERSION,
        "compatibility_version": "approval-card-test",
        "total_duration_seconds": 300,
        "sections": [],
    }
    resolved = {"fps": 24, "total_frames": 7200, "recipes": recipes}
    orchestration_body = {
        "contract_version": orchestration.ORCHESTRATION_CONTRACT_VERSION,
        "decision_rules_version": orchestration.DECISION_RULES_VERSION,
        "semantic_input": semantic_input,
        "semantic_input_hash": contract.canonical_hash(semantic_input),
        "approved_beat_plan": resolved,
        "approved_beat_plan_hash": contract.canonical_hash(resolved),
        "resolved_plan": resolved,
        "resolved_plan_hash": contract.canonical_hash(resolved),
        "reference_compatible": False,
        "story_identity": contract.canonical_hash(semantic_input),
        "signals_hash": contract.canonical_hash(
            [recipe["signals"] for recipe in recipes]
        ),
        "recipe_hash": contract.canonical_hash(recipes),
        "reference_plan_version": None,
    }
    quote["orchestration"] = {
        **orchestration_body,
        "contract_hash": contract.canonical_hash(orchestration_body),
    }
    quote["finishing_canvas"] = {
        **copy.deepcopy(chat_route._CUSTOM_FILM_REMOTION_FINISHING_CANVAS),
        "orchestration_contract_hash": quote["orchestration"]["contract_hash"],
        "story_identity": quote["orchestration"]["story_identity"],
        "recipe_hash": quote["orchestration"]["recipe_hash"],
    }
    card = chat_route._custom_film_approval_card(quote, display_plan)
    assert card["finishing_engine"] == "remotion"
    assert "layered remotion orchestration is locked" in card["finishing_notice"].lower()
    for treatment in (
        "approved media",
        "motion",
        "caption",
        "camera",
        "transition",
        "audio",
        "creator-visible beat",
    ):
        assert treatment in card["finishing_notice"].lower()

    unbound_quote = copy.deepcopy(quote)
    unbound_quote.pop("finishing_canvas")
    unbound = chat_route._custom_film_approval_card(
        unbound_quote,
        display_plan,
    )
    assert unbound["finishing_engine"] == "ffmpeg"

    quote["sections"][1]["duration_seconds"] = 104
    quote["totals"]["duration_seconds"] = 299
    fallback = chat_route._custom_film_approval_card(quote, display_plan)
    assert fallback["finishing_engine"] == "ffmpeg"
    assert "creator-visible beat recipes" in fallback["finishing_notice"]


def test_chat_intent_routes_before_normal_producer_and_cannot_dispatch(monkeypatch):
    calls = []

    async def fake_create(_tenant_id):
        return {
            "id": "conversation-a",
            "transcript": [],
            "state": {
                "last_spec": {"title": "stale legacy plan"},
                "pending_action": {"verb": "build"},
            },
            "video_id": None,
        }

    async def fake_hydrate(*_args):
        return None

    async def fake_handler(*args):
        calls.append(args)
        return chat_route.ChatTurnResponse(
            conversation_id="conversation-a",
            assistant_text="safe plan",
            plan=None,
            ready_to_create=False,
            phase="plan",
        )

    def forbidden_producer(*_args, **_kwargs):
        raise AssertionError("normal producer must not run for explicit Custom Film")

    async def forbidden_approve(*_args, **_kwargs):
        raise AssertionError("planning must not reach approval or dispatch")

    monkeypatch.setattr(chat_route, "_create_conversation", fake_create)
    monkeypatch.setattr(chat_route, "_hydrate_creator_brief", fake_hydrate)
    monkeypatch.setattr(chat_route, "_handle_custom_film_plan", fake_handler)
    monkeypatch.setattr(chat_route, "call_producer", forbidden_producer)
    monkeypatch.setattr(chat_route, "_handle_approve", forbidden_approve)

    response = asyncio.run(
        chat_route.chat_turn(
            chat_route.ChatTurnRequest(
                message="Mix documentary and animation styles section by section",
                approve=True,
            ),
            background_tasks=object(),
            tenant_id="tenant-a",
        )
    )
    assert response.plan is None
    assert response.ready_to_create is False
    assert len(calls) == 1


def test_chat_custom_film_no_key_stops_usefully_before_planning(monkeypatch):
    persisted = {}

    async def no_client(_tenant_id):
        return None

    async def fake_persist(_conversation_id, _tenant_id, transcript, state, phase):
        persisted.update(transcript=transcript, state=state, phase=phase)

    async def forbidden_planner(*_args, **_kwargs):
        raise AssertionError("keyless Custom Film must not invoke the planner")

    monkeypatch.setattr(chat_route, "_resolve_producer_client", no_client)
    monkeypatch.setattr(planner, "plan_custom_film", forbidden_planner)
    monkeypatch.setattr(chat_route, "_persist", fake_persist)

    response = asyncio.run(
        chat_route._handle_custom_film_plan(
            "conversation-a",
            "tenant-a",
            [],
            {
                "last_spec": {"legacy": "must be quarantined"},
                "pending_action": {"verb": "build"},
            },
            "Make a custom film about steel",
        )
    )
    assert response.ready_to_create is False
    assert response.plan is None
    assert "your own" in response.assistant_text.lower()
    assert "nothing has been generated or charged" in response.assistant_text.lower()
    assert "pending_custom_film_plan" not in persisted["state"]
    assert "last_spec" not in persisted["state"]
    assert "pending_action" not in persisted["state"]


def test_custom_mode_approve_and_selection_taps_are_planning_only(
    monkeypatch, manifest
):
    compiled = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _proposal(),
        manifest,
    )
    stored = {}

    async def fake_load(_conversation_id, _tenant_id):
        state = _pending_state(compiled)
        state.update(
            {
                "last_spec": {"title": "stale paid plan"},
                "pending_action": {"verb": "build"},
                "pending_style_draft": {"name": "stale"},
                "pending_quality_rules_draft": {"rules": ["stale"]},
                "pending_dna_digest": True,
                "pending_reference_url": "https://example.invalid/stale",
                "pending_assets": ["stale-asset"],
                "selections": {"confirm_action": "yes"},
            }
        )
        return {
            "id": "conversation-a",
            "transcript": [],
            "state": state,
            "video_id": None,
        }

    async def no_op(*_args, **_kwargs):
        return None

    async def fake_persist(_cid, _tid, _transcript, state, phase):
        stored.update(state=copy.deepcopy(state), phase=phase)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("selection-only Custom Film turn reached an action seam")

    monkeypatch.setattr(chat_route, "_load_conversation", fake_load)
    monkeypatch.setattr(chat_route, "_hydrate_creator_brief", no_op)
    monkeypatch.setattr(chat_route, "_persist", fake_persist)
    monkeypatch.setattr(chat_route, "_handle_approve", forbidden)
    monkeypatch.setattr(chat_route, "_handle_style_draft_confirm", forbidden)
    monkeypatch.setattr(chat_route, "_handle_quality_rules_draft_confirm", forbidden)
    monkeypatch.setattr(chat_route, "_handle_dna_digest_action", forbidden)
    monkeypatch.setattr(chat_route, "_resolve_producer_client", forbidden)
    monkeypatch.setattr(chat_route, "_estimate_plan_cost", forbidden)
    monkeypatch.setattr(chat_route.generation_claims, "acquire", forbidden)

    response = asyncio.run(
        chat_route.chat_turn(
            chat_route.ChatTurnRequest(
                conversation_id="conversation-a",
                approve=True,
                selections={
                    "confirm_action": "yes",
                    "style_draft": "yes",
                    "quality_rules_draft": "yes",
                    "channel_dna_digest": "confirm_pattern",
                },
            ),
            background_tasks=object(),
            tenant_id="tenant-a",
        )
    )
    assert response.plan is None
    assert response.ready_to_create is False
    assert response.video_id is None
    assert "unapproved plan" in response.assistant_text.lower()
    assert stored["state"]["pending_custom_film_plan"]["plan_hash"] == (
        compiled.plan_hash
    )
    for stale_key in chat_route._CUSTOM_FILM_STALE_STATE_KEYS:
        assert stale_key not in stored["state"]


def test_immediate_approve_after_custom_plan_cannot_consume_stale_state(
    monkeypatch, manifest
):
    compiled = asyncio.run(
        planner.plan_custom_film(
            "Make a custom film about steel",
            manifest,
            FakePlannerClient(_proposal()),
        )
    )
    stored = {}

    async def fake_resolve(_tenant_id):
        return object()

    async def fake_load_manifest():
        return manifest

    async def fake_plan(*_args, **_kwargs):
        return compiled

    async def fake_novelty(*_args, **_kwargs):
        return planner.NoveltyResult(is_novel=True)

    async def capture_persist(_cid, _tid, transcript, state, phase, **_kwargs):
        stored.update(
            transcript=copy.deepcopy(transcript),
            state=copy.deepcopy(state),
            phase=phase,
        )

    monkeypatch.setattr(chat_route, "_resolve_producer_client", fake_resolve)
    monkeypatch.setattr(planner, "load_capability_manifest", fake_load_manifest)
    monkeypatch.setattr(planner, "plan_custom_film", fake_plan)
    monkeypatch.setattr(planner, "classify_plan_novelty", fake_novelty)
    monkeypatch.setattr(chat_route, "_persist", capture_persist)

    asyncio.run(
        chat_route._handle_custom_film_plan(
            "conversation-a",
            "tenant-a",
            [],
            {
                "last_spec": {"title": "old paid video"},
                "pending_action": {"verb": "build"},
            },
            "Make a custom film about steel",
        )
    )
    assert "last_spec" not in stored["state"]
    assert "pending_action" not in stored["state"]

    async def fake_load(_conversation_id, _tenant_id):
        return {
            "id": "conversation-a",
            "transcript": stored["transcript"],
            "state": stored["state"],
            "video_id": None,
        }

    async def fake_hydrate(*_args):
        return None

    async def no_ideas(*_args, **_kwargs):
        return None

    async def has_competitors(*_args, **_kwargs):
        return [{}]

    async def forbidden_async(*_args, **_kwargs):
        raise AssertionError("approval/generation seam must not run")

    def forbidden_sync(*_args, **_kwargs):
        raise AssertionError("estimate/autobuild seam must not run")

    class ForbiddenBackgroundTasks:
        def add_task(self, *_args, **_kwargs):
            raise AssertionError("background generation must not be scheduled")

    monkeypatch.setattr(chat_route, "_load_conversation", fake_load)
    monkeypatch.setattr(chat_route, "_hydrate_creator_brief", fake_hydrate)
    monkeypatch.setattr(chat_route, "_generate_competitor_ideas", no_ideas)
    monkeypatch.setattr(chat_route, "_recent_competitor_rows", has_competitors)
    monkeypatch.setattr(chat_route, "_handle_approve", forbidden_async)
    monkeypatch.setattr(chat_route.generation_claims, "acquire", forbidden_async)
    monkeypatch.setattr(chat_route, "_estimate_plan_cost", forbidden_async)
    monkeypatch.setattr(chat_route, "_make_autobuild_step", forbidden_sync)

    response = asyncio.run(
        chat_route.chat_turn(
            chat_route.ChatTurnRequest(
                conversation_id="conversation-a",
                approve=True,
            ),
            background_tasks=ForbiddenBackgroundTasks(),
            tenant_id="tenant-a",
        )
    )
    assert response.ready_to_create is False
    assert response.video_id is None
    assert response.phase == "plan"


def _pending_state(compiled):
    return {
        "mode": "custom_film",
        "pending_custom_film_plan": {
            "internal_plan": copy.deepcopy(compiled.internal_plan),
            "display_plan": copy.deepcopy(compiled.display_plan),
            "planner_proposal": copy.deepcopy(compiled.planner_proposal),
            "plan_hash": compiled.plan_hash,
            "recipe_signature": compiled.recipe_signature,
            "novelty": {"is_novel": True},
            "status": "planned_unapproved",
        },
    }


def test_custom_followup_uses_prior_proposal_and_reuses_section_ids(
    monkeypatch, manifest
):
    first = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _proposal(),
        manifest,
    )
    revised_payload = _proposal()
    revised_payload["sections"][1]["visual_source"] = "photo_documentary"
    client = FakePlannerClient(revised_payload)
    persisted = {}

    async def fake_resolve(_tenant_id):
        return client

    async def fake_load_manifest():
        return manifest

    async def fake_novelty(*_args, **_kwargs):
        return planner.NoveltyResult(is_novel=True)

    async def fake_persist(_cid, _tid, transcript, state, phase):
        persisted.update(
            transcript=copy.deepcopy(transcript),
            state=copy.deepcopy(state),
            phase=phase,
        )

    monkeypatch.setattr(chat_route, "_resolve_producer_client", fake_resolve)
    monkeypatch.setattr(planner, "load_capability_manifest", fake_load_manifest)
    monkeypatch.setattr(planner, "classify_plan_novelty", fake_novelty)
    monkeypatch.setattr(chat_route, "_persist", fake_persist)

    response = asyncio.run(
        chat_route._handle_custom_film_plan(
            "conversation-a",
            "tenant-a",
            [],
            _pending_state(first),
            "Make the second section more visual",
        )
    )
    assert response.plan is None
    assert response.ready_to_create is False
    assert "CURRENT CONSTRAINED PLAN TO REVISE" in client.calls[0]["prompt"]
    assert "photo_documentary" in client.calls[0]["prompt"]
    assert "Preserve its section count and order exactly" in client.calls[0]["prompt"]
    assert [
        section["section_id"] for section in persisted["state"][
            "pending_custom_film_plan"
        ]["internal_plan"]["sections"]
    ] == [
        section["section_id"] for section in first.internal_plan["sections"]
    ]


def test_failed_custom_followup_keeps_last_valid_unapproved_plan(
    monkeypatch, manifest
):
    first = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _proposal(),
        manifest,
    )
    original_pending = _pending_state(first)["pending_custom_film_plan"]
    persisted = {}

    async def fake_resolve(_tenant_id):
        return FakePlannerClient({"sections": []})

    async def fake_load_manifest():
        return manifest

    async def fake_persist(_cid, _tid, _transcript, state, phase):
        persisted.update(state=copy.deepcopy(state), phase=phase)

    monkeypatch.setattr(chat_route, "_resolve_producer_client", fake_resolve)
    monkeypatch.setattr(planner, "load_capability_manifest", fake_load_manifest)
    monkeypatch.setattr(chat_route, "_persist", fake_persist)

    state = _pending_state(first)
    state["last_spec"] = {"title": "stale paid plan"}
    state["pending_action"] = {"verb": "build"}
    response = asyncio.run(
        chat_route._handle_custom_film_plan(
            "conversation-a",
            "tenant-a",
            [],
            state,
            "Make the second section more visual",
        )
    )
    assert response.plan is None
    assert response.ready_to_create is False
    assert response.phase == "plan"
    assert "previous unapproved plan is unchanged" in response.assistant_text.lower()
    assert persisted["state"]["pending_custom_film_plan"] == original_pending
    assert "last_spec" not in persisted["state"]
    assert "pending_action" not in persisted["state"]


def test_section_count_followup_is_held_for_m2_3_without_client_or_state_loss(
    monkeypatch, manifest
):
    first = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _proposal(),
        manifest,
    )
    state = _pending_state(first)
    original_pending = copy.deepcopy(state["pending_custom_film_plan"])
    state["last_spec"] = {"title": "stale paid plan"}
    state["pending_action"] = {"verb": "build"}
    persisted = {}

    async def forbidden_client(*_args, **_kwargs):
        raise AssertionError("structural edit must stop before planner/key resolution")

    async def fake_persist(_cid, _tid, _transcript, saved_state, phase):
        persisted.update(state=copy.deepcopy(saved_state), phase=phase)

    monkeypatch.setattr(chat_route, "_resolve_producer_client", forbidden_client)
    monkeypatch.setattr(chat_route, "_persist", fake_persist)

    response = asyncio.run(
        chat_route._handle_custom_film_plan(
            "conversation-a",
            "tenant-a",
            [],
            state,
            "Add a new closing section",
        )
    )
    assert response.plan is None
    assert response.ready_to_create is False
    assert response.phase == "plan"
    assert "adding, removing, or reordering" in response.assistant_text.lower()
    assert persisted["state"]["pending_custom_film_plan"] == original_pending
    assert "last_spec" not in persisted["state"]
    assert "pending_action" not in persisted["state"]


def test_custom_mode_exit_clears_custom_state_and_reaches_ordinary_producer(
    monkeypatch
):
    captured = {}

    async def fake_load(_conversation_id, _tenant_id):
        return {
            "id": "conversation-a",
            "transcript": [],
            "state": {
                "mode": "custom_film",
                "pending_custom_film_plan": {"status": "planned_unapproved"},
                "last_spec": {"title": "stale paid plan"},
                "pending_action": {"verb": "build"},
                "selections": {"production_style": "photo_documentary"},
            },
            "video_id": None,
        }

    async def no_op(*_args, **_kwargs):
        return None

    async def empty_brief(*_args, **_kwargs):
        return ""

    async def fake_resolve(_tenant_id):
        return object()

    def fake_call_producer(transcript, _system_prompt, **_kwargs):
        captured["producer_transcript"] = copy.deepcopy(transcript)
        return {
            "assistant_text": "I switched to an ordinary Photo Documentary plan.",
            "phase": "asking",
        }

    async def fake_apply(data, *_args, **_kwargs):
        return data["assistant_text"]

    async def fake_persist(_cid, _tid, _transcript, state, phase):
        captured.update(state=copy.deepcopy(state), phase=phase)

    async def forbidden_approve(*_args, **_kwargs):
        raise AssertionError("mode exit must not approve or dispatch")

    monkeypatch.setattr(chat_route, "_load_conversation", fake_load)
    monkeypatch.setattr(chat_route, "_hydrate_creator_brief", no_op)
    monkeypatch.setattr(
        chat_route,
        "_handle_cold_start_competitor_followup",
        no_op,
    )
    monkeypatch.setattr(chat_route, "_resolve_producer_client", fake_resolve)
    monkeypatch.setattr(chat_route, "call_producer", fake_call_producer)
    monkeypatch.setattr(chat_route, "_apply_and_merge_profile_ops", fake_apply)
    monkeypatch.setattr(chat_route, "_persist", fake_persist)
    monkeypatch.setattr(chat_route, "_handle_approve", forbidden_approve)
    for name in (
        "_identity_pool_brief",
        "_modeled_runtime_hint",
        "_channel_intel_brief",
        "_competitor_winners_brief",
        "_loop_brief",
        "_reference_brief",
        "_profile_state_brief",
        "_format_brief",
        "_script_template_brief",
        "_style_presets_brief",
        "_visual_styles_brief",
        "_assets_brief",
        "_preferences_brief",
    ):
        monkeypatch.setattr(chat_route, name, empty_brief)

    response = asyncio.run(
        chat_route.chat_turn(
            chat_route.ChatTurnRequest(
                conversation_id="conversation-a",
                message=(
                    "Cancel Custom Film; make a normal Photo Documentary instead"
                ),
                approve=True,
            ),
            background_tasks=object(),
            tenant_id="tenant-a",
        )
    )
    assert response.ready_to_create is False
    assert response.video_id is None
    assert "ordinary Photo Documentary" in response.assistant_text
    assert "Cancel Custom Film" in captured["producer_transcript"][-1]["content"]
    assert captured["state"]["mode"] == "producer"
    assert "pending_custom_film_plan" not in captured["state"]
    assert "last_spec" not in captured["state"]
    assert "pending_action" not in captured["state"]
    assert "selections" not in captured["state"]


def test_bare_custom_cancel_clears_state_without_invoking_any_planner(
    monkeypatch, manifest
):
    compiled = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _proposal(),
        manifest,
    )
    captured = {}

    async def fake_load(_conversation_id, _tenant_id):
        state = _pending_state(compiled)
        state.update(
            {
                "last_spec": {"title": "stale"},
                "pending_action": {"verb": "build"},
                "pending_style_draft": {"name": "stale"},
                "pending_quality_rules_draft": {"rules": ["stale"]},
                "pending_dna_digest": True,
                "pending_reference_url": "stale",
                "pending_assets": ["stale"],
                "selections": {"confirm_action": "yes"},
            }
        )
        return {
            "id": "conversation-a",
            "transcript": [],
            "state": state,
            "video_id": None,
        }

    async def no_op(*_args, **_kwargs):
        return None

    async def fake_persist(_cid, _tid, _transcript, state, phase):
        captured.update(state=copy.deepcopy(state), phase=phase)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("bare cancel must not invoke a planner or action")

    monkeypatch.setattr(chat_route, "_load_conversation", fake_load)
    monkeypatch.setattr(chat_route, "_hydrate_creator_brief", no_op)
    monkeypatch.setattr(chat_route, "_persist", fake_persist)
    monkeypatch.setattr(chat_route, "_resolve_producer_client", forbidden)
    monkeypatch.setattr(chat_route, "_handle_approve", forbidden)
    monkeypatch.setattr(chat_route.generation_claims, "acquire", forbidden)

    response = asyncio.run(
        chat_route.chat_turn(
            chat_route.ChatTurnRequest(
                conversation_id="conversation-a",
                message="never mind",
                approve=True,
            ),
            background_tasks=object(),
            tenant_id="tenant-a",
        )
    )
    assert response.plan is None
    assert response.ready_to_create is False
    assert response.phase == "asking"
    assert "cancelled" in response.assistant_text.lower()
    assert captured["state"]["mode"] == "producer"
    assert "pending_custom_film_plan" not in captured["state"]
    for stale_key in chat_route._CUSTOM_FILM_STALE_STATE_KEYS:
        assert stale_key not in captured["state"]


def test_saved_recipe_chat_commands_are_small_and_deterministic():
    parse = chat_route._custom_film_recipe_command
    assert parse("Show my saved Custom Film recipes") == ("list", ())
    assert parse("Show my saved recipes") is None
    assert parse(
        'Save this recipe as "Power Mix"', has_save_candidate=True
    ) == ("save", ("Power Mix",))
    assert parse('Save this Custom Film recipe as "Power Mix"') == (
        "save",
        ("Power Mix",),
    )
    assert parse('Rename recipe "Power Mix" to "Evidence Mix"') == (
        "rename",
        ("Power Mix", "Evidence Mix"),
    )
    assert parse('Archive recipe "Evidence Mix"') == (
        "archive",
        ("Evidence Mix",),
    )
    assert parse(
        'Reuse saved recipe "Evidence Mix" for a film about clean steel'
    ) == (
        "reuse",
        ("Evidence Mix", "a film about clean steel"),
    )
    assert parse("Save this recipe", has_save_candidate=True) == ("save", ())
    assert parse("Save this recipe") is None
    assert parse("Make a normal video about recipes") is None
    for ordinary_film_request in (
        "Make a Custom Film about how to save this species",
        "Create a documentary about an archive that preserves recipes",
        "Make a film about companies that rename products",
        "Show how saved recipes changed family cooking",
        "A video about when creators use recipe metaphors",
        "rename this video to Launch Cut",
        "archive this project",
        "save it",
        "save this draft",
        "use the recipe for the intro",
    ):
        assert parse(ordinary_film_request) is None


@pytest.mark.parametrize(
    "message",
    (
        "rename this video",
        "archive this project",
        "save it",
        "save this draft",
        "use the recipe for the intro",
    ),
)
def test_ordinary_recipe_words_still_reach_legacy_copilot(monkeypatch, message):
    async def fake_load(*_args):
        return {
            "id": "conversation-a",
            "video_id": "video-a",
            "transcript": [],
            "state": {},
            "phase": "created",
        }

    async def no_op(*_args, **_kwargs):
        return None

    async def fake_copilot(
        _body, conversation_id, _tenant_id, _transcript, _state, video_id, _bg
    ):
        return chat_route.ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=f"legacy:{message}",
            video_id=video_id,
            phase="created",
        )

    monkeypatch.setattr(chat_route, "_load_conversation", fake_load)
    monkeypatch.setattr(chat_route, "_hydrate_creator_brief", no_op)
    monkeypatch.setattr(chat_route, "_handle_copilot", fake_copilot)
    response = asyncio.run(
        chat_route.chat_turn(
            chat_route.ChatTurnRequest(
                conversation_id="conversation-a",
                message=message,
            ),
            background_tasks=object(),
            tenant_id="tenant-a",
        )
    )
    assert response.assistant_text == f"legacy:{message}"


@pytest.mark.asyncio
async def test_reuse_planner_only_grounds_focus_and_reapplies_exact_recipe(manifest):
    compiled = planner.compile_planner_proposal(
        "Make a Custom Film about steel",
        _proposal(),
        manifest,
        total_duration_seconds=300,
    )
    prompts = []

    class Client:
        async def generate(self, **kwargs):
            prompts.append(kwargs)
            return json.dumps(
                {"sections": [{"focus": "clean steel"}, {"focus": "clean steel"}]}
            )

    reused = await planner.plan_custom_film_from_recipe(
        "Make a film about clean steel",
        compiled.normalized_recipe,
        manifest,
        Client(),
        total_duration_seconds=420,
    )
    assert reused.recipe_signature == compiled.recipe_signature
    assert reused.normalized_recipe == compiled.normalized_recipe
    assert [s["duration_units"] for s in reused.internal_plan["sections"]] == [
        s["duration_units"] for s in compiled.normalized_recipe["sections"]
    ]
    assert all("clean steel" in s["purpose"] for s in reused.internal_plan["sections"])
    prompt = prompts[0]["prompt"]
    assert "fresh topic" in prompt
    assert "provider_id" not in prompt
    assert "duration_weight" not in planner.ReuseFocusProposal.model_json_schema()[
        "$defs"
    ]["ReuseFocusSection"]["properties"]


@pytest.mark.asyncio
async def test_reuse_rejects_wrong_focus_count_and_never_inherits_approval(manifest):
    compiled = planner.compile_planner_proposal(
        "Make a Custom Film about steel", _proposal(), manifest
    )

    class Client:
        async def generate(self, **_kwargs):
            return '{"sections":[{"focus":"new steel"}]}'

    with pytest.raises(planner.CustomFilmPlannerError):
        await planner.plan_custom_film_from_recipe(
            "A film about new steel",
            compiled.normalized_recipe,
            manifest,
            Client(),
        )
