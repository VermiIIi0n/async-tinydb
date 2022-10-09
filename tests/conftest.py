import os.path
import tempfile

import pytest  # type: ignore
import asyncio

import nest_asyncio
nest_asyncio.apply()
from asynctinydb.middlewares import CachingMiddleware
from asynctinydb.storages import MemoryStorage, EncryptedJSONStorage
from asynctinydb import TinyDB, JSONStorage


@pytest.fixture(params=['memory', 'json', 'json-encrypted'])
def db(request):
    with tempfile.TemporaryDirectory() as tmpdir:
        if request.param == 'json':
            db_ = TinyDB(os.path.join(tmpdir, 'test.db'), storage=JSONStorage)
        elif request.param == 'memory':
            db_ = TinyDB(storage=MemoryStorage)
        elif request.param == 'json-encrypted':
            db_ = TinyDB(os.path.join(tmpdir, 'test.db'), storage=EncryptedJSONStorage, key="asdfghjklzxcvbnm")
        loop = asyncio.get_event_loop()
        loop.run_until_complete(db_.drop_tables())
        loop.run_until_complete(db_.insert_multiple({'int': 1, 'char': c} for c in 'abc'))
        
        yield db_


@pytest.fixture
def storage():
    return CachingMiddleware(MemoryStorage)()
