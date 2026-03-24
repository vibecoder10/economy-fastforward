"""Backward compatibility shim — real code at script/segmentation_engine.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("script.segmentation_engine")
_sys.modules[__name__] = _real_module
