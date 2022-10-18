"""
Async Utilities.
"""

from __future__ import annotations
import inspect
import asyncio
from asyncio import Future, CancelledError
from threading import Thread, RLock, local, Condition
from queue import Empty, PriorityQueue
from concurrent.futures import Executor, Future as SyncFuture
from concurrent.futures._base import CancelledError as SyncCancelledError
from concurrent.futures._base import TimeoutError as SyncTimeoutError
from contextvars import copy_context
from functools import wraps, partial
import threading
from typing import (Literal, TypeVar, Any, Callable, overload, Awaitable,
                    Generator, AsyncGenerator, ParamSpec)
import nest_asyncio

K = TypeVar("K")
V = TypeVar("V")
D = TypeVar("D")
T = TypeVar("T")
G = TypeVar("G", bound=Generator)
A = TypeVar("A", bound=Awaitable)
AG = TypeVar("AG", bound=AsyncGenerator)
ARGS = ParamSpec("ARGS")
Future_T = Future | SyncFuture
_LOCAL = local()

__all__ = ("sync_await", "ensure_async",
           "to_async", "to_async_gen", "get_create_loop",
           "async_run", "AsinkRunner", "TerminateRunner")


def sync_await(fut: Awaitable[V],
               loop: asyncio.AbstractEventLoop = None, timeout: float = None) -> V:
    """
    Get future in a synchronous context.

    This function is thread-safe. However, its behavior is varies.
    If the thread of the loop is the same as the current thread,
    the function will start the loop and wait for the future to complete.

    If the thread of the loop is different from the current thread,
    the function will NOT start the loop.
    **Be careful!** If the loop is not running, the function will block.
    Or if join this thread from which the loop is running, the function will block.

    * `fut` - the awaitable to wait for
    * `loop` - the event loop to use
    * `timeout` - the timeout in seconds if loop is in another thread
    """

    loop = loop or get_create_loop()
    if loop._thread_id in (None, threading.get_ident()):  # type: ignore
        nest_asyncio.apply(loop)
        return loop.run_until_complete(fut)

    # If loop is running in another thread
    syncfuture = SyncFuture[V]()

    def callsoon():
        """workaround for thread safety"""
        def callback(future: Future):
            try:
                syncfuture.set_result(future.result())
            except asyncio.CancelledError:
                syncfuture.cancel()
            except BaseException as e:
                syncfuture.set_exception(e)

        async def wrap():
            return await fut
        try:
            loop.create_task(wrap()).add_done_callback(callback)
        except BaseException as e:  # pragma: no cover # Hard to test
            syncfuture.set_exception(e)

    loop.call_soon_threadsafe(callsoon)
    return syncfuture.result(timeout=timeout)


@overload
def ensure_async(item: Callable[ARGS, A], loop: asyncio.AbstractEventLoop = None,
                 executor: Executor = None) -> Callable[ARGS, A]: ...


@overload
def ensure_async(item: Callable[ARGS, T], loop: asyncio.AbstractEventLoop = None,
                 executor: Executor = None) -> Callable[ARGS, Awaitable[T]]: ...


@overload
def ensure_async(item: Generator[K, None, V], loop: asyncio.AbstractEventLoop = None,
                 executor: Executor = None) -> AsyncGenerator[K, V]: ...


def ensure_async(item, loop=None, executor=None):
    """
    Convert a sync function or generator to async. Returns the
    original item if it is already a coroutine or an async generator.
    """
    if asyncio.iscoroutinefunction(item) or inspect.isasyncgen(item):
        return item
    if inspect.isgenerator(item):
        return to_async_gen(item, loop, executor)
    if callable(item):
        return to_async(item, loop, executor)
    raise TypeError(f"Expected a callable or generator, got {type(item)}")


def to_async(func: Callable[ARGS, T], loop: asyncio.AbstractEventLoop = None,
             executor: Executor = None) -> Callable[ARGS, Awaitable[T]]:
    """Ensure that the sync function is run within the event loop.
    If the *func* is not a coroutine it will be wrapped such that
    it runs in the default executor (use loop.set_default_executor
    to change). This ensures that synchronous functions do not
    block the event loop.
    """

    @wraps(func)
    async def _wrapper(*args: Any, **kwargs: Any) -> Any:
        nonlocal loop
        loop = loop or asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor, copy_context().run, partial(func, *args, **kwargs)
        )

    return _wrapper


def to_async_gen(gen: Generator[T, D, None],
                 loop: asyncio.AbstractEventLoop = None,
                 executor: Executor = None) -> AsyncGenerator[T, D]:
    async def _gen_wrapper():
        # Wrap the generator such that each iteration runs
        # in the executor. Then rationalise the raised
        # errors so that it ends.
        nonlocal loop

        loop = loop or asyncio.get_running_loop()

        def _run(f, v):
            """Wraps .send, .throw, .close"""
            ctx = copy_context()

            def _inner():
                try:
                    return ctx.run(f, v)
                except StopIteration as e:
                    # StopIteration has special meaning
                    raise StopAsyncIteration from e

            return loop.run_in_executor(executor, _inner)

        try:
            ret = await _run(next, gen)

            while True:
                try:
                    v = yield ret
                except Exception as e:  # skipcq: PYL-W0703
                    ret = await _run(gen.throw, e)
                except GeneratorExit:
                    # Unable to wrap close to async
                    gen.close()
                    raise
                else:
                    ret = await _run(gen.send, v)

        except StopAsyncIteration:
            return

    return _gen_wrapper()


def get_create_loop():
    """
    Get or create the event loop. Works in another thread.
    """

    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        loop: asyncio.AbstractEventLoop = getattr(_LOCAL, "loop", None)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _LOCAL.loop = loop
        return _LOCAL.loop


async def async_run(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Run sync function in a separate thread.
    * `func` - the function to run
    * `*args` - the arguments to pass to the function
    * `**kwargs` - the keyword arguments to pass to the function
    """

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, copy_context().run, partial(func, *args, **kwargs))


class TerminateRunner(BaseException):
    """Raised to terminate the runner."""


class _SinkTuple(tuple[int, Callable, Future_T]):
    """Tuple for PriorityQueue."""

    def __lt__(self, other: tuple) -> bool:
        return self[0] < other[0]


class AsinkRunner:
    """
    # AsinkRunner Class
    #### Asynchronously run lots of sync functions in order in another thread
    Works like a sink.

    This class is thread safe.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop = None, cold_run=False):
        """
        * `cold_run` - if `True`, the runner will not start by `run*` methods.
         Requires `start` method to be called.
        * `loop` - the event loop to use for `asyncio.Future`, if `None` 
         then every `run*` call will get the current running loop
        """
        self._queue: PriorityQueue[_SinkTuple] = PriorityQueue()
        """Stores tuples of (priority, func, future)"""
        self._runner = Thread(target=self._run, daemon=True)
        self._lock = RLock()
        """Protects status and queue"""
        self._closed = False
        self._state = Condition()
        """Make sure states are updated immediately after operations"""
        self._cold_run = cold_run
        self.loop = loop
        """The event loop to use for `asyncio.Future`, if `None`
        then every `run*` call will get the current running loop"""

    @property
    def alive(self) -> bool:
        """Whether the runner is alive"""
        return self._runner.is_alive()

    @property
    def closed(self) -> bool:
        """
        Whether the runner is closed
        Won't accept any more functions to run
        but may still be alive
        """
        return self._closed

    def start(self):
        """Start the runner"""
        if not self.alive:
            try:
                with self._state:
                    self._runner.start()
                    self._state.wait()
            except RuntimeError as e:
                if self.closed:
                    raise RuntimeError("Can't start: Runner is closed")
                raise RuntimeError("Can't start runner") from e  # pragma: no cover

    def _put_nowait(self, *args):
        """Put a function on the queue"""
        self._queue.put_nowait(_SinkTuple(args))

    def _get(self) -> tuple[Callable, Future_T]:
        """Get a function from the queue"""
        return self._queue.get()[1:3]  # Drop the priority

    def _task_done(self):
        """Mark a task as done"""
        self._queue.task_done()

    def sync_run_as(self, priority: int, func: Callable[ARGS, T],
                    *args: ARGS.args, **kw: ARGS.kwargs) -> SyncFuture[T]:
        """
        Same as `run_as` but returns a sync future (concurrent.futures.Future)

        * `priority` - the priority of the function, highest priority is run first.
        Must be a non-negative integer.
        """

        if priority < 0:
            raise ValueError("Priority must be a non-negative integer")
        fut: SyncFuture[T] = SyncFuture()
        f = partial(func, *args, **kw)
        with self._lock:
            if self.closed:
                raise RuntimeError("Can't run, AsinkRunner is closed")
            if not self._cold_run:
                self.start()
            # Reverse the priority since the heapq is a min-heap
            self._put_nowait(-priority, f, fut)
        return fut

    def sync_run(self, func: Callable[ARGS, T],
                 *args: ARGS.args, **kw: ARGS.kwargs) -> SyncFuture[T]:
        """Same as `run` but returns a sync future (concurrent.futures.Future)"""
        return self.sync_run_as(1, func, *args, **kw)

    def run_as(self, priority: int, func: Callable[ARGS, T],
               *args: ARGS.args, **kw: ARGS.kwargs) -> Future[T]:
        """
        Run a function in the runner, with a priority.
        Must run in an async context if `AsinkRunner().loop` is not set.

        * `priority` - the priority of the function, highest priority is run first.
        Must be a non-negative integer.
        """

        if priority < 0:
            raise ValueError("Priority must be a non-negative integer")
        loop = self.loop or asyncio.get_running_loop()
        fut: Future[T] = Future(loop=loop)
        f = partial(copy_context().run, partial(func, *args, **kw))
        with self._lock:
            if self._closed:
                raise RuntimeError("AsinkRunner is closed")
            if not self._cold_run:
                self.start()
            # Reverse priority since heapq is a min heap
            self._put_nowait(-priority, f, fut)
        return fut

    def run(self, func: Callable[ARGS, T],
            *args: ARGS.args, **kw: ARGS.kwargs) -> Future[T]:
        """
        Run a function in the runner with priority `1`.
        Must run in an async context if `AsinkRunner().loop` is not set.
        """
        return self.run_as(1, func, *args, **kw)

    def _run(self):

        def let_future(f: Future_T, fun: Callable, *arg):
            if isinstance(f, Future):
                return f.get_loop().call_soon_threadsafe(fun, *arg)
            return fun(*arg)

        fut: Future_T = None  # Current future

        try:
            with self._state:
                self._state.notify()

            while True:
                func, fut = self._get()
                try:
                    ret = func()
                except TerminateRunner:
                    let_future(fut, fut.set_result, True)
                    fut = SyncFuture()  # Dummy future
                    break
                except BaseException as e:
                    let_future(fut, fut.set_exception, e)
                else:
                    let_future(fut, fut.set_result, ret)
                finally:
                    self._task_done()
        except BaseException:
            # Make sure the failed future is cancelled last
            self._put_nowait(1, None, fut)
            raise
        finally:
            self._closed = True
            with self._lock:
                while True:
                    try:
                        _, _, fut = self._queue.get_nowait()
                        let_future(fut, fut.cancel)
                        self._task_done()
                    except Empty:
                        break
                    except BaseException:
                        pass

    def to_async(self, func: Callable[ARGS, T]) -> Callable[ARGS, Awaitable[T]]:
        """
        Wrap a sync function to run in the runner, but won't execute until awaited.
        Returns an async function.
        """

        @wraps(func)
        async def _wrapper(*args: ARGS.args, **kwargs: ARGS.kwargs) -> T:
            return await self.run(func, *args, **kwargs)

        return _wrapper

    def to_async_gen(self, gen: Generator[T, D, None]) -> AsyncGenerator[T, D]:
        """
        Wrap a sync generator to run in the runner, but won't execute until awaited.
        Returns an async generator.
        """

        async def _wrapper():
            def _run(f, v) -> Future[T]:
                """Wraps .send, .throw, .close"""

                def _inner():
                    try:
                        return f(v)
                    except StopIteration:
                        # StopIteration has special meaning
                        raise StopAsyncIteration()

                return self.run(_inner)

            try:
                ret = await _run(next, gen)
                while True:
                    try:
                        v = yield ret
                    except Exception as e:  # skipcq: PYL-W0703
                        ret = await _run(gen.throw, e)
                    except GeneratorExit:
                        # Unable to wrap close to async
                        gen.close()
                        raise
                    else:
                        ret = await _run(gen.send, v)
            except StopAsyncIteration:
                return

        return _wrapper()

    def join(self, close=False, timeout: float = None) -> bool:
        """
        Wait for the runner to finish
        * `close` - if `True`, close the runner after joining
        Returns `True` if the runner is joined, `False` if it was already closed
        * `timeout` - the timeout in seconds

        Raises:
        * `TimeoutError` if the timeout is reached
        * `RuntimeError` if the the operation fails
        """

        if self.alive:
            with self._lock:
                if self.closed:  # pragma: no cover # Hard to test
                    return False

                def f(): return True
                if close:
                    def f(): raise TerminateRunner()  # Kill the runner
                fut: SyncFuture[Literal[True]] = self.sync_run_as(0, f)
                self._closed = self.closed | close
            try:
                return fut.result(timeout)
            except SyncCancelledError as e:
                raise RuntimeError("Join cancelled") from e
            except SyncTimeoutError as e:
                raise TimeoutError("Join timed out") from e

        if self._queue.unfinished_tasks:
            raise RuntimeError("AsinkRunner is dead with tasks unfinished")
        return False

    async def ajoin(self, close=False) -> bool:
        """
        Async version of `join`
        * `close` - if `True`, close the runner after joining
        Returns `True` if the runner is joined, `False` if it was already closed

        Raises:
        * `RuntimeError` if the the operation fails
        """

        if self.alive:
            with self._lock:
                if self.closed:  # pragma: no cover # Hard to test
                    return False

                def f(): return True
                if close:
                    def f(): raise TerminateRunner()
                fut: Future[Literal[True]] = self.run_as(0, f)
                self._closed = self.closed | close
            try:
                return await fut
            except CancelledError as e:
                raise RuntimeError("Join cancelled") from e
        if self._queue.unfinished_tasks:
            raise RuntimeError("AsinkRunner is dead with tasks unfinished")
        return False

    def close(self, timeout: float = None) -> bool:
        """Close the runner"""
        return self.join(close=True, timeout=timeout)

    async def aclose(self) -> bool:
        """Close the runner"""
        return await self.ajoin(close=True)
