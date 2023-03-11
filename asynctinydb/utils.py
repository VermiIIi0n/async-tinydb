"""
Utility functions.
"""

from __future__ import annotations
from collections import OrderedDict
from contextlib import suppress
from typing import Iterator, TypeVar, Generic, Type, \
    TYPE_CHECKING, Callable,  MutableMapping

from vermils.collections.fridge import FrozenDict, FrozenList, freeze
from vermils.collections.strchain import StrChain
from vermils.gadgets import mimics, sort_class, stringify_keys, supports_in
from vermils.asynctools import *
from vermils.asynctools import __all__ as _async_tools_all

K = TypeVar("K")
V = TypeVar("V")
D = TypeVar("D")
T = TypeVar("T")
K_co = TypeVar("K_co", covariant=True)
V_co = TypeVar("V_co", covariant=True)
S = TypeVar("S", bound="StrChain")
C = TypeVar("C", bound=Callable)

__all__ = (("LRUCache", "freeze", "with_typehint", "stringify_keys",
            "supports_in", "is_container", "is_iterable", "is_hashable",
            "StrChain", "FrozenDict", "mimics", "sort_class", "FrozenList",
            ) + _async_tools_all)


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

    def __init__(self, capacity=None) -> None:
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
