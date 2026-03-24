"""Backward compatibility shim — real code at script/brief_translator/."""
import importlib as _importlib
import sys as _sys
_real = _importlib.import_module("script.brief_translator")
# Forward all attributes
for _attr in dir(_real):
    if not _attr.startswith("__"):
        globals()[_attr] = getattr(_real, _attr)
