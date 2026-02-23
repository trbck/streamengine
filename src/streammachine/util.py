#https://gitlab.com/pineiden/tasktools/blob/master/tasktools/async_queue.py
from multiprocessing import Manager, cpu_count
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
import asyncio
import venusian
import functools
import os
import threading
import time
import inspect
from typing import Any, Callable, Optional, Awaitable

from .models import ConsumerConfig, TimerConfig

#from .client import xack, xlen

try:
    import contextvars  # Python 3.7+ only.
except ImportError:
    contextvars = None

# === Decorators and Registry ===

class AgentTaskDecorator:
    """
    Decorator for registering agent (consumer) tasks with Venusian.
    """
    def __init__(self, stream: str, group: Optional[str] = None, concurrency: int = 1, processes: Optional[int] = None):
        self.config = ConsumerConfig("agent", stream, group, concurrency, processes)

    def __call__(self, wrapped: Callable) -> Any:
        me = self
        class Wrapper:
            def __init__(self, wrapped_func: Callable):
                self.callback = wrapped
            def on_scan(self, scanner, name, obj):
                frm = inspect.stack()[len(inspect.stack()) - 1]
                me.config.mod = inspect.getmodule(frm[0])
                me.config.obj_name = self.callback.__name__
                me.config.inner_vars = inspect.signature(self.callback)
                scanner.registry.add(me.config)
            async def __call__(self, *args, **kwargs):
                return await self.callback(*args, **kwargs)
        w = Wrapper(wrapped)
        venusian.attach(w, w.on_scan)
        return w

class TimerTaskDecorator:
    """
    Decorator for registering timer tasks with Venusian.
    """
    def __init__(self, t: int):
        self.config = TimerConfig("timer", t)
    def __call__(self, wrapped: Callable) -> Any:
        me = self
        class Wrapper:
            def __init__(self, wrapped_func: Callable):
                self.callback = wrapped
            def on_scan(self, scanner, name, obj):
                frm = inspect.stack()[5]
                me.config.mod = inspect.getmodule(frm[0])
                me.config.obj_name = self.callback.__name__
                me.config.inner_vars = inspect.signature(self.callback)
                scanner.registry.add(me.config)
            async def __call__(self, *args, **kwargs):
                return await self.callback(*args, **kwargs)
        w = Wrapper(wrapped)
        venusian.attach(w, w.on_scan)
        return w

class Registry:
    """
    Venusian registry class for collecting registered agent/timer configs.
    """
    def __init__(self) -> None:
        self.registered = []
    def add(self, data: Any) -> None:
        self.registered.append(data)

# === Async/Sync Utilities ===

class AsyncToSync:
    """
    Utility class to turn an awaitable into a synchronous callable for subthreads.
    """
    def __init__(self, awaitable: Awaitable):
        self.awaitable = awaitable
        try:
            self.main_event_loop = asyncio.get_event_loop()
        except RuntimeError:
            self.main_event_loop = getattr(SyncToAsync.threadlocal, "main_event_loop", None)
    def __call__(self, *args, **kwargs):
        try:
            event_loop = asyncio.get_event_loop()
        except RuntimeError:
            pass
        else:
            if event_loop.is_running():
                raise RuntimeError("You cannot use AsyncToSync in the same thread as an async event loop - just await the async function directly.")
        call_result = Future()
        if not (self.main_event_loop and self.main_event_loop.is_running()):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.main_wrap(args, kwargs, call_result))
            finally:
                try:
                    if hasattr(loop, "shutdown_asyncgens"):
                        loop.run_until_complete(loop.shutdown_asyncgens())
                finally:
                    loop.close()
                    asyncio.set_event_loop(self.main_event_loop)
        else:
            self.main_event_loop.call_soon_threadsafe(
                self.main_event_loop.create_task,
                self.main_wrap(args, kwargs, call_result),
            )
        return call_result.result()
    def __get__(self, parent, objtype):
        return functools.partial(self.__call__, parent)
    async def main_wrap(self, args, kwargs, call_result):
        try:
            result = await self.awaitable(*args, **kwargs)
        except Exception as e:
            call_result.set_exception(e)
        else:
            call_result.set_result(result)

class SyncToAsync:
    """
    Utility class to turn a synchronous callable into an awaitable that runs in a threadpool.
    """
    if "ASGI_THREADS" in os.environ:
        loop = asyncio.get_event_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=int(os.environ["ASGI_THREADS"])))
    threadlocal = threading.local()
    def __init__(self, func: Callable):
        self.func = func
    async def __call__(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        if contextvars is not None:
            context = contextvars.copy_context()
            child = functools.partial(self.func, *args, **kwargs)
            func = context.run
            args = (child, )
            kwargs = {}
        else:
            func = self.func
        future = loop.run_in_executor(
            None,
            functools.partial(self.thread_handler, loop, func, *args, **kwargs))
        return await asyncio.wait_for(future, timeout=None)
    def __get__(self, parent, objtype):
        return functools.partial(self.__call__, parent)
    def thread_handler(self, loop, func, *args, **kwargs):
        self.threadlocal.main_event_loop = loop
        return func(*args, **kwargs)

# Lowercase aliases
sync_to_async = SyncToAsync
async_to_sync = AsyncToSync

# === Timing and Process Queue Utilities ===

def timeit(func: Callable) -> Callable:
    """
    Async timeit decorator for measuring coroutine execution time.
    """
    async def process(func: Callable, *args, **params):
        if asyncio.iscoroutinefunction(func):
            print(f'this function is a coroutine: {func.__name__}')
            return await func(*args, **params)
        else:
            print('this is not a coroutine')
            return func(*args, **params)
    async def helper(*args, **params):
        print(f'{func.__name__}.time')
        start = time.time()
        result = await process(func, *args, **params)
        print('>>>', time.time() - start)
        return result
    return helper

def AsyncProcessQueue(maxsize: int = 0) -> Any:
    """
    Create a multiprocessing-backed queue with async put/get support.
    """
    m = Manager()
    q = m.Queue(maxsize=maxsize)
    return _ProcQueue(q)

class _ProcQueue:
    def __init__(self, q: Any):
        self._queue = q
        self._real_executor = None
        self._cancelled_join = False
    @property
    def _executor(self) -> ThreadPoolExecutor:
        if not self._real_executor:
            self._real_executor = ThreadPoolExecutor(max_workers=cpu_count())
        return self._real_executor
    def __getstate__(self):
        self_dict = self.__dict__
        self_dict['_real_executor'] = None
        return self_dict
    def __getattr__(self, name: str) -> Any:
        if name in [
                'qsize', 'empty', 'full', 'put', 'put_nowait', 'get',
                'get_nowait', 'close'
        ]:
            return getattr(self._queue, name)
        else:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    async def coro_put(self, item: Any) -> Any:
        loop = asyncio.get_event_loop()
        return (await loop.run_in_executor(self._executor, self.put, item))
    async def coro_get(self) -> Any:
        loop = asyncio.get_event_loop()
        return (await loop.run_in_executor(self._executor, self.get))
    def cancel_join_thread(self) -> None:
        self._cancelled_join = True
        self._queue.cancel_join_thread()
    def join_thread(self) -> None:
        self._queue.join_thread()
        if self._real_executor and not self._cancelled_join:
            self._real_executor.shutdown()

# --- Cythonization candidates ---
# If you have any CPU-bound data processing, mark here for Cythonization.
# Example:
# def heavy_processing(...):
#     ... # Move to .pyx and use nogil for true parallelism
