"""Functional test for Stage 1.2 / Cycle 46: SEC-SSE-001 cross-tenant task
leak — regression lock.

The bug (pre-fix): `_running_tasks` dict in routes/pipeline.py was keyed by
`video_id` alone. Two tenants happening to use the same video_id (a UUID
collision is astronomically unlikely, but the shape of the fix was the point)
would share task state through the dict — tenant A polling SSE for their job
could see tenant B's status string leak through.

The fix was to re-key the dict on `(tenant_id, video_id)` and require
tenant_id at every read/write. That fix is already landed. This test pins it:
if a future refactor drops tenant_id from a setter or accepts a raw video_id
key, CI fails before the leak ships again.

Strategy: pure static audit of routes/pipeline.py. We check the type
annotation, confirm there is no bare `_running_tasks[video_id]` indexing, and
confirm the helpers `_set_task_status`, `_get_task_status`,
`_clear_task_status` all require tenant_id.
"""
import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _pipeline_py() -> Path:
    return Path(__file__).resolve().parents[2] / "routes" / "pipeline.py"


def test_running_tasks_keyed_by_tuple():
    """The dict type annotation must be the composite-key form. A regression
    to `dict[str, dict]` would silently re-enable the cross-tenant leak."""
    text = _pipeline_py().read_text()
    match = re.search(
        r"_running_tasks\s*:\s*dict\[\s*tuple\[\s*str\s*,\s*str\s*\]\s*,\s*dict\s*\]",
        text,
    )
    assert match, (
        "_running_tasks is no longer typed as `dict[tuple[str, str], dict]` — "
        "SEC-SSE-001 regression. The tuple key (tenant_id, video_id) is what "
        "prevents cross-tenant task state from bleeding through the SSE feed."
    )
    print("✅ test_running_tasks_keyed_by_tuple")


def test_no_single_key_indexing_into_running_tasks():
    """The exact shape of the SEC-SSE-001 bug was `_running_tasks[video_id]`
    (or `.get(video_id)`) — a single name where the key should be a tuple.
    Flag any subscript / get / pop / setdefault whose argument is a bare
    `video_id` Name. A variable bound to a tuple (e.g. `key =
    (tenant_id, video_id); _running_tasks[key]`) is fine — that's the current
    pattern."""
    text = _pipeline_py().read_text()
    tree = ast.parse(text)

    offenders: list[str] = []

    FORBIDDEN_NAMES = {"video_id", "vid"}

    class Visitor(ast.NodeVisitor):
        def visit_Subscript(self, node: ast.Subscript) -> None:
            if isinstance(node.value, ast.Name) and node.value.id == "_running_tasks":
                if (
                    isinstance(node.slice, ast.Name)
                    and node.slice.id in FORBIDDEN_NAMES
                ):
                    offenders.append(
                        f"line {node.lineno}: _running_tasks[{node.slice.id}] — "
                        "single-name key, the exact SEC-SSE-001 shape"
                    )
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "_running_tasks"
                and node.func.attr in ("get", "pop", "setdefault")
                and len(node.args) >= 1
            ):
                arg = node.args[0]
                if isinstance(arg, ast.Name) and arg.id in FORBIDDEN_NAMES:
                    offenders.append(
                        f"line {node.lineno}: _running_tasks.{node.func.attr}"
                        f"({arg.id}) — single-name key, SEC-SSE-001 shape"
                    )
            self.generic_visit(node)

    Visitor().visit(tree)
    assert not offenders, (
        "SEC-SSE-001 regression — `_running_tasks` is being indexed with a "
        "bare video_id / vid name (no tenant component):\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\n\nKey must be the 2-tuple (tenant_id, video_id), typically via "
        "`key = (tenant_id, video_id); _running_tasks[key]`."
    )
    print("✅ test_no_single_key_indexing_into_running_tasks")


def test_task_helpers_require_tenant_id():
    """_set_task_status, _get_task_status, and _clear_task_status must all
    require a tenant_id argument. If tenant_id becomes Optional again or
    disappears, a caller can silently key by video_id only."""
    text = _pipeline_py().read_text()
    tree = ast.parse(text)

    helpers = {"_set_task_status", "_get_task_status", "_clear_task_status"}
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in helpers:
            found.add(node.name)
            arg_names = {a.arg for a in node.args.args}
            kw_names = {a.arg for a in node.args.kwonlyargs}
            all_names = arg_names | kw_names
            assert "tenant_id" in all_names, (
                f"{node.name} is missing tenant_id parameter — cross-tenant "
                "leak regression."
            )
            # tenant_id must NOT have a default of None (that was the old
            # Optional footgun). Check kwonly defaults first, then positional.
            if node.name == "_set_task_status":
                # kwonly: walk parallel lists
                for kw, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                    if kw.arg == "tenant_id":
                        if default is not None and not (
                            isinstance(default, ast.Constant) and default.value is not None
                        ):
                            raise AssertionError(
                                f"_set_task_status.tenant_id has a default — "
                                f"that was the original SEC-SSE-001 footgun."
                            )
                        if isinstance(default, ast.Constant) and default.value is None:
                            raise AssertionError(
                                "_set_task_status.tenant_id defaults to None — "
                                "cross-tenant regression."
                            )

    missing = helpers - found
    assert not missing, (
        f"task helpers removed or renamed: {missing}. If intentional, update "
        "this test to track the new surface."
    )
    print("✅ test_task_helpers_require_tenant_id")


def test_sse_loop_filters_by_tenant():
    """The SSE progress loop iterates `_running_tasks.items()`. It MUST
    filter each entry by the caller's tenant_id before emitting. Without
    that filter, tenant A's SSE feed would leak tenant B's task status."""
    text = _pipeline_py().read_text()
    # Find the iteration header
    header = re.search(
        r"for\s+\(\s*tid\s*,\s*vid\s*\)\s*,\s*task\s+in\s+list\(\s*_running_tasks\.items\(\)\s*\)\s*:",
        text,
    )
    assert header, (
        "SSE progress loop `for (tid, vid), task in list(_running_tasks.items()):` "
        "not found in routes/pipeline.py. If the loop moved or was renamed, "
        "update this test to track the new location — but do NOT drop the filter."
    )
    # Take the 300 chars after the header as the body window; the filter must
    # appear there.
    start = header.end()
    body = text[start : start + 300]
    assert re.search(r"\btid\s*!=\s*tenant_id\b", body), (
        "SSE iteration over _running_tasks no longer has `if tid != tenant_id: "
        "continue` immediately after the loop header. Without that filter, "
        "tenant A sees tenant B's task state on the SSE feed."
    )
    print("✅ test_sse_loop_filters_by_tenant")


TESTS = [
    test_running_tasks_keyed_by_tuple,
    test_no_single_key_indexing_into_running_tasks,
    test_task_helpers_require_tenant_id,
    test_sse_loop_filters_by_tenant,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
