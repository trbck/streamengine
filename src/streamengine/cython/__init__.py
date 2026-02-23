"""
Cython-accelerated decoding utilities for StreamEngine.

This module provides optimized functions for decoding Redis stream data.
If the Cython extension is not compiled, the pure Python fallback is used.
"""

try:
    from .cython_decode import decode_dict_bytes_to_utf8
    _has_cython_decode = True
except ImportError:
    decode_dict_bytes_to_utf8 = None
    _has_cython_decode = False

__all__ = ['decode_dict_bytes_to_utf8', '_has_cython_decode']