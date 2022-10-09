"""
Utility functions.
"""

from __future__ import annotations
import inspect
import asyncio
import nest_asyncio
import platform
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, Executor
from contextvars import copy_context
from functools import wraps, partial
from collections import OrderedDict, abc
from typing import List, Iterator, TypeVar, Generic, Union, Optional, Type, \
    TYPE_CHECKING, Iterable, Any, Callable, Sequence, overload, Awaitable, \
    Generator, AsyncGenerator

K = TypeVar('K')
V = TypeVar('V')
D = TypeVar('D')
T = TypeVar('T')
S = TypeVar("S", bound="StrChain")

__all__ = ('LRUCache', 'freeze', 'with_typehint', 'StrChain')


def with_typehint(baseclass: Type[T]):
    """
    Add type hints from a specified class to a base class:

    >>> class Foo(with_typehint(Bar)):
    ...     pass

    This would add type hints from class ``Bar`` to class ``Foo``.

    Note that while PyCharm and Pyright (for VS Code) understand this pattern,
    MyPy does not. For that reason TinyDB has a MyPy plugin in
    ``mypy_plugin.py`` that adds support for this pattern.
    """
    if TYPE_CHECKING:
        # In the case of type checking: pretend that the target class inherits
        # from the specified base class
        return baseclass

    # Otherwise: just inherit from `object` like a regular Python class
    return object


def sync_await(coro: Awaitable[V], loop: asyncio.AbstractEventLoop = None) -> V:
    loop = loop or get_create_loop()
    nest_asyncio.apply(loop)
    return loop.run_until_complete(coro)


def ensure_async(func: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
    if asyncio.iscoroutinefunction(func):
        return func
    return to_async(func)

#### quart.utils ####


def to_async(func: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
    """Ensure that the sync function is run within the event loop.
    If the *func* is not a coroutine it will be wrapped such that
    it runs in the default executor (use loop.set_default_executor
    to change). This ensures that synchronous functions do not
    block the event loop.
    """

    @wraps(func)
    async def _wrapper(*args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, copy_context().run, partial(func, *args, **kwargs)
        )
        if inspect.isgenerator(result):
            return to_async_iter(result)
        return result

    return _wrapper


def to_async_iter(iterable: Generator[Any, None, None]) -> AsyncGenerator[Any, None]:
    async def _gen_wrapper() -> AsyncGenerator[Any, None]:
        # Wrap the generator such that each iteration runs
        # in the executor. Then rationalise the raised
        # errors so that it ends.
        def _inner() -> Any:
            # https://bugs.python.org/issue26221
            # StopIteration errors are swallowed by the
            # run_in_exector method
            try:
                return next(iterable)
            except StopIteration as e:
                raise StopAsyncIteration() from e

        loop = asyncio.get_running_loop()
        while True:
            try:
                yield await loop.run_in_executor(None, copy_context().run, _inner)
            except StopAsyncIteration:
                return

    return _gen_wrapper()


def get_create_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


_executor: Executor | None = None


def get_executor() -> Executor:
    """
    Get the default executor for the current platform.
    """
    global _executor
    if _executor:
        return _executor
    if platform.system() == "Linux":
        try:
            mp.set_start_method("fork", force=True)
        except RuntimeError:
            ...
        if mp.get_start_method() == "fork":
            _executor = ProcessPoolExecutor()
    _executor = ThreadPoolExecutor()
    return _executor


class LRUCache(abc.MutableMapping, Generic[K, V]):
    """
    A least-recently used (LRU) cache with a fixed cache size.

    This class acts as a dictionary but has a limited size. If the number of
    entries in the cache exceeds the cache size, the least-recently accessed
    entry will be discarded.

    This is implemented using an ``OrderedDict``. On every access the accessed
    entry is moved to the front by re-inserting it into the ``OrderedDict``.
    When adding an entry and the cache size is exceeded, the last entry will
    be discarded.
    """

    def __init__(self, capacity=None):
        self.capacity = capacity
        self.cache: OrderedDict[K, V] = OrderedDict()

    @property
    def lru(self) -> List[K]:
        return list(self.cache.keys())

    @property
    def length(self) -> int:
        return len(self.cache)

    def clear(self) -> None:
        self.cache.clear()

    def __len__(self) -> int:
        return self.length

    def __contains__(self, key: object) -> bool:
        return key in self.cache

    def __setitem__(self, key: K, value: V) -> None:
        self.set(key, value)

    def __delitem__(self, key: K) -> None:
        del self.cache[key]

    def __getitem__(self, key) -> V:
        value = self.get(key)
        if value is None:
            raise KeyError(key)

        return value

    def __iter__(self) -> Iterator[K]:
        return iter(self.cache)

    def get(self, key: K, default: D = None) -> Optional[Union[V, D]]:
        value = self.cache.get(key)

        if value is not None:
            self.cache.move_to_end(key, last=True)

            return value

        return default

    def set(self, key: K, value: V):
        if self.cache.get(key):
            self.cache.move_to_end(key, last=True)

        else:
            self.cache[key] = value

            # Check, if the cache is full and we have to remove old items
            # If the queue is of unlimited size, self.capacity is NaN and
            # x > NaN is always False in Python and the cache won't be cleared.
            if self.capacity is not None and self.length > self.capacity:
                self.cache.popitem(last=False)


class FrozenDict(dict):
    """
    An immutable dictionary.

    This is used to generate stable hashes for queries that contain dicts.
    Usually, Python dicts are not hashable because they are mutable. This
    class removes the mutability and implements the ``__hash__`` method.
    """

    def __hash__(self):
        # Calculate the has by hashing a tuple of all dict items
        return hash(tuple(sorted(self.items())))

    @staticmethod
    def _immutable(*args, **kws):
        raise TypeError('object is immutable')

    # Disable write access to the dict
    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    setdefault = _immutable  # type: ignore
    popitem = _immutable

    def update(self, e=None, **f):
        raise TypeError('object is immutable')

    def pop(self, k, d=None):
        raise TypeError('object is immutable')


def freeze(obj):
    """
    Freeze an object by making it immutable and thus hashable.
    """
    if isinstance(obj, dict):
        # Transform dicts into ``FrozenDict``s
        return FrozenDict((k, freeze(v)) for k, v in obj.items())
    if isinstance(obj, list):
        # Transform lists into tuples
        return tuple(freeze(el) for el in obj)
    if isinstance(obj, set):
        # Transform sets into ``frozenset``s
        return frozenset(obj)
    return obj


class StrChain(Sequence[str]):
    """
    ### StrChain: More than a convenient way to create strings.
    It is NOT a subclass of `str`, use `str()` to convert it to str.

    By default `callback` is `str`, so simply calling the instance will 
    return the string.

    StrChain is immutable. Hash is the same as the string it represents.

    Usage:
    ```Python
    str_chain = StrChain()
    str_chain.hello.world() is "hello.world"
    # String can't start with '_' when using __getattr__ , 
    # use __getitem__ instead
    str_chain.["hello"]["_world"]() is "hello._world"

    path = StrChain(['/'], joint="/") # Init with a list and set a custom joint
    path.home.user() is "/home/user"
    str(path + "home" + "user") == "/home/user" # Comparing with str

    # callback: used when calling StrChain, default is `str`
    # First argument is the StrChain itself followed by args and kwargs
    string = StrChain(callback=lambda x: '!'.join([i.lower() for i in x]))
    string.Hello.World() == "hello!world"
    ```
    And much more...
    """

    def __init__(
            self: S,
            it: Iterable[str] | None = None,
            joint: str = '.',
            callback: Callable[..., Any] = str,
            **kw):
        """
        * `it`: Iterable[str], the initial string chain
        * `joint`: str, the joint between strings
        * `callback`: Callable[[StrChain, ...], Any], 
        used when calling the StrChain instance
        """
        self._joint = joint
        self._callback = callback
        self._kw = kw
        it = [it] if isinstance(it, str) else it
        self._list: list[str] = list(it or [])

    def __call__(self: S, *args: Any, **kw: Any) -> Any:
        return self._callback(self, *args, **kw)

    def __create(self: S, it: Iterable[str]) -> S:
        return type(self)(it=it, joint=self._joint, callback=self._callback, **self._kw)

    def __len__(self: S) -> int:
        return len(self._list)

    def __getattr__(self: S, name: str) -> S:
        if name.startswith('_'):
            raise AttributeError(
                f"{name} : String can't start with '_' when using __getattr__" +
                " , use __getitem__ instead")
        return self.__create(self._list + [name])

    @overload
    def __getitem__(self: S, index: int) -> str:
        ...

    @overload
    def __getitem__(self: S, s: slice) -> S:
        ...

    @overload
    def __getitem__(self: S, string: str) -> S:
        ...

    def __getitem__(self: S, value: int | slice | str) -> str | S:
        if isinstance(value, int):
            return self._list[value]
        if isinstance(value, slice):
            return self.__create(self._list[value])
        if isinstance(value, str):
            return self.__create(self._list + [value])
        raise TypeError(f"Invalid type {type(value)}")

    def __eq__(self, other) -> bool:
        if type(other) is type(self):
            return self._list == other._list \
                and self._joint == other._joint \
                and self._callback == other._callback \
                and self._kw == other._kw
        return False

    def __hash__(self: S) -> int:
        return hash(str(self))

    def __add__(self: S, other: Iterable[str] | str) -> S:
        other = [other] if isinstance(other, str) else list(other)
        return self.__create(self._list + other)

    def __radd__(self: S, other: Iterable[str] | str) -> S:
        other = [other] if isinstance(other, str) else list(other)
        return self.__create(other + self._list)

    def __iadd__(self: S, other: Iterable[str] | str) -> S:
        return self + other

    def __mul__(self: S, other: int) -> S:
        return self.__create(self._list * other)

    def __rmul__(self: S, other: int) -> S:
        return self.__create(self._list * other)

    def __imul__(self: S, other: int) -> S:
        return self * other

    def __iter__(self: S) -> Iterator[str]:
        return iter(self._list)

    def __str__(self: S) -> str:
        return self._joint.join(self._list)

    def __repr__(self: S) -> str:
        return self._joint.join(self._list)
