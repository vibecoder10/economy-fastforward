"""Execute the sanctioned deploy wrapper against fake VPS commands.

This proves ordering and trap recovery without SSH, a real database, service
restarts, or provider work.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


STORYENGINE = Path(__file__).resolve().parents[3]
SOURCE_DEPLOY = STORYENGINE / "scripts" / "vps-deploy.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
    path.chmod(0o755)


def _fake_vps(tmp_path: Path, *, fail_pull: bool = False) -> tuple[dict[str, str], Path, Path]:
    home = tmp_path / "home"
    repo = home / "projects" / "economy-fastforward"
    scripts = repo / "storyengine" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SOURCE_DEPLOY, scripts / "vps-deploy.sh")
    (scripts / "drain_control.py").write_text("# fake helper; intercepted by fake python3\n")
    (repo / "storyengine" / "backend").mkdir(parents=True)
    (repo / "storyengine" / "backend" / "requirements.txt").write_text("")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    trace = tmp_path / "trace.log"

    _write_executable(
        fake_bin / "python3",
        'printf "python %s\\n" "$*" >> "$TRACE"\n',
    )
    _write_executable(
        fake_bin / "git",
        """
printf "git %s\\n" "$*" >> "$TRACE"
if [ "${1:-}" = "pull" ] && [ "${FAIL_PULL:-0}" = "1" ]; then exit 17; fi
if [ "${1:-}" = "rev-parse" ]; then echo abc1234; fi
""",
    )
    _write_executable(fake_bin / "pip3", 'printf "pip %s\\n" "$*" >> "$TRACE"\n')
    _write_executable(
        fake_bin / "systemctl",
        """
if [ "${1:-}" = "show" ]; then echo 0; exit 0; fi
if [ "${2:-}" = "--quiet" ] || [ "${1:-}" = "is-active" ]; then
  [ "${2:-}" = "--quiet" ] || echo active
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "curl",
        """
for arg in "$@"; do
  if [ "$arg" = "%{http_code}" ]; then echo 200; exit 0; fi
done
echo '{"status":"healthy","drain":{"draining":true}}'
""",
    )
    _write_executable(fake_bin / "sleep", "exit 0\n")
    _write_executable(fake_bin / "npm", 'printf "npm %s\\n" "$*" >> "$TRACE"\n')

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "TRACE": str(trace),
        "FAIL_PULL": "1" if fail_pull else "0",
        "DRAIN_TIMEOUT_SECONDS": "10",
    }
    return env, scripts / "vps-deploy.sh", trace


def test_deploy_drains_waits_deploys_verifies_then_undrains(tmp_path):
    env, script, trace = _fake_vps(tmp_path)
    result = subprocess.run(
        ["bash", str(script), "integration-test"],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    events = trace.read_text().splitlines()
    drain = next(i for i, line in enumerate(events) if " drain --owner " in line)
    wait = next(i for i, line in enumerate(events) if " wait --timeout " in line)
    pull = next(i for i, line in enumerate(events) if line == "git pull --ff-only")
    undrain = next(i for i, line in enumerate(events) if " undrain --owner " in line)
    assert drain < wait < pull < undrain
    assert not (Path(env["HOME"]) / "deploy.lock").exists()


def test_deploy_failure_still_undrains_and_releases_lock(tmp_path):
    env, script, trace = _fake_vps(tmp_path, fail_pull=True)
    result = subprocess.run(
        ["bash", str(script), "integration-test"],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 17

    events = trace.read_text().splitlines()
    assert any(" drain --owner " in line for line in events)
    assert any(" wait --timeout " in line for line in events)
    assert any(" undrain --owner " in line for line in events)
    assert not (Path(env["HOME"]) / "deploy.lock").exists()
