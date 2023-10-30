"""
Indecies for the database.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from contextlib import suppress
from typing import Any, Iterable, Mapping, Sequence, Generic, TypeVar, overload, Callable
from .queries import QueryLike, QueryInstance
from .utils import is_hashable, StrChain, freeze
from . import table as tb
from . import database as db

K = TypeVar("K")
V = TypeVar("V")
IDVar = TypeVar("IDVar", bound=tb.BaseID)
IndexVar = TypeVar("IndexVar", bound="BaseIndex")


class NotIndexedError(Exception):
    """Raised when query is not indexed."""


class BaseIndex(Generic[IDVar], ABC):
    """Map values back to doc_ids"""

    @overload
    def __init__(self: BaseIndex[tb.IncreID],
                 table: db.TinyDB, path: Sequence[str] = None) -> None: ...

    @overload
    def __init__(self,
                 table: tb.Table[IDVar, Any], path: Sequence[str] = None) -> None: ...

    @abstractmethod
    def __init__(self, table, path=None):
        """
        :param path: The path to the field this index is for
        :param table: The table this index is for
        """

    @abstractmethod
    @property
    def at(self: IndexVar) -> Callable[..., IndexVar]: ...


class HashIndex(BaseIndex[IDVar]):
    """
    # HashIndex Class
    Requires values to be freezable/hashable
    """

    @overload
    def __init__(self: HashIndex[tb.IncreID],
                 table: db.TinyDB, path: Sequence[str] = None) -> None: ...

    @overload
    def __init__(self,
                 table: tb.Table[IDVar, Any], path: Sequence[str] = None) -> None: ...

    def __init__(self, table, path=None) -> None:
        super().__init__(table, path)
        self._table = table
        self._bound = False
        if isinstance(table, db.TinyDB):
            self._table = table.default_table
        self._index: dict[Any, set[IDVar]] = {}

        def extract(chain: StrChain, item: Mapping):
            for key in chain:
                item = item[key]
            return item
        self._path = StrChain(path, callback=extract)

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(self._path)

    def add(self, doc: tb.BaseDocument):
        with suppress(KeyError):
            val = self._path(doc)
            f_val = freeze(val, True)
            if f_val not in self._index:
                self._index[f_val] = set()
            self._index[f_val].add(doc.doc_id)

    def remove(self, doc: tb.BaseDocument):
        with suppress(KeyError):
            val = self._path(doc)
            f_val = freeze(val, True)
            self._index[f_val].remove(doc.doc_id)
            if not self._index[f_val]:
                del self._index[f_val]

    def update(self, doc: tb.BaseDocument):
        self.remove(doc)
        self.add(doc)

    def build(self, docs: Iterable[tb.BaseDocument]):
        self.clear()
        for doc in docs:
            self.add(doc)
        self._bind()

    def get(self, item, default=None):
        with suppress(TypeError, KeyError, AttributeError):
            return self._index[freeze(item, True)].copy()
        return default

    def match(self, cond: QueryInstance) -> set[IDVar]:
        op, path = cond._frame[:2]
        if path != self.path and op != "noop":
            raise NotIndexedError(f"{path} is not indexed in this index")
        match op:
            case "exists" | "noop":
                matched = set()
                for k in self._index.values():
                    matched |= k
                return matched
            case "==":
                if cond.cacheable:
                    value = cond._frame[2]
                    return set(self._index[value])
                return self._general_match(cond)
            case "!=":
                if cond.cacheable:
                    value = cond._frame[2]
                    return set(self._index) - set(self._index[value])
                return self._general_match(cond)
            case _:
                return self._general_match(cond)

    def clear(self):
        self._index.clear()

    def _general_match(self, cond: QueryInstance) -> set[IDVar]:
        """Test a query against the index."""
        matched = set()
        for k in self._index:
            dummy = k
            for node in self._path[::-1]:
                dummy = {node: dummy}
            if cond(dummy):
                matched |= self._index[k]
        return matched

    def _bind(self):
        if not self._bound:
            self._bound = True

            @self._table.on.create
            def add(_: str, tab: tb.Table, doc: tb.BaseDocument):
                self.add(doc)

            @self._table.on.update
            def update(_: str, tab: tb.Table, doc: tb.BaseDocument):
                self.update(doc)

            @self._table.on.delete
            def remove(_: str, tab: tb.Table, doc: tb.BaseDocument):
                self.remove(doc)

            @self._table.on.truncate
            def clear(_: str, tab: tb.Table):
                self.clear()

    def __bool__(self):
        return bool(self._index)

    def __len__(self):
        return len(self._index)

    def __iter__(self):
        return iter(self._index)

    def __contains__(self, item):
        with suppress(TypeError, KeyError):
            return freeze(item, True) in self._index

    def __getitem__(self, item) -> set[IDVar]:
        with suppress(TypeError, KeyError, AttributeError):
            return self._index[freeze(item, True)].copy()
        raise KeyError(f"Item {item} not found in the index")


class SortedIndex(BaseIndex[IDVar]):
    """
    # SortedIndex Class
    Requires values to be comparable
    """


class IndexManager:
    ...
