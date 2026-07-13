"""Lock the DVsU Anton runbook to the one-machine proof contract."""

from pathlib import Path


def _runbook() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "notes"
        / "dvsu-anton-single-machine-pipeline.md"
    )


def test_dvsu_anton_runbook_keeps_one_machine_evidence_contract():
    text = _runbook().read_text()

    assert "Raw source package" in text or "raw source package" in text
    assert "original_problem -> engineering_decision -> tradeoff -> reality" in text
    assert "Do not research or pre-write a standalone \"meaning\" beat" in text
    assert "For the current proof, only the selected first machine is researched or previewed" in text
    assert "run one-machine research for `Boeing XB-15` only" in text
    assert "Run only the single-machine script preview for `Boeing XB-15`" in text


def test_dvsu_anton_runbook_keeps_failed_preview_as_review_artifact():
    text = _runbook().read_text()

    assert "Selected-machine preview gates that fail before a paragraph LLM call" in text
    assert "save a failed `machine_script_previews[<machine_key>]` artifact" in text
    assert "reviewable UI audit artifacts" in text
    assert "They still do not call Claude, mutate `scripts`, update `script_validation`, or advance the video" in text
    assert "Do not run broad research or full script generation" in text
