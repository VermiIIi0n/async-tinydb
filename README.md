![logo](https://raw.githubusercontent.com/msiemens/tinydb/master/artwork/logo.png)

## What's This?

"An asynchronous IO version of `TinyDB` based on `aiofiles`."

Almost every method is asynchronous. And it's based on `TinyDB 4.7.0+`.  
I will try to keep up with the latest version of `TinyDB`.

Since I modified it in just a few hours, I'm not sure if it's stable enough for production.  
But hey! It passed all the tests anyways.

## Major Changes
* **asynchronous** Say goodbye to blocking IO.
* **drop support** Only supports Python 3.8+.
* **event hooks** You can now use event hooks to do something before or after an operation. see [Event Hooks](#event-hooks) for more details.
* **redesigned id & doc class** Now the ID class and Document class are more abstract. You can use your own class to replace the default ones in a more pleasing way.
  As long as they are inherited from `asynctinydb.table.BaseID/BaseDocument`. The default ID class is `IncreID`, which mimics the behaviours of the original `int` ID but requires much fewer IO operations.
* **db level caching** This significantly improves the performance of all operations. But requires more memory, and the responsibility of converting the data to the correct type is moved to the Storage. e.g. `JSONStorage` needs to convert the keys to `str` by itself.

## Minor differences from the original `TinyDB`:

* **lazy-load:** When `access_mode` is set to `'r'`, `FileNotExistsError` is not raised until the first read operation.

* **ujson:** Using `ujson` instead of `json`. Some arguments aren't compatible with `json`
  Why not `orjson`? Because `ujson` is fast enough and has more features.
  
* **Storage `closed` property** Original `TinyDB` won't raise exceptions when operating on a closed file. Now the property `closed` of `Storage` classes is required to be implemented. An `IOError` will be raised.
  
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


Basically, all you need to do is insert an `await` before every method that needs IO.

Notice that some parts of the code are blocking, for example when calling `len()` on `TinyDB` or `Table` Objects.

#### Event Hooks
Event Hooks give you more flexibility than middleware.
For example, you can achieve compress/decompress data without creating a new Storage class.

Currently only supports storage events: `write.pre`, `write.post`, `read.pre`, `read.post`, `close`.

* `write.pre` is called before json dumping, args: `str`(event name), `Storage`, `dict`(data).
* `write.post` is called after json dumping, args: `str`(event name), `Storage`, `str|bytes`(json str or bytes).
  Only one function can be registered for this event. Return non `None` value will be written to the file.
* `read.pre` is called before json loading, args: `str`(event name), `Storage`, `str|bytes`(json str or bytes).
  Only one function can be registered for this event. Return non `None` value will be used as the data.
* `read.post` is called after json loading, args: `str`(event name), `Storage`, `dict`(data).
* `close` is called when the storage is closed, args: `str`(event name), `Storage`.

For `write.pre` and `read.post`, you can directly modify data to edit its content.

However, `write.post` and `read.pre` requires you to return the value to update content because `str` is immutable in Python. If no return value or returns a `None`, you won't change anything.

```Python
s = Storage()
# By accessing the attribute `on`, you can register a new func to the event
@s.on.write.pre
async def f(ev, s, data):  # Will be executed on event `write.pre`
  ...
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
    await db.insert({"answer": 21})
    await db.close()
    # Reload
    db = TinyDB('test.json')
    print(await db.search(Query().answer == 42))  # >>> [{'answer': 42}] 
```
