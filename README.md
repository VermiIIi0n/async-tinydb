<img src="./artwork/logo.png" alt="logo" style="zoom:50%;" />

# What's This?

An asynchronous version of `TinyDB`.

Almost every method is asynchronous. And it's based on `TinyDB 4.7.0+`.  

I will try to keep up with the latest version of `TinyDB`.



# Incompatible Changes

* **Asynchronous**: Say goodbye to blocking IO. **Don't forget to `await` async methods**!

* **Drop support**: Only supports Python 3.10+.

* **`ujson`:** Using `ujson` instead of `json`. Some arguments aren't compatible with `json`[^1]

* **Storage `closed` property**: Original `TinyDB` won't raise exceptions when operating on a closed file. Now the property `closed` of `Storage` classes is required to be implemented. An `IOError` should be raised.

* **[Miscellaneous](#misc)**: Differences only matter in edge cases.

# New Features

* **Event hooks**: You can now use event hooks to do something before or after an operation. See [Event Hooks](#event-hooks) for more details.

* **Redesigned ID & Doc class**: You can [replace](#replacing-id-&-document-class) and [customise them](#customise-id-class) more pleasingly.
  
* **DB-level caching**: This significantly improves the performance of all operations. However, the responsibility of converting the data to the correct type is transferred to the Storage[^2][^disable-db-level]. 

* **Built-in `Modifier`**: Use `Modifier` to easily [encrypt](#encryption), [compress](./docs/Modifier.md#Compression) and [extend types](./docs/Modifier.md#Conversion) of your database. Sure you can do much more than these. _(See [Modifier](./docs/Modifier.md))_

* **Isolation Level**: Performance or ACID? It's up to you[^isolevel].

* **Atomic Write**: **A**CID!

* **Batch search by IDs**: `search` method now takes an extra `doc_ids` argument (works like an additional condition)

# How to use it?

## Installation

* Minimum: `pip install async-tinydb`
* Encryption: `pip install async-tinydb[encryption]`
* Compression: `pip install async-tinydb[compression]`
* Full: `pip install async-tinydb[all]`

## Importing

```Python
from asynctinydb import TinyDB, where
```

## Using

See the [original `TinyDB` documents](https://tinydb.readthedocs.org). Insert an `await` in front of async methods. 

Notice that some codes are still blocking, for example, when calling `len()` on `TinyDB` or `Table` Objects.

That's it.

******

## Documents For Advances Usage

* [Modifier](./docs/Modifier.md)
* [Event Hooks](./docs/EventHooks.md)

## Replacing ID & Document Class

**NOTICE: Mixing classes in one table may cause errors!**

When a table exists in a file, `Async-TinyDB` won't determine classes by itself, it is your duty to make sure classes are matching.

### ID Classes

* `IncreID`: Default ID class, mimics the behaviours of the original `int` ID but requires much fewer IO operations.
* `UUID`: Uses `uuid.UUID`[^uuid-version].

### Document Class

* `Document`: Default document class, uses `dict`under the bonet.

```Python
from asynctinydb import TinyDB, UUID, IncreID, Document

db = TinyDB("database.db")

# Setting ID class to UUID, document class to Document
tab = db.table("table1", document_id_class=UUID, document_class=Document)
```

_See [Customisation](#customise-id-class) for more details_

## Encryption

Currently only supports AES-GCM encryption.

There are two ways to use encryption:

### 1. Use `EncryptedJSONStorage` directly

```Python
from asynctinydb import EncryptedJSONStorage, TinyDB

async def main():
    db = TinyDB("db.json", key="your key goes here", storage=EncryptedJSONStorage)

```

### 2. Use  `Modifier` class

_See [Encryption](./docs/Modifier.md#Encryption)_

## Isolation Level

To avoid blocking codes, Async-TinyDB puts CPU-bound tasks into another thread (Useful with interpreters without GIL)

Unfortunately, this introduces chances of data being modified when:

* Manipulating mutable objects within `Document` instances in another coroutine
* Performing updating/saving/searching operations (These operations are run in a different thread/process)
* The conditions above are satisfied in the same `Table`
* The conditions above are satisfied simultaneously.

Avoid these operations or set a higher isolation level to mitigate this problem.

```Python
db.isolevel = 2
```

`isolevel`:

0. No isolation
1. Serialised CRUD operations (Also ensures thread safety) (default)
2. Deepcopy documents on CRUD (Ensures `Index` & `Query Cache` consistency)



## DB-level caching

DB-level caching improves performance dramatically.

However, this may cause data inconsistency between `Storage` and `TinyDB` if the file that `Storage` referred to is been shared.

To disable it:

```Python
db = TinyDB("./path", no_dbcache=True)
```

# Example Codes:

## Simple One

```Python
import asyncio
from asynctinydb import TinyDB, Query

async def main():
    db = TinyDB('test.json')
    await db.insert({"answer": 42})
    print(await db.search(Query().answer == 42))  # >>> [{'answer': 42}] 

asyncio.run(main())
```
## Event Hooks Example

```Python
async def main():
    db = TinyDB('test.json')

    @db.storage.on.write.pre
    async def mul(ev: str, s: Storage, data: dict):
        data["_default"]["1"]['answer'] *= 2  # directly manipulate on data

    @db.storage.on.write.post
    async def _print(ev, s, anystr):
      	print(anystr)  # print json dumped string
 
    await db.insert({"answer": 21})  # insert() will trigger both write events
    await db.close()
    # Reload
    db = TinyDB('test.json')
    print(await db.search(Query().answer == 42))  # >>> [{'answer': 42}] 
```

## Customise ID Class

Inherit from `BaseID` and implement the following methods, and then you are good to go.

```Python
from asynctinydb import BaseID

class MyID(BaseID):
  def __init__(self, value: Any):
        """
        You should be able to convert str into MyID instance if you want to use JSONStorage.
        """

    def __str__(self) -> str:
        """
        Optional.
        It should be implemented if you want to use JSONStorage.
        """

    def __hash__(self) -> int:
        ...

    def __eq__(self, other: object) -> bool:
        ...

    @classmethod
    def next_id(cls, table: Table, keys) -> MyID:
        """
        It should return a unique ID.
        """

    @classmethod
    def mark_existed(cls, table: Table, new_id):
        """
        Marks an ID as existing; the same ID shouldn't be generated by next_id.
        """

    @classmethod
    def clear_cache(cls, table: Table):
        """
        Clear cache of existing IDs, if such cache exists.
        """
```

## Customise Document Class

```Python
from asynctinydb import BaseDocument

class MyDoc(BaseDocument):
  """
  I am too lazy to write those necessary methods.
  """
```

Anyways, a BaseDocument class looks like this:

```Python
class BaseDocument(Mapping[IDVar, Any]):
    @property
    @abstractmethod
    def doc_id(self) -> IDVar:
        raise NotImplementedError()

    @doc_id.setter
    def doc_id(self, value: IDVar):
        raise NotImplementedError()
```

Make sure you have implemented all the methods required by  `BaseDocument` class.

# Misc

* Lazy-load: File loading & dirs creating are delayed to the first IO operation.
* `CachingMiddleWare`: `WRITE_CACHE_SIZE` is now instance-specific.  
  Example: `TinyDB("test.db", storage=CachingMiddleWare(JSONStorage, 1024))`
* `search` accepts optional `cond`, returns all docs if no arguments are provided
* `get` and `contains` raises `ValueError` instead of `RuntimeError` when `cond` and `doc_id` are both `None`
* `LRUCache` stores `tuple`s of ids instead of `list`s of docs
* `search` and `get` treat `doc_id` and `doc_ids` as extra conditions instead of ignoring conditions when they are provided. That is to say, when `cond` and `doc_id(s)` are passed, they return docs satisfies both conditions.



[^1]: Why not `orjson`? Because `ujson` is fast enough and has more features.
[^2]: e.g. `JSONStorage` needs to convert the keys to `str` by itself.
[^UUID-version]:Currently using UUID4
[^disable-db-level]: See [DB-level caching](#db-level-caching) to learn how to disable this feature if it causes dirty reads.
[^isolevel]: See [isolevel](#isolation-level)
