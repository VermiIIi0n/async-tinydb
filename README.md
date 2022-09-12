![logo](https://raw.githubusercontent.com/msiemens/tinydb/master/artwork/logo.png)

## What's This?

"An asynchronous IO version of `TinyDB` based on `aiofiles`."

Almost every method is asynchronous. And it's based on `TinyDB 4.7.0+`.  
I will try to keep up with the latest version of `TinyDB`.

Since I modified it in just a few hours, I'm not sure if it's stable enough for production.  
But hey! It passed all the tests anyways.

## A few extra minor differences from the original `TinyDB`:

* **lazy-load:** When access-mode is set to `'r'`, `FileNotExistsError` is not raised until the first read operation.
* **ujson:** Using `ujson` instead of `json`. Some arguments aren't compatible with `json`

## How to use IT?

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
