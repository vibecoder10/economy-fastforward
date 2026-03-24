"""Backward compatibility shim — real code at render/audio_sync/transition_engine.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("render.audio_sync.transition_engine")
_sys.modules[__name__] = _real_module
