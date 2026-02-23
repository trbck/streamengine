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
├── src/streamengine/           # Main package
│   ├── __init__.py             # Package exports
│   ├── app.py                  # Main application logic and event loop
│   ├── models.py               # Central dataclasses and data model utilities
│   ├── redisapi.py             # Async Redis connection and stream helpers
│   ├── storage.py              # Async, multiprocessing-safe in-memory storage
│   ├── util.py                 # Decorators, registry, and async utilities
│   ├── cython/                 # Cython acceleration
│   │   ├── __init__.py
│   │   ├── cython_decode.pyx   # Fast bytes-to-string decoding
│   │   └── cython_decode.c     # Generated C code
│   └── objstorage/             # Optional object storage
│       ├── __init__.py
│       └── redisobjstore.py    # Redis object storage with pickle
├── examples/                   # Example scripts
│   ├── basic_usage.py          # Basic usage example
│   ├── batch_processing.py     # Batch message processing
│   ├── benchmark_latency.py    # Latency benchmarking
│   ├── benchmark_decode.py     # Decode performance benchmarking
│   ├── health_check_example.py # Health check example
│   ├── multiple_consumers.py   # Multiple consumer groups
│   └── storage_example.py      # Shared storage example
├── tests/                      # Test suite
│   ├── conftest.py             # Pytest fixtures
│   ├── test_app.py             # App tests
│   ├── test_models.py          # Model tests
│   ├── test_redisapi.py        # Redis API tests
│   ├── test_storage.py         # Storage tests
│   └── test_objstorage.py      # Object storage tests
├── config/                     # Configuration files
├── pyproject.toml              # Project configuration
├── setup.py                    # Setup script
├── plan.md                     # Development plan
└── README.md                   # This file
```

## Quick Example
```python
from streamengine import App, Message

app = App(name="my_app")

@app.timer(1)
async def producer():
    await app.send("test_channel", {"test": 10})

@app.agent("test_channel", concurrency=1, group="test")
async def consumer(record: Message):
    print("Received:", record.message)

if __name__ == "__main__":
    app.start()
```

## Installation
```bash
pip install streamengine
```

Or install from source:
```bash
git clone https://github.com/anthropics/streamengine.git
cd streamengine
pip install -e .
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
- `coredis`, `uvloop`, `venusian`, `pandas`, `numpy`

## Running Tests
```bash
pytest tests/
```

## Contributing
- Add new agents/timers via decorators.
- Add tests in `tests/`.
- Document new features in `docs/`.
- Mark CPU-bound code for Cythonization as needed.

---

For more details, see the code and examples. PRs and issues welcome!