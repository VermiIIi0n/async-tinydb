"""
This module implements tables, the central place for accessing and manipulating
data in TinyDB.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
import uuid
from copy import deepcopy
from typing import TYPE_CHECKING, AsyncGenerator, Collection, MutableMapping
from typing import overload, Callable, Iterable
from typing import Mapping, Generic, cast, TypeVar, Type, Any, ParamSpec
from .queries import QueryLike
from .storages import Storage
from .utils import LRUCache, sync_await, AsinkRunner
from .utils import async_run

__all__ = ("Document", "Table", "IncreID")
IDVar = TypeVar("IDVar", bound="BaseID")
DocVar = TypeVar("DocVar", bound="BaseDocument")
ARGS = ParamSpec("ARGS")
V = TypeVar("V")


class BaseID(ABC):
    """
    # BaseID Class
    An abstract class that represents a unique identifier for a document.
    """

    @abstractmethod
    def __init__(self, value):
        super().__init__()

    @abstractmethod
    def __hash__(self) -> int:
        return NotImplemented

    @abstractmethod
    def __eq__(self, other: object) -> bool:
        return NotImplemented

    @classmethod
    @abstractmethod
    def next_id(cls: Type[IDVar], table: Table, keys: Collection[IDVar]) -> IDVar:
        """
        Get the next ID for the given table.
        """
        raise NotImplementedError()

    @classmethod
    @abstractmethod
    def mark_existed(cls: Type[IDVar], table: Table, new_id: IDVar):
        """
        Mark the given id as existed.
        """
        raise NotImplementedError()

    @classmethod
    @abstractmethod
    def clear_cache(cls, table: Table):
        """
        Clear the ID cache for a table.
        """
        raise NotImplementedError()


class IncreID(int, BaseID):
    """ID class using incrementing integers."""
    _cache: dict[str, int] = {}

    __init__ = int.__init__

    def __hash__(self):
        return hash(int(self))

    @classmethod
    def next_id(cls, table: Table, keys: Collection[IncreID]) -> IncreID:
        # If we already know the next ID
        if table.name in cls._cache:
            new = cls(cls._cache[table.name])
            cls._cache[table.name] += 1
            return new

        # If the table is empty, set the initial ID
        if not keys:
            next_id = 1
            cls._cache[table.name] = next_id + 1
            return cls(next_id)

        # Determine the next ID based on the maximum ID that's currently in use
        max_id = max(keys)
        next_id = max_id + 1

        # The next ID we wil return AFTER this call needs to be larger than
        # the current next ID we calculated
        cls._cache[table.name] = next_id + 1
        return cls(next_id)

    @classmethod
    def mark_existed(cls, table: Table, new_id: IncreID):
        cls._cache[table.name] = max(
            cls._cache.get(table.name, 0), int(new_id) + 1)

    @classmethod
    def clear_cache(cls, table: Table):
        cls._cache.pop(table.name, None)


class UUID(uuid.UUID, BaseID):
    """ID class using uuid4 UUIDs."""
    _cache: dict[str, set[uuid.UUID]] = {}

    def __init__(self, value: str | uuid.UUID):  # skipcq: PYL-W0231
        super().__init__(str(value))

    def __hash__(self):
        return uuid.UUID.__hash__(self)

    @classmethod
    def next_id(cls, table: Table, keys: Collection[UUID]) -> UUID:
        if table.name not in cls._cache:
            cls._cache[table.name] = set()
        while True:
            new_id = cls(uuid.uuid4())
            if (new_id not in cls._cache[table.name]  # pragma: no branch
                    and new_id not in keys):
                cls._cache[table.name].add(new_id)
                return new_id

    @classmethod
    def mark_existed(cls, table: Table, new_id: UUID):
        cache = cls._cache.get(table.name, set())
        cache.add(new_id)
        cls._cache[table.name] = cache

    @classmethod
    def clear_cache(cls, table: Table):
        cls._cache.pop(table.name, None)


class BaseDocument(MutableMapping[IDVar, Any]):
    @property
    @abstractmethod
    def doc_id(self) -> IDVar:
        raise NotImplementedError()

    @doc_id.setter
    def doc_id(self, value: IDVar):
        raise NotImplementedError()


class Document(dict, BaseDocument[IDVar]):
    """
    A document stored in the database.

    This class provides a way to access both a document's content and
    its ID using ``doc.doc_id``.
    """

    def __init__(self, value: Mapping, doc_id: IDVar):
        super().__init__(value)
        self.doc_id = doc_id

    @property
    def doc_id(self) -> IDVar:
        return self._doc_id

    @doc_id.setter
    def doc_id(self, value: IDVar):
        self._doc_id = value


class Table(Generic[IDVar, DocVar]):
    """
    Represents a single TinyDB table.

    It provides methods for accessing and manipulating documents.

    .. admonition:: Query Cache

        As an optimization, a query cache is implemented using a
        :class:`~tinydb.utils.LRUCache`. This class mimics the interface of
        a normal ``dict``, but starts to remove the least-recently used entries
        once a threshold is reached.

        The query cache is updated on every search operation. When writing
        data, the whole cache is discarded as the query results may have
        changed.
    """

    #: The class used to represent documents

    #: The class used for caching query results
    #:
    #: .. versionadded:: 4.0
    query_cache_class = LRUCache

    #: The default capacity of the query cache
    #:
    #: .. versionadded:: 4.0
    default_query_cache_capacity = 10
    # A stupid workaround for mypy

    @overload
    def __init__(self: Table[IncreID, Document], storage: Storage, name: str,
                 cache_size=default_query_cache_capacity, *, no_dbcache=False): ...

    @overload
    def __init__(self: Table[IncreID, DocVar], storage: Storage, name: str,
                 cache_size=default_query_cache_capacity,
                 *, document_class: Type[DocVar], no_dbcache=False): ...

    @overload
    def __init__(self: Table[IDVar, Document], storage: Storage, name: str,
                 cache_size=default_query_cache_capacity,
                 *, document_id_class: Type[IDVar], no_dbcache=False): ...

    @overload
    def __init__(self: Table[IDVar, DocVar], storage: Storage, name: str,
                 cache_size=default_query_cache_capacity, *, no_dbcache=False,
                 document_id_class: Type[IDVar], document_class: Type[DocVar],
                 ): ...

    def __init__(
        self,
        storage: Storage,
        name: str,
        cache_size=default_query_cache_capacity,
        *,
        no_dbcache=False,
        document_id_class=IncreID,
        document_class=Document,
    ):
        """
        Create a table instance.
        """

        self.document_id_class = document_id_class
        """The class used for document IDs in this table."""
        self.document_class = document_class
        """The class used to represent documents in this table."""
        self.no_dbcache = no_dbcache
        """Whether to disable the DB-level cache for this table."""
        self._storage = storage
        self._name = name
        self._cache: dict[IDVar, DocVar] = None  # type: ignore
        """Cache for documents in this table."""
        self._query_cache: LRUCache[QueryLike, tuple[IDVar, ...]] \
            = self.query_cache_class(capacity=cache_size)
        """Cache for query results in this table."""

        self.document_id_class.clear_cache(self)  # clear the ID cache

        self._isolevel = 0
        self._closed = False
        self._sink = AsinkRunner()
        """Serialise all operations on this table."""

    def __repr__(self):
        args = [
            f"name='{self.name}'",
            f"total={len(self)}",
            f"storage={self._storage}",
        ]

        return f"<{type(self).__name__} {', '.join(args)}>"

    @property
    def name(self) -> str:
        """
        Get the table name.
        """
        return self._name

    @property
    def storage(self) -> Storage:
        """
        Get the table storage instance.
        """
        return self._storage

    async def insert(self, document: Mapping) -> IDVar:
        """
        Insert a new document into the table.

        :param document: the document to insert
        :returns: the inserted document's ID
        """

        # Make sure the document implements the ``Mapping`` interface
        if not isinstance(document, Mapping):
            raise ValueError("Document is not a Mapping")

        doc_id: IDVar = None  # type: ignore

        def updater(table: dict[IDVar, DocVar]):
            # Now, we update the table and add the document
            nonlocal doc_id
            nonlocal document

            if isinstance(document, self.document_class):
                # For a `Document` object we use the specified ID
                doc_id = self.document_id_class(document.doc_id)

                if doc_id in table:
                    raise ValueError(f"Document with ID {str(doc_id)} "
                                     "already exists")

                # We also mark the ID as existing to prevent it from being
                # generated again
                self.document_id_class.mark_existed(self, doc_id)
            else:
                # For other objects we generate a new ID
                doc_id = self._get_next_id(table.keys())

            # If isolevel is higher than 2, deep copy the document
            if self._isolevel >= 2:
                document = deepcopy(document)

            table[doc_id] = self.document_class(document, doc_id)

        # See below for details on ``Table._update``
        await self._update_table(updater)

        return doc_id

    async def insert_multiple(self, documents: Iterable[Mapping]) -> list[IDVar]:
        """
        Insert multiple documents into the table.

        :param documents: an Iterable of documents to insert
        :returns: a list containing the inserted documents' IDs
        """

        doc_ids = []

        def updater(table: dict[IDVar, DocVar]):
            for document in documents:

                # Make sure the document implements the ``Mapping`` interface
                if not isinstance(document, Mapping):
                    raise ValueError("Document is not a Mapping")

                if self._isolevel >= 2:
                    document = deepcopy(document)

                if isinstance(document, self.document_class):
                    # Check if document does not override an existing document
                    if document.doc_id in table:
                        raise ValueError(
                            f"Document with ID {str(document.doc_id)} "
                            f"already exists"
                        )

                    # Store the doc_id, so we can return all document IDs
                    # later. Then save the document with its doc_id and
                    # skip the rest of the current loop
                    doc_id = self.document_id_class(document.doc_id)
                    doc_ids.append(doc_id)
                    table[doc_id] = self.document_class(document, doc_id)
                    continue

                # Generate new document ID for this document
                # Store the doc_id, so we can return all document IDs
                # later, then save the document with the new doc_id
                doc_id = self._get_next_id(table.keys())
                doc_ids.append(doc_id)
                table[doc_id] = self.document_class(document, doc_id)

        # See below for details on ``Table._update``
        await self._update_table(updater)

        return doc_ids

    async def all(self) -> list[DocVar]:
        """
        Get all documents stored in the table.

        :returns: a list with all documents.
        """

        # iter(self) (implemented in Table.__iter__ provides an iterator
        # that returns all documents in this table. We use it to get a list
        # of all documents by using the ``list`` constructor to perform the
        # conversion.

        return await self.search()

    async def search(
            self,
            cond: QueryLike = None,
            limit: int = None,
            doc_ids: Iterable[IDVar] = None) -> list[DocVar]:
        """
        Search for all documents matching a 'where' cond,
        whilst they ids are in `doc_ids`(if specified).

        * `cond`: the condition to check against
        * `limit`: the maximum number of documents to return, `None` for no limit
        * `doc_ids`: an iterable of document IDs to search in
        """

        table = await self._read_table()
        ret = await self._run_with_iso(self._search, cond, table, limit, doc_ids)
        return list(ret.values())

    async def get(
        self,
        cond: QueryLike = None,
        doc_id: IDVar = None,
    ) -> DocVar | None:
        """
        Get exactly one document specified by a query or a document ID.

        Returns ``None`` if the document doesn't exist.

        :param cond: the condition to check against
        :param doc_id: the document's ID

        :returns: the document or ``None``
        """

        if cond is None and doc_id is None:
            raise ValueError("You have to pass either cond or doc_id")

        table = await self._read_table()
        doc_ids = None if doc_id is None else (doc_id,)
        ret = await self._run_with_iso(self._search, cond, table, 1, doc_ids)
        if ret:
            return ret.popitem()[1]
        return None

    async def contains(
        self,
        cond: QueryLike = None,
        doc_id: IDVar = None
    ) -> bool:
        """
        Check whether the database contains a document matching a query or
        an ID.

        If ``doc_id`` is set, it checks if the db contains the specified ID.

        :param cond: the condition use
        :param doc_id: the document ID to look for
        """
        if cond is None and doc_id is None:
            raise ValueError("You have to pass either cond or doc_id")
        return (await self.get(cond, doc_id=doc_id)) is not None

    async def update(
        self,
        fields: Mapping | Callable[[Mapping], None],
        cond: QueryLike = None,
        doc_ids: Iterable[IDVar] = None,
    ) -> list[IDVar]:
        """
        Update all matching documents to have a given set of fields.

        :param fields: the fields that the matching documents will have
                       or a method that will update the documents
        :param cond: which documents to update
        :param doc_ids: a list of document IDs
        :returns: a list containing the updated document's ID
        """

        # Define the function that will perform the update
        if callable(fields):
            def perform_update(table: dict[IDVar, DocVar], doc_id: IDVar):
                # Update documents by calling the update function provided by
                # the user
                if TYPE_CHECKING:
                    assert callable(fields)  # skipcq: BAN-B101
                fields(table[doc_id])
        else:
            def perform_update(table: dict[IDVar, DocVar], doc_id: IDVar):
                nonlocal fields
                if TYPE_CHECKING:
                    assert isinstance(fields, dict)  # skipcq: BAN-B101
                if self._isolevel >= 2:
                    fields = deepcopy(fields)
                # Update documents by setting all fields from the provided data
                table[doc_id].update(fields)

        if doc_ids is not None:
            # Perform the update operation for documents specified by a list
            # of document IDs

            updated_ids = list(doc_ids)

            def updater_by_ids(table: dict[IDVar, DocVar]):
                # Call the processing callback with all document IDs
                for doc_id in updated_ids:
                    perform_update(table, doc_id)

            # Perform the update operation (see _update_table for details)
            await self._update_table(updater_by_ids)

            return updated_ids

        if cond is not None:
            # Perform the update operation for documents specified by a query

            # Collect affected doc_ids
            updated_ids = []

            def updater_by_cond(table: dict[IDVar, DocVar]):
                _cond = cast(QueryLike, cond)

                # We need to convert the keys iterator to a list because
                # we may remove entries from the ``table`` dict during
                # iteration and doing this without the list conversion would
                # result in an exception (RuntimeError: dictionary changed size
                # during iteration)
                for doc_id in list(table.keys()):
                    # Pass through all documents to find documents matching the
                    # query. Call the processing callback with the document ID
                    if _cond(table[doc_id]):
                        # Add ID to list of updated documents
                        updated_ids.append(doc_id)

                        # Perform the update (see above)
                        perform_update(table, doc_id)

            # Perform the update operation (see _update_table for details)
            await self._update_table(updater_by_cond)

            return updated_ids

        # Update all documents unconditionally

        updated_ids = []

        def updater(table: dict[IDVar, DocVar]):
            # Process all documents
            for doc_id in list(table.keys()):
                # Add ID to list of updated documents
                updated_ids.append(doc_id)

                # Perform the update (see above)
                perform_update(table, doc_id)

        # Perform the update operation (see _update_table for details)
        await self._update_table(updater)

        return updated_ids

    async def update_multiple(
        self,
        updates: Iterable[
            tuple[Mapping | Callable[[Mapping], None], QueryLike]
        ],
    ) -> list[IDVar]:
        """
        Update all matching documents to have a given set of fields.

        :returns: a list containing the updated document's ID
        """

        # Define the function that will perform the update
        def perform_update(fields: Callable[[Mapping], None] | Mapping,
                           table: dict[IDVar, DocVar], doc_id: IDVar):
            if callable(fields):
                # Update documents by calling the update function provided
                # by the user
                fields(table[doc_id])
            else:
                if self._isolevel >= 2:
                    fields = deepcopy(fields)
                # Update documents by setting all fields from the provided
                # data
                table[doc_id].update(fields)

        # Perform the update operation for documents specified by a query

        # Collect affected doc_ids
        updated_ids = []

        def updater(table: dict[IDVar, DocVar]):
            # We need to convert the keys iterator to a list because
            # we may remove entries from the ``table`` dict during
            # iteration and doing this without the list conversion would
            # result in an exception (RuntimeError: dictionary changed size
            # during iteration)
            for doc_id in list(table.keys()):
                for fields, cond in updates:
                    _cond = cast(QueryLike, cond)

                    # Pass through all documents to find documents matching the
                    # query. Call the processing callback with the document ID
                    if _cond(table[doc_id]):
                        # Add ID to list of updated documents
                        updated_ids.append(doc_id)

                        # Perform the update (see above)
                        perform_update(fields, table, doc_id)

        # Perform the update operation (see _update_table for details)
        await self._update_table(updater)

        return updated_ids

    async def upsert(self, document: Mapping, cond: QueryLike = None) -> list[IDVar]:
        """
        Update documents, if they exist, insert them otherwise.

        Note: This will update *all* documents matching the query. Document
        argument can be a tinydb.table.Document object if you want to specify a
        doc_id.

        :param document: the document to insert or the fields to update
        :param cond: which document to look for, optional if you've passed a
        Document with a doc_id
        :returns: a list containing the updated documents' IDs
        """

        # Extract doc_id
        if isinstance(document, self.document_class):
            doc_ids: list[IDVar] | None = [document.doc_id]
        else:
            doc_ids = None

        # Make sure we can actually find a matching document
        if doc_ids is None and cond is None:
            raise ValueError("If you don't specify a search query, you must "
                             "specify a doc_id. Hint: use a table.Document "
                             "object.")

        # Perform the update operation
        try:
            updated_docs = await self.update(document, cond, doc_ids)
        except KeyError:
            # This happens when a doc_id is specified, but it's missing
            updated_docs = None

        # If documents have been updated: return their IDs
        if updated_docs:
            return updated_docs

        # There are no documents that match the specified query -> insert the
        # data as a new document
        return [await self.insert(document)]

    async def remove(
        self,
        cond: QueryLike = None,
        doc_ids: Iterable[IDVar] = None,
    ) -> list[IDVar]:
        """
        Remove all matching documents.

        :param cond: the condition to check against
        :param doc_ids: a list of document IDs
        :returns: a list containing the removed documents' ID
        """
        if doc_ids is not None:
            # This function returns the list of IDs for the documents that have
            # been removed. When removing documents identified by a set of
            # document IDs, it's this list of document IDs we need to return
            # later.
            # We convert the document ID iterator into a list, so we can both
            # use the document IDs to remove the specified documents and
            # to return the list of affected document IDs
            removed_ids = list(doc_ids)

            def updater(table: dict[IDVar, DocVar]):
                for doc_id in removed_ids:
                    table.pop(doc_id)

            # Perform the remove operation
            await self._update_table(updater)

            return removed_ids

        if cond is not None:
            removed_ids = []

            # This updater function will be called with the table data
            # as its first argument. See ``Table._update`` for details on this
            # operation
            def rm_updater(table: dict[IDVar, DocVar]):
                # We need to convince MyPy (the static type checker) that
                # the ``cond is not None`` invariant still holds true when
                # the updater function is called
                _cond = cast(QueryLike, cond)

                # We need to convert the keys iterator to a list because
                # we may remove entries from the ``table`` dict during
                # iteration and doing this without the list conversion would
                # result in an exception (RuntimeError: dictionary changed size
                # during iteration)
                for doc_id in list(table.keys()):
                    if _cond(table[doc_id]):
                        # Add document ID to list of removed document IDs
                        removed_ids.append(doc_id)

                        # Remove document from the table
                        table.pop(doc_id)

            # Perform the remove operation
            await self._update_table(rm_updater)

            return removed_ids

        raise RuntimeError('Use truncate() to remove all documents')

    async def truncate(self) -> None:
        """
        Truncate the table by removing all documents.
        """

        # Update the table by resetting all data
        await self._update_table(lambda table: table.clear())

        # Reset document ID counter
        self.document_id_class.clear_cache(self)

    async def count(self, cond: QueryLike) -> int:
        """
        Count the documents matching a query.

        :param cond: the condition use
        """

        return len(await self.search(cond))

    async def close(self) -> None:
        """
        Close the table.
        """

        if not self._closed:
            self.clear_cache()
            self.clear_data_cache()
            await self._sink.aclose()
            self._closed = True

    def clear_cache(self) -> None:
        """
        Clear the query cache.

        Scheduled to be executed immediately
        """

        # Put function in execution queue and run with a higher priority
        # This is to ensure thread safety
        self._sink.sync_run_as(2, self._query_cache.clear).result()

    def clear_data_cache(self):
        """
        Clear the DB-level cache.

        Scheduled to be executed immediately
        """

        def updater():
            self._cache = None
        # Put function in execution queue and run with a higher priority
        self._sink.sync_run_as(2, updater).result()

    def __len__(self):
        """
        Count the total number of documents in this table.
        """
        table = sync_await(self._read_table())
        return len(table)

    def __aiter__(self) -> AsyncGenerator[DocVar, None]:
        """
        Iterate over all documents stored in the table.

        :returns: an iterator over all documents.
        """

        # Iterate all documents and their IDs
        async def iterator():
            for doc_id, doc in (await self._read_table()).items():
                # Convert documents to the document class
                if self._isolevel >= 2:
                    yield deepcopy(doc)
                else:
                    yield self.document_class(doc, doc_id)
        return iterator()

    def _get_next_id(self, keys: Collection[IDVar]) -> IDVar:
        """
        Return the ID for a newly inserted document.
        """

        return self.document_id_class.next_id(self, keys)

    def __del__(self):
        """
        Clean up the table.
        """
        self._sink.close()

    def _search(self, cond: QueryLike | None,
                docs: dict[IDVar, DocVar],
                limit: int | None,
                doc_ids: Iterable[IDVar] | None) -> dict[IDVar, DocVar]:
        limit = len(docs) if limit is None else limit
        if limit < 0:
            raise ValueError("Limit must be non-negative")
        cacheable = True  # Whether the query is cacheable
        # Only cache cacheable queries

        # First, we check if the query has a cache
        cached_ids = None if cond is None else self._query_cache.get(cond)
        if cached_ids is not None:
            try:
                docs = {_id: docs[_id] for _id in cached_ids}
                cacheable = False  # No need to cache again
            except KeyError:
                # The cache is invalid, so we need to recompute it
                cached_ids = None

        # doc_ids sieve, if doc_ids are specified
        if doc_ids is not None:
            cacheable = False  # cache only based on cond
            docs = {_id: docs[_id] for _id in doc_ids if _id in docs}

        # cond sieve, if cond is specified, otherwise apply limit here
        if cond is not None and cached_ids is None:
            # Also apply limit here since cond() might be expensive
            docs = {
                _id: doc for _id, doc in docs.items()
                if cond(doc) and (limit := limit - 1) >= 0
            }
            # Note also that by default we expect custom query objects to be
            # cacheable (which means they need to have a stable hash value).
            # This is to keep consistency with TinyDB's behavior before
            # `is_cacheable` was introduced which assumed that all queries
            # are cacheable.
            cacheable = cacheable and getattr(cond, "is_cacheable", lambda: True)()
        # limit sieve
        elif limit < len(docs):
            docs = {_id: docs[_id] for _id in docs if (limit := limit - 1) >= 0}

        cacheable = cacheable and limit >= 0  # If the limit is not reached

        if cacheable:
            if TYPE_CHECKING:  # Make stupid mypy happy
                assert cond is not None  # skipcq: BAN-B101
            # Update the query cache
            self._query_cache[cond] = tuple(docs.keys())

        # deepcopy if isolation level is >= 2
        # otherwise return shallow copy in case of no sieve been applied
        return deepcopy(docs) if self._isolevel >= 2 else docs.copy()

    async def _read_table(self) -> dict[IDVar, DocVar]:
        """
        Read the table data from the underlying storage 
        if cache is not exist.
        """

        # If cache exists
        if self._cache is not None:
            return self._cache

        # Read the table data from the underlying storage
        raw = await self._read_raw_table()
        cooked: dict[IDVar, DocVar] | None = None

        def cook():
            nonlocal cooked
            doc_cls = self.document_class
            id_cls = self.document_id_class
            cooked = {
                id_cls(doc_id): doc_cls(rdoc, doc_id=id_cls(doc_id))
                for doc_id, rdoc in raw.items()
            }
            if not self.no_dbcache:
                # Caching if no_dbcache is not set
                self._cache = cooked

        await self._run_with_iso(cook)
        return self._cache or cooked

    async def _read_raw_table(self) -> MutableMapping[Any, Mapping]:
        """
        Read the table data from the underlying storage.

        Documents and doc_ids are NOT yet transformed, as 
        we may not want to convert *all* documents when returning
        only one document for example.
        """

        # Retrieve the tables from the storage
        tables = await self._storage.read()

        if tables is None:
            # The database is empty
            return {}

        # Retrieve the current table's data
        return tables.get(self.name, {})

    async def _update_table(self, updater: Callable[[dict[IDVar, DocVar]], None]):
        """
        Perform a table update operation.

        The storage interface used by TinyDB only allows to read/write the
        complete database data, but not modifying only portions of it. Thus,
        to only update portions of the table data, we first perform a read
        operation, perform the update on the table data and then write
        the updated data back to the storage.

        As a further optimization, we don't convert the documents into the
        document class, as the table data will *not* be returned to the user.
        """

        tables: MutableMapping[Any, Mapping] = await self._storage.read() or {}

        table = await self._read_table()

        # Perform the table update operation
        await self._run_with_iso(updater, table)
        tables[self.name] = table

        try:
            # Write the newly updated data back to the storage
            await self._storage.write(tables)
        except Exception:
            # Writing failure, data cache is out of sync
            self.clear_data_cache()
            raise
        finally:
            # Clear the query cache, as the table contents have changed
            self.clear_cache()

    async def _run_with_iso(self, func: Callable[ARGS, V],
                            *args: ARGS.args, **kwargs: ARGS.kwargs) -> V:
        """Run sync function with isolation level"""
        if self._isolevel:
            return await self._sink.run(func, *args, **kwargs)
        return await async_run(func, *args, **kwargs)
