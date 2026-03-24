"""Backward compatibility shim — real code at script/brief_translator/script_generator.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("script.brief_translator.script_generator")
_sys.modules[__name__] = _real_module
