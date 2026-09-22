"""One-time extraction: turn the 14 raw gold .txt scripts into clean narration-only
fixtures (title, metadata lines, and trailing on-screen name/graphics lists stripped).

Resolves the "structural label vs narration" open thread from HANDOFF.md: there is
no docx paragraph-style signal to lean on (verified by inspecting the source .docx
files - narration, titles, and on-screen name lists all use the same "Normal" style
in most files, and even the one file using "Heading1" for its title also used it for
the on-screen names section header, so style is not a reliable discriminator across
the corpus). The real, consistent signal is textual/positional: 6 of the 14 files
carry a trailing on-screen name/graphics list (always after the last real paragraph,
sometimes behind an explicit marker like "[END OF SCRIPT]" / "GRAPHICS LIST" / a
divider line, sometimes just glued onto the tail with no marker at all). The other 8
files - all with "voiceover" (any casing/position) in the filename - are already
clean narration with no title and no trailing list. That naming correlation is
confirmed exactly across all 14 files below (see NEEDS_STRIPPING vs the rest).

Run: python3 build_fixtures.py
Writes: fixtures.json (list of {name, title_stripped, tail_stripped, paragraphs}).
"""
import json
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
OUT_PATH = Path(__file__).resolve().parent / "fixtures.json"

# Per-file strip config, hand-verified against each raw .txt (see docs/gold-scripts/
# grammar/EXTRACTION_NOTES.md for the evidence). `title_strip` is an exact prefix to
# remove from the start of the raw text (covers both "title on its own line" and
# "title glued directly onto the first paragraph" cases). `tail_marker` is the exact
# substring whose first occurrence marks the start of the trailing on-screen list;
# everything from that point to EOF is dropped. Both are None for the 8 files that
# are already clean voiceover-only text.
FILE_CONFIG = {
    "every-aircraft-carrier-that-was-sunk-in-combat-voiceover.txt": {
        "title_strip": None,
        "tail_marker": None,
    },
    "every-british-aircraft-carrier-class-ever-built.txt": {
        "title_strip": "Every British Aircraft Carrier Class Ever Built",
        "tail_marker": "—------HMS Furious",
    },
    "every-british-battleship-class-ever-built-vo.txt": {
        "title_strip": None,
        "tail_marker": None,
    },
    "every-us-aircraft-carrier-ever-built.txt": {
        "title_strip": "Every US Aircraft Carrier Ever Built\n",
        "tail_marker": "────",
    },
    "every-us-battleship-class-ever-built-voiceover.txt": {
        "title_strip": None,
        "tail_marker": None,
    },
    "every-us-destroyer-class-ever-built-1898-1945.txt": {
        "title_strip": "EVERY US DESTROYER CLASS EVER BUILT (1898-1945)\n",
        "tail_marker": "Bainbridge Bainbridge-class",
    },
    "every-us-military-helicopter-ever-built.txt": {
        "title_strip": "Every U.S. Military Helicopter Ever Built\n"
        "DvsU — Production Script  |  30 Units  |  ~22 min runtime\n",
        "tail_marker": "GRAPHICS LIST",
    },
    "every-us-strategic-bomber-ever-built.txt": {
        "title_strip": "EVERY US STRATEGIC BOMBER EVER BUILT \n",
        "tail_marker": "[END OF SCRIPT]",
    },
    "most-hated-helicopters-to-fly-by-pilots-ever-voiceover.txt": {
        "title_strip": None,
        "tail_marker": None,
    },
    "most-hated-warships-by-their-own-crews-ever.txt": {
        "title_strip": "MOST HATED WARSHIPS BY THEIR OWN CREWS EVER\n",
        "tail_marker": "—--------HMS Captain",
    },
    "voiceover-every-soviet-submarine-class-ever-built.txt": {
        "title_strip": None,
        "tail_marker": None,
    },
    "voiceover-every-wwii-landing-ship-class-ever-built.txt": {
        "title_strip": None,
        "tail_marker": None,
    },
    "voiceover-most-hated-fighter-jets-v1-3.txt": {
        "title_strip": None,
        "tail_marker": None,
    },
    "voiceover-never-built-us-destroyers-we-nearly-got.txt": {
        "title_strip": None,
        "tail_marker": None,
    },
}


def extract(raw: str, cfg: dict) -> tuple[list[str], bool, bool]:
    text = raw
    title_stripped = False
    if cfg["title_strip"] is not None:
        assert text.startswith(cfg["title_strip"]), "title_strip prefix mismatch"
        text = text[len(cfg["title_strip"]):]
        title_stripped = True

    tail_stripped = False
    if cfg["tail_marker"] is not None:
        idx = text.index(cfg["tail_marker"])
        text = text[:idx]
        tail_stripped = True

    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    return paragraphs, title_stripped, tail_stripped


def main() -> None:
    fixtures = []
    for filename, cfg in FILE_CONFIG.items():
        raw = (SCRIPTS_DIR / filename).read_text(encoding="utf-8")
        paragraphs, title_stripped, tail_stripped = extract(raw, cfg)
        fixtures.append(
            {
                "name": filename,
                "title_stripped": title_stripped,
                "tail_stripped": tail_stripped,
                "paragraph_count": len(paragraphs),
                "paragraphs": paragraphs,
            }
        )
        print(f"{filename}: {len(paragraphs)} paragraphs "
              f"(title_stripped={title_stripped}, tail_stripped={tail_stripped})")

    OUT_PATH.write_text(json.dumps(fixtures, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote {len(fixtures)} fixtures to {OUT_PATH}")


if __name__ == "__main__":
    main()
