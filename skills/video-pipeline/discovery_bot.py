"""Backward compatibility shim — real code at discovery/bot.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("discovery.bot")
_sys.modules[__name__] = _real_module
