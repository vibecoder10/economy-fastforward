"""Backward compatibility shim — real code at script/brief_translator/validator.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("script.brief_translator.validator")
_sys.modules[__name__] = _real_module
