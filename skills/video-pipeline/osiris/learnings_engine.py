"""Backward compatibility shim — real code at analytics/osiris/learnings_engine.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("analytics.osiris.learnings_engine")
_sys.modules[__name__] = _real_module
