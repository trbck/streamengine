from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

import coredis
from coredis import Redis
from coredis.patterns.streams import GroupConsumer

from .models import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_MAX_CONNECTIONS,
    REDIS_CONNECTION_STRING,
)

logger = logging.getLogger(__name__)


class RedisConnection:
    """
    Async Redis connection manager using coredis with connection pooling.
    Provides consumer group support for Redis Streams.

    Can be initialized with individual parameters or a connection URL.
    Supports async context manager protocol for proper resource cleanup.

    Example:
        async with RedisConnection() as rc:
            await rc.client.set("key", "value")

        # Or with URL:
        rc = RedisConnection(url="redis://localhost:6379/0")
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: Optional[int] = None,
        max_connections: Optional[int] = None,
        url: Optional[str] = None,
    ):
        """
        Initialize Redis connection.

        Args:
            host: Redis host (default from REDIS_HOST env var)
            port: Redis port (default from REDIS_PORT env var)
            db: Redis database number (default from REDIS_DB env var)
            max_connections: Max connection pool size (default from REDIS_MAX_CONNECTIONS env var)
            url: Redis connection URL (overrides individual params if provided)
        """
        self._url = url or REDIS_CONNECTION_STRING
        self._host = host or REDIS_HOST
        self._port = port or REDIS_PORT
        self._db = db if db is not None else REDIS_DB
        self._max_connections = max_connections or REDIS_MAX_CONNECTIONS

        if url:
            # Parse URL and create client from it
            self.client: Redis[bytes] = coredis.Redis.from_url(
                url,
                max_connections=self._max_connections
            )
        else:
            self.client: Redis[bytes] = coredis.Redis(
                host=self._host,
                port=self._port,
                db=self._db,
                max_connections=self._max_connections
            )

    async def __aenter__(self) -> "RedisConnection":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Async context manager exit - close connection."""
        await self.close()
        return False

    async def close(self) -> None:
        """Close the Redis connection pool."""
        await self.client.close()
        logger.debug("Redis connection closed")

    async def consumer(
        self,
        channel: List[str],
        consumer: str,
        group: str,
        start_from_backlog: bool = False,
        auto_acknowledge: bool = True,
    ) -> GroupConsumer:
        """
        Create a Redis stream group consumer for the given channels.

        Args:
            channel: List of stream names to consume from
            consumer: Unique consumer identifier
            group: Consumer group name
            start_from_backlog: Whether to start from pending messages
            auto_acknowledge: Whether to auto-ack messages after processing

        Returns:
            GroupConsumer instance for iterating over messages
        """
        if isinstance(channel, str):
            channel = [channel]
        return await GroupConsumer(
            self.client,
            streams=channel,
            group=group,
            consumer=consumer,
            auto_acknowledge=auto_acknowledge,
            start_from_backlog=start_from_backlog
        )

    async def pipeline_xadd(self, topic: str, records: List[dict]) -> List:
        """
        Batch add multiple records to a Redis stream using pipeline for speed.

        Args:
            topic: Stream name
            records: List of record dictionaries to add

        Returns:
            List of message IDs from the XADD commands
        """
        async with self.client.pipeline() as pipe:
            for record in records:
                await pipe.xadd(topic, record)
            return await pipe.execute()

    async def health_check(self) -> bool:
        """
        Check if Redis connection is healthy.

        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            await self.client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False


async def tests():
    """Test Redis connection functionality."""
    rc = RedisConnection()

    await rc.client.flushdb()

    async def producer():
        while True:
            [await rc.client.xadd("channel", {"id": i}) for i in range(11)]
            await asyncio.sleep(1)

    async def consumer():
        cons = await rc.consumer("channel", "consumer1", "group")

        while True:
            async for stream, entry in cons:
                print(stream)
                print(entry)

    res1, res2 = await asyncio.gather(
        producer(),
        consumer()
    )

    print("##################################################################################")
    print("test done")
    print("##################################################################################")

    await rc.close()


# asyncio.run(tests())