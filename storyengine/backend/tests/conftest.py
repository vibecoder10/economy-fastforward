"""Shared pytest configuration for storyengine/backend tests.

Adds the backend root to sys.path so all test files can import backend modules
without needing their own sys.path manipulation.
"""
import os
import sys

# Add storyengine/backend to sys.path (parent of this tests/ directory)
_backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)
