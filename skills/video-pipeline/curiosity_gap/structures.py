"""Backward compatibility shim — real code at title_idea/curiosity_gap/structures.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("title_idea.curiosity_gap.structures")
_sys.modules[__name__] = _real_module
