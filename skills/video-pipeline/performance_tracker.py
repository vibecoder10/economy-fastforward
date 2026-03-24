"""Backward compatibility shim — real code at analytics/performance_tracker.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("analytics.performance_tracker")
_sys.modules[__name__] = _real_module
