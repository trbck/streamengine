#!/usr/bin/env python3
"""
FastMCP-compatible entry point for StreamMachine MCP Server.

This provides a FastMCP server that can be used with `mcp dev` command.

Usage:
    mcp dev src/streammachine/mcp_fast.py --with-editable .
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("FastMCP not available. Install with: pip install mcp[cli]")
    raise

# StreamMachine imports
from streammachine.redisapi import RedisConnection
from streammachine.storage import Storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("streammachine.mcp")

# Create FastMCP server
mcp = FastMCP("streammachine")

# Global state for connections
_redis: Optional[RedisConnection] = None
_storage: Optional[Storage] = None
_ALLOW_UNSAFE_OBJECT_TOOLS = os.environ.get("STREAMMACHINE_ENABLE_UNSAFE_PICKLE_TOOLS") == "1"


async def get_redis() -> RedisConnection:
    """Get or create Redis connection."""
    global _redis
    if _redis is None:
        _redis = RedisConnection()
    return _redis


async def get_storage() -> Storage:
    """Get or create Storage instance."""
    global _storage
    if _storage is None:
        _storage = Storage()
        await _storage.start()
    return _storage


def _format_response(data: Any, success: bool = True, error: Optional[str] = None) -> str:
    """Format a response as JSON."""
    return json.dumps({
        "success": success,
        "data": data if success else None,
        "error": error,
    }, default=str)


def _decode_value(value: Any) -> Any:
    """Normalize Redis bytes responses to strings where appropriate."""
    if isinstance(value, bytes):
        return value.decode()
    return value


def _stream_group_count(info: dict[str, Any]) -> int:
    """Handle coredis XINFO responses that return groups as either count or list."""
    groups = info.get("groups", 0)
    return groups if isinstance(groups, int) else len(groups)


# =============================================================================
# STREAM TOOLS
# =============================================================================

@mcp.tool()
async def stream_send(stream: str, message: dict[str, str]) -> str:
    """Send a message to a Redis stream.

    Args:
        stream: Name of the Redis stream to send to
        message: Message data as key-value pairs

    Returns:
        JSON response with message_id
    """
    redis = await get_redis()
    await redis._ensure_pool()
    import time
    message["sent"] = str(time.time())
    result = await redis.client.xadd(stream, message)
    return _format_response({"message_id": result})


@mcp.tool()
async def stream_read(stream: str, count: int = 10, start: str = "+") -> str:
    """Read messages from a Redis stream.

    Args:
        stream: Name of the Redis stream to read from
        count: Number of messages to read (default: 10)
        start: Start ID (default: + for latest)

    Returns:
        JSON response with messages
    """
    redis = await get_redis()
    await redis._ensure_pool()
    results = await redis.client.xrevrange(stream, start, "-", count=count)
    messages = []
    for msg_id, data in results:
        messages.append({
            "id": msg_id.decode() if isinstance(msg_id, bytes) else msg_id,
            "data": {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()},
        })
    return _format_response({"count": len(messages), "messages": messages})


@mcp.tool()
async def stream_info(stream: str) -> str:
    """Get information about a Redis stream.

    Args:
        stream: Name of the Redis stream

    Returns:
        JSON response with stream info
    """
    redis = await get_redis()
    await redis._ensure_pool()
    info = await redis.client.xinfo_stream(stream)
    result = {
        "length": info.get("length", 0),
        "groups": _stream_group_count(info),
        "last_generated_id": str(info.get("last-generated-id", "")),
    }
    return _format_response(result)


@mcp.tool()
async def stream_list(pattern: str = "*") -> str:
    """List all Redis streams matching a pattern.

    Args:
        pattern: Pattern to match stream names (default: *)

    Returns:
        JSON response with list of streams
    """
    redis = await get_redis()
    await redis._ensure_pool()
    keys = await redis.client.keys(pattern)
    streams = []
    for key in keys:
        key_str = _decode_value(key)
        key_type = _decode_value(await redis.client.type(key))
        if key_type == "stream":
            streams.append(key_str)
    return _format_response({"streams": streams})


# =============================================================================
# STORAGE TOOLS
# =============================================================================

@mcp.tool()
async def storage_read(key: str, default: Any = None) -> str:
    """Read a value from StreamMachine's shared storage.

    Args:
        key: Key to read from storage
        default: Default value if key doesn't exist

    Returns:
        JSON response with the value
    """
    storage = await get_storage()
    value = await storage.read(key, default=default)
    return _format_response({"key": key, "value": value})


@mcp.tool()
async def storage_write(key: str, value: Any) -> str:
    """Write a value to StreamMachine's shared storage.

    Args:
        key: Key to write to
        value: Value to store (can be any JSON-serializable value)

    Returns:
        JSON response confirming write
    """
    storage = await get_storage()
    await storage.write(key, value)
    return _format_response({"key": key, "written": True})


@mcp.tool()
async def storage_delete(key: str) -> str:
    """Delete a key from StreamMachine's shared storage.

    Args:
        key: Key to delete

    Returns:
        JSON response with whether key existed
    """
    storage = await get_storage()
    existed = await storage.delete(key)
    return _format_response({"key": key, "existed": existed})


@mcp.tool()
async def storage_keys() -> str:
    """List all keys in StreamMachine's shared storage.

    Returns:
        JSON response with list of keys
    """
    storage = await get_storage()
    keys = await storage.keys()
    return _format_response({"keys": keys, "count": len(keys)})


# =============================================================================
# HEALTH TOOLS
# =============================================================================

@mcp.tool()
async def health_check() -> str:
    """Check the health status of Redis connection.

    Returns:
        JSON response with health status
    """
    redis = await get_redis()
    healthy = await redis.health_check()
    result = {
        "status": "healthy" if healthy else "unhealthy",
        "redis": "connected" if healthy else "disconnected",
    }
    return _format_response(result)


@mcp.tool()
async def redis_ping() -> str:
    """Ping Redis server to check connectivity.

    Returns:
        JSON response with ping result
    """
    redis = await get_redis()
    result = await redis.health_check()
    return _format_response({"ping": "pong" if result else "failed"})


# =============================================================================
# RESOURCES
# =============================================================================

@mcp.resource("streammachine://config")
async def get_config() -> str:
    """Get current configuration and environment variables."""
    import os
    config = {
        "redis_url": os.environ.get("REDIS_URL", "redis://localhost:6379"),
        "redis_host": os.environ.get("REDIS_HOST", "localhost"),
        "redis_port": int(os.environ.get("REDIS_PORT", "6379")),
        "redis_db": int(os.environ.get("REDIS_DB", "0")),
    }
    return json.dumps(config, indent=2)


@mcp.resource("streammachine://status")
async def get_status() -> str:
    """Get current status of connections and storage."""
    try:
        redis = await get_redis()
        healthy = await redis.health_check()
    except Exception:
        healthy = False

    try:
        storage = await get_storage()
        keys = await storage.keys()
    except Exception:
        keys = []

    status = {
        "redis": {
            "connected": healthy,
            "status": "connected" if healthy else "disconnected",
        },
        "storage": {
            "keys": len(keys),
            "keys_list": keys[:100],
        },
    }
    return json.dumps(status, indent=2)


if __name__ == "__main__":
    mcp.run()
