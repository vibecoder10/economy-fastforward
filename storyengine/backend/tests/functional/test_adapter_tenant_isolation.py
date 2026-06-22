"""Lock: every title/status lookup in SupabaseAdapter is tenant-scoped.

The adapter is built per-request with a tenant_id (pipeline_executor.py:200).
Before this fix, its title- and status-based reads/deletes ignored that
tenant_id — so two tenants sharing a video title or pipeline status could
read, or DELETE, each other's rows. No secret needed; it triggers on any
collision under normal multi-tenant load.

This test captures the SQL + params every method emits and proves:
  1. When a tenant is bound, EVERY query carries that tenant_id in its params.
  2. The two DELETE methods carry a tenant predicate in their SQL text.
  3. When NO tenant is bound (standalone/CLI), behavior is unchanged (no clause).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import supabase_adapter
from supabase_adapter import SupabaseAdapter

TENANT = "11111111-1111-1111-1111-111111111111"


def _install_capture():
    """Replace the module-level DB helpers with recorders. Returns the call log."""
    calls = []

    def cap_fetch_one(sql, params=None):
        calls.append((sql, params))
        return None

    def cap_fetch_all(sql, params=None):
        calls.append((sql, params))
        return []

    def cap_execute(sql, params=None):
        calls.append((sql, params))
        return "DELETE 0"  # lets delete_* parse a rowcount

    supabase_adapter._fetch_one = cap_fetch_one
    supabase_adapter._fetch_all = cap_fetch_all
    supabase_adapter._execute = cap_execute
    return calls


# Methods that resolve rows by TITLE or STATUS — every one must be tenant-scoped.
def _exercise(adapter):
    """Call every title/status lookup; return {method_name: [(sql, params), ...]}."""
    by_method = {}

    def run(name, fn):
        calls = _install_capture()
        try:
            fn()
        except Exception as e:  # a method may post-process empty results; SQL was still captured
            by_method.setdefault(name + "__error", str(e))
        by_method[name] = list(calls)

    run("get_idea", lambda: adapter.get_idea("rec-1"))
    run("get_ideas_by_status", lambda: adapter.get_ideas_by_status("idea_logged"))
    run("get_all_ideas", lambda: adapter.get_all_ideas())
    run("find_idea_by_title", lambda: adapter.find_idea_by_title("Family Manners"))
    run("get_scripts_by_title", lambda: adapter.get_scripts_by_title("Family Manners"))
    run("get_scripts_to_create", lambda: adapter.get_scripts_to_create())
    run("get_pending_images", lambda: adapter.get_pending_images())
    run("get_all_images_for_video", lambda: adapter.get_all_images_for_video("Family Manners"))
    run("get_pending_images_for_video", lambda: adapter.get_pending_images_for_video("Family Manners"))
    run("get_images_ready_for_video_generation",
        lambda: adapter.get_images_ready_for_video_generation("Family Manners"))
    run("delete_scripts_for_video", lambda: adapter.delete_scripts_for_video("Family Manners"))
    run("delete_images_for_video", lambda: adapter.delete_images_for_video("Family Manners"))

    # also the id-based current-video path of get_scripts_by_title
    adapter.current_video_id = "vid-1"
    run("get_scripts_by_title__current", lambda: adapter.get_scripts_by_title("Family Manners"))
    adapter.current_video_id = None
    return by_method


def test_bound_tenant_scopes_every_query():
    adapter = SupabaseAdapter(tenant_id=TENANT)
    by_method = _exercise(adapter)

    failures = []
    for name, calls in by_method.items():
        if name.endswith("__error"):
            continue
        if not calls:
            failures.append(f"{name}: emitted no SQL (test wiring issue)")
            continue
        for sql, params in calls:
            params = tuple(params) if params is not None else ()
            if TENANT not in params:
                failures.append(
                    f"{name}: query has NO tenant param — cross-tenant leak:\n    {sql.strip()[:160]}"
                )

    assert not failures, "Tenant isolation broken:\n" + "\n".join(failures)
    print(f"✅ test_bound_tenant_scopes_every_query ({len(by_method)} methods)")


def test_delete_methods_have_tenant_predicate_in_sql():
    """Deletes are the dangerous ones — prove the SQL text itself is scoped."""
    adapter = SupabaseAdapter(tenant_id=TENANT)
    for name in ("delete_scripts_for_video", "delete_images_for_video"):
        calls = _install_capture()
        getattr(adapter, name)("Family Manners")
        sql = calls[0][0]
        assert "tenant_id = %s" in sql, (
            f"{name} DELETE is not tenant-scoped in SQL:\n{sql}"
        )
    print("✅ test_delete_methods_have_tenant_predicate_in_sql")


def test_no_tenant_keeps_legacy_behavior():
    """Standalone/CLI callers (no tenant bound) must still work — no clause added."""
    adapter = SupabaseAdapter(tenant_id=None)
    calls = _install_capture()
    adapter.delete_scripts_for_video("Family Manners")
    sql, params = calls[0]
    assert "tenant_id" not in sql, "Unbound adapter unexpectedly added a tenant clause"
    assert tuple(params) == ("Family Manners",), f"Unexpected params: {params}"
    print("✅ test_no_tenant_keeps_legacy_behavior")


TESTS = [
    test_bound_tenant_scopes_every_query,
    test_delete_methods_have_tenant_predicate_in_sql,
    test_no_tenant_keeps_legacy_behavior,
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
