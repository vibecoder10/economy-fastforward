"""Backward compatibility shim — real code at script/brief_translator/pipeline_writer.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("script.brief_translator.pipeline_writer")
_sys.modules[__name__] = _real_module
