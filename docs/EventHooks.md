# Event Hooks

Event Hooks give you more flexibility than middleware.

For example, you can achieve compress/decompress data without creating a new Storage class.

`Modifier` heavily uses event hooks.

Currently only supports json storage events: `write.pre`, `write.post`, `read.pre`, `read.post`, `close`.

* `write.pre` is called before json dumping, args: `str`(event name), `Storage`, `dict`(data).  
  Return non `None` value will overwrite data to be saved[^1].
* `write.post` is called after json dumping, args: `str`(event name), `Storage`, `str|bytes`(json str or bytes).  
  Return non `None` value will overwrite data to be saved[^1].
* `read.pre` is called before json loading, args: `str`(event name), `Storage`, `str|bytes`(json str or bytes).  
  Return non `None` value will overwrite data to be read. **Actions executed in reversed order**
* `read.post` is called after json loading, args: `str`(event name), `Storage`, `dict`(data).  
  Return non `None` value will overwrite data to be read. **Actions executed in reversed order**
* `close` is called when the storage is closed, args: `str`(event name), `Storage`.

```Python
s = Storage()
# By accessing the attribute `on`, you can register a new func to the event
@s.on.write.pre
async def f(ev, s, data):  # Will be executed on event `write.pre`
  ...
```

### Event Hooks Example

```Python
async def main():
    db = TinyDB('test.json')

    @db.storage.on.write.pre
    async def mul(ev: str, s: Storage, data: dict):
        data["_default"]["1"]['answer'] *= 2  # Manipulate data, not a good idea, just for demonstration

    @db.storage.on.write.post
    async def _print(ev, s, anystr):
      	print(anystr)  # print json dumped string
        # No return value or return None will not affect data
 
    await db.insert({"answer": 21})  # insert() will trigger both write events
    await db.close()
    # Reload
    db = TinyDB('test.json')
    print(await db.search(Query().answer == 42))  # >>> [{'answer': 42}] 
```

[^1]: Return value won't affect original data unless the database updates its DB level cache.





