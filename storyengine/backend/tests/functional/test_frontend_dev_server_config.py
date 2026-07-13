"""Lock the local StoryEngine frontend dev server to a usable CSS resolver.

The DVsU one-machine proof needs the operator UI to open locally. Next 16's
Turbopack dev server resolved Tailwind imports from the parent `storyengine`
directory in this checkout, while the production build succeeded. Local dev
uses Webpack until that resolver behavior is fixed upstream or the workspace is
restructured.
"""

import json
from pathlib import Path


def _frontend_root() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend"


def test_frontend_dev_script_uses_webpack_for_local_review():
    package_json = json.loads((_frontend_root() / "package.json").read_text())

    assert package_json["scripts"]["dev"] == "next dev --webpack --port 3001"


def test_frontend_config_pins_roots_to_frontend_directory():
    next_config = (_frontend_root() / "next.config.ts").read_text()
    postcss_config = (_frontend_root() / "postcss.config.mjs").read_text()

    assert 'fileURLToPath(import.meta.url)' in next_config
    assert "const appDir = path.dirname" in next_config
    assert "root: appDir" in next_config
    assert "root: process.cwd()" not in next_config

    assert 'fileURLToPath(import.meta.url)' in postcss_config
    assert "const __dirname = path.dirname" in postcss_config
    assert "base: __dirname" in postcss_config
