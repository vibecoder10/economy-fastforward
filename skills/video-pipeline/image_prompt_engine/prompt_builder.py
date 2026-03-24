"""Backward compatibility shim — real code at image_prompts/engine/prompt_builder.py."""
import importlib as _importlib
import sys as _sys
_real_module = _importlib.import_module("image_prompts.engine.prompt_builder")
_sys.modules[__name__] = _real_module
