"""
This module contains the main component of TinyDB: the database.
"""

from __future__ import annotations
from typing import AsyncGenerator, Type, overload, TypeVar, Generic
from .storages import Storage, JSONStorage
from .middlewares import Middleware
from .table import Table, Document, IncreID, IDVar, DocVar, BaseDocument
from .utils import with_typehint, sync_await

# The table's base class. This is used to add type hinting from the Table
# class to TinyDB. Currently, this supports PyCharm, Pyright/VS Code and MyPy.
TableBase: Type[Table] = with_typehint(Table)
S = TypeVar("S", bound=Storage, covariant=True)


class TinyDB(Generic[S], TableBase):
    """
    The main class of TinyDB.

    The ``TinyDB`` class is responsible for creating the storage class instance
    that will store this database's documents, managing the database
    tables as well as providing access to the default table.

    For table management, a simple ``dict`` is used that stores the table class
    instances accessible using their table name.

    Default table access is provided by forwarding all unknown method calls
    and property access operations to the default table by implementing
    ``__getattr__``.

    When creating a new instance, all arguments and keyword arguments (except
    for ``storage``) will be passed to the storage class that is provided. If
    no storage class is specified, :class:`~tinydb.storages.JSONStorage` will be
    used.

    .. admonition:: Customization

        For customization, the following class variables can be set:

        - ``table_class`` defines the class that is used to create tables,
        - ``default_table_name`` defines the name of the default table, and
        - ``default_storage_class`` will define the class that will be used to
          create storage instances if no other storage is passed.

        .. versionadded:: 4.0

    .. admonition:: Data Storage Model

        Data is stored using a storage class that provides persistence for a
        ``dict`` instance. This ``dict`` contains all tables and their data.
        The data is modelled like this::

            {
                "table1": {
                    0: {document...},
                    1: {document...},
                },
                "table2": {
                    ...
                }
            }

        Each entry in this ``dict`` uses the table name as its key and a
        ``dict`` of documents as its value. The document ``dict`` contains
        document IDs as keys and the documents themselves as values.

    :param storage: The class of the storage to use. Will be initialized
                    with ``args`` and ``kwargs``.
    """

    #: The class that will be used to create table instances
    #:
    #: .. versionadded:: 4.0
    table_class = Table

    #: The name of the default table
    #:
    #: .. versionadded:: 4.0
    default_table_name = "_default"

    @overload
    def __init__(self: TinyDB[S], *args, storage: Type[S], **kw) -> None:
        """For `Storage` classes passed to `storage`"""
    @overload
    def __init__(self: TinyDB[S], *args, storage: Middleware[S], **kw) -> None:
        """For `Middleware` passed to `storage`"""
    @overload
    def __init__(self: TinyDB[JSONStorage], *args, **kw) -> None:
        """For default `JSONStorage`"""

    def __init__(self, *args, storage=JSONStorage, **kw) -> None:
        """
        Create a new instance of TinyDB.
        * `storage`: The class of the storage to use.
        * `no_dbcache`: If set to ``True``, the DB-level cache will be disabled.
        * `isolevel`: The isolation level to use for the database.
        """

        self._isolevel = kw.pop("isolevel", 1)
        self._no_dbcache: bool = kw.pop("no_dbcache", False)

        # Prepare the storage
        self._storage: S = storage(*args, **kw)

        self._opened = True
        self._tables: dict[str, Table] = {}

    def __repr__(self):
        tables = sync_await(self.tables())
        args = [
            f"tables={list(tables)}",
            f"tables_count={len(tables)}",
            f"default_table_documents_count={self.__len__()}",
            "all_tables_documents_count="
            f"{[f'{table}={len(self.table(table))}' for table in tables]}",
        ]

        return f"<{type(self).__name__} {', '.join(args)}>"

    @overload
    def table(self, name: str, cache_size: int = 10, *,
              document_id_class: Type[IDVar],
              document_class: Type[DocVar], **kw) -> Table[IDVar, DocVar]: ...

    @overload
    def table(self, name: str, cache_size: int = 10, *,
              document_id_class: Type[IDVar], **kw) -> Table[IDVar, Document]: ...

    @overload
    def table(self, name: str, cache_size: int = 10, *,
              document_class: Type[DocVar], **kw) -> Table[IncreID, DocVar]: ...

    @overload
    def table(self, name: str, cache_size: int = 10,
              **kw) -> Table[IncreID, Document]: ...

    def table(self, name, cache_size=10, *,
              document_id_class=None, document_class=None, **kw):
        """
        Get access to a specific table.

        If the table hasn't been accessed yet, a new table instance will be
        created using the :attr:`~tinydb.database.TinyDB.table_class` class.
        Otherwise, the previously created table instance wil be returned.

        All further options besides the name are passed to the table class which
        by default is :class:`~tinydb.table.Table`. Check its documentation
        for further parameters you can pass.

        * `name`: The name of the table.
        * `cache_size`: The size of the cache used to store the query results.
        * `document_id_class`: By default :class:`~asynctinydb.IncreID` is used.
        * `document_class`: By default :class:`~asynctinydb.Document` is used.
        * `kw`: Keyword arguments to pass to the table class constructor
        """

        if not self._opened:
            raise IOError('Database is closed')

        if name in self._tables:
            table = self._tables[name]
            if (document_id_class is not None and
                    document_id_class is not table.document_id_class
                or document_class is not None and
                    document_class is not table.document_class):
                raise ValueError(
                    f"Table {name} already exists with different "
                    "document_id_class or document_class"
                )
            return table

        kw["cache_size"] = cache_size
        kw["no_dbcache"] = self._no_dbcache
        kw["document_id_class"] = document_id_class or IncreID
        kw["document_class"] = document_class or Document
        table = self.table_class(self.storage, name, **kw)
        table._isolevel = self._isolevel
        self._tables[name] = table

        return table

    async def tables(self) -> set[str]:
        """
        Get the names of all tables in the database.

        :returns: a set of table names
        """

        # TinyDB stores data as a dict of tables like this:
        #
        #   {
        #       "_default": {
        #           0: {document...},
        #           1: {document...},
        #       },
        #       "table1": {
        #           ...
        #       }
        #   }
        #
        # To get a set of table names, we thus construct a set of this main
        # dict which returns a set of the dict keys which are the table names.
        #
        # Storage.read() may return ``None`` if the database file is empty,
        # so we need to consider this case to and return an empty set in this
        # case.
        if not self._opened:
            raise IOError("Database is closed")

        return set((await self.storage.read()) or {})

    async def drop_tables(self) -> None:
        """
        Drop all tables from the database. **CANNOT BE REVERSED!**
        """

        if not self._opened:
            raise IOError('Database is closed')

        # We drop all tables from this database by writing an empty dict
        # to the storage thereby returning to the initial state with no tables.
        await self.storage.write({})

        # Clear in ram cache
        for tab in self._tables.values():
            tab.clear_data_cache()

        # After that we need to remember to empty the ``_tables`` dict, so we'll
        # create new table instances when a table is accessed again.
        self._tables.clear()

    async def drop_table(self, name: str) -> None:
        """
        Drop a specific table from the database. **CANNOT BE REVERSED!**

        :param name: The name of the table to drop.
        """

        if not self._opened:
            raise IOError("Database is closed")

        # If the table is currently opened, we need to forget the table class
        # instance
        if name in self._tables:
            self._tables.pop(name).clear_data_cache()

        data = await self.storage.read()

        # The database is uninitialized, there's nothing to do
        if data is None:
            return

        # The table does not exist, there's nothing to do
        if name not in data:
            return

        # Remove the table from the data dict
        del data[name]

        # Store the updated data back to the storage
        await self.storage.write(data)

    @property
    def default_table(self) -> Table[IncreID, Document]:
        """
        Get the default table.

        The default table is the table with the name ``"_default"``. If the
        table does not exist, it will be created.
        """

        return self.table(self.default_table_name)

    @property
    def storage(self) -> S:
        """
        Get the storage instance used for this TinyDB instance.

        :return: This instance's storage
        """
        return self._storage

    @property
    def isolevel(self) -> int:
        """
        Get the isolation level used for this TinyDB instance.

        * `0`: No isolation
        * `1`: Serialised CRUD operations (default) (thread-safe)

        :return: This instance's isolation level
        """
        return self._isolevel

    @isolevel.setter
    def isolevel(self, value: int) -> None:
        for tab in self._tables.values():
            tab._isolevel = value
        self._isolevel = value

    async def close(self) -> None:
        """
        Close the database.

        This may be needed if the storage instance used for this database
        needs to perform cleanup operations like closing file handles.

        To ensure this method is called, the TinyDB instance can be used as a
        context manager::

            async with TinyDB("data.json") as db:
                await db.insert({"foo": "bar"})

        Upon leaving this context, the ``close`` method will be called.
        """
        if self._opened:
            self._opened = False
            for tab in self._tables.values():
                await tab.close()
            await self.storage.close()

    async def __aenter__(self):
        """
        Use the database as a context manager.

        Using the database as a context manager ensures that the
        :meth:`~tinydb.database.TinyDB.close` method is called upon leaving
        the context.

        :return: The current instance
        """
        return self

    async def __aexit__(self, *args):
        """
        Close the storage instance when leaving a context.
        """
        if self._opened:
            await self.close()

    def __getattr__(self, name):
        """
        Forward all unknown attribute calls to the default table instance.
        """
        return getattr(self.default_table, name)

    # Here we forward magic methods to the default table instance. These are
    # not handled by __getattr__ so we need to forward them manually here

    def __len__(self):
        """
        Get the total number of documents in the default table.

        >>> db = TinyDB("db.json")
        >>> len(db)
        0
        """
        return len(self.table(self.default_table_name))

    def __aiter__(self) -> AsyncGenerator[BaseDocument, None]:
        """
        Return an iterator for the default table's documents.
        """
        return self.table(self.default_table_name).__aiter__()
