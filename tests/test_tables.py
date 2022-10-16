import re

import pytest

from asynctinydb import where
from asynctinydb.database import TinyDB
from asynctinydb.table import UUID, Document


async def test_next_id(db: TinyDB):
    await db.truncate()

    assert db._get_next_id((await db._read_table()).keys()) == 1
    assert db._get_next_id((await db._read_table()).keys()) == 2
    assert db._get_next_id((await db._read_table()).keys()) == 3


async def test_tables_list(db: TinyDB):
    await db.table('table1').insert({'a': 1})
    await db.table('table2').insert({'a': 1})

    assert await db.tables() == {'_default', 'table1', 'table2'}


async def test_one_table(db: TinyDB):
    table1 = db.table('table1')

    await table1.insert_multiple({'int': 1, 'char': c} for c in 'abc')

    assert (await table1.get(where('int') == 1))['char'] == 'a'
    assert (await table1.get(where('char') == 'b'))['char'] == 'b'


async def test_multiple_tables(db: TinyDB):
    table1 = db.table('table1')
    table2 = db.table('table2')
    table3 = db.table('table3')

    await table1.insert({'int': 1, 'char': 'a'})
    await table2.insert({'int': 1, 'char': 'b'})
    await table3.insert({'int': 1, 'char': 'c'})

    assert await table1.count(where('char') == 'a') == 1
    assert await table2.count(where('char') == 'b') == 1
    assert await table3.count(where('char') == 'c') == 1

    await db.drop_tables()

    assert len(table1) == 0
    assert len(table2) == 0
    assert len(table3) == 0


async def test_caching(db: TinyDB):
    table1 = db.table('table1')
    table2 = db.table('table1')

    assert table1 is table2


async def test_query_cache(db: TinyDB):
    query1 = where('int') == 1

    assert await db.count(query1) == 3
    assert query1 in db._query_cache

    assert await db.count(query1) == 3
    assert query1 in db._query_cache

    query2 = where('int') == 0

    assert await db.count(query2) == 0
    assert query2 in db._query_cache

    assert await db.count(query2) == 0
    assert query2 in db._query_cache


async def test_query_cache_with_mutable_callable(db: TinyDB):
    table = db.table('table')
    await table.insert({'val': 5})

    mutable = 5
    def increase(x): return x + mutable

    assert where('val').is_cacheable()
    assert not where('val').map(increase).is_cacheable()
    assert not (where('val').map(increase) == 10).is_cacheable()

    search = where('val').map(increase) == 10
    assert await table.count(search) == 1

    # now `increase` would yield 15, not 10
    mutable = 10

    assert await table.count(search) == 0
    assert len(table._query_cache) == 0


async def test_zero_cache_size(db: TinyDB):
    table = db.table('table3', cache_size=0)
    query = where('int') == 1

    await table.insert({'int': 1})
    await table.insert({'int': 1})

    assert await table.count(query) == 2
    assert await table.count(where('int') == 2) == 0
    assert len(table._query_cache) == 0


async def test_query_cache_size(db: TinyDB):
    table = db.table('table3', cache_size=1)
    query = where('int') == 1

    await table.insert({'int': 1})
    await table.insert({'int': 1})

    assert await table.count(query) == 2
    assert await table.count(where('int') == 2) == 0
    assert len(table._query_cache) == 1


async def test_lru_cache(db: TinyDB):
    # Test integration into TinyDB
    table = db.table('table3', cache_size=2)
    query = where('int') == 1

    await table.search(query)
    await table.search(where('int') == 2)
    await table.search(where('int') == 3)
    assert query not in table._query_cache

    await table.remove(where('int') == 1)
    assert not table._query_cache.lru

    await table.search(query)

    assert len(table._query_cache) == 1
    table.clear_cache()
    assert len(table._query_cache) == 0


async def test_table_is_iterable(db: TinyDB):
    table = db.table('table1')

    await table.insert_multiple({'int': i} for i in range(3))

    assert [r async for r in table] == await table.all()


async def test_table_name(db: TinyDB):
    name = 'table3'
    table = db.table(name)
    assert name == table.name

    with pytest.raises(AttributeError):
        table.name = 'foo'


async def test_table_repr(db: TinyDB):
    name = 'table4'
    table = db.table(name)

    assert re.match(
        r"<Table name=\'table4\', total=0, "
        r"storage=<asynctinydb\.storages\.(.*?Storage) object at [a-zA-Z0-9]+>>",
        repr(table))


async def test_truncate_table(db: TinyDB):
    await db.truncate()
    assert db._get_next_id((await db._read_table()).keys()) == 1


async def test_uuid(db: TinyDB):
    table = db.table("table1", document_id_class=UUID)

    for i in range(2):
        doc = {str(i): i}
        await table.insert(doc)

    for d in await table.all():
        assert isinstance(d.doc_id, UUID)

    doc = Document({"answer": 42}, doc_id=UUID("00000000-0000-0000-0000-000000000000"))
    await table.insert(doc)
    assert isinstance(doc.doc_id, UUID)

    assert len(await table.all()) == 3
    assert await table.get(doc_id=UUID("00000000-0000-0000-0000-000000000000")) == doc

    with pytest.raises(ValueError):
        await table.insert(doc)

    await table.truncate()
    await table.insert(doc)


async def test_table_close(db: TinyDB):
    table = db.table("table1")
    await table.close()
    await table.close()  # Should not raise
