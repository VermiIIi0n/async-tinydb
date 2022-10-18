"""
Utility functions.
"""

from __future__ import annotations
from collections import OrderedDict
from . import async_utils
from .async_utils import *
from typing import Iterator, Mapping, MutableSequence, \
    MutableSet, TypeVar, Generic, Type, \
    TYPE_CHECKING, Iterable, Any, Callable, Sequence, overload, MutableMapping

K = TypeVar("K")
V = TypeVar("V")
D = TypeVar("D")
T = TypeVar("T")
S = TypeVar("S", bound="StrChain")
C = TypeVar("C", bound=Callable)

__all__ = (("LRUCache", "freeze", "with_typehint", "StrChain", "FrozenDict", "mimics")
           + async_utils.__all__)


def mimics(_: C) -> Callable[[Callable], C]:
    """
    Type trick. This decorator is used to make a function mimic the signature
    of another function.
    """
    def decorator(wrapper: Callable) -> C:
        return wrapper  # type: ignore

    return decorator


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


class LRUCache(MutableMapping, Generic[K, V]):
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
    def lru(self) -> list[K]:
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

    def get(self, key: K, default: D = None) -> V | D | None:
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


class FrozenDict(Mapping[K, V]):
    """
    An immutable dictionary.

    This is used to generate stable hashes for queries that contain dicts.
    Usually, Python dicts are not hashable because they are mutable. This
    class removes the mutability and implements the ``__hash__`` method.
    """

    @overload
    def __init__(self): ...
    @overload
    def __init__(self: FrozenDict[str, V], **kw: V): ...
    @overload
    def __init__(self, _map: Mapping[K, V]): ...
    @overload
    def __init__(self: FrozenDict[str, V], _map: Mapping[str, V], **kw: V): ...
    @overload
    def __init__(self, _iter: Iterable[tuple[K, V]]): ...
    @overload
    def __init__(self: FrozenDict[str, V], _: Iterable[tuple[str, V]], **kw: V): ...
    @overload
    def __init__(self: FrozenDict[str, str], _iter: Iterable[list[str]]): ...

    def __init__(self, *args, **kw):
        super().__init__()
        self._dict = dict[K, V](*args, **kw)
        self._hash = None

    def __repr__(self):
        return f"<FrozenDict {self._dict}>"

    def __hash__(self):
        if self._hash is None:
            # Calculate the hash by hashing a tuple of sorted hashes of dict k/v pairs
            self._hash = hash(tuple(sorted(hash((k, v)) for k, v in self.items())))
        return self._hash

    def __getitem__(self, key):
        return self._dict[key]

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)

    def __contains__(self, __o: object) -> bool:
        return __o in self._dict

    def __eq__(self, __o: object) -> bool:
        return self._dict == __o

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def items(self):
        return self._dict.items()

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._dict.values()


def freeze(obj, memo: set[int] = None):
    """
    Freeze an object by making it immutable and thus hashable.
    """
    if memo is None:
        memo = set()
    if id(obj) in memo:
        raise ValueError("Cannot freeze recursive data structures")
    memo.add(id(obj))

    if isinstance(obj, MutableMapping):
        # Transform dicts into ``FrozenDict``s
        return FrozenDict((k, freeze(v, memo.copy())) for k, v in obj.items())
    if isinstance(obj, MutableSequence):
        # Transform lists into tuples
        return tuple(freeze(el, memo.copy()) for el in obj)
    if isinstance(obj, MutableSet):
        # Transform sets into ``frozenset``s
        return frozenset(freeze(item, memo.copy()) for item in obj)
    return obj


class StrChain(Sequence[str]):
    """
    # StrChain Class
    ## More than a convenient way to create strings.
    **It is NOT a subclass of `str`, use `str()` to convert it to str.**

    By default `callback` is `str`, so simply calling the instance will 
    return the string.

    StrChain is immutable. Hash is the same as the string it represents.

    ### Usage:
    ```Python
    str_chain = StrChain()
    str_chain.hello.world() == "hello.world"
    ```

    **String can't start with '_' when using __getattr__ , 
    use __getitem__ instead**
    ```Python
    str_chain.["hello"]["_world"]() is "hello._world"

    path = StrChain(['/'], joint="/") # Init with a list and set a custom joint
    path.home.user() is "/home/user"
    str(path + "home" + "user") == "/home/user" # Comparing with str
    ```
    ### callback
    Used when calling StrChain, default is `str`
    First argument is the StrChain itself followed by args and kwargs
    ```Python
    string = StrChain(callback=lambda x: '!'.join([i.lower() for i in x]))
    string.Hello.World() == "hello!world"
    ```
    And much more...
    """

    def __init__(
            self: S,
            it: str | Iterable[str] | None = None,
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
                f"{name} : String can't start with '_' when using __getattr__"
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
        if isinstance(other, StrChain):
            return self._list == other._list and self._joint == other._joint
        return False

    def __hash__(self: S) -> int:
        return hash(str(self))

    def __bool__(self: S) -> bool:
        return bool(self._list)

    def __add__(self: S, other: Iterable[str] | str) -> S:
        other = [other] if isinstance(other, str) else list(other)
        return self.__create(self._list + other)

    def __radd__(self: S, other: Iterable[str] | str) -> S:
        other = [other] if isinstance(other, str) else list(other)
        return self.__create(other + self._list)

    def __iadd__(self: S, other: Iterable[str] | str) -> S:
        return self + other

    def __mul__(self: S, other: int) -> S:
        if not isinstance(other, int):
            return NotImplemented
        return self.__create(self._list * other)

    def __rmul__(self: S, other: int) -> S:
        return self * other

    def __imul__(self: S, other: int) -> S:
        return self * other

    def __iter__(self: S) -> Iterator[str]:
        return iter(self._list)

    def __reversed__(self: S) -> Iterator[str]:
        return reversed(self._list)

    def __contains__(self: S, item: object) -> bool:
        return item in self._list

    def __str__(self: S) -> str:
        return self._joint.join(self._list)

    def __repr__(self: S) -> str:
        return (f"{type(self).__name__}({self._list!r}, "
                f"joint={self._joint!r}, "
                f"callback={self._callback!r}, **{self._kw!r})")
