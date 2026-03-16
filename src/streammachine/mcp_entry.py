#!/usr/bin/env python3
"""
MCP Server entry point.

Usage:
    # From the streammachine source directory:
    mcp dev src/streammachine/mcp_entry.py

    # Or after installation:
    mcp dev $(python -c "import streammachine.mcp_entry; print(streammachine.mcp_entry.__file__)")
"""

from __future__ import annotations

import sys


def main() -> None:
    """Run the MCP entry point with an actionable optional-dependency error."""
    try:
        from streammachine.mcp_server import main as run_mcp
    except ImportError as exc:
        print(
            "MCP support is not installed. Install with `pip install streammachine[mcp]`.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    run_mcp()

if __name__ == "__main__":
    main()
