"""
TinyDB is a tiny, document oriented database optimized for your happiness :)

TinyDB stores differrent types of Python data types using a configurable
storage mechanism. It comes with a syntax for querying data and storing
data in multiple tables.

.. codeauthor:: Markus Siemens <markus@m-siemens.de>

Usage example:

>>> from tinydb import TinyDB, where
>>> from tinydb.storages import MemoryStorage
>>> db = TinyDB(storage=MemoryStorage)
>>> await db.insert({'data': 5})  # Insert into '_default' table
>>> await db.search(where('data') == 5)
[{'data': 5, '_id': 1}]
>>> # Now let's create a new table
>>> tbl = db.table('our_table')
>>> for i in range(10):
...     tbl.insert({'data': i})
...
>>> len(tbl.search(where('data') < 5))
5
"""

from .queries import Query, where
from .storages import Storage, JSONStorage, EncryptedJSONStorage, MemoryStorage
from .middlewares import CachingMiddleware
from .modifier import Modifier
from .database import TinyDB
from .version import __version__  # noqa
from .table import BaseID, BaseDocument, IncreID, Document, UUID

__all__ = (
    "TinyDB", "Storage", "JSONStorage",
    "EncryptedJSONStorage", "MemoryStorage",
    "CachingMiddleware",
    "Query", "where", "BaseID", "BaseDocument",
    "Modifier", "IncreID", "Document", "UUID"
)
