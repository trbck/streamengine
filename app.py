import asyncio
import logging
import signal
import uuid
import time
import uvloop
import inspect
import venusian
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from signal import signal as sig_signal, SIGINT
from typing import Any, Callable, List, Optional

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

class App:
    """
    Python Stream Processing with Redis Streams.
    App and entry point of streamengine.
    """
    def __init__(self, name: str = __name__, to_scan: bool = True, max_processes: int = 5, max_threads: int = 5):
        self.config = AppConfig(name, to_scan, max_processes, max_threads)
        self.process_pool = ProcessPoolExecutor(max_workers=max_processes)
        self.thread_pool = ThreadPoolExecutor(max_workers=max_threads)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.global_tasks: List[asyncio.Task] = []
        self.registry = Registry()
        self.agent = AgentTaskDecorator
        self.timer = TimerTaskDecorator
        self.rc = RedisConnection()
        self.storage = storage.Storage()

    def _discover(self) -> None:
        if self.config.to_scan:
            frm = inspect.stack()[len(inspect.stack()) - 1]
            mod = inspect.getmodule(frm[0])
            scanner = venusian.Scanner(registry=self.registry)
            scanner.scan(mod)

    def _get_concurrent_agents(self) -> List[Callable[[], Any]]:
        return [
            agent_container(item) for item in self.registry.registered
            if item.decorator_type == "agent" and item.processes is None
            for _ in range(item.concurrency)
        ]

    def _get_timers(self) -> List[Callable[[], Any]]:
        return [
            timer_container(item) for item in self.registry.registered
            if item.decorator_type == "timer"
        ]

    def _get_multiprocesses_concurrent_agents(self) -> List[Any]:
        return [
            item for item in self.registry.registered
            if item.decorator_type == "agent" and item.processes is not None
            for _ in range(item.concurrency)
        ]

    def start(self) -> None:
        """Entry point."""
        self._discover()
        agents = self._get_concurrent_agents()
        timers = self._get_timers()
        self.global_tasks.append(maintenance_task())
        asyncio.set_event_loop(uvloop.new_event_loop())
        self.loop = asyncio.get_event_loop()
        tasks: List[asyncio.Task] = []
        tasks.extend(self.global_tasks)
        tasks.extend(timers)
        tasks.extend(agents)
        for task in tasks:
            asyncio.ensure_future(task)
        asyncio.ensure_future(self.storage.start())
        try:
            self.loop.run_forever()
        except Exception:
            self.loop.stop()

    async def send(self, topic: str, record: dict) -> Any:
        t = time.time()
        record["sent"] = t
        return await self.rc.client.xadd(topic, record)

    async def send_batch(self, topic: str, records: List[dict]) -> List:
        """Batch send records to a Redis stream for speed."""
        t = time.time()
        for record in records:
            record["sent"] = t
        return await self.rc.pipeline_xadd(topic, records)

    async def shutdown(self) -> None:
        """Cleanup tasks tied to the service's shutdown."""
        logging.info(f"Received exit signal...")
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        [task.cancel() for task in tasks]
        logging.info(f"Cancelling {len(tasks)} outstanding tasks")
        await asyncio.gather(*tasks, return_exceptions=True)
        self.loop.stop()

async def agent_container(item: ConsumerConfig) -> Any:
    agent = StreamConsumer(item)
    return await agent()

async def timer_container(item: TimerConfig) -> None:
    while True:
        await asyncio.sleep(item.t)
        await getattr(item.mod, item.obj_name)()

class StreamConsumer:
    """
    Consumer class to perform redis stream communications.
    """
    def __init__(self, config: ConsumerConfig):
        self.config = config
        if isinstance(self.config.topic, str):
            self.config.topic = [self.config.topic]
    async def __call__(self) -> None:
        consumer_id = str(uuid.uuid4())
        self.rc = RedisConnection()
        cons = await self.rc.consumer(self.config.topic, consumer_id, self.config.group)
        while True:
            async for stream, entry in cons:
                m = Message(
                    topic=stream.decode("UTF-8"),
                    key=entry.identifier.decode("UTF-8"),
                    received=time.time(),
                    consumer_id=consumer_id,
                    data=entry.field_values
                )
                if b'sent' in entry.field_values:
                    m.sent = float(entry.field_values[b'sent'])
                    del entry.field_values[b'sent']
                result = await getattr(self.config.mod, self.config.obj_name)(m)
                await asyncio.sleep(0)  # Yield to event loop for lowest latency

async def maintenance_task() -> None:
    while True:
        await asyncio.sleep(60)  # Maintenance interval
        # Add maintenance logic here

# --- Cythonization candidates ---
# If you have any CPU-bound data processing, mark here for Cythonization.
# Example:
# def heavy_processing(...):
#     ... # Move to .pyx and use nogil for true parallelism

if __name__ == "__main__":
    main()