![logo](https://raw.githubusercontent.com/msiemens/tinydb/master/artwork/logo.png)

## What's This?

"An asynchronous IO version of `TinyDB` based on `aiofiles`."

Almost every method is asynchronous. And it's based on `TinyDB 4.7.0+`.  
I will try to keep up with the latest version of `TinyDB`.

## Major Changes
* **Asynchronous**: Say goodbye to blocking IO.
  
* **Drop support**: Only supports Python 3.8+.
  
* **Event hooks**: You can now use event hooks to do something before or after an operation. See [Event Hooks](#event-hooks) for more details.
  
* **Redesigned ID & Doc class**: You can customise them more pleasingly.
  The default ID class is `IncreID`, which mimics the behaviours of the original `int` ID but requires much fewer IO operations.

  The default Doc class remains almost the same.
  
* **DB level caching**: This significantly improves the performance of all operations. But it requires more memory, and the responsibility of converting the data to the correct type is moved to the Storage. e.g. `JSONStorage` needs to convert the keys to `str` by itself.

* **Built-in AES encryption**: You can now encrypt your database with AES. See [Encryption](#encryption) for more details.

## Minor Changes:

* **Lazy-load:** When `access_mode` is set to `'r'`, `FileNotExistsError` is not raised until the first read operation.

* **`ujson`:** Using `ujson` instead of `json`. Some arguments aren't compatible with `json`
  Why not `orjson`? Because `ujson` is fast enough and has more features.
  
* **Storage `closed` property**: Original `TinyDB` won't raise exceptions when operating on a closed file. Now the property `closed` of `Storage` classes is required to be implemented. An `IOError should be raised.
  
  I strongly suggest doing the same for `middleware`.

## How to use it?

#### Installation

```Bash
pip install async-tinydb
```

#### Importing
```Python
from asynctinydb import TinyDB, where
```


All you need to do is insert an `await` before every method that needs IO.

Notice that some parts of the code are blocking, for example, when calling `len()` on `TinyDB` or `Table` Objects.

#### Event Hooks
Event Hooks give you more flexibility than middleware.
For example, you can achieve compress/decompress data without creating a new Storage class.

Currently only supports json storage events: `write.pre`, `write.post`, `read.pre`, `read.post`, `close`.

* `write.pre` is called before json dumping, args: `str`(event name), `Storage`, `dict`(data).

* `write.post` is called after json dumping, args: `str`(event name), `Storage`, `str|bytes`(json str or bytes).
  Only one function can be registered for this event. Return non `None` value will be written to the file.

* `read.pre` is called before json loading, args: `str`(event name), `Storage`, `str|bytes`(json str or bytes).
  Only one function can be registered for this event. Return non `None` value will be used as the data.

* `read.post` is called after json loading, args: `str`(event name), `Storage`, `dict`(data).

* `close` is called when the storage is closed, args: `str`(event name), `Storage`.

For `write.pre` and `read.post`, you can directly modify data to edit its content.

However, `write.post` and `read.pre` requires you to return the value to update content because `str` is immutable in Python. If there is no return value or returns a `None`, you won't change anything.

```Python
s = Storage()
# By accessing the attribute `on`, you can register a new func to the event
@s.on.write.pre
async def f(ev, s, data):  # Will be executed on event `write.pre`
  ...
```

#### Encryption

Currently only supports AES-GCM encryption.

The final data produced has such a structure:

| Structure     |               |                  |       |                |
| ------------- | :-----------: | :--------------: | :---: | :------------: |
| Bytes Length: |       1       |       4-16       |  16   |   <Unknown>    |
| Content:      | Digest Length | Digest (MAC Tag) | Nonce | Encrypted Data |

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

`add_encryption` is a method of the `Modifier` class. It will add encryption to the storage that fulfils the following conditions:

1. The storage has "write.post" and "read.pre" events.
2. The storage stores data in `bytes`.
3. The argument passed to the events is `str` or `bytes`. See the implementation of `JSONStorage` for more details.

```Python
from asynctinydb import TinyDB, Modifier

async def main():
    db = TinyDB("db.json", access_mode="rb+")  # Binary mode is required
    Modifier.add_encryption(db.storage, "your key goes here")

```

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

Make sure you have implemented all the methods required by `Mapping` and `BaseDocument` classes.
