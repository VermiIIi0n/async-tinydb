# Introduction of `Modifier` class

`Modifier` class:

* It can modify the behaviour of `Storage` and `TinyDB` classes.

* It contains methods to add encryption, compression, and other features to the database.

* It relies on `event hooks`.

## How To Use

Let's add encryption to the database:

```python
import asyncio
from asynctinydb import TinyDB, Modifier

async def main():
    async with TinyDB("db.json", access_mode="rb+") as db:  # Binary mode is required
        Modifier.Encryption.AES_GCM(db, "your key goes here")
        await db.insert({"answer": 42})

asyncio.run(main())

```
That's it! 
After calling `Modifier.Encryption.AES_GCM`, the database will be encrypted.  
**Applying modifiers at the beginning of the database instantiation is strongly recommended.**

## Order

**The order matters when applying modifiers in some cases.**

When the `BaseActionChain` of an event is `ActionCentipede`, the order becomes vital since the output of one modifier will be the input of the next modifier. ( See [event_hooks.py](../asynctinydb/event_hooks.py) and [storages.py](../asynctinydb/storages.py))

Look at this example:

```Python
from asynctinydb import TinyDB, Modifier

db = TinyDB("db.json", access_mode="rb+")
Modifier.Conversion.ExtendedJSON(db)
Modifier.Compression.brotli(db)
Modifier.Encryption.AES_GCM(db, "your key goes here")
```

| Layer |         Modifier          |
| :---: | :-----------------------: |
|   0   | `Conversion.ExtendedJSON` |
|   1   |   `Compression.brotli`    |
|   2   |   `Encryption.AES_GCM`    |

Layer 1 and 2 are interchangeable, since they both take `str` or `bytes` as input and produce `bytes`.  
**However, you should always apply compression before encryption, since encryption will likely turn your data into high-entropy state.**

What if you switch the order of layer 0 and 1? Layer 0 takes a `dict` and produces another `dict`, so you may expect an error? 

Not in this case! 

Since `Conversion.ExtendedJSON` hooks into `write.pre` and `read.post` instead of `write.post` and `read.pre`, it doesn't interact with the other two layers.

# Subclasses

Similar methods are grouped into subclasses.

## Encryption

**Order-Aware**

This subclass contains methods to add encryption to the storage.
### `AES_GCM`

* `events`: `write.post`, `read.pre`
* `input`: `str`|`bytes`
* `output`: `bytes`

This method adds AES-GCM encryption to the storage.

The final data produced has such a structure:

| Bytes Length: |       1       |       4-16       |  16   |   [Unknown]    |
| ------------- | :-----------: | :--------------: | :---: | :------------: |
| Content:      | Digest Length | Digest (MAC Tag) | Nonce | Encrypted Data |

```python
from asynctinydb import TinyDB, Modifier
db = TinyDB("db.json", access_mode="rb+")  # Binary mode is required
Modifier.Encryption.AES_GCM(db, "your key goes here")
```

## Compression

**Order-Aware**

This subclass contains methods to add compression to the storage.
### `brotli`

* `events`: `write.post`, `read.pre`
* `input`: `str`|`bytes`
* `output`: `bytes`

This method adds brotli compression to the storage.

```python
from asynctinydb import TinyDB, Modifier
db = TinyDB("db.json", access_mode="rb+")  # Binary mode is required
Modifier.Compression.brotli(db)
```

###  `blosc2`

* `events`: `write.post`, `read.pre`
* `input`: `str`|`bytes`
* `output`: `bytes`

This method adds blosc2 compression to the storage.

```python
from asynctinydb import TinyDB, Modifier
db = TinyDB("db.json", access_mode="rb+")  # Binary mode is required
Modifier.Compression.blosc2(db)
```
## Conversion

This subclass contains methods to convert the data to a different format.

### `ExtendedJSON`

* `events`: `write.pre`, `read.post`
* `input`: `dict`
* `output`: `dict`

This method allows JSONStorage to store more data types.

#### Extended Types

* `uuid.UUID`
* `datetime.datetime`: Converted to `ISO 8601` format.
* `datetime.timestamp`
* `bytes`: It is stored as a base64 string.
* `complex`
* `set`
* `frozenset`
* `tuple`
* `re.Pattern`

```python
from asynctinydb import TinyDB, Modifier
db = TinyDB("db.json")
Modifier.Converter.ExtendedJSON(db)
```

#### Customise Extended Types

By passing `type_hooks` and `marker_hooks` arguments to the modifier, you can modifiy the behaviour of the conversion.

##### To modify `type_hooks`

```Python
type_hooks = {
    int: lambda x, c: {"$int": str(x)},
    set: None
}
```

The first argument `x` is the data to be converted.  
The second argument `c` is the converter function, useful when you are dealing with `Container` types.

In this example, we convert `int` to a `dict` with a `$int` key and a `str` as the value(i.e. `42` -> `{"$int": "42"}`), and we remove `set` from the conversion.  
Return value of the hook does not necessarily have to be a `dict`. It can be anything that is JSON serializable.

##### To modify `marker_hooks`

A marker is a special key that is used to identify the type of the data.  
We use a MongoDB style marker by default (a `str` starts with `'$'`), but you can change it to anything you want.

```Python
marker_hooks = {
    "$int": lambda x, r: int(x["$int"]),
}
```

The first argument `x` is the data to be converted.  
The second argument `r` is the reverse converter function, useful when you are dealing with `Container` types.

In this example, we convert `dict` with the `$int` marker back to an `int` (i.e. `{"$int":"42"}` -> `42`).

##### A more complicated example

```Python
import asyncio
from asynctinydb import TinyDB, Modifier

class Myclass:
  def __init__(self, value: bytes):
    self.value = value

type_hooks = {
  Myclass: lambda x, c: {"$Myclass": c(x.value)}
  # Converts `bytes` with the converter
}

marker_hooks = {
  "$Myclass": lambda x, r: Myclass(r(x["$Myclass"]))
  # Converts back to `bytes` then pass it to Myclass
}

async def main():
  async with TinyDB("test.json") as db:
    Modifier.Conversion.ExtendedJSON(db, 
                                     type_hooks=type_hooks, 
                                     marker_hooks=marker_hooks
                                    )
    db.insert({"test": Myclass(b"some bytes")})

asyncio.run(main())
```

