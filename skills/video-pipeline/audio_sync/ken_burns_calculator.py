"""Backward compatibility shim — real code at render/audio_sync/ken_burns_calculator.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("render.audio_sync.ken_burns_calculator")
_sys.modules[__name__] = _real_module
