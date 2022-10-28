# Event Hooks

Event Hooks give you more flexibility than middleware.

For example, you can achieve compress/decompress data without creating a new Storage class.

It is the low-level API for `Modifier` and `Index`

## Storage Events

### `write.pre`
Called before json dumping
* `ChainType`: `ActionCentipede`
* `ActionType`: `async`
#### args
* `str`(event name)
* `Storage`(storage)
* `dict`(data)

#### return
* `None` or `dict`(data)

Return any non-None value will overwrite data to be saved.
### `write.post`
Called after json dumping
* `ChainType`: `ActionCentipede`
* `ActionType`: `async`

#### args
* `str`(event name)
* `Storage`(storage)
* `str|bytes`(json str or bytes)

#### return
* `None` or `str|bytes`(json str or bytes)

Return any non-None value will overwrite data to be saved.

### `read.pre`
Called before json loading
**Executed in reversed order**
* `ChainType`: `ActionCentipede`
* `ActionType`: `async`

#### args
* `str`(event name)
* `Storage`(storage)
* `str|bytes`(json str or bytes)

#### return
* `None` or `str|bytes`(json str or bytes)

Return any non-None value will overwrite data to be read.

### `read.post`
Called after json loading
**Executed in reversed order**
* `ChainType`: `ActionCentipede`
* `ActionType`: `async`

#### args
* `str`(event name)
* `Storage`(storage)
* `dict`(data)

#### return
* `None` or `dict`(data)

### `close`
Called when storage is closed
* `ChainType`: `ActionChain`
* `ActionType`: `async`

#### args
* `str`(event name)
* `Storage`(storage)

#### return
* `None`

Return any non-None value will overwrite data to be read.
## Table Events
### `create`
Called when a document is created
* `ChainType`: `ActionChain`
* `ActionType`: `sync`

#### args
* `str`(event name)
* `Table`(table)
* `BaseDocument`(document)

#### return
* `None`

### `read`
Called when a document is read
* `ChainType`: `ActionChain`
* `ActionType`: `sync`

#### args
* `str`(event name)
* `Table`(table)
* `BaseDocument`(document)

#### return
* `None`

### `update`
Called when a document is updated
* `ChainType`: `ActionChain`
* `ActionType`: `sync`

#### args
* `str`(event name)
* `Table`(table)
* `BaseDocument`(document)

#### return
* `None`

### `delete`
Called when a document is deleted
* `ChainType`: `ActionChain`
* `ActionType`: `sync`

#### args
* `str`(event name)
* `Table`(table)
* `BaseDocument`(document)

#### return
* `None`

### `truncate`
Called when a table is truncated
* `ChainType`: `ActionChain`
* `ActionType`: `sync`

#### args
* `str`(event name)
* `Table`(table)

#### return
* `None`

## Event Hooks Example

```Python
s = Storage()
# By accessing the attribute `on`, you can register a new func to the event
@s.on.write.pre
async def f(ev, s, data):  # Will be executed on event `write.pre`
  ...
```

```Python
async def main():
    db = TinyDB('test.json')

    @db.storage.on.write.pre
    async def mul(ev: str, s: Storage, data: dict):
        data["_default"]["1"]['answer'] *= 2  # Manipulate data, not a good idea, just for demonstration

    @db.storage.on.write.post
    async def _print(ev, s, anystr):
      	print(anystr)  # print json dumped string
        # No return value or return None will not affect tdata
 
    await db.insert({"answer": 21})  # insert() will trigger both write events
    await db.close()
    # Reload
    db = TinyDB('test.json')
    print(await db.search(Query().answer == 42))  # >>> [{'answer': 42}] 
```

[^1]: Return value won't affect original data unless the database updates its DB level cache.





