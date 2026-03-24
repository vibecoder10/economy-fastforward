"""Backward compatibility shim — real code at competitor_scraper/scraper.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("competitor_scraper.scraper")
_sys.modules[__name__] = _real_module
