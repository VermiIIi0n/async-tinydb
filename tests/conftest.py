from asynctinydb import TinyDB, JSONStorage, Modifier
from asynctinydb.storages import MemoryStorage, EncryptedJSONStorage
from asynctinydb.middlewares import CachingMiddleware
from itertools import product
from functools import partial
import os.path
import tempfile

import pytest  # type: ignore

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
    "memory", "json", "json-encrypted",
    "json-encrypted-modifier", "json-isolevel0", "json-isolevel1", "json-isolevel2",
    "json-nocache", "json_extend"] + mods)
async def db(request):
    with tempfile.TemporaryDirectory() as tmpdir:
        if request.param == "json":
            db_ = TinyDB(os.path.join(tmpdir, "test.db"), storage=JSONStorage)
        elif request.param == "memory":
            db_ = TinyDB(storage=MemoryStorage)
        elif request.param == "json-encrypted":
            db_ = TinyDB(os.path.join(tmpdir, "test.db"),
                         storage=EncryptedJSONStorage, key=key)
        elif request.param == "json-encrypted-modifier":
            db_ = TinyDB(os.path.join(tmpdir, "test.db"), access_mode="rb+")
            Modifier.Encryption.AES_GCM(db_, key=key)
        elif request.param == "json-isolevel0":
            db_ = TinyDB(os.path.join(tmpdir, "test.db"), isolevel=0)
        elif request.param == "json-isolevel1":
            db_ = TinyDB(os.path.join(tmpdir, "test.db"), storage=JSONStorage)
            db_.isolevel = 1
        elif request.param == "json-isolevel2":
            db_ = TinyDB(os.path.join(tmpdir, "test.db"), storage=JSONStorage)
            db_.isolevel = 2
        elif request.param == "json-nocache":
            db_ = TinyDB(os.path.join(tmpdir, "test.db"), no_dbcache=True)
        elif request.param == "json_extend":
            db_ = TinyDB(os.path.join(tmpdir, "test.db"), storage=JSONStorage)
            Modifier.Conversion.ExtendedJSON(db_)
        elif isinstance(request.param, tuple):
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
