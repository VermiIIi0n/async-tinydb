import os

import pytest

from asynctinydb import TinyDB
from asynctinydb.middlewares import CachingMiddleware
from asynctinydb.storages import MemoryStorage, JSONStorage

doc = {'none': [None, None], 'int': 42, 'float': 3.1415899999999999,
       'list': ['LITE', 'RES_ACID', 'SUS_DEXT'],
       'dict': {'hp': 13, 'sp': 5},
       'bool': [True, False, True, False]}

@pytest.mark.asyncio
async def test_caching(storage):
    # Write contents
    await storage.write(doc)

    # Verify contents
    assert doc == await storage.read()

@pytest.mark.asyncio
async def test_caching_read():
    db = TinyDB(storage=CachingMiddleware(MemoryStorage))
    assert (await db.all()) == []

@pytest.mark.asyncio
async def test_caching_write_many(storage):
    storage.WRITE_CACHE_SIZE = 3

    # Storage should be still empty
    assert storage.memory is None

    # Write contents
    for x in range(2):
        await storage.write(doc)
        assert storage.memory is None  # Still cached

    await storage.write(doc)

    # Verify contents: Cache should be emptied and written to storage
    assert storage.memory

@pytest.mark.asyncio
async def test_caching_flush(storage):
    # Write contents
    for _ in range(CachingMiddleware.WRITE_CACHE_SIZE - 1):
        await storage.write(doc)

    # Not yet flushed...
    assert storage.memory is None

    await storage.write(doc)

    # Verify contents: Cache should be emptied and written to storage
    assert storage.memory

@pytest.mark.asyncio
async def test_caching_flush_manually(storage):
    # Write contents
    await storage.write(doc)

    await storage.flush()

    # Verify contents: Cache should be emptied and written to storage
    assert storage.memory

@pytest.mark.asyncio
async def test_caching_write(storage):
    # Write contents
    await storage.write(doc)

    await storage.close()

    # Verify contents: Cache should be emptied and written to storage
    assert storage.storage.memory

@pytest.mark.asyncio
async def test_nested():
    storage = CachingMiddleware(MemoryStorage)
    storage()  # Initialization

    # Write contents
    await storage.write(doc)

    # Verify contents
    assert doc == await storage.read()

@pytest.mark.asyncio
async def test_caching_json_write(tmpdir):
    path = str(tmpdir.join('test.db'))

    async with TinyDB(path, storage=CachingMiddleware(JSONStorage)) as db:
        await db.insert({'key': 'value'})

    # Verify database filesize
    statinfo = os.stat(path)
    assert statinfo.st_size != 0

    # Assert JSON file has been closed
    assert db._storage._handle.closed

    del db

    # Reopen database
    async with TinyDB(path, storage=CachingMiddleware(JSONStorage)) as db:
        assert (await db.all()) == [{'key': 'value'}]
