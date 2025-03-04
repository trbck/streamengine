
import asyncio
import logging
import random
import signal
import string
import uuid
import time
import uvloop
import ujson

import inspect
import venusian

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from signal import signal, SIGINT

#eventengine app imports
from util import Registry, AgentTaskDecorator, TimerTaskDecorator
from models import AppConfig, ConsumerConfig, TimerConfig, StreamTopic, Message, REDIS_CONNECTION_STRING, RECORDS, COUNT
from redisapi import RedisConnection
import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


class App():
    """
    Python Stream Processing with Redis Streams.
    App and entry point of streamengine. 
    """

    def __init__(self,
                 name=__name__,
                 to_scan=True,
                 max_processes=5,
                 max_threads=5):
        self.config = AppConfig(name, to_scan, max_processes, max_threads)
        self.process_pool = ProcessPoolExecutor(max_workers=max_processes)
        self.thread_pool = ThreadPoolExecutor(max_workers=max_threads)
        self.loop = None

        self.global_tasks = []

        # Venusian autodiscovery of agent and timer tasks (decorators).
        self.registry = Registry()

        # Decorator classes
        self.agent = AgentTaskDecorator
        self.timer = TimerTaskDecorator
        #self.maintenencetimer = MaintenanceTaskDecorator
        
        #redis connection
        self.rc = RedisConnection()
        # Start the storage manager
        self.storage = storage.Storage()

    def _discover(self):
        if self.config.to_scan == True:
            """ 
            Get App calling module path to let venusian scanner 
            know where to check for decoraters and functions.
            Get last frame by:[len(inspect.stack()) - 1]
            """
            frm = inspect.stack()[len(inspect.stack()) - 1]
            mod = inspect.getmodule(frm[0])
            scanner = venusian.Scanner(registry=self.registry)
            scanner.scan(mod)
            #scanner.scan(inspect.getmodule(helpers))

    def _get_concurrent_agents(self):
        # Get registered agent functions and concurrency count.
        # Return list of consumer agent functions for loop.
        return [
            agent_container(item) for item in self.registry.registered
            if item.decorator_type == "agent" and item.processes == None
            for sub in range(item.concurrency)
        ]

    def _get_timers(self):
        # Get registered agent functions and concurrency count.
        # Return list of consumer agent functions for loop.
        return [
            timer_container(item) for item in self.registry.registered
            if item.decorator_type == "timer"
        ]

    def _get_multiprocesses_concurrent_agents(self):
        # Get registered agent functions and concurrency count.
        # Return list of consumer agent functions for loop.
        return [
            item for item in self.registry.registered
            if item.decorator_type == "agent" and item.processes != None
            for sub in range(item.concurrency)
        ]

    def start(self):
        """Entry point."""
        # Get calling script decorators and inner function details.
        self._discover()

        agents = self._get_concurrent_agents()
        timers = self._get_timers()
        
        # Add maintenance task here
        self.global_tasks.append(maintenance_task())

        asyncio.set_event_loop(uvloop.new_event_loop())
        self.loop = asyncio.get_event_loop()
        
        tasks = []
        tasks.extend(self.global_tasks)
        tasks.extend(timers)
        tasks.extend(agents)
        

        for task in tasks:
            asyncio.ensure_future(task)

        #add storage
        asyncio.ensure_future(self.storage.start())

        try:
            self.loop.run_forever()
        except:
            self.loop.stop()

    async def send(self, topic, record):
        t = time.time()
        record["sent"] = t
        return await self.rc.client.xadd(topic, record)
    

    async def shutdown(self):
        """Cleanup tasks tied to the service's shutdown."""
        logging.info(f"Received exit signal...")
        tasks = [t for t in asyncio.all_tasks() if t is not
                asyncio.current_task()]

        [task.cancel() for task in tasks]

        logging.info(f"Cancelling {len(tasks)} outstanding tasks")
        await asyncio.gather(*tasks, return_exceptions=True)
        self.loop.stop()


async def agent_container(item):
    # Consumer container from StreamConsumer class
    # https://stackoverflow.com/questions/33128325/how-to-set-class-attribute-with-await-in-init
    agent = StreamConsumer(item)
    return await agent()

async def timer_container(item):
    # Consumer container
    while True:
        await asyncio.sleep(item.t)
        await getattr(item.mod, item.obj_name)()
        
class StreamConsumer:
    # Consumer class to perform redis stream commmunications.
    def __init__(self, config: ConsumerConfig):
        self.config = config
        # aioredis is expecting stream(s) to be sent as a list.
        if isinstance(self.config.topic, str):
            self.config.topic = [self.config.topic]

    async def __call__(self):
        """"
        ConsumerConfig(decorator_type='agent', 
        topic=['test_channel'], 
        group='test', 
        concurrency=1, 
        processes=None, 
        obj_name='job1', 
        inner_vars=<Signature (record)>, 
        mod=<module '__main__' from '/home/trbck/scripts/eventengine/example.py'>)
        """

        # Create unique consumer id.
        consumer_id = str(uuid.uuid4())

        # Create a redis connection.
        self.rc = RedisConnection()

        cons = await self.rc.consumer(self.config.topic, consumer_id, self.config.group)
    
        while True:
            async for stream, entry in cons:

                m = Message(topic=stream.decode("UTF-8"),
                            key=entry.identifier.decode("UTF-8"),
                            received=time.time(),
                            consumer_id=consumer_id,
                            data=entry.field_values)
                
                if b'sent' in entry.field_values:
                    m.sent = float(entry.field_values[b'sent'])
                    del entry.field_values[b'sent']
                else:
                    pass

                #execute agent function
                result = await getattr(self.config.mod,
                                        self.config.obj_name)(m)
                

async def maintenance_task():
    while True:
        await asyncio.sleep(1)
        #rc = RedisConnection()
        #[await rc.client.xadd("test_channel", {"id": i, "test": 12}) for i in range(1)]
        pass


        
if __name__ == "__main__":
    pass





def main():
    loop = asyncio.get_event_loop()
    # May want to catch other signals too
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(
            s, lambda s=s: asyncio.create_task(shutdown(s, loop)))

if __name__ == "__main__":
    main()