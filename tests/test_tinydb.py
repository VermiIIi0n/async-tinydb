from asynctinydb.table import Document, IncreID, UUID
from asynctinydb.storages import MemoryStorage, JSONStorage
from asynctinydb.middlewares import Middleware, CachingMiddleware
from asynctinydb.queries import QueryLike
from asynctinydb import TinyDB, where, Query
import asyncio
import re
from collections.abc import Mapping

import pytest
import nest_asyncio
nest_asyncio.apply()


async def test_drop_tables(db: TinyDB):
    await db.drop_tables()

    await db.insert({})
    await db.drop_tables()

    assert len(db) == 0


async def test_all(db: TinyDB):
    await db.drop_tables()

    for i in range(10):
        await db.insert({})

    assert len(await db.all()) == 10


async def test_insert(db: TinyDB):
    await db.drop_tables()
    await db.insert({'int': 1, 'char': 'a'})

    assert await db.count(where('int') == 1) == 1

    await db.drop_tables()

    await db.insert({'int': 1, 'char': 'a'})
    await db.insert({'int': 1, 'char': 'b'})
    await db.insert({'int': 1, 'char': 'c'})

    assert await db.count(where('int') == 1) == 3
    assert await db.count(where('char') == 'a') == 1


async def test_insert_ids(db: TinyDB):
    await db.drop_tables()
    assert await db.insert({'int': 1, 'char': 'a'}) == 1
    assert await db.insert({'int': 1, 'char': 'a'}) == 2


async def test_insert_with_doc_id(db: TinyDB):
    await db.drop_tables()
    assert await db.insert({'int': 1, 'char': 'a'}) == 1
    assert await db.insert(Document({'int': 1, 'char': 'a'}, 12)) == 12
    assert await db.insert(Document({'int': 1, 'char': 'a'}, 77)) == 77
    assert await db.insert({'int': 1, 'char': 'a'}) == 78


async def test_insert_with_duplicate_doc_id(db: TinyDB):
    await db.drop_tables()
    assert await db.insert({'int': 1, 'char': 'a'}) == 1

    with pytest.raises(ValueError):
        await db.insert(Document({'int': 1, 'char': 'a'}, 1))


async def test_insert_multiple(db: TinyDB):
    await db.drop_tables()
    assert not await db.contains(where('int') == 1)

    # Insert multiple from list
    await db.insert_multiple([{'int': 1, 'char': 'a'},
                              {'int': 1, 'char': 'b'},
                              {'int': 1, 'char': 'c'}])

    assert await db.count(where('int') == 1) == 3
    assert await db.count(where('char') == 'a') == 1

    # Insert multiple from generator function
    def generator():
        for j in range(10):
            yield {'int': j}

    await db.drop_tables()

    await db.insert_multiple(generator())

    for i in range(10):
        assert await db.count(where('int') == i) == 1
    assert await db.count(where('int').exists()) == 10

    # Insert multiple from inline generator
    await db.drop_tables()

    await db.insert_multiple({'int': i} for i in range(10))

    for i in range(10):
        assert await db.count(where('int') == i) == 1


async def test_insert_multiple_with_ids(db: TinyDB):
    await db.drop_tables()

    # Insert multiple from list
    assert await db.insert_multiple([{'int': 1, 'char': 'a'},
                                     {'int': 1, 'char': 'b'},
                                     {'int': 1, 'char': 'c'}]) == [1, 2, 3]


async def test_insert_multiple_with_doc_ids(db: TinyDB):
    await db.drop_tables()

    assert await db.insert_multiple([
        Document({'int': 1, 'char': 'a'}, 12),
        Document({'int': 1, 'char': 'b'}, 77)
    ]) == [12, 77]
    assert await db.get(doc_id=12) == {'int': 1, 'char': 'a'}
    assert await db.get(doc_id=77) == {'int': 1, 'char': 'b'}

    with pytest.raises(ValueError):
        await db.insert_multiple([Document({'int': 1, 'char': 'a'}, 12)])


async def test_insert_invalid_type_raises_error(db: TinyDB):
    with pytest.raises(ValueError, match='Document is not a Mapping'):
        # object() as an example of a non-mapping-type
        await db.insert(object())  # type: ignore


async def test_insert_valid_mapping_type(db: TinyDB):
    class CustomDocument(Mapping):
        def __init__(self, data):
            self.data = data

        def __getitem__(self, key):
            return self.data[key]

        def __iter__(self):
            return iter(self.data)

        def __len__(self):
            return len(self.data)

    await db.drop_tables()
    await db.insert(CustomDocument({'int': 1, 'char': 'a'}))
    assert await db.count(where('int') == 1) == 1


async def test_custom_mapping_type_with_json(tmpdir):
    class CustomDocument(Mapping):
        def __init__(self, data):
            self.data = data

        def __getitem__(self, key):
            return self.data[key]

        def __iter__(self):
            return iter(self.data)

        def __len__(self):
            return len(self.data)

    # Insert
    db = TinyDB(str(tmpdir.join('test.db')))
    await db.drop_tables()
    await db.insert(CustomDocument({'int': 1, 'char': 'a'}))
    assert await db.count(where('int') == 1) == 1

    # Insert multiple
    await db.insert_multiple([
        CustomDocument({'int': 2, 'char': 'a'}),
        CustomDocument({'int': 3, 'char': 'a'})
    ])
    assert await db.count(where('int') == 1) == 1
    assert await db.count(where('int') == 2) == 1
    assert await db.count(where('int') == 3) == 1

    # Write back
    doc_id = (await db.get(where('int') == 3)).doc_id
    await db.update(CustomDocument({'int': 4, 'char': 'a'}), doc_ids=[doc_id])
    assert await db.count(where('int') == 3) == 0
    assert await db.count(where('int') == 4) == 1

    await db.close()


async def test_remove(db: TinyDB):
    await db.remove(where('char') == 'b')

    assert len(db) == 2
    assert await db.count(where('int') == 1) == 2


async def test_remove_all_fails(db: TinyDB):
    with pytest.raises(RuntimeError):
        await db.remove()


async def test_remove_multiple(db: TinyDB):
    await db.remove(where('int') == 1)

    assert len(db) == 0


async def test_remove_ids(db: TinyDB):
    await db.remove(doc_ids=[1, 2])

    assert len(db) == 1


async def test_remove_returns_ids(db: TinyDB):
    assert await db.remove(where('char') == 'b') == [2]


async def test_update(db: TinyDB):
    assert len(db) == 3

    await db.update({'int': 2}, where('char') == 'a')

    assert await db.count(where('int') == 2) == 1
    assert await db.count(where('int') == 1) == 2


async def test_update_all(db: TinyDB):
    assert await db.count(where('int') == 1) == 3

    await db.update({'newField': True})

    assert await db.count(where('newField') == True) == 3  # noqa


async def test_update_returns_ids(db: TinyDB):
    await db.drop_tables()
    assert await db.insert({'int': 1, 'char': 'a'}) == 1
    assert await db.insert({'int': 1, 'char': 'a'}) == 2

    assert await db.update({'char': 'b'}, where('int') == 1) == [1, 2]


async def test_update_transform(db: TinyDB):
    def increment(field):
        def transform(el):
            el[field] += 1

        return transform

    def delete(field):
        def transform(el):
            del el[field]

        return transform

    assert await db.count(where('int') == 1) == 3

    await db.update(increment('int'), where('char') == 'a')
    await db.update(delete('char'), where('char') == 'a')

    assert await db.count(where('int') == 2) == 1
    assert await db.count(where('char') == 'a') == 0
    assert await db.count(where('int') == 1) == 2


async def test_update_ids(db: TinyDB):
    await db.update({'int': 2}, doc_ids=[1, 2])

    assert await db.count(where('int') == 2) == 2


async def test_update_multiple(db: TinyDB):
    assert len(db) == 3

    await db.update_multiple([
        ({'int': 2}, where('char') == 'a'),
        ({'int': 4}, where('char') == 'b'),
    ])

    assert await db.count(where('int') == 1) == 1
    assert await db.count(where('int') == 2) == 1
    assert await db.count(where('int') == 4) == 1


async def test_update_multiple_operation(db: TinyDB):
    def increment(field):
        def transform(el):
            el[field] += 1

        return transform

    assert await db.count(where('int') == 1) == 3

    await db.update_multiple([
        (increment('int'), where('char') == 'a'),
        (increment('int'), where('char') == 'b')
    ])

    assert await db.count(where('int') == 2) == 2


async def test_upsert(db: TinyDB):
    assert len(db) == 3

    # Document existing
    await db.upsert({'int': 5}, where('char') == 'a')
    assert await db.count(where('int') == 5) == 1

    # Document missing
    assert await db.upsert({'int': 9, 'char': 'x'}, where('char') == 'x') == [4]
    assert await db.count(where('int') == 9) == 1


async def test_upsert_by_id(db: TinyDB):
    assert len(db) == 3

    # Single document existing
    extant_doc = Document({'char': 'v'}, doc_id=1)
    assert await db.upsert(extant_doc) == [1]
    doc = await db.get(where('char') == 'v')
    assert doc is not None
    assert doc.doc_id == 1
    assert len(db) == 3

    # Single document missing
    missing_doc = Document({'int': 5, 'char': 'w'}, doc_id=5)
    assert await db.upsert(missing_doc) == [5]
    doc = await db.get(where('char') == 'w')
    assert doc is not None
    assert doc.doc_id == 5
    assert len(db) == 4

    # Missing doc_id and condition
    with pytest.raises(ValueError, match=r"(?=.*\bdoc_id\b)(?=.*\bquery\b)"):
        await db.upsert({'no_Document': 'no_query'})

    # Make sure we didn't break anything
    assert await db.insert({'check': '_next_id'}) == 6


async def test_search(db: TinyDB):
    assert not db._query_cache
    assert len(await db.search(where('int') == 1)) == 3

    assert len(db._query_cache) == 1
    assert len(await db.search(where('int') == 1)) == 3  # Query result from cache

    class BlindQuery(QueryLike):
        def __call__(self, doc):
            return True

        def __hash__(self):
            return 114514
    assert len(await db.search(BlindQuery())) == 3


async def test_search_path(db: TinyDB):
    assert not db._query_cache
    assert len(await db.search(where('int').exists())) == 3
    assert len(db._query_cache) == 1

    assert len(await db.search(where('asd').exists())) == 0
    assert len(await db.search(where('int').exists())) == 3  # Query result from cache


async def test_search_no_results_cache(db: TinyDB):
    assert len(await db.search(where('missing').exists())) == 0
    assert len(await db.search(where('missing').exists())) == 0


async def test_get(db: TinyDB):
    item = await db.get(where('char') == 'b')
    assert item is not None
    assert item['char'] == 'b'
    with pytest.raises(ValueError):
        await db.get(where('char') == 'x', doc_id=1)


async def test_get_ids(db: TinyDB):
    el = (await db.all())[0]
    assert await db.get(doc_id=el.doc_id) == el
    assert await db.get(doc_id=float('NaN')) is None  # type: ignore


async def test_get_invalid(db: TinyDB):
    with pytest.raises(RuntimeError):
        await db.get()


async def test_count(db: TinyDB):
    assert await db.count(where('int') == 1) == 3
    assert await db.count(where('char') == 'd') == 0


async def test_contains(db: TinyDB):
    assert await db.contains(where('int') == 1)
    assert not await db.contains(where('int') == 0)


async def test_contains_ids(db: TinyDB):
    assert await db.contains(doc_id=1)
    assert await db.contains(doc_id=2)
    assert not await db.contains(doc_id=88)


async def test_contains_invalid(db: TinyDB):
    with pytest.raises(RuntimeError):
        await db.contains()


async def test_get_idempotent(db: TinyDB):
    u = await db.get(where('int') == 1)
    z = await db.get(where('int') == 1)
    assert u == z


async def test_multiple_dbs():
    """
    Regression test for issue #3
    """
    db1 = TinyDB(storage=MemoryStorage)
    db2 = TinyDB(storage=MemoryStorage)

    await db1.insert({'int': 1, 'char': 'a'})
    await db1.insert({'int': 1, 'char': 'b'})
    await db1.insert({'int': 1, 'value': 5.0})

    await db2.insert({'color': 'blue', 'animal': 'turtle'})

    assert len(db1) == 3
    assert len(db2) == 1

    await db1.close()
    await db2.close()


async def test_storage_closed_once():
    class Storage:
        def __init__(self):
            self.closed = False

        async def read(self):
            return {}

        async def write(self, data):
            pass

        async def close(self):
            assert not self.closed
            self.closed = True

    async with TinyDB(storage=Storage) as db:
        await db.close()

    del db
    # If await db.close() is called during cleanup, the assertion will fail and throw
    # and exception


async def test_unique_ids(tmpdir):
    """
    :type tmpdir: py._path.local.LocalPath
    """
    path = str(tmpdir.join('db.json'))

    # Verify ids are unique when reopening the DB and inserting
    async with TinyDB(path) as db:
        await db.insert({'x': 1})

    async with TinyDB(path) as db:
        await db.insert({'x': 1})

    async with TinyDB(path) as db:
        data = await db.all()

        assert data[0].doc_id != data[1].doc_id

    # Verify ids stay unique when inserting/removing
    async with TinyDB(path) as db:
        await db.drop_tables()
        await db.insert_multiple({'x': i} for i in range(5))
        await db.remove(where('x') == 2)

        assert len(db) == 4

        ids = [e.doc_id for e in await db.all()]
        assert len(ids) == len(set(ids))


async def test_lastid_after_open(tmpdir):
    """
    Regression test for issue #34

    :type tmpdir: py._path.local.LocalPath
    """

    NUM = 100
    path = str(tmpdir.join('db.json'))

    async with TinyDB(path) as db:
        await db.insert_multiple({'i': i} for i in range(NUM))

    async with TinyDB(path) as db:
        assert db._get_next_id((await db._read_table()).keys()) - 1 == NUM


async def test_doc_ids_json(tmpdir):
    """
    Regression test for issue #45
    """

    path = str(tmpdir.join('db.json'))

    async with TinyDB(path) as db:
        await db.drop_tables()
        assert await db.insert({'int': 1, 'char': 'a'}) == 1
        assert await db.insert({'int': 1, 'char': 'a'}) == 2

        await db.drop_tables()
        assert await db.insert_multiple([{'int': 1, 'char': 'a'},
                                         {'int': 1, 'char': 'b'},
                                         {'int': 1, 'char': 'c'}]) == [1, 2, 3]

        assert await db.contains(doc_id=1)
        assert await db.contains(doc_id=2)
        assert not await db.contains(doc_id=88)

        await db.update({'int': 2}, doc_ids=[1, 2])
        assert await db.count(where('int') == 2) == 2

        el = (await db.all())[0]
        assert await db.get(doc_id=el.doc_id) == el
        assert await db.get(doc_id=float('NaN')) is None

        await db.remove(doc_ids=[1, 2])
        assert len(db) == 1


async def test_insert_string(tmpdir):
    path = str(tmpdir.join('db.json'))

    async with TinyDB(path) as db:
        data = [{'int': 1}, {'int': 2}]
        await db.insert_multiple(data)

        with pytest.raises(ValueError):
            await db.insert([1, 2, 3])  # Fails

        with pytest.raises(ValueError):
            await db.insert({'bark'})  # Fails

        assert data == await db.all()

        await db.insert({'int': 3})  # Does not fail


async def test_insert_invalid_dict(tmpdir):
    path = str(tmpdir.join('db.json'))

    async with TinyDB(path) as db:
        data = [{'int': 1}, {'int': 2}]
        await db.insert_multiple(data)

        with pytest.raises(TypeError):
            await db.insert({'int': pytest})  # Fails

        assert data == await db.all()

        await db.insert({'int': 3})  # Does not fail


async def test_gc(tmpdir):
    # See https://github.com/msiemens/asynctinydb/issues/92
    path = str(tmpdir.join('db.json'))
    db = TinyDB(path)
    table = db.table('foo')
    await table.insert({'something': 'else'})
    await table.insert({'int': 13})
    assert len(await table.search(where('int') == 13)) == 1
    assert await table.all() == [{'something': 'else'}, {'int': 13}]
    await db.close()


async def test_drop_table():
    db = TinyDB(storage=MemoryStorage)
    default_table_name = db.table(db.default_table_name).name

    assert [] == list(await db.tables())
    await db.drop_table(default_table_name)

    await db.insert({'a': 1})
    assert [default_table_name] == list(await db.tables())

    await db.drop_table(default_table_name)
    assert [] == list(await db.tables())

    table_name = 'some-other-table'
    db = TinyDB(storage=MemoryStorage)
    await db.table(table_name).insert({'a': 1})
    assert {table_name} == await db.tables()

    await db.drop_table(table_name)
    assert set() == await db.tables()
    assert table_name not in db._tables

    await db.drop_table('non-existent-table-name')
    assert set() == await db.tables()
    await db.close()


async def test_empty_write(tmpdir):
    path = str(tmpdir.join('db.json'))

    class ReadOnlyMiddleware(Middleware):
        async def write(self, data):
            raise AssertionError('No write for unchanged db')

    await TinyDB(path).close()
    await TinyDB(path, storage=ReadOnlyMiddleware(JSONStorage)).close()


async def test_query_cache():
    db = TinyDB(storage=MemoryStorage)
    await db.insert_multiple([
        {'name': 'foo', 'value': 42},
        {'name': 'bar', 'value': -1337}
    ])

    query = where('value') > 0

    results = await db.search(query)
    assert len(results) == 1

    # Modify the db instance to not return any results when
    # bypassing the query cache
    async def f():
        return {}
    db._tables[db.table(db.default_table_name).name]._read_table = f

    # Make sure we got an independent copy of the result list
    results.extend([1])
    assert await db.search(query) == [{'name': 'foo', 'value': 42}]
    await db.close()


async def test_asynctinydb_is_iterable(db: TinyDB):
    assert [r async for r in db] == await db.all()


async def test_repr(tmpdir):
    path = str(tmpdir.join('db.json'))

    db = TinyDB(path)
    await db.insert({'a': 1})

    assert re.match(
        r"<TinyDB "
        r"tables=\[u?\'_default\'\], "
        r"tables_count=1, "
        r"default_table_documents_count=1, "
        r"all_tables_documents_count=\[\'_default=1\'\]>",
        repr(db))
    await db.close()


async def test_delete(tmpdir):
    path = str(tmpdir.join('db.json'))

    db = TinyDB(path, ensure_ascii=False)
    q = Query()
    await db.insert({'network': {'id': '114', 'name': 'ok', 'rpc': 'dac',
                                 'ticker': 'mkay'}})
    assert await db.search(q.network.id == '114') == [
        {'network': {'id': '114', 'name': 'ok', 'rpc': 'dac',
                     'ticker': 'mkay'}}
    ]
    await db.remove(q.network.id == '114')
    assert await db.search(q.network.id == '114') == []
    await db.close()


async def test_insert_multiple_with_single_dict(db: TinyDB):
    with pytest.raises(ValueError):
        d = {'first': 'John', 'last': 'smith'}
        await db.insert_multiple(d)  # type: ignore
        await db.close()


async def test_access_storage():
    assert isinstance(TinyDB(storage=MemoryStorage).storage,
                      MemoryStorage)
    db = TinyDB(storage=CachingMiddleware(MemoryStorage))
    assert isinstance(db.storage,
                      CachingMiddleware)


async def test_empty_db_len():
    db = TinyDB(storage=MemoryStorage)
    assert len(db) == 0
    await db.close()


async def test_insert_on_existing_db(tmpdir):
    path = str(tmpdir.join('db.json'))

    db = TinyDB(path, ensure_ascii=False)
    await db.insert({'foo': 'bar'})

    assert len(db) == 1

    await db.close()

    db = TinyDB(path, ensure_ascii=False)
    await db.insert({'foo': 'bar'})
    await db.insert({'foo': 'bar'})

    assert len(db) == 3

    await db.close()


def test_syncwait_methods(tmpdir):
    db = TinyDB(str(tmpdir.join('db.json')))
    len(db)  # syncwait
    str(db)
    loop = asyncio.get_event_loop()

    async def test():
        await db.insert({'foo': 'bar'})
        assert len(db) == 1
        await db.close()
    loop.run_until_complete(test())


async def test_storage_access():
    db = TinyDB(storage=MemoryStorage)

    assert isinstance(db.storage, MemoryStorage)

    tab = db.table('foo')
    assert tab.storage is db.storage
    await db.close()


async def test_lambda_query():
    db = TinyDB(storage=MemoryStorage)
    await db.insert({'foo': 'bar'})

    def query(doc): return doc.get('foo') == 'bar'
    query.is_cacheable = lambda: False
    assert await db.search(query) == [{'foo': 'bar'}]
    assert not db._query_cache
    await db.close()


async def test_closed_db():
    db = TinyDB(storage=MemoryStorage)
    await db.insert({'foo': 'bar'})
    await db.close()
    await db.close()  # Should not raise

    with pytest.raises(IOError):
        db.table("foo")

    with pytest.raises(IOError):
        await db.tables()

    with pytest.raises(IOError):
        await db.drop_table("foo")

    with pytest.raises(IOError):
        await db.drop_tables()


async def test_id_classes():
    db = TinyDB(storage=MemoryStorage)
    tab0 = db.table("foo")
    await tab0.insert({'foo': 'bar'})
    tab1 = db.table("IncreID", document_id_class=IncreID)
    await tab1.insert({'foo': 'bar'})
    assert type((await tab1.get(Query().foo == 'bar')).doc_id) is IncreID
    tab2 = db.table("UUID", document_id_class=UUID)
    _id = await tab2.insert({'foo': 'bar'})
    await tab2.update({'foo': 'baz'}, doc_ids=[_id])
    assert type((await tab2.get(Query().foo == 'baz')).doc_id) is UUID

    # Altering classes of existing tables is not allowed
    with pytest.raises(ValueError):
        db.table("foo", document_id_class=UUID)
    await db.close()


async def test_isolevel():
    db = TinyDB(storage=MemoryStorage)
    assert db.isolevel == 1
    tabs = [db.table(n) for n in "abcd"]

    assert all(tab._isolevel == 1 for tab in tabs)

    db.isolevel = 2

    tabs.append(db.table("e"))

    assert db.isolevel == 2
    assert all(tab._isolevel == 2 for tab in tabs)
    doc = {
        "inner": {
            "list": [1, 2, 3],
        }
    }
    _id = await db.insert(doc)
    assert await db.get(doc_id=_id) == doc
    doc["inner"]["new"] = "value"
    doc["inner"]["list"].append(4)
    assert (await db.get(doc_id=_id))["inner"]["list"] == [1, 2, 3]
    with pytest.raises(KeyError):
        (await db.get(doc_id=_id))["inner"]["new"]
    await db.close()
