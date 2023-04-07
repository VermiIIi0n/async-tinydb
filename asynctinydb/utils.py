"""
Utility functions.
"""

from __future__ import annotations
from collections import OrderedDict
from contextlib import suppress
from typing import Any, Iterator, TypeVar, Generic, Type, \
    TYPE_CHECKING, Callable

from contextlib import suppress
from cachetools import LRUCache as _LRUCache
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
            ) + _async_tools_all
           )


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


class LRUCache(_LRUCache, Generic[K, V]):
    """
    A least-recently used (LRU) cache with a fixed cache size.

    This class acts as a dictionary but has a limited size. If the number of
    entries in the cache exceeds the cache size, the least-recently accessed
    entry will be discarded.

    This is implemented uses the ``cachetools`` package.
    """

    def __init__(self, capacity=None,
                 getsizeof: Callable[[Any], int] = None) -> None:
        capacity = float("inf") if capacity is None else capacity
        super().__init__(maxsize=capacity, getsizeof=getsizeof)

    @property
    def lru(self) -> list[K]:
        return list(self.keys())

    @property
    def length(self) -> int:
        return len(self)

    def __setitem__(self, key: K, value: V) -> None:
        with suppress(ValueError):
            super().__setitem__(key, value)
