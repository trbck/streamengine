#!/usr/bin/env python3
"""
MCP Server entry point for use with `mcp dev` command.

Usage:
    # From the streammachine source directory:
    mcp dev src/streammachine/mcp_entry.py

    # Or after installation:
    mcp dev $(python -c "import streammachine.mcp_entry; print(streammachine.mcp_entry.__file__)")
"""

from streammachine.mcp_server import main

if __name__ == "__main__":
    main()