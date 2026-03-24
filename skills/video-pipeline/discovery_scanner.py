"""Backward compatibility shim — real code at discovery/scanner.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("discovery.scanner")
_sys.modules[__name__] = _real_module
