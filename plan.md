# StreamMachine Code Review & Improvement Plan

## Executive Summary

StreamMachine is a well-architected async-first Python framework for distributed stream processing using Redis Streams. The codebase demonstrates good use of modern Python features (dataclasses, type hints, asyncio). However, there are several areas for improvement ranging from critical bug fixes to code quality enhancements.

---

## Critical Issues (Must Fix)

### 1. Missing `main()` Function in `app.py`
**Location:** `app.py:158`

```python
if __name__ == "__main__":
    main()  # main() is not defined!
```

**Issue:** The `main()` function is called but never defined. This will raise a `NameError` when running `app.py` directly.

**Fix:** Either define `main()` or remove the block:
```python
if __name__ == "__main__":
    # Option 1: Define main
    main()

    # Option 2: Remove entirely (app.py is not meant to be run directly)
```

---

### 2. Undefined `helpers` Variable in `util.py`
**Location:** `util.py:42` and `util.py:69`

```python
me.config.mod = inspect.getmodule(helpers)  # helpers is not defined!
```

**Issue:** The `helpers` variable is referenced but never imported or defined. This will cause a `NameError` when `helper=True` is passed to decorators.

**Fix:** Either remove the `helper` parameter or define the helpers module:
```python
# Option 1: Remove the helper parameter entirely
# Option 2: Import helpers module
from . import helpers  # or wherever helpers module is located
```

---

### 3. Undefined `value1` Variable in `example.py`
**Location:** `example.py:31-33`

```python
@app.agent("test_channel1", concurrency=1, group="test")
async def job2(record: Message):
    # value1 = await app.storage.read('key1')  # commented out
    # ...
    print(f"[job2] Value: {value1} | Message: {record}")  # value1 undefined!
```

**Issue:** `value1` is commented out but still used in the print statement. This will raise a `NameError`.

**Fix:** Uncomment the line or remove the reference:
```python
value1 = await app.storage.read('key1')
# or remove value1 from the print statement
```

---

### 4. Redis Lock Import Error in `objstorage/redisobjstore.py`
**Location:** `objstorage/redisobjstore.py:20`

```python
lock = redis.lock.Lock(self.redis_client, f"lock:{key}")
```

**Issue:** `redis.lock.Lock` is incorrect usage. The correct import is `redis.asyncio.Lock`.

**Fix:**
```python
from redis.asyncio import Lock

lock = Lock(self.redis_client, f"lock:{key}")
# or use the redis-py recommended approach:
lock = self.redis_client.lock(f"lock:{key}")
```

---

## High Priority Improvements

### 5. Missing Dependencies File
**Issue:** No `requirements.txt`, `pyproject.toml`, or `setup.py` for dependency management.

**Recommendation:** Create `pyproject.toml`:
```toml
[project]
name = "streammachine"
version = "0.1.0"
description = "High-performance async stream processing with Redis Streams"
requires-python = ">=3.8"
dependencies = [
    "coredis>=4.0.0",
    "uvloop>=0.17.0",
    "venusian>=3.0.0",
    "pandas>=1.5.0",
    "numpy>=1.23.0",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "black", "mypy", "ruff"]
cython = ["cython"]
fast-json = ["ujson", "orjson"]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"
```

---

### 6. Hardcoded Redis Connection String
**Location:** `models.py:15`

```python
REDIS_CONNECTION_STRING: str = "redis://localhost:6379"
```

**Issue:** Hardcoded connection string makes configuration inflexible.

**Recommendation:** Use environment variables:
```python
import os

REDIS_CONNECTION_STRING = os.getenv(
    "REDIS_URL",
    "redis://localhost:6379"
)
```

And in `RedisConnection`:
```python
def __init__(self, url: Optional[str] = None):
    url = url or REDIS_CONNECTION_STRING
    self.client = coredis.Redis.from_url(url, max_connections=10)
```

---

### 7. No Graceful Shutdown Handling
**Location:** `app.py:85-88`

```python
try:
    self.loop.run_forever()
except Exception:
    self.loop.stop()
```

**Issue:** Exception handling is too broad and doesn't properly clean up resources.

**Recommendation:** Implement proper signal handling:
```python
import signal

def start(self) -> None:
    self._discover()
    # ... setup code ...

    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        self.loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(self.shutdown())
        )

    try:
        self.loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        self._cleanup()

async def shutdown(self) -> None:
    logging.info("Shutting down...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    # Close resources
    await self.rc.client.close()
    self.process_pool.shutdown(wait=True)
    self.thread_pool.shutdown(wait=True)
    self.loop.stop()
```

---

### 8. Storage Singleton Thread Safety Issue
**Location:** `storage.py:13-17`

```python
def __new__(cls) -> 'Storage':
    if cls._instance is None:
        cls._instance = super(Storage, cls).__new__(cls)
        cls._instance.init_storage()
    return cls._instance
```

**Issue:** Not thread-safe. Two threads could create instances simultaneously.

**Recommendation:** Use a lock:
```python
import threading

class Storage:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls) -> 'Storage':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:  # Double-check
                    cls._instance = super().__new__(cls)
                    cls._instance.init_storage()
        return cls._instance
```

---

### 9. Missing Message Acknowledgment on Error
**Location:** `app.py:132-145`

```python
while True:
    async for stream, entry in cons:
        m = Message(...)
        result = await getattr(self.config.mod, self.config.obj_name)(m)
        await asyncio.sleep(0)
```

**Issue:** If the handler raises an exception, the message is not reprocessed (due to `auto_acknowledge=True`). Consider error handling and retry logic.

**Recommendation:**
```python
MAX_RETRIES = 3

async def __call__(self) -> None:
    consumer_id = str(uuid.uuid4())
    self.rc = RedisConnection()
    cons = await self.rc.consumer(
        self.config.topic, consumer_id, self.config.group
    )

    while True:
        async for stream, entry in cons:
            try:
                m = Message(...)
                result = await getattr(self.config.mod, self.config.obj_name)(m)
            except Exception as e:
                logging.error(f"Error processing message: {e}")
                # Implement retry or dead letter queue
                if self.config.max_retries:
                    # Retry logic here
                    pass
            await asyncio.sleep(0)
```

---

## Medium Priority Improvements

### 10. Inconsistent Redis Client Usage
**Issue:** `app.py` uses `coredis` while `objstorage/redisobjstore.py` uses `redis.asyncio`.

**Recommendation:** Standardize on one Redis client. Prefer `coredis` for consistency, or document why both are used.

---

### 11. Missing Type Annotations in Several Places
**Locations:** Multiple

**Examples:**
- `util.py:177`: `async def process(func: Callable, *args, **params)` - params not typed
- `storage.py:11`: `_instance: Optional['Storage'] = None` - forward reference could use `from __future__ import annotations`

**Recommendation:** Add `from __future__ import annotations` at the top of files and complete type hints.

---

### 12. `dataframe_to_dataclass_list` Missing Error Handling
**Location:** `models.py:31-37`

```python
def dataframe_to_dataclass_list(df: pd.DataFrame, cls: Type[T]) -> List[T]:
    if not hasattr(cls, '__dataclass_fields__'):
        raise ValueError("cls must be a dataclass type.")
    return [cls(**row) for row in df.to_dict(orient='records')]
```

**Issue:** If DataFrame columns don't match dataclass fields, this will raise an unclear error.

**Recommendation:**
```python
def dataframe_to_dataclass_list(df: pd.DataFrame, cls: Type[T]) -> List[T]:
    if not hasattr(cls, '__dataclass_fields__'):
        raise ValueError("cls must be a dataclass type.")

    expected_fields = set(cls.__dataclass_fields__.keys())
    actual_fields = set(df.columns)
    missing = expected_fields - actual_fields
    extra = actual_fields - expected_fields

    if missing:
        raise ValueError(f"DataFrame missing fields: {missing}")
    if extra:
        logging.warning(f"DataFrame has extra fields that will be ignored: {extra}")

    return [cls(**row) for row in df.to_dict(orient='records')]
```

---

### 13. No Health Check or Metrics
**Issue:** No way to monitor the health of running agents or collect metrics.

**Recommendation:** Add health check endpoint and metrics collection:
```python
from dataclasses import dataclass, field
from typing import Dict
import time

@dataclass
class AgentMetrics:
    messages_processed: int = 0
    errors: int = 0
    last_message_time: Optional[float] = None
    total_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        if self.messages_processed == 0:
            return 0.0
        return self.total_latency_ms / self.messages_processed

class MetricsCollector:
    def __init__(self):
        self.agent_metrics: Dict[str, AgentMetrics] = defaultdict(AgentMetrics)

    def record_message(self, agent_name: str, latency_ms: float):
        metrics = self.agent_metrics[agent_name]
        metrics.messages_processed += 1
        metrics.last_message_time = time.time()
        metrics.total_latency_ms += latency_ms

    def record_error(self, agent_name: str):
        self.agent_metrics[agent_name].errors += 1
```

---

### 14. Process Pool Not Utilized
**Location:** `app.py:33`

```python
self.process_pool = ProcessPoolExecutor(max_workers=max_processes)
```

**Issue:** `ProcessPoolExecutor` is created but never used. The `_get_multiprocesses_concurrent_agents` method returns configs but they're never processed.

**Recommendation:** Either implement multiprocess agent execution or remove the dead code.

---

### 15. Timer Error Handling Missing
**Location:** `util.py:115-118`

```python
async def timer_container(item: TimerConfig) -> None:
    while True:
        await asyncio.sleep(item.t)
        await getattr(item.mod, item.obj_name)()
```

**Issue:** If a timer task raises an exception, the timer stops running silently.

**Recommendation:**
```python
async def timer_container(item: TimerConfig) -> None:
    while True:
        await asyncio.sleep(item.t)
        try:
            await getattr(item.mod, item.obj_name)()
        except Exception as e:
            logging.error(f"Timer {item.obj_name} failed: {e}")
            # Optionally continue or re-raise
```

---

### 16. No Connection Pool Configuration
**Location:** `redisapi.py:15`

```python
self.client: Redis = coredis.Redis(host=host, port=port, db=db, max_connections=10)
```

**Issue:** `max_connections=10` is hardcoded. Should be configurable.

**Recommendation:**
```python
def __init__(
    self,
    host: str = '127.0.0.1',
    port: int = 6379,
    db: int = 0,
    max_connections: int = 10
):
    self.client = coredis.Redis(
        host=host, port=port, db=db,
        max_connections=max_connections
    )
```

---

## Low Priority / Code Quality

### 17. Add `__all__` to Public Modules
**Recommendation:** Define public API in each module:
```python
# app.py
__all__ = ['App', 'StreamConsumer']

# models.py
__all__ = ['Message', 'AppConfig', 'ConsumerConfig', 'TimerConfig', 'StreamTopic']
```

---

### 18. Add Docstrings to All Public Methods
**Issue:** Some methods lack docstrings (e.g., `App._discover`, `App._get_concurrent_agents`).

**Recommendation:** Add comprehensive docstrings following Google or NumPy style.

---

### 19. Use `asyncio.Event` Instead of `while True` in `maintenance_task`
**Location:** `app.py:147-150`

```python
async def maintenance_task() -> None:
    while True:
        await asyncio.sleep(60)
```

**Recommendation:** Use an event for graceful shutdown:
```python
class App:
    def __init__(self, ...):
        self._shutdown_event = asyncio.Event()

async def maintenance_task(app: App) -> None:
    while not app._shutdown_event.is_set():
        await asyncio.wait_for(
            app._shutdown_event.wait(),
            timeout=60.0
        )
        # Perform maintenance
```

---

### 20. Consider Using `asyncio.TaskGroup` (Python 3.11+)
**Location:** `app.py:82-83`

```python
for task in tasks:
    asyncio.ensure_future(task)
```

**Recommendation:** For Python 3.11+, use TaskGroup for better error handling:
```python
async def run_tasks(self):
    async with asyncio.TaskGroup() as tg:
        for task in self._get_concurrent_agents():
            tg.create_task(task())
        for timer in self._get_timers():
            tg.create_task(timer)
```

---

### 21. Add Structured Logging
**Issue:** Using basic `logging` without structured context.

**Recommendation:** Consider using `structlog` or add context to log messages:
```python
import logging
import json
from dataclasses import asdict

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        if hasattr(record, 'extra_data'):
            log_data['extra'] = record.extra_data
        return json.dumps(log_data)
```

---

### 22. Create Proper Test Suite
**Issue:** README mentions `tests/` folder but it doesn't exist. Only `objstorage/test_redisobjstore.py` has tests.

**Recommendation:** Create comprehensive test suite:
```
tests/
├── __init__.py
├── conftest.py           # Fixtures
├── test_app.py           # App tests
├── test_models.py        # Model tests
├── test_redisapi.py      # Redis connection tests
├── test_storage.py       # Storage tests
├── test_util.py          # Utility tests
└── test_integration.py   # Integration tests
```

---

### 23. Add Configuration Validation
**Location:** `models.py` dataclasses

**Recommendation:** Use `pydantic` or add `__post_init__` validation:
```python
from dataclasses import dataclass

@dataclass
class AppConfig:
    name: str = ""
    max_processes: int = 5
    max_threads: int = 5

    def __post_init__(self):
        if self.max_processes < 1:
            raise ValueError("max_processes must be >= 1")
        if self.max_threads < 1:
            raise ValueError("max_threads must be >= 1")
```

---

### 24. Use Context Manager for Redis Connection
**Location:** `redisapi.py`

**Recommendation:** Make `RedisConnection` a context manager:
```python
class RedisConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.close()
        return False
```

---

### 25. Benchmark File Issues
**Location:** `bench_mass_latency.py`

**Issues:**
1. Uses global variables (`latencies`, `received_count`, `last_id`)
2. `last_id` initialization as `"0"` may not be correct for all cases
3. Debug print statements left in code

**Recommendation:** Refactor into a class with proper cleanup.

---

## Architecture Recommendations

### 26. Consider Adding a CLI Entry Point
**Recommendation:** Add a CLI for common operations:
```python
# cli.py
import click

@click.group()
def cli():
    """StreamMachine CLI"""
    pass

@cli.command()
@click.option('--config', default='config.yaml')
def start(config):
    """Start the stream processor"""
    pass

@cli.command()
def status():
    """Check status of running processors"""
    pass
```

---

### 27. Add Middleware/Interceptor Support
**Recommendation:** Allow users to add middleware for cross-cutting concerns:
```python
class Middleware:
    async def before_process(self, message: Message) -> Message:
        return message

    async def after_process(self, message: Message, result: Any):
        pass

    async def on_error(self, message: Message, error: Exception):
        pass

class App:
    def __init__(self):
        self.middlewares: List[Middleware] = []

    def add_middleware(self, middleware: Middleware):
        self.middlewares.append(middleware)
```

---

### 28. Add Dead Letter Queue Support
**Recommendation:** Implement DLQ for failed messages:
```python
class StreamConsumer:
    async def handle_failure(self, message: Message, error: Exception):
        await self.rc.client.xadd(
            f"{self.config.topic}:dlq",
            {
                "original_topic": message.topic,
                "error": str(error),
                "original_data": json.dumps(message.message),
                "timestamp": time.time()
            }
        )
```

---

## Summary Table

| Priority | Issue | Location | Impact |
|----------|-------|----------|--------|
| Critical | Missing `main()` function | app.py:158 | Runtime error |
| Critical | Undefined `helpers` variable | util.py:42,69 | Runtime error |
| Critical | Undefined `value1` variable | example.py:31-33 | Runtime error |
| Critical | Redis Lock import error | objstorage/redisobjstore.py:20 | Runtime error |
| High | Missing dependencies file | Project root | Deployment issues |
| High | Hardcoded Redis connection | models.py:15 | Configuration inflexibility |
| High | No graceful shutdown | app.py:85-88 | Resource leaks |
| High | Singleton thread safety | storage.py:13-17 | Race conditions |
| High | No error handling in consumer | app.py:132-145 | Message loss |
| Medium | Inconsistent Redis clients | Multiple | Maintenance burden |
| Medium | Missing type annotations | Multiple | Code clarity |
| Medium | No health checks | N/A | Operational visibility |
| Medium | Unused ProcessPool | app.py:33,63-68 | Dead code |
| Medium | Timer error handling | util.py:115-118 | Silent failures |
| Low | No `__all__` definitions | All modules | API clarity |
| Low | Missing docstrings | Multiple | Documentation |
| Low | No test suite | tests/ | Quality assurance |

---

## Recommended Implementation Order

1. **Phase 1 - Critical Fixes (Immediate)**
   - Fix undefined variables and functions
   - Fix Redis Lock import
   - Add missing dependencies file

2. **Phase 2 - Stability (1-2 weeks)**
   - Implement graceful shutdown
   - Add error handling to consumers/timers
   - Fix singleton thread safety
   - Add configuration via environment variables

3. **Phase 3 - Observability (2-3 weeks)**
   - Add health checks
   - Add metrics collection
   - Add structured logging
   - Add dead letter queue support

4. **Phase 4 - Quality (Ongoing)**
   - Add comprehensive test suite
   - Complete type annotations
   - Add docstrings
   - Add middleware support

---

## Conclusion

StreamMachine has a solid foundation with good architectural decisions (async-first, dataclasses, decorator-based registration). The critical issues are primarily around undefined variables and missing error handling, which should be addressed immediately. The medium and low priority items will improve maintainability and operational visibility over time.