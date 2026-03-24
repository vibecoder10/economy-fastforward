"""Backward compatibility shim — real code at script/brief_translator/psych_angle_assigner.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("script.brief_translator.psych_angle_assigner")
_sys.modules[__name__] = _real_module
