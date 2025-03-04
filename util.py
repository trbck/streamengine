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

from models import ConsumerConfig, TimerConfig

#from .client import xack, xlen

try:
    import contextvars  # Python 3.7+ only.
except ImportError:
    contextvars = None


class AgentTaskDecorator(object):
    def __init__(self,
                 stream,
                 group=None,
                 concurrency=1,
                 processes=None,
                 helper=False):
        self.helper = helper
        self.config = ConsumerConfig("agent", stream, group, concurrency,
                                     processes)

    def __call__(self, wrapped):
        me = self

        class Wrapper(object):
            def __init__(self, wrapped_func):
                self.callback = wrapped

            def on_scan(self, scanner, name, obj):
                if me.helper == False:
                    # get last frame
                    frm = inspect.stack()[len(inspect.stack()) - 1]
                    me.config.mod = inspect.getmodule(frm[0])
                else:
                    me.config.mod = inspect.getmodule(helpers)
                me.config.obj_name = self.callback.__name__
                me.config.inner_vars = inspect.signature(self.callback)
                scanner.registry.add(me.config)

            async def __call__(self, *args, **kwargs):
                # Make worker inner function available for redis consumer and stream topic.
                # TODO: add try/ except logging of errors raised by tasks
                result = await self.callback(*args, **kwargs)

        w = Wrapper(wrapped)
        venusian.attach(w, w.on_scan)
        return w


class TimerTaskDecorator(object):
    def __init__(self, t, helper=False):
        self.helper = helper
        self.config = TimerConfig("timer", t)

    def __call__(self, wrapped):
        me = self

        class Wrapper(object):
            def __init__(self, wrapped_func):
                self.callback = wrapped

            def on_scan(self, scanner, name, obj):
                if me.helper == False:
                    frm = inspect.stack()[5]
                    me.config.mod = inspect.getmodule(frm[0])
                else:
                    me.config.mod = inspect.getmodule(helpers)
                me.config.obj_name = self.callback.__name__
                me.config.inner_vars = inspect.signature(self.callback)
                scanner.registry.add(me.config)

            async def __call__(self, *args, **kwargs):
                # Make worker inner function available for redis consumer and stream topic.
                result = await self.callback(*args, **kwargs)
                return result

        w = Wrapper(wrapped)
        venusian.attach(w, w.on_scan)
        return w
    

class Registry(object):
    """venusian registry class
    
    Arguments:
        None
    """

    def __init__(self):
        self.registered = []

    def add(self, data):
        self.registered.append(data)


class Event(object):
    def __init__(self, val):
        self.decorator_type = val

    def __call__(self, wrapped):
        me = self

        class Wrapper(object):
            def __init__(self, wrapped_func):
                self.callback = wrapped

            def on_scan(self, scanner, name, obj):
                def decorated(*args, **kwargs):
                    v = wrapped_func(*args, **kwargs)
                    return v

                #self.callback = decorated
                scanner.registry.add(me.decorator_type, self.callback, [])

            def __call__(self, *args, **kwargs):
                return self.callback(*args, **kwargs)

        w = Wrapper(wrapped)
        venusian.attach(w, w.on_scan)
        return w


class AsyncToSync:
    """
    Utility class which turns an awaitable that only works on the thread with
    the event loop into a synchronous callable that works in a subthread.
    Must be initialised from the main thread.
    """

    def __init__(self, awaitable):
        self.awaitable = awaitable
        try:
            self.main_event_loop = asyncio.get_event_loop()
        except RuntimeError:
            # There's no event loop in this thread. Look for the threadlocal if
            # we're inside SyncToAsync
            self.main_event_loop = getattr(SyncToAsync.threadlocal,
                                           "main_event_loop", None)

    def __call__(self, *args, **kwargs):
        # You can't call AsyncToSync from a thread with a running event loop
        try:
            event_loop = asyncio.get_event_loop()
        except RuntimeError:
            pass
        else:
            if event_loop.is_running():
                raise RuntimeError(
                    "You cannot use AsyncToSync in the same thread as an async event loop - "
                    "just await the async function directly.")
        # Make a future for the return information
        call_result = Future()
        # Use call_soon_threadsafe to schedule a synchronous callback on the
        # main event loop's thread
        if not (self.main_event_loop and self.main_event_loop.is_running()):
            # Make our own event loop and run inside that.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    self.main_wrap(args, kwargs, call_result))
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
        # Wait for results from the future.
        return call_result.result()

    def __get__(self, parent, objtype):
        """
        Include self for methods
        """
        return functools.partial(self.__call__, parent)

    async def main_wrap(self, args, kwargs, call_result):
        """
        Wraps the awaitable with something that puts the result into the
        result/exception future.
        """
        try:
            result = await self.awaitable(*args, **kwargs)
        except Exception as e:
            call_result.set_exception(e)
        else:
            call_result.set_result(result)


class SyncToAsync:
    """
    Utility class which turns a synchronous callable into an awaitable that
    runs in a threadpool. It also sets a threadlocal inside the thread so
    calls to AsyncToSync can escape it.
    """

    # If they've set ASGI_THREADS, update the default asyncio executor for now
    if "ASGI_THREADS" in os.environ:
        loop = asyncio.get_event_loop()
        loop.set_default_executor(
            ThreadPoolExecutor(max_workers=int(os.environ["ASGI_THREADS"])))

    threadlocal = threading.local()

    def __init__(self, func):
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
            functools.partial(self.thread_handler, loop, func, *args,
                              **kwargs))
        return await asyncio.wait_for(future, timeout=None)

    def __get__(self, parent, objtype):
        """
        Include self for methods
        """
        return functools.partial(self.__call__, parent)

    def thread_handler(self, loop, func, *args, **kwargs):
        """
        Wraps the sync application with exception handling.
        """
        # Set the threadlocal for AsyncToSync
        self.threadlocal.main_event_loop = loop
        # Run the function
        return func(*args, **kwargs)


# Lowercase is more sensible for most things
sync_to_async = SyncToAsync
async_to_sync = AsyncToSync


def timeit(func):
    """
    #from: https://gist.github.com/Integralist/77d73b2380e4645b564c28c53fae71fb

    async def compute(x, y):
    print('Compute %s + %s ...' % (x, y))
    await asyncio.sleep(1.0)  # asyncio.sleep is also a coroutine
    return x + y

    @timeit
    async def print_sum(x, y):
        result = await compute(x, y)
        print('%s + %s = %s' % (x, y, result))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(print_sum(1, 2))
    loop.close()    
    """
    async def process(func, *args, **params):
        if asyncio.iscoroutinefunction(func):
            print('this function is a coroutine: {}'.format(func.__name__))
            return await func(*args, **params)
        else:
            print('this is not a coroutine')
            return func(*args, **params)

    async def helper(*args, **params):
        print('{}.time'.format(func.__name__))
        start = time.time()
        result = await process(func, *args, **params)

        # Test normal function route...
        # result = await process(lambda *a, **p: print(*a, **p), *args, **params)

        print('>>>', time.time() - start)
        return result

    return helper


def AsyncProcessQueue(maxsize=0):
    m = Manager()
    q = m.Queue(maxsize=maxsize)
    return _ProcQueue(q)


class _ProcQueue(object):
    def __init__(self, q):
        self._queue = q
        self._real_executor = None
        self._cancelled_join = False

    @property
    def _executor(self):
        if not self._real_executor:
            self._real_executor = ThreadPoolExecutor(max_workers=cpu_count())
        return self._real_executor

    def __getstate__(self):
        self_dict = self.__dict__
        self_dict['_real_executor'] = None
        return self_dict

    def __getattr__(self, name):
        if name in [
                'qsize', 'empty', 'full', 'put', 'put_nowait', 'get',
                'get_nowait', 'close'
        ]:
            return getattr(self._queue, name)
        else:
            raise AttributeError("'%s' object has no attribute '%s'" %
                                 (self.__class__.__name__, name))

    async def coro_put(self, item):
        loop = asyncio.get_event_loop()
        return (await loop.run_in_executor(self._executor, self.put, item))

    async def coro_get(self):
        loop = asyncio.get_event_loop()
        return (await loop.run_in_executor(self._executor, self.get))

    def cancel_join_thread(self):
        self._cancelled_join = True
        self._queue.cancel_join_thread()

    def join_thread(self):
        self._queue.join_thread()
        if self._real_executor and not self._cancelled_join:
            self._real_executor.shutdown()
