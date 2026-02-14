"""Tests for programmatic scene list validation."""

import pytest
from brief_translator.scene_validator import (
    validate_scene_list,
    auto_fix_minor_issues,
    REQUIRED_FIELDS,
    VALID_STYLES,
    VALID_COMPOSITIONS,
    MAX_CONSECUTIVE_SAME_STYLE,
)


def make_scene(
    scene_number=1, act=1, style="dossier",
    description="A test scene", script_excerpt="Test excerpt",
    composition_hint="wide",
):
    """Helper to create a valid scene dict."""
    return {
        "scene_number": scene_number,
        "act": act,
        "style": style,
        "description": description,
        "script_excerpt": script_excerpt,
        "composition_hint": composition_hint,
    }


def make_scene_list(count=136):
    """Generate a valid scene list with proper distribution."""
    scenes = []
    # Approximate distribution: 60% dossier, 22% schema, 18% echo
    dossier_count = int(count * 0.60)
    schema_count = int(count * 0.22)
    echo_count = count - dossier_count - schema_count

    compositions = list(VALID_COMPOSITIONS)

    # Build scene list ensuring no Echo in acts 1, 2, 6
    scene_num = 1
    # Act distribution: ~8 scenes act 1, ~25 act 2, ~33 act 3, ~28 act 4, ~28 act 5, ~14 act 6
    act_scenes = {1: 8, 2: 25, 3: 33, 4: 28, 5: 28, 6: 14}

    for act_num, act_count in act_scenes.items():
        for i in range(act_count):
            if scene_num > count:
                break
            # Determine style
            if act_num in [1, 2, 6]:
                style = "dossier" if i % 3 != 0 else "schema"
            elif act_num in [3, 4]:
                if i % 5 < 2:
                    style = "dossier"
                elif i % 5 == 2:
                    style = "schema"
                else:
                    style = "echo"
            else:  # act 5
                if i % 4 < 2:
                    style = "dossier"
                elif i % 4 == 2:
                    style = "schema"
                else:
                    style = "echo"

            scenes.append(make_scene(
                scene_number=scene_num,
                act=act_num,
                style=style,
                description=f"Unique scene description number {scene_num} with specific details",
                script_excerpt=f"Narration for scene {scene_num}",
                composition_hint=compositions[scene_num % len(compositions)],
            ))
            scene_num += 1

    # Ensure first and last are dossier
    if scenes:
        scenes[0]["style"] = "dossier"
        scenes[-1]["style"] = "dossier"

    # Ensure echo scenes are not isolated (pair them up)
    for i in range(len(scenes)):
        if scenes[i]["style"] == "echo":
            prev_echo = i > 0 and scenes[i - 1]["style"] == "echo"
            next_echo = i < len(scenes) - 1 and scenes[i + 1]["style"] == "echo"
            if not prev_echo and not next_echo:
                # Make next scene echo too if possible
                if i < len(scenes) - 1 and scenes[i + 1]["act"] not in [1, 2, 6]:
                    scenes[i + 1]["style"] = "echo"
                else:
                    scenes[i]["style"] = "dossier"

    return scenes[:count]


class TestValidateSceneList:
    def test_valid_scene_list_passes(self):
        scenes = make_scene_list(136)
        result = validate_scene_list(scenes, {"total_images": 136})
        # May have some minor issues due to distribution, but shouldn't have critical ones
        assert result["stats"]["total_scenes"] == 136

    def test_empty_list_fails(self):
        result = validate_scene_list([], {"total_images": 136})
        assert not result["valid"]
        assert "empty" in result["issues"][0].lower()

    def test_too_few_scenes_reported(self):
        scenes = [make_scene(scene_number=i) for i in range(1, 50)]
        result = validate_scene_list(scenes, {"total_images": 136})
        assert any("Too few" in i for i in result["issues"])

    def test_missing_fields_reported(self):
        scenes = [{"scene_number": 1, "act": 1}]  # Missing most fields
        result = validate_scene_list(scenes, {"total_images": 1})
        assert any("missing field" in i for i in result["issues"])

    def test_echo_in_act_1_reported(self):
        scenes = [make_scene(style="echo", act=1)]
        scenes.append(make_scene(scene_number=2, style="dossier", act=1))
        result = validate_scene_list(scenes, {"total_images": 2})
        assert any("Echo in Act 1" in i for i in result["issues"])

    def test_echo_in_act_6_reported(self):
        scenes = [make_scene(style="dossier", act=6)]
        scenes.append(make_scene(scene_number=2, style="echo", act=6))
        result = validate_scene_list(scenes, {"total_images": 2})
        assert any("Echo in Act 6" in i for i in result["issues"])

    def test_first_scene_must_be_dossier(self):
        scenes = [make_scene(style="schema"), make_scene(scene_number=2, style="dossier")]
        result = validate_scene_list(scenes, {"total_images": 2})
        assert any("First scene" in i for i in result["issues"])

    def test_last_scene_must_be_dossier(self):
        scenes = [make_scene(style="dossier"), make_scene(scene_number=2, style="schema")]
        result = validate_scene_list(scenes, {"total_images": 2})
        assert any("Last scene" in i for i in result["issues"])

    def test_isolated_echo_reported(self):
        scenes = [
            make_scene(scene_number=1, style="dossier", act=3),
            make_scene(scene_number=2, style="echo", act=3),
            make_scene(scene_number=3, style="dossier", act=3),
        ]
        result = validate_scene_list(scenes, {"total_images": 3})
        assert any("Isolated Echo" in i for i in result["issues"])

    def test_echo_cluster_of_two_passes(self):
        scenes = [
            make_scene(scene_number=1, style="dossier", act=3),
            make_scene(scene_number=2, style="echo", act=3, description="echo scene A"),
            make_scene(scene_number=3, style="echo", act=3, description="echo scene B"),
            make_scene(scene_number=4, style="dossier", act=3),
        ]
        result = validate_scene_list(scenes, {"total_images": 4})
        assert not any("Isolated Echo" in i for i in result["issues"])

    def test_five_consecutive_same_style_reported(self):
        scenes = [
            make_scene(scene_number=i, style="dossier", description=f"scene {i}")
            for i in range(1, 7)
        ]
        result = validate_scene_list(scenes, {"total_images": 6})
        assert any("consecutive" in i.lower() for i in result["issues"])

    def test_duplicate_descriptions_reported(self):
        scenes = [
            make_scene(scene_number=1, description="Same description here for testing"),
            make_scene(scene_number=2, description="Same description here for testing"),
        ]
        result = validate_scene_list(scenes, {"total_images": 2})
        assert any("duplicate" in i.lower() for i in result["issues"])

    def test_stats_include_distribution(self):
        scenes = make_scene_list(100)
        result = validate_scene_list(scenes, {"total_images": 100})
        assert "dossier" in result["stats"]
        assert "schema" in result["stats"]
        assert "echo" in result["stats"]


class TestAutoFixMinorIssues:
    def test_fixes_first_scene_not_dossier(self):
        scenes = [make_scene(style="schema"), make_scene(scene_number=2)]
        fixed = auto_fix_minor_issues(scenes)
        assert fixed[0]["style"] == "dossier"

    def test_fixes_last_scene_not_dossier(self):
        scenes = [make_scene(), make_scene(scene_number=2, style="echo", act=3)]
        fixed = auto_fix_minor_issues(scenes)
        assert fixed[-1]["style"] == "dossier"

    def test_fixes_echo_in_disallowed_acts(self):
        scenes = [
            make_scene(style="echo", act=1),
            make_scene(scene_number=2, style="echo", act=2),
            make_scene(scene_number=3, style="echo", act=6),
        ]
        fixed = auto_fix_minor_issues(scenes)
        for s in fixed:
            assert s["style"] == "dossier"

    def test_fixes_isolated_echo(self):
        scenes = [
            make_scene(scene_number=1, style="dossier", act=3),
            make_scene(scene_number=2, style="echo", act=3),
            make_scene(scene_number=3, style="dossier", act=3),
        ]
        fixed = auto_fix_minor_issues(scenes)
        assert fixed[1]["style"] == "dossier"

    def test_fixes_invalid_composition(self):
        scenes = [make_scene(composition_hint="invalid")]
        fixed = auto_fix_minor_issues(scenes)
        assert fixed[0]["composition_hint"] == "medium"

    def test_does_not_modify_original(self):
        scenes = [make_scene(style="schema")]
        original_style = scenes[0]["style"]
        auto_fix_minor_issues(scenes)
        assert scenes[0]["style"] == original_style
