"""Backward compatibility shim — real code at analytics/osiris/performance_analyzer.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("analytics.osiris.performance_analyzer")
_sys.modules[__name__] = _real_module
