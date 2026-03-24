"""Backward compatibility shim — real code at analytics/osiris/competitor_scraper.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("analytics.osiris.competitor_scraper")
_sys.modules[__name__] = _real_module
