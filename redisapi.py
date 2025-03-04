
import asyncio
import coredis
from coredis import Redis
from coredis.stream import GroupConsumer
from typing import List, AnyStr
import time

class RedisConnection:
    def __init__(self):
        #client init
        self.client = coredis.Redis(host='127.0.0.1', port=6379, db=0)

    #consumer init
    async def consumer(self, channel: List, consumer: AnyStr, group: AnyStr):
        if isinstance(channel, str):
            channel = [channel]

        return await GroupConsumer(
                self.client,
                streams = channel,
                group = group,
                consumer = consumer,
                auto_acknowledge = True,
                start_from_backlog = False
            )



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