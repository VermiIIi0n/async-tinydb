![logo](https://raw.githubusercontent.com/msiemens/tinydb/master/artwork/logo.png)

## What's This?

An asynchronous IO version of `TinyDB` based on `aiofiles`.

Almost every methods are asynchronous. And it's based on `TinyDB 4.7.0+`.

Since I modified it in just few hours, I'm not sure if it's stable enough for production.
So I haven't upload it to PyPI yet.

A few extra minor differences from the original `TinyDB`:

* **lazy-load:** When access-mode is set to `'r'`, `FileNotExistsError` is not raised until the first read operation.
* **ujson:** Using `ujson` instead of `json`. Some arguments aren't compatible with `json`

## How to use?

Basically all you need to do is inserting an `await` before every method that needs IO.

Notice that some parts of the code is blocking, for example when calling `len()` on `TinyDB` or `Table` Objects.

## Example Codes:

```Python
import asyncio
from asynctinydb import TinyDB, Query

async def main():
    db = TinyDB('test.json')
    await db.insert({"answer": 42})
    print(await db.search(Query().answer == 42))  # >>> [{'answer': 42}] 

asyncio.run(main())
```
