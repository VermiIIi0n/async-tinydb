"""
Utility functions.
"""

from __future__ import annotations
from collections import OrderedDict
from contextlib import suppress
from . import async_utils
from .async_utils import *
from typing import Iterator, Mapping, TypeVar, Generic, Type, \
    TYPE_CHECKING, Iterable, Any, Callable, Sequence, overload, MutableMapping

K = TypeVar("K")
V = TypeVar("V")
D = TypeVar("D")
T = TypeVar("T")
K_co = TypeVar("K_co", covariant=True)
V_co = TypeVar("V_co", covariant=True)
S = TypeVar("S", bound="StrChain")
C = TypeVar("C", bound=Callable)

__all__ = (("LRUCache", "freeze", "with_typehint", "stringfy_keys",
            "supports_in", "is_container", "is_iterable", "is_hashable",
            "StrChain", "FrozenDict", "mimics", "sort_class", "FrozenList")
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


def is_hashable(obj) -> bool:
    with suppress(TypeError):
        hash(obj)
        return True
    return False


def is_iterable(obj) -> bool:
    return hasattr(obj, "__iter__")


def is_container(obj) -> bool:
    return hasattr(obj, "__contains__")


def supports_in(obj) -> bool:
    """
    Check if an object supports the ``in`` operator.

    Be careful: When a `Generator` be evaluated when using ``in``
    and the desired value never appears, the statement could never end.
    """
    return any(hasattr(obj, attr)
               for attr in ("__contains__", "__iter__", "__getitem__"))


def stringfy_keys(data, memo: dict = None):
    if memo is None:
        memo = {}
    if isinstance(data, Mapping):
        if id(data) in memo:
            return memo[id(data)]
        memo[id(data)] = {}  # Placeholder in case of loop references
        memo[id(data)].update((str(k), stringfy_keys(v, memo))
                              for k, v in data.items())
        return memo[id(data)]
    if isinstance(data, list | tuple):
        return [stringfy_keys(v, memo) for v in data]
    return data


def sort_class(cls: Iterable[type]) -> list[type]:
    """Sort classes by inheritance. From child to parent."""
    ls: list[type] = []
    for c in cls:
        it = iter(enumerate(ls))
        try:
            while True:
                i, p = next(it)
                if issubclass(c, p):
                    ls.insert(i, c)
                    break
        except StopIteration:
            ls.append(c)
    return ls


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


class FrozenDict(Mapping[K_co, V_co]):
    """
    An immutable dictionary.

    This is used to generate stable hashes for queries that contain dicts.
    Usually, Python dicts are not hashable because they are mutable. This
    class removes the mutability and implements the ``__hash__`` method.
    """

    def __new__(cls, *args, **kw):
        if len(args) == 1 and isinstance(args[0], FrozenDict) and not kw:
            return args[0]
        return super().__new__(cls)

    @overload
    def __init__(self): ...
    @overload
    def __init__(self: FrozenDict[str, V_co], **kw: V_co): ...
    @overload
    def __init__(self, _map: Mapping[K_co, V_co]): ...

    @overload
    def __init__(self: FrozenDict[str, V_co],
                 _map: Mapping[str, V_co], **kw: V_co): ...

    @overload
    def __init__(self, _iter: Iterable[tuple[K_co, V_co]]): ...

    @overload
    def __init__(self: FrozenDict[str, V_co],
                 _: Iterable[tuple[str, V_co]], **kw: V_co): ...

    @overload
    def __init__(self: FrozenDict[str, str], _iter: Iterable[list[str]]): ...

    def __init__(self, *args, **kw):
        if hasattr(self, "_dict"):
            return
        super().__init__()
        self._dict = dict[K, V](*args, **kw)
        self._hash = None

    def __repr__(self):
        return f"FrozenDict{self._dict}"

    def __hash__(self):
        if self._hash is None:
            # Calculate the hash of a tuple of sorted hashes of k/v pairs
            self._hash = hash(tuple(sorted(hash((k, v))
                              for k, v in self.items())))
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
        if isinstance(__o, FrozenDict):
            return self._dict == __o._dict
        return self._dict == __o

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def items(self):
        return self._dict.items()

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._dict.values()


class FrozenList(tuple[V_co]):
    """
    # FrozenList Class
    Basically just a tuple, but is able to be compared with lists.
    """

    def __new__(cls, value: Iterable[V_co]):
        if isinstance(value, FrozenList):
            return value
        return tuple.__new__(cls, value)

    def __eq__(self, other) -> bool:
        if isinstance(other, list):
            return self == tuple(other)
        return super().__eq__(other)

    def __ne__(self, other) -> bool:
        return not self == other

    def __gt__(self, other) -> bool:
        if isinstance(other, list):
            return self > tuple(other)
        return super().__gt__(other)

    def __ge__(self, other) -> bool:
        if isinstance(other, list):
            return self >= tuple(other)
        return super().__ge__(other)

    def __lt__(self, other) -> bool:
        return not self >= other

    def __le__(self, other) -> bool:
        if isinstance(other, list):
            return self <= tuple(other)
        return super().__le__(other)

    def __hash__(self) -> int:
        return tuple.__hash__(self)

    def __repr__(self) -> str:
        return f"FrozenList{super().__repr__()}"


@overload
def freeze(obj: dict, ensure_hashable=False,  # type: ignore[misc]
           *, memo: set[int] = None) -> FrozenDict: ...


@overload
def freeze(obj: list, ensure_hashable=False,  # type: ignore[misc]
           *, memo: set[int] = None) -> FrozenList: ...


@overload
def freeze(obj: set, ensure_hashable=False,  # type: ignore[misc]
           *, memo: set[int] = None) -> frozenset: ...


@overload
def freeze(obj: V, ensure_hashable=False, *, memo: set[int] = None) -> V: ...


def freeze(obj, ensure_hashable=False, *, memo: set[int] = None):
    """
    Freeze an object by making it immutable and thus hashable.

    **Conservative approach, freezes elements of
    (`list` | `tuple` | `dict` | `FrozenDict` | `set` | `frozenset`)**

    * `obj` is the object to freeze.
    * `ensure_hashable` If `True`, raise `TypeError` when unable to freeze
    """

    if memo is None:
        memo = set()
    if id(obj) in memo:
        raise TypeError("Cannot freeze recursive data structures")
    memo.add(id(obj))
    if hasattr(obj, "__freeze__"):
        obj = obj.__freeze__(memo=memo.copy())
    elif isinstance(obj, dict | FrozenDict):
        # Transform dicts into ``FrozenDict``s
        return FrozenDict((k, freeze(v, ensure_hashable, memo=memo.copy()))
                          for k, v in obj.items())
    elif isinstance(obj, list | tuple):
        # Transform sequences into FrozenLists
        return FrozenList(freeze(el, ensure_hashable, memo=memo.copy())
                          for el in obj)
    elif isinstance(obj, set | frozenset):
        # Transform sets into ``frozenset``s
        return frozenset(freeze(item, ensure_hashable, memo=memo.copy())
                         for item in obj)
    if ensure_hashable:
        hash(obj)
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
            callback=str,
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

    def __call__(self: S, *args: Any, **kw: Any):
        return self._callback(self, *args, **kw)

    def __create(self: S, it: Iterable[str]) -> S:
        return type(self)(it=it, joint=self._joint,
                          callback=self._callback, **self._kw)

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


v = StrChain(["123", '.'])()
