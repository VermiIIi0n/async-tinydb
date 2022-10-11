<img src="./artwork/logo.png" alt="logo" style="zoom:50%;" />

## What's This?

An asynchronous version of `TinyDB` based on `aiofiles`.

Almost every method is asynchronous. And it's based on `TinyDB 4.7.0+`.  

I will try to keep up with the latest version of `TinyDB`.



## Incompatible Changes

Major Changes:

* **Asynchronous**: Say goodbye to blocking IO. **Don't forget to `await` async methods**!
* **Drop support**: Only supports Python 3.8+.

Minor Changes:

* **Lazy-load:** When `access_mode` is set to `'r'`, `FileNotExistsError` is not raised until the first read operation.

* **`ujson`:** Using `ujson` instead of `json`. Some arguments aren't compatible with `json`
  Why not `orjson`? Because `ujson` is fast enough and has more features.

* **Storage `closed` property**: Original `TinyDB` won't raise exceptions when operating on a closed file. Now the property `closed` of `Storage` classes is required to be implemented. An `IOError` should be raised.

* **`CachingMiddleWare`**: `WRITE_CACHE_SIZE` is now instance-specific.  
  Example: `TinyDB("test.db", storage=CachingMiddleWare(JSONStorage, 1024))`

## New Features

* **Event hooks**: You can now use event hooks to do something before or after an operation. See [Event Hooks](#event-hooks) for more details.

* **Redesigned ID & Doc class**: You can [customise them](#customise-id-class) more pleasingly.  
  The default ID class is `IncreID`, which mimics the behaviours of the original `int` ID but requires much fewer IO operations.  
  The default Doc class remains almost the same.

* **DB level caching**: This significantly improves the performance of all operations. But it requires more memory, and the responsibility of converting the data to the correct type is transmitted to the Storage. e.g. `JSONStorage` needs to convert the keys to `str` by itself.

* **Built-in `Modifier`**: Use `Modifier` to easily [encrypt](#encryption) and [compress](#compression) your database. Sure you can do much more than these. _(See [Modifier](./docs/Modifier.md))_

## How to use it?

#### Installation

```Bash
pip install async-tinydb
```

#### Importing

```Python
from asynctinydb import TinyDB, where
```

#### Using

See the [original `TinyDB` documents](https://tinydb.readthedocs.org). Insert an `await` in front of async methods. 

Notice that some codes are still blocking, for example, when calling `len()` on `TinyDB` or `Table` Objects.

That's it.

******

#### Documents For Advances Usage

* [Modifier](./docs/Modifier.md)
* [Event Hooks](./docs/EventHooks.md)

#### Replacing ID & Document Class

**Mixing classes in one table may cause errors!**

```Python
from asynctinydb import TinyDB, UUID, IncreID, Document

db = TinyDB("database.db")

# Replacing ID class to UUID
# By default, ID class is IncreID, document_class is Document
tab = db.table("table1", document_id_class=UUID, document_class=Document)
```

_See [Customisation](#customise-id-class) for more details_

#### Encryption

Currently only supports AES-GCM encryption.

There are two ways to use encryption:

##### 1. Use `EncryptedJSONStorage` directly

```Python
from asynctinydb import EncryptedJSONStorage, TinyDB

async def main():
    db = TinyDB("db.json", key="your key goes here", storage=EncryptedJSONStorage)

```

##### 2. Use  `Modifier` class

The modifier class contains some methods to modify the behaviour of `TinyDB` and `Storage` classes.

It relies on `event hooks`.

`Encryption` is a subclass of the `Modifier` class. It contains methods to add encryption to the storage that fulfils the following conditions:

1. The storage has `write.post` and `read.pre` events.
2. The storage stores data in `bytes`.
3. The argument passed to the methods is `str` or `bytes`. See the implementation of `JSONStorage` for more details.

```Python
from asynctinydb import TinyDB, Modifier

async def main():
    db = TinyDB("db.json", access_mode="rb+")  # Binary mode is required
    Modifier.Encryption.AES_GCM(db, "your key goes here")
    # Or, you can pass a Storage instance
    # Modifier.Encryption.AES_GCM(db.storage, "your key goes here")

```

#### Isolation Level

To avoid blocking codes, Async-TinyDB puts CPU-bound tasks to another thread/process (On Linux, if forking a process is possible, `ProcessPoolExecutor` will be used instead of the `ThreadPoolExecutor`).

Unfortunately, this introduces chances of data being modified when:

* Manipulating mutable objects within `Document` instances in another coroutine
* Performing updating/saving/searching operations (These operations are run in a different thread/process)
* The conditions above are satisfied in the same `Table`
* The conditions above are satisfied simultaneously

You can either avoid these operations or set a higher isolation level to mitigate this problem.

```Python
db.isolevel = 1  # By default isolevel is 0
```

`isolevel`:

0. No isolation
1. Don't run operations in another thread/process, or run in a blocking way.
2. Disable

## Example Codes:

### Simple One

```Python
import asyncio
from asynctinydb import TinyDB, Query

async def main():
    db = TinyDB('test.json')
    await db.insert({"answer": 42})
    print(await db.search(Query().answer == 42))  # >>> [{'answer': 42}] 

asyncio.run(main())
```
### Event Hooks Example

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

### Customise ID Class

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
    def next_id(cls, table: Table) -> IncreID:
        """
        Recommended to define it as an async function, but a sync def will do.
        It should return a unique ID.
        """

    @classmethod
    def mark_existed(cls, table: Table, new_id: IncreID):
        """
        Marks an ID as existing; the same ID shouldn't be generated by next_id again.
        """

    @classmethod
    def clear_cache(cls, table: Table):
        """
        Clear cache of existing IDs, if such cache exists.
        """
```

### Customise Document Class

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
