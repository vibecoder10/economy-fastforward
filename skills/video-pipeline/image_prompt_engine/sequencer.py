"""Backward compatibility shim — real code at image_prompts/engine/sequencer.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("image_prompts.engine.sequencer")
_sys.modules[__name__] = _real_module
