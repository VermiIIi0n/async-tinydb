from asynctinydb import TinyDB, JSONStorage, Modifier
from asynctinydb.storages import MemoryStorage, EncryptedJSONStorage
from asynctinydb.middlewares import CachingMiddleware
from itertools import product
from functools import partial
import os.path
import tempfile

import pytest

enc = Modifier.Encryption
comp = Modifier.Compression
conv = Modifier.Conversion

key = "asdfghjklzxcvbnm"
mods: list = list(product(
    (lambda x: x, comp.blosc2, comp.brotli),
    (partial(alg, key=key)  # type: ignore
     for alg in (lambda x, key: x, enc.AES_GCM,)),
    (lambda x: x, conv.ExtendedJSON,),
))


@pytest.fixture(params=[
    "memory", "json", "json-encrypted", "json-isolevel0",
    "json-isolevel1", "json-isolevel2", "json-nocache"] + mods)
async def db(request):
    with tempfile.TemporaryDirectory() as tmpdir:
        match request.param:
            case "json":
                db_ = TinyDB(os.path.join(tmpdir, "test.db"), storage=JSONStorage)
            case "memory":
                db_ = TinyDB(storage=MemoryStorage)
            case "json-encrypted":
                db_ = TinyDB(os.path.join(tmpdir, "test.db"),
                         storage=EncryptedJSONStorage, key=key)
            case "json-isolevel0":
                db_ = TinyDB(os.path.join(tmpdir, "test.db"), isolevel=0)
            case "json-isolevel1":
                db_ = TinyDB(os.path.join(tmpdir, "test.db"), storage=JSONStorage)
                db_.isolevel = 1
            case "json-isolevel2":
                db_ = TinyDB(os.path.join(tmpdir, "test.db"), storage=JSONStorage)
                db_.isolevel = 2
            case "json-nocache":
                db_ = TinyDB(os.path.join(tmpdir, "test.db"), no_dbcache=True)
            case _:
                if isinstance(request.param, tuple):
                    db_ = TinyDB(os.path.join(tmpdir, "test.db"),
                            access_mode="rb+", storage=JSONStorage)
                    for mod in request.param:
                        mod(db_)

        await db_.drop_tables()
        await db_.insert_multiple({"int": 1, "char": c} for c in "abc")

        async with db_:
            yield db_


@pytest.fixture
def storage():
    return CachingMiddleware(MemoryStorage)()
