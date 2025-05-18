import asyncio
import coredis
from coredis import Redis
from coredis.stream import GroupConsumer
from typing import List, AnyStr, Optional
import time

class RedisConnection:
    """
    Async Redis connection manager using coredis with connection pooling.
    Provides consumer group support for Redis Streams.
    """
    def __init__(self, host: str = '127.0.0.1', port: int = 6379, db: int = 0):
        # Use connection pooling for speed
        self.client: Redis = coredis.Redis(host=host, port=port, db=db, max_connections=10)

    #consumer init
    async def consumer(self, channel: List[str], consumer: str, group: str) -> GroupConsumer:
        """
        Create a Redis stream group consumer for the given channels.
        """
        if isinstance(channel, str):
            channel = [channel]
        return await GroupConsumer(
            self.client,
            streams=channel,
            group=group,
            consumer=consumer,
            auto_acknowledge=True,
            start_from_backlog=False
        )

    async def pipeline_xadd(self, topic: str, records: List[dict]) -> List:
        """
        Batch add multiple records to a Redis stream using pipeline for speed.
        """
        async with self.client.pipeline() as pipe:
            for record in records:
                await pipe.xadd(topic, record)
            return await pipe.execute()

    # --- Cythonization candidates ---
    # If you have any CPU-bound data processing, mark here for Cythonization.
    # Example:
    # def heavy_processing(...):
    #     ... # Move to .pyx and use nogil for true parallelism

async def tests():

    rc = RedisConnection()

    await rc.client.flushdb()

    async def producer():
        while True:
            [await rc.client.xadd("channel", {"id": i}) for i in range(11)]
            await asyncio.sleep(1)

    async def consumer():
        # fetch all ten entries and simulate a bug occurring 50% of the time
        # when processing the entry
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

#asyncio.run(tests())