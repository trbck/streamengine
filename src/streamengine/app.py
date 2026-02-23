from __future__ import annotations

import asyncio
import logging
import signal
import uuid
import time
import uvloop
import inspect
import venusian
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any, Callable, List, Optional, Set

from .util import Registry, AgentTaskDecorator, TimerTaskDecorator
from .models import (
    AppConfig,
    ConsumerConfig,
    TimerConfig,
    StreamTopic,
    Message,
    DEFAULT_CONSUMER_GROUP,
)
from .redisapi import RedisConnection
from . import storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(levelname)s [%(name)s]: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Set uvloop as the default event loop policy
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


class App:
    """
    Python Stream Processing with Redis Streams.

    Main application class that manages the event loop, task discovery,
    and lifecycle of stream consumers and timers.

    Example:
        app = App(name="my_app")

        @app.timer(1)
        async def my_timer():
            await app.send("topic", {"data": "value"})

        @app.agent("topic", group="my_group")
        async def my_agent(record: Message):
            print(record)

        if __name__ == "__main__":
            app.start()
    """

    def __init__(
        self,
        name: str = __name__,
        to_scan: bool = True,
        max_processes: int = 5,
        max_threads: int = 5,
    ):
        """
        Initialize the StreamEngine application.

        Args:
            name: Application name for logging
            to_scan: Whether to scan for decorated tasks
            max_processes: Maximum number of process pool workers
            max_threads: Maximum number of thread pool workers
        """
        self.config = AppConfig(name, to_scan, max_processes, max_threads)
        self.process_pool = ProcessPoolExecutor(max_workers=max_processes)
        self.thread_pool = ThreadPoolExecutor(max_workers=max_threads)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown_event = asyncio.Event()
        self._running_tasks: Set[asyncio.Task] = set()
        self.registry = Registry()
        self.agent = AgentTaskDecorator
        self.timer = TimerTaskDecorator
        self.rc = RedisConnection()
        self.storage = storage.Storage()
        self._is_shutting_down = False

    def _discover(self) -> None:
        """Discover decorated agents and timers using Venusian scanner."""
        if self.config.to_scan:
            frm = inspect.stack()[len(inspect.stack()) - 1]
            mod = inspect.getmodule(frm[0])
            if mod is not None:
                scanner = venusian.Scanner(registry=self.registry)
                scanner.scan(mod)
                logger.info(
                    f"Discovered {len(self.registry.registered)} tasks: "
                    f"{sum(1 for t in self.registry.registered if t.decorator_type == 'agent')} agents, "
                    f"{sum(1 for t in self.registry.registered if t.decorator_type == 'timer')} timers"
                )

    def _get_concurrent_agents(self) -> List[Callable[[], Any]]:
        """Get list of agent coroutines to run."""
        return [
            agent_container(item)
            for item in self.registry.registered
            if item.decorator_type == "agent" and item.processes is None
            for _ in range(item.concurrency)
        ]

    def _get_timers(self) -> List[Callable[[], Any]]:
        """Get list of timer coroutines to run."""
        return [
            timer_container(item, self._shutdown_event)
            for item in self.registry.registered
            if item.decorator_type == "timer"
        ]

    def _get_multiprocesses_concurrent_agents(self) -> List[Any]:
        """Get list of agents configured for multiprocess execution."""
        return [
            item
            for item in self.registry.registered
            if item.decorator_type == "agent" and item.processes is not None
            for _ in range(item.concurrency)
        ]

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        if self.loop is None:
            return

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self.loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self._handle_signal(s))
                )
                logger.debug(f"Registered handler for signal {sig.name}")
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                logger.warning(f"Cannot register signal handler for {sig.name} on this platform")

    async def _handle_signal(self, sig: signal.Signals) -> None:
        """Handle shutdown signals gracefully."""
        if self._is_shutting_down:
            logger.info("Already shutting down, ignoring signal")
            return

        self._is_shutting_down = True
        logger.info(f"Received signal {sig.name}, initiating graceful shutdown...")
        await self.shutdown()

    def start(self) -> None:
        """
        Start the application event loop.

        This is the main entry point that discovers tasks, sets up signal handlers,
        and runs the event loop until shutdown is requested.
        """
        self._discover()
        agents = self._get_concurrent_agents()
        timers = self._get_timers()

        asyncio.set_event_loop(uvloop.new_event_loop())
        self.loop = asyncio.get_event_loop()

        # Set up signal handlers
        self._setup_signal_handlers()

        # Create and schedule all tasks
        all_coros = [maintenance_task(self._shutdown_event)]
        all_coros.extend(timers)
        all_coros.extend(agents)
        all_coros.append(self.storage.start())

        for coro in all_coros:
            task = asyncio.ensure_future(coro)
            self._running_tasks.add(task)
            task.add_done_callback(self._running_tasks.discard)

        logger.info(
            f"Starting {len(agents)} agents and {len(timers)} timers "
            f"(total tasks: {len(self._running_tasks)})"
        )

        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received")
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        """Clean up resources after event loop stops."""
        logger.info("Cleaning up resources...")

        # Shutdown executors
        try:
            self.process_pool.shutdown(wait=False)
            self.thread_pool.shutdown(wait=False)
        except Exception as e:
            logger.warning(f"Error shutting down executors: {e}")

        # Close event loop
        if self.loop and not self.loop.is_closed():
            self.loop.close()

        logger.info("Cleanup complete")

    async def send(self, topic: str, record: dict) -> Any:
        """
        Send a single record to a Redis stream.

        Args:
            topic: Stream name
            record: Record data as a dictionary

        Returns:
            Message ID from Redis
        """
        t = time.time()
        record["sent"] = t
        return await self.rc.client.xadd(topic, record)

    async def send_batch(self, topic: str, records: List[dict]) -> List:
        """
        Batch send multiple records to a Redis stream.

        Args:
            topic: Stream name
            records: List of record dictionaries

        Returns:
            List of message IDs from Redis
        """
        t = time.time()
        for record in records:
            record["sent"] = t
        return await self.rc.pipeline_xadd(topic, records)

    async def shutdown(self) -> None:
        """
        Gracefully shutdown all running tasks.

        Cancels all running tasks and waits for them to complete,
        then stops the event loop.
        """
        self._shutdown_event.set()
        logger.info("Shutting down...")

        # Get all tasks except current
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

        if tasks:
            logger.info(f"Cancelling {len(tasks)} outstanding tasks...")
            for task in tasks:
                task.cancel()

            # Wait for all tasks to complete (with timeout)
            done, pending = await asyncio.wait(
                tasks,
                timeout=10.0,
                return_when=asyncio.ALL_COMPLETED
            )

            if pending:
                logger.warning(f"{len(pending)} tasks did not complete in time")

        # Close Redis connection
        try:
            await self.rc.close()
            logger.debug("Redis connection closed")
        except Exception as e:
            logger.warning(f"Error closing Redis connection: {e}")

        # Stop the event loop
        if self.loop:
            self.loop.stop()

        logger.info("Shutdown complete")

    async def health_check(self) -> dict:
        """
        Perform a health check of the application.

        Returns:
            Dictionary with health status information
        """
        redis_healthy = await self.rc.health_check()

        return {
            "status": "healthy" if redis_healthy else "degraded",
            "redis": "connected" if redis_healthy else "disconnected",
            "active_tasks": len(self._running_tasks),
            "registered_agents": sum(
                1 for t in self.registry.registered if t.decorator_type == "agent"
            ),
            "registered_timers": sum(
                1 for t in self.registry.registered if t.decorator_type == "timer"
            ),
        }


async def agent_container(item: ConsumerConfig) -> Any:
    """
    Create and run an agent consumer.

    Args:
        item: Consumer configuration

    Returns:
        Result of the agent (typically runs forever)
    """
    agent = StreamConsumer(item)
    return await agent()


async def timer_container(item: TimerConfig, shutdown_event: asyncio.Event) -> None:
    """
    Run a timer task periodically until shutdown is requested.

    Args:
        item: Timer configuration
        shutdown_event: Event to signal shutdown
    """
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=item.t)
            # If we get here, shutdown was requested
            break
        except asyncio.TimeoutError:
            # Timeout means it's time to run the timer
            pass

        try:
            await getattr(item.mod, item.obj_name)()
        except Exception as e:
            logger.error(f"Timer {item.obj_name} failed: {e}", exc_info=True)


class StreamConsumer:
    """
    Redis Stream consumer that processes messages from one or more streams.

    Each consumer creates its own Redis connection and consumer group membership,
    processing messages and passing them to the configured handler function.
    """

    def __init__(self, config: ConsumerConfig):
        """
        Initialize the stream consumer.

        Args:
            config: Consumer configuration including topic, group, and handler
        """
        self.config = config
        if isinstance(self.config.topic, str):
            self.config.topic = [self.config.topic]
        self._rc: Optional[RedisConnection] = None

    async def __call__(self) -> None:
        """Run the consumer loop, processing messages indefinitely."""
        consumer_id = str(uuid.uuid4())
        self._rc = RedisConnection()
        group = self.config.group or DEFAULT_CONSUMER_GROUP

        logger.info(f"Starting consumer {consumer_id} for {self.config.topic} in group {group}")

        try:
            cons = await self._rc.consumer(
                self.config.topic,
                consumer_id,
                group
            )

            async for stream, entry in cons:
                try:
                    await self._process_message(stream, entry, consumer_id)
                except Exception as e:
                    logger.error(
                        f"Error processing message from {stream}: {e}",
                        exc_info=True
                    )
                    # Continue processing next messages
                await asyncio.sleep(0)  # Yield to event loop
        except asyncio.CancelledError:
            logger.info(f"Consumer {consumer_id} cancelled")
        except Exception as e:
            logger.error(f"Consumer {consumer_id} error: {e}", exc_info=True)
        finally:
            if self._rc:
                await self._rc.close()

    async def _process_message(self, stream: bytes, entry: Any, consumer_id: str) -> None:
        """
        Process a single message from the stream.

        Args:
            stream: Stream name as bytes
            entry: Message entry from Redis
            consumer_id: Consumer identifier
        """
        m = Message(
            topic=stream.decode("UTF-8"),
            key=entry.identifier.decode("UTF-8"),
            received=time.time(),
            consumer_id=consumer_id,
            data=entry.field_values
        )

        # Extract sent timestamp if present
        if b'sent' in entry.field_values:
            m.sent = float(entry.field_values[b'sent'])
            # Don't delete from field_values to avoid mutation issues
            # del entry.field_values[b'sent']

        # Call the handler
        handler = getattr(self.config.mod, self.config.obj_name)
        await handler(m)


async def maintenance_task(shutdown_event: asyncio.Event) -> None:
    """
    Run periodic maintenance tasks.

    Args:
        shutdown_event: Event to signal shutdown
    """
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=60.0)
            # Shutdown was requested
            break
        except asyncio.TimeoutError:
            # Time for maintenance
            pass

        # Add maintenance logic here
        # e.g., cleanup old messages, update metrics, health checks
        logger.debug("Running maintenance task")


# Public API
__all__ = [
    "App",
    "StreamConsumer",
    "Message",
    "AppConfig",
    "ConsumerConfig",
    "TimerConfig",
    "StreamTopic",
    "agent_container",
    "timer_container",
    "maintenance_task",
]


if __name__ == "__main__":
    # This module is not meant to be run directly.
    # Use example.py or create your own entry point.
    print("Run 'python example.py' to start the application.")