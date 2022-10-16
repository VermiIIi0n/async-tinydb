from asynctinydb import where, TinyDB
from asynctinydb.operations import delete, increment, decrement, add, subtract, set


async def test_delete(db: TinyDB):
    await db.update(delete('int'), where('char') == 'a')
    assert 'int' not in await db.get(where('char') == 'a')


async def test_add_int(db: TinyDB):
    await db.update(add('int', 5), where('char') == 'a')
    assert (await db.get(where('char') == 'a'))['int'] == 6


async def test_add_str(db: TinyDB):
    await db.update(add('char', 'xyz'), where('char') == 'a')
    assert (await db.get(where('char') == 'axyz'))['int'] == 1


async def test_subtract(db: TinyDB):
    await db.update(subtract('int', 5), where('char') == 'a')
    assert (await db.get(where('char') == 'a'))['int'] == -4


async def test_set(db: TinyDB):
    await db.update(set('char', 'xyz'), where('char') == 'a')
    assert (await db.get(where('char') == 'xyz'))['int'] == 1


async def test_increment(db: TinyDB):
    await db.update(increment('int'), where('char') == 'a')
    assert (await db.get(where('char') == 'a'))['int'] == 2


async def test_decrement(db: TinyDB):
    await db.update(decrement('int'), where('char') == 'a')
    assert (await db.get(where('char') == 'a'))['int'] == 0
