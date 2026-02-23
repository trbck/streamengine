# StreamEngine

StreamEngine is a high-performance, async-first Python framework for distributed stream processing using Redis Streams. It is designed for ultra-low-latency, high-throughput event-driven applications, and is ready for both I/O-bound and CPU-bound workloads (with Cython acceleration support).

## Features
- **Async-first**: All I/O and orchestration is async for lowest latency.
- **Redis Streams**: Uses Redis Streams for distributed, atomic, and fast message passing.
- **Agent/Timer Decorators**: Register stream consumers and periodic tasks with simple decorators.
- **Multiprocessing**: Supports CPU-bound parallelism via `ProcessPoolExecutor`.
- **Cython-ready**: Mark and migrate CPU-bound code to `.pyx` for true parallelism and speed.
- **Batch Operations**: Batch/pipeline support for Redis operations.
- **Centralized Data Models**: All data structures are defined as dataclasses in `models.py`.
- **Type Hints & Docstrings**: Fully type-hinted and documented for maintainability.
- **Testable**: Designed for easy unit and integration testing.

## File Structure
```
streamengine/
├── app.py                # Main application logic and event loop
├── models.py             # Central dataclasses and data model utilities
├── redisapi.py           # Async Redis connection and stream helpers
├── storage.py            # Async, multiprocessing-safe in-memory storage
├── util.py               # Decorators, registry, and async utilities
├── tasks/                # (Empty) Place for CLI scripts (run_*.py)
├── objstorage/
│   ├── redisobjstore.py  # (Optional) Redis object storage helpers
│   └── ...
├── examples/
│   └── example.py        # Example usage script
├── tests/                # (Empty) Place for unittests
├── config/               # (Empty) Place for config.yaml
├── docs/                 # (Empty) Place for API docs
├── __init__.py           # (Empty) Package marker
├── LICENSE
├── .gitignore
├── .cursorrules
```

## Quick Example
```python
from app import App

app = App()

@app.timer(1)
async def timer1():
    await app.send("test_channel", {"test": 10})

@app.agent("test_channel", concurrency=1, group="test")
async def job1(record):
    print("Received:", record)

if __name__ == "__main__":
    app.start()
```

## How It Works
- **Define agents and timers** using decorators (`@app.agent`, `@app.timer`).
- **Start the app**: The event loop discovers and runs all registered tasks.
- **Send and process messages**: Agents consume from Redis Streams, timers run periodically.
- **Scale horizontally**: Run multiple app instances for distributed processing.
- **Accelerate CPU-bound code**: Move hot spots to Cython for true parallelism.

## Requirements
- Python 3.8+
- Redis server (for Streams)
- `coredis`, `uvloop`, `venusian`, `pandas`, `multiprocessing` (standard), `asyncio` (standard)

## Contributing
- Add new agents/timers via decorators.
- Add tests in `tests/`.
- Document new features in `docs/`.
- Mark CPU-bound code for Cythonization as needed.

---

For more details, see the code and examples. PRs and issues welcome! 