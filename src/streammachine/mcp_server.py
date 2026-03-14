"""
StreamMachine MCP Server

An MCP (Model Context Protocol) server that exposes StreamMachine functionality
as tools for LLM-powered applications.

Usage:
    # Run as standalone server
    python -m streammachine.mcp_server

    # Or use in Claude Desktop config:
    # {
    #   "mcpServers": {
    #     "streammachine": {
    #       "command": "python",
    #       "args": ["-m", "streammachine.mcp_server"]
    #     }
    #   }
    # }
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

# MCP SDK imports
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    Resource,
    Prompt,
    GetPromptResult,
)
import mcp.server.session

# StreamMachine imports
from .redisapi import RedisConnection
from .storage import Storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("streammachine.mcp")

# Create MCP server instance
server = Server("streammachine")

# Global state for connections
_redis: Optional[RedisConnection] = None
_storage: Optional[Storage] = None


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


# =============================================================================
# TOOLS
# =============================================================================

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available StreamMachine tools."""
    return [
        # Redis Stream Tools
        Tool(
            name="stream_send",
            description="Send a message to a Redis stream. Use this to publish events or data to a stream for processing by StreamMachine agents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "stream": {
                        "type": "string",
                        "description": "Name of the Redis stream to send to",
                    },
                    "message": {
                        "type": "object",
                        "description": "Message data as key-value pairs",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["stream", "message"],
            },
        ),
        Tool(
            name="stream_send_batch",
            description="Send multiple messages to a Redis stream in a single batch operation for better throughput.",
            inputSchema={
                "type": "object",
                "properties": {
                    "stream": {
                        "type": "string",
                        "description": "Name of the Redis stream",
                    },
                    "messages": {
                        "type": "array",
                        "description": "List of messages to send",
                        "items": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                },
                "required": ["stream", "messages"],
            },
        ),
        Tool(
            name="stream_read",
            description="Read messages from a Redis stream. Returns recent messages without consuming them.",
            inputSchema={
                "type": "object",
                "properties": {
                    "stream": {
                        "type": "string",
                        "description": "Name of the Redis stream to read from",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of messages to read (default: 10)",
                        "default": 10,
                    },
                    "start": {
                        "type": "string",
                        "description": "Start ID (default: latest messages)",
                    },
                },
                "required": ["stream"],
            },
        ),
        Tool(
            name="stream_info",
            description="Get information about a Redis stream including length, consumer groups, and last entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "stream": {
                        "type": "string",
                        "description": "Name of the Redis stream",
                    },
                },
                "required": ["stream"],
            },
        ),
        Tool(
            name="stream_list",
            description="List all Redis streams matching a pattern.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Pattern to match stream names (default: *)",
                        "default": "*",
                    },
                },
            },
        ),

        # Storage Tools
        Tool(
            name="storage_read",
            description="Read a value from StreamMachine's shared storage. Storage is persisted across processes and can be used to share state between agents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key to read from storage",
                    },
                    "default": {
                        "description": "Default value if key doesn't exist",
                    },
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="storage_write",
            description="Write a value to StreamMachine's shared storage. Values persist across process boundaries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key to write to",
                    },
                    "value": {
                        "description": "Value to store (can be any JSON-serializable value)",
                    },
                },
                "required": ["key", "value"],
            },
        ),
        Tool(
            name="storage_delete",
            description="Delete a key from StreamMachine's shared storage.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key to delete",
                    },
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="storage_keys",
            description="List all keys in StreamMachine's shared storage.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="storage_clear",
            description="Clear all keys from StreamMachine's shared storage. Use with caution!",
            inputSchema={
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to confirm clearing all data",
                    },
                },
                "required": ["confirm"],
            },
        ),

        # Health & Status Tools
        Tool(
            name="health_check",
            description="Check the health status of Redis connection and get server info.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="redis_info",
            description="Get detailed Redis server information including version, memory usage, and connected clients.",
            inputSchema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Info section to query (default: default)",
                        "default": "default",
                    },
                },
            },
        ),
        Tool(
            name="redis_ping",
            description="Ping Redis server to check connectivity.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),

        # Object Storage Tools (if available)
        Tool(
            name="obj_get",
            description="Retrieve a pickled Python object from Redis object storage.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key to retrieve",
                    },
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="obj_list",
            description="List keys in Redis object storage matching a pattern.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Pattern to match keys (default: *)",
                        "default": "*",
                    },
                },
            },
        ),
        Tool(
            name="obj_delete",
            description="Delete keys from Redis object storage matching a pattern.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Pattern of keys to delete",
                    },
                },
                "required": ["pattern"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent | ImageContent | EmbeddedResource]:
    """Execute a tool and return the result."""
    try:
        if name == "stream_send":
            redis = await get_redis()
            await redis._ensure_pool()
            # Add timestamp
            arguments["message"]["sent"] = str(__import__("time").time())
            result = await redis.client.xadd(arguments["stream"], arguments["message"])
            return [TextContent(type="text", text=_format_response({"message_id": result}))]

        elif name == "stream_send_batch":
            redis = await get_redis()
            await redis._ensure_pool()
            t = __import__("time").time()
            for msg in arguments["messages"]:
                msg["sent"] = str(t)
            results = await redis.pipeline_xadd(arguments["stream"], arguments["messages"])
            return [TextContent(type="text", text=_format_response({"message_ids": results}))]

        elif name == "stream_read":
            redis = await get_redis()
            await redis._ensure_pool()
            count = arguments.get("count", 10)
            start = arguments.get("start", "+")  # + means latest
            results = await redis.client.xrevrange(arguments["stream"], "+", "-", count=count)
            messages = []
            for msg_id, data in results:
                messages.append({
                    "id": msg_id.decode() if isinstance(msg_id, bytes) else msg_id,
                    "data": {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()},
                })
            return [TextContent(type="text", text=_format_response({"count": len(messages), "messages": messages}))]

        elif name == "stream_info":
            redis = await get_redis()
            await redis._ensure_pool()
            info = await redis.client.xinfo_stream(arguments["stream"])
            result = {
                "length": info.get("length", 0),
                "groups": len(info.get("groups", [])),
                "last_generated_id": str(info.get("last-generated-id", "")),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
            }
            return [TextContent(type="text", text=_format_response(result))]

        elif name == "stream_list":
            redis = await get_redis()
            await redis._ensure_pool()
            pattern = arguments.get("pattern", "*")
            keys = await redis.client.keys(pattern)
            # Filter for streams only
            streams = []
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                key_type = await redis.client.type(key)
                if key_type == "stream":
                    streams.append(key_str)
            return [TextContent(type="text", text=_format_response({"streams": streams}))]

        elif name == "storage_read":
            storage = await get_storage()
            key = arguments["key"]
            default = arguments.get("default")
            value = await storage.read(key, default=default)
            return [TextContent(type="text", text=_format_response({"key": key, "value": value}))]

        elif name == "storage_write":
            storage = await get_storage()
            key = arguments["key"]
            value = arguments["value"]
            await storage.write(key, value)
            return [TextContent(type="text", text=_format_response({"key": key, "written": True}))]

        elif name == "storage_delete":
            storage = await get_storage()
            key = arguments["key"]
            existed = await storage.delete(key)
            return [TextContent(type="text", text=_format_response({"key": key, "existed": existed}))]

        elif name == "storage_keys":
            storage = await get_storage()
            keys = await storage.keys()
            return [TextContent(type="text", text=_format_response({"keys": keys, "count": len(keys)}))]

        elif name == "storage_clear":
            if not arguments.get("confirm", False):
                return [TextContent(type="text", text=_format_response({"cleared": False}, success=False, error="Must set confirm=true to clear all data"))]
            storage = await get_storage()
            await storage.clear()
            return [TextContent(type="text", text=_format_response({"cleared": True}))]

        elif name == "health_check":
            redis = await get_redis()
            healthy = await redis.health_check()
            result = {
                "status": "healthy" if healthy else "unhealthy",
                "redis": "connected" if healthy else "disconnected",
            }
            return [TextContent(type="text", text=_format_response(result))]

        elif name == "redis_info":
            redis = await get_redis()
            await redis._ensure_pool()
            section = arguments.get("section", "default")
            info = await redis.client.info(section)
            # Convert bytes keys to strings
            result = {}
            for k, v in info.items():
                key = k.decode() if isinstance(k, bytes) else k
                result[key] = v
            return [TextContent(type="text", text=_format_response(result))]

        elif name == "redis_ping":
            redis = await get_redis()
            result = await redis.health_check()
            return [TextContent(type="text", text=_format_response({"ping": "pong" if result else "failed"}))]

        elif name == "obj_get":
            from .objstorage.redisobjstore import RedisObjectStorage
            obj_store = RedisObjectStorage()
            try:
                value = await obj_store.retrieve_with_pickle(arguments["key"])
                return [TextContent(type="text", text=_format_response({"key": arguments["key"], "value": value}))]
            finally:
                await obj_store.close()

        elif name == "obj_list":
            from .objstorage.redisobjstore import RedisObjectStorage
            obj_store = RedisObjectStorage()
            try:
                pattern = arguments.get("pattern", "*")
                keys = await obj_store.list_keys(pattern)
                return [TextContent(type="text", text=_format_response({"keys": keys, "count": len(keys)}))]
            finally:
                await obj_store.close()

        elif name == "obj_delete":
            from .objstorage.redisobjstore import RedisObjectStorage
            obj_store = RedisObjectStorage()
            try:
                pattern = arguments["pattern"]
                count = await obj_store.delete_keys(pattern)
                return [TextContent(type="text", text=_format_response({"deleted": count}))]
            finally:
                await obj_store.close()

        else:
            return [TextContent(type="text", text=_format_response(None, success=False, error=f"Unknown tool: {name}"))]

    except Exception as e:
        logger.error(f"Tool {name} failed: {e}", exc_info=True)
        return [TextContent(type="text", text=_format_response(None, success=False, error=str(e)))]


# =============================================================================
# RESOURCES
# =============================================================================

@server.list_resources()
async def list_resources() -> list[Resource]:
    """List available StreamMachine resources."""
    return [
        Resource(
            uri="streammachine://config",
            name="StreamMachine Configuration",
            description="Current configuration and environment variables",
            mimeType="application/json",
        ),
        Resource(
            uri="streammachine://status",
            name="StreamMachine Status",
            description="Current status of connections and storage",
            mimeType="application/json",
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """Read a resource by URI."""
    import os

    if uri == "streammachine://config":
        config = {
            "redis_url": os.environ.get("REDIS_URL", "redis://localhost:6379"),
            "redis_host": os.environ.get("REDIS_HOST", "localhost"),
            "redis_port": int(os.environ.get("REDIS_PORT", "6379")),
            "redis_db": int(os.environ.get("REDIS_DB", "0")),
            "redis_max_connections": int(os.environ.get("REDIS_MAX_CONNECTIONS", "10")),
            "default_records": int(os.environ.get("STREAMMACHINE_RECORDS", "10000")),
            "default_count": int(os.environ.get("STREAMMACHINE_COUNT", "10")),
            "default_group": os.environ.get("STREAMMACHINE_DEFAULT_GROUP", "eventengine"),
        }
        return json.dumps(config, indent=2)

    elif uri == "streammachine://status":
        redis = await get_redis()
        storage = await get_storage()
        try:
            redis_healthy = await redis.health_check()
        except Exception:
            redis_healthy = False

        try:
            storage_keys = await storage.keys()
        except Exception:
            storage_keys = []

        status = {
            "redis": {
                "connected": redis_healthy,
                "status": "connected" if redis_healthy else "disconnected",
            },
            "storage": {
                "keys": len(storage_keys),
                "keys_list": storage_keys[:100],  # Limit to first 100
            },
        }
        return json.dumps(status, indent=2)

    else:
        raise ValueError(f"Unknown resource: {uri}")


# =============================================================================
# PROMPTS
# =============================================================================

@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List available prompts."""
    return [
        Prompt(
            name="streammachine-guide",
            description="A guide for using StreamMachine through this MCP server",
            arguments=[],
        ),
        Prompt(
            name="stream-processing-patterns",
            description="Common stream processing patterns and how to implement them",
            arguments=[],
        ),
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str]) -> GetPromptResult:
    """Get a prompt by name."""
    from mcp.types import PromptMessage

    if name == "streammachine-guide":
        return GetPromptResult(
            description="Guide for using StreamMachine MCP Server",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text="""I want to use StreamMachine for stream processing. Please help me:

1. Understand what streams exist
2. Send test messages to a stream
3. Read messages from a stream
4. Use shared storage for state management

Guide me through the process.""",
                    ),
                ),
            ],
        )

    elif name == "stream-processing-patterns":
        return GetPromptResult(
            description="Common stream processing patterns",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text="""Explain these common stream processing patterns and how to implement them with StreamMachine:

1. Producer-Consumer: One producer sends work, one or more consumers process it
2. Pipeline: Multiple stages of processing chained together
3. Fan-Out: Multiple consumer groups receive the same messages
4. Aggregation: Combining multiple messages into summaries
5. Time Windows: Processing data within time boundaries

Show examples of how to use the MCP tools for each pattern.""",
                    ),
                ),
            ],
        )

    else:
        raise ValueError(f"Unknown prompt: {name}")


# =============================================================================
# MAIN
# =============================================================================

async def run_server():
    """Run the MCP server."""
    logger.info("Starting StreamMachine MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """Entry point for the MCP server."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()