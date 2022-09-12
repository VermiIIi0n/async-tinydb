import pytest
from asynctinydb import where
from asynctinydb.operations import delete, increment, decrement, add, subtract, set

@pytest.mark.asyncio
async def test_delete(db):
    await db.update(delete('int'), where('char') == 'a')
    assert 'int' not in await db.get(where('char') == 'a')

@pytest.mark.asyncio
async def test_add_int(db):
    await db.update(add('int', 5), where('char') == 'a')
    assert (await db.get(where('char') == 'a'))['int'] == 6

@pytest.mark.asyncio
async def test_add_str(db):
    await db.update(add('char', 'xyz'), where('char') == 'a')
    assert (await db.get(where('char') == 'axyz'))['int'] == 1

@pytest.mark.asyncio
async def test_subtract(db):
    await db.update(subtract('int', 5), where('char') == 'a')
    assert (await db.get(where('char') == 'a'))['int'] == -4

@pytest.mark.asyncio
async def test_set(db):
    await db.update(set('char', 'xyz'), where('char') == 'a')
    assert (await db.get(where('char') == 'xyz'))['int'] == 1

@pytest.mark.asyncio
async def test_increment(db):
    await db.update(increment('int'), where('char') == 'a')
    assert (await db.get(where('char') == 'a'))['int'] == 2

@pytest.mark.asyncio
async def test_decrement(db):
    await db.update(decrement('int'), where('char') == 'a')
    assert (await db.get(where('char') == 'a'))['int'] == 0
