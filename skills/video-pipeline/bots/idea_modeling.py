"""Backward compatibility shim — real code at title_idea/idea_modeling.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("title_idea.idea_modeling")
_sys.modules[__name__] = _real_module
