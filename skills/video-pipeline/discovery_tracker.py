"""Backward compatibility shim — real code at discovery/tracker.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("discovery.tracker")
_sys.modules[__name__] = _real_module
