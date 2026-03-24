"""Backward compatibility shim — real code at script/brief_translator/concept_repair.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("script.brief_translator.concept_repair")
_sys.modules[__name__] = _real_module
