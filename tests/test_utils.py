import asyncio
from asyncio import futures
from functools import partial
import threading
import pytest
import inspect
import time
from threading import Thread, get_ident
from concurrent.futures._base import CancelledError as SyncCancelledError
from asynctinydb.utils import LRUCache, freeze, FrozenDict, to_async_gen
from asynctinydb.utils import StrChain, ensure_async, sync_await, mimics
from asynctinydb.utils import get_create_loop, AsinkRunner, TerminateRunner


def test_lru_cache():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3
    _ = cache["a"]  # move to front in lru queue
    cache["d"] = 4  # move oldest item out of lru queue

    try:
        _ = cache['f']
    except KeyError:
        pass

    assert cache.lru == ["c", "a", "d"]


def test_lru_cache_set_multiple():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["a"] = 2
    cache["a"] = 3
    cache["a"] = 4

    assert cache.lru == ["a"]


def test_lru_cache_get():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["b"] = 1
    cache["c"] = 1
    cache.get("a")
    cache["d"] = 4

    assert cache.lru == ["c", "a", "d"]


def test_lru_cache_delete():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["b"] = 2
    del cache["a"]

    try:
        del cache['f']
    except KeyError:
        pass

    assert cache.lru == ["b"]


def test_lru_cache_clear():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["b"] = 2
    cache.clear()

    assert cache.lru == []


def test_lru_cache_unlimited():
    cache = LRUCache()
    for i in range(100):
        cache[i] = i

    assert len(cache.lru) == 100


def test_lru_cache_unlimited_explicit():
    cache = LRUCache(capacity=None)
    for i in range(100):
        cache[i] = i

    assert len(cache.lru) == 100


def test_lru_cache_iteration_works():
    cache = LRUCache()
    count = 0
    for _ in cache:
        assert False, 'there should be no elements in the cache'

    assert count == 0


def test_mimics():

    @mimics(dict.__init__)
    def init(*args, **kw):
        dict(*args, **kw)

    # init(123)
    
    assert init.__name__ == 'init'


def test_frozendict():
    d = {'a': 1, 'b': 2}
    fd = FrozenDict(d)
    assert str(fd) == f"<FrozenDict {d}>"
    assert fd['a'] == 1
    assert fd.get('a') == 1
    assert fd.get('n', 123) == 123
    assert fd.get('n') is None
    assert tuple(fd.keys()) == tuple(d.keys())
    assert tuple(fd.values()) == tuple(d.values())
    assert tuple(fd.items()) == tuple(d.items())
    assert fd == d
    assert hash(fd)
    assert hash(fd) == hash(fd)
    assert 'a' in fd
    assert 'n' not in fd
    assert all(k in d for k in fd)
    assert len(fd) == 2


def test_freeze():
    frozen = freeze([0, 1, 2, {'a': [1, 2, 3]}, {1, 2}])
    assert isinstance(frozen, tuple)
    assert isinstance(frozen[3], FrozenDict)
    assert isinstance(frozen[3]['a'], tuple)
    assert isinstance(frozen[4], frozenset)

    d = {}
    d['d'] = d
    with pytest.raises(ValueError, match="recursive"):
        freeze(d)

    with pytest.raises(TypeError):
        frozen[0] = 10

    with pytest.raises(TypeError):
        frozen[3]['a'] = 10

    with pytest.raises(AttributeError):
        frozen[3].pop('a')

    with pytest.raises(AttributeError):
        frozen[3].update({'a': 9})


async def test_get_create_loop():
    loop = get_create_loop()
    assert loop is asyncio.get_event_loop()
    assert loop is get_create_loop()
    assert loop is asyncio.get_running_loop()
    assert loop._thread_id == get_ident()

    def run():
        loop2 = get_create_loop()
        assert loop2 is get_create_loop()
        assert loop2 is not loop

        async def _inner():
            assert loop2 is get_create_loop()
        loop2.run_until_complete(_inner())

    t = Thread(target=run, daemon=True)
    t.start()
    t.join()


def test_get_create_loop_in_sync():
    loop = get_create_loop()
    assert loop is get_create_loop()
    assert not loop.is_closed()
    assert not loop.is_running()
    assert loop._thread_id is None

    def run():
        loop = get_create_loop()
        assert loop is get_create_loop()

    t = Thread(target=run, daemon=True)
    t.start()
    t.join()


def test_sync_wait_in_sync():
    async def func():
        return 1

    loop = asyncio.new_event_loop()

    assert sync_await(func()) == 1
    assert sync_await(func(), loop) == 1  # Repeated calls should work

    async def exc1():
        raise ValueError("hell")

    with pytest.raises(ValueError):
        sync_await(exc1())


async def test_sync_wait_in_async():
    async def func():
        return 1

    loop = asyncio.get_running_loop()

    assert sync_await(func()) == 1
    assert sync_await(func(), loop) == 1

    async def exc1():
        raise ValueError("hell")

    with pytest.raises(ValueError):
        sync_await(exc1(), loop)


async def test_sync_await_threadsafe():
    loop = asyncio.get_running_loop()

    async def func():
        return 1

    def run():
        assert sync_await(func(), loop) == 1

    t = Thread(target=run, daemon=True)
    t.start()
    await asyncio.sleep(0.01)


async def test_sync_await_threadsafe_exc():
    loop = asyncio.get_running_loop()

    async def raise_exc():
        raise ValueError("hell")

    def run_exc():
        with pytest.raises(ValueError):
            sync_await(raise_exc(), loop)

    t = Thread(target=run_exc, daemon=True)
    t.start()
    await asyncio.sleep(0.01)

    fut = asyncio.Future(loop=loop)

    def run_cancel():
        with pytest.raises(SyncCancelledError):
            fut.cancel()
            sync_await(fut, loop)

    t = Thread(target=run_cancel, daemon=True)
    t.start()
    await asyncio.sleep(0.01)

    def run_type_error():
        with pytest.raises(TypeError):
            sync_await(1, loop)

    t = Thread(target=run_type_error, daemon=True)
    t.start()
    await asyncio.sleep(0.01)


def test_sync_await_threadsafe_on_closed_loop():
    loop = asyncio.new_event_loop()
    f = asyncio.sleep(0.01)
    loop.run_until_complete(f)
    loop.close()

    def run():
        with pytest.raises(RuntimeError, match="Event loop is closed"):
            sync_await(f, loop)

    t = Thread(target=run, daemon=True)
    t.start()


async def test_sync_await_threadsafe_misbound_future():
    loop = asyncio.get_running_loop()
    future = asyncio.Future(loop=asyncio.new_event_loop())

    def run():
        with pytest.raises(ValueError, match="The future belongs to a different loop"):
            sync_await(future, loop)

    t = Thread(target=run, daemon=True)
    t.start()


async def test_to_async_gen():
    recv = []
    send = []

    def gen():
        for i in range(1, 11):
            a = yield i
            if a == 11:
                with pytest.raises(ValueError):
                    yield 11
            send.append(a)

    agen = to_async_gen(gen())
    assert inspect.isasyncgen(agen)

    for j in range(11):
        if j == 10:
            with pytest.raises(StopAsyncIteration):
                await agen.asend(j)
            break
        recv.append(await agen.asend(j or None))
    assert send == recv
    g = gen()
    agen = to_async_gen(g)
    await agen.asend(None)
    assert 11 == await agen.asend(11)
    assert 2 == await agen.athrow(ValueError("shit"))

    # Test close
    g = gen()
    agen = to_async_gen(g)
    await agen.asend(None)
    await agen.aclose()
    with pytest.raises(StopAsyncIteration):
        await agen.asend(0)
    with pytest.raises(StopIteration):
        g.send(None)


async def test_ensure_async():
    rets: list = []

    def func():
        rets.append(1)
        return 1

    async def async_func():
        rets.append(2)
        return 2
    afunc = ensure_async(func)
    assert inspect.iscoroutinefunction(afunc)
    assert func is not afunc
    assert 1 == await afunc()
    assert async_func is ensure_async(async_func)
    assert 2 == await ensure_async(async_func)()
    assert rets == [1, 2]

    def gen():
        yield 0
        yield 1
        yield 2
        yield 3

    async def async_gen():
        yield 0
        yield 1

    # Test generator
    agen = ensure_async(gen())
    assert inspect.isasyncgen(agen)

    j = 0
    async for i in agen:
        assert i == j
        j += 1
        rets.append(i)
    assert rets == [1, 2, 0, 1, 2, 3]

    rets.clear()
    j = 0
    # Test async generator
    agen = async_gen()
    assert inspect.isasyncgen(agen)
    assert ensure_async(agen) is agen
    async for i in agen:
        assert i == j
        j += 1
        rets.append(i)

    with pytest.raises(TypeError):
        ensure_async(0)


async def test_asinkrunner_run_join():
    sink = AsinkRunner()

    rets: list = []

    def f1():
        rets.append(1)
        return 1

    assert 1 == await sink.run(f1)
    assert rets == [1]

    for _ in range(16):
        assert 1 == await sink.run(f1)
    sink.join()
    assert rets == [1] * 17

    rets.clear()
    for _ in range(16):
        assert 1 == await sink.run(f1)
    await sink.ajoin()
    assert rets == [1] * 16


async def test_asinkrunner_rejoin():
    sink = AsinkRunner()

    await sink.run(lambda: 1919180)
    assert sink.join()
    assert sink.join()


async def test_asinkrunner_reajoin():
    sink = AsinkRunner()

    await sink.run(lambda: 1919180)
    assert await sink.ajoin()
    assert await sink.ajoin()


def test_asinkrunner_sync_run():
    def f1():
        return 1

    sink = AsinkRunner()

    assert 1 == sink.sync_run(f1).result()

    def raise_exc():
        raise ValueError("hell")

    with pytest.raises(ValueError, match="hell"):
        sink.sync_run(raise_exc).result()


async def test_asinkrunner_close():
    sink = AsinkRunner()

    rets: list = []

    def f1():
        rets.append(1)
        return 1
    for _ in range(16):
        await sink.run(f1)
    assert sink.join(close=True)
    assert not sink.join()

    with pytest.raises(RuntimeError, match="closed"):
        sink.start()


def test_asinkrunner_close_timeout():
    sink = AsinkRunner()

    def wait():
        time.sleep(0.02)
    sink.sync_run(wait)
    with pytest.raises(TimeoutError):
        sink.close(timeout=0.001)


async def test_asinkrunner_reclose():
    sink = AsinkRunner()
    await sink.run(lambda: 114514)
    assert sink.close()
    assert not sink.close()  # Should be idempotent


async def test_asinkrunner_aclose():
    sink = AsinkRunner()
    sink.run(lambda: time.sleep(0.03))
    assert await sink.ajoin(close=True)
    assert not await sink.aclose()  # Should be idempotent


async def test_asinkrunner_exc():
    rets: list = []
    sink = AsinkRunner(cold_run=True)
    for i in range(16):
        sink.run_as(i, partial(rets.append, i))

    with pytest.raises(RuntimeError,
                       match="AsinkRunner is dead with tasks unfinished"):
        await sink.ajoin()  # Haven't started yet

    sink.start()
    await sink.ajoin()

    assert rets == list(range(16))[::-1]

    def exc():
        raise ValueError("hell")

    with pytest.raises(ValueError):
        await sink.run(exc)

    with pytest.raises(ValueError):
        sink.run_as(-1, lambda: 1)

    with pytest.raises(ValueError):
        sink.sync_run_as(-1, lambda: 1)

    sink = AsinkRunner(cold_run=True)

    with pytest.raises(asyncio.exceptions.CancelledError):
        def f(): raise TerminateRunner()
        sink.run(lambda: 1)
        sink.run(f)
        sink.run(lambda: 1)
        fut = sink.run(lambda: 1)
        sink.start()
        await fut


async def test_asinkrunner_fatal_exc():
    """Causes the futures to be cancelled"""
    sink = AsinkRunner(cold_run=True)  # For RuntimeError
    sink2 = AsinkRunner(cold_run=True)  # For asyncio.CancelledError
    sink3 = AsinkRunner(cold_run=True)  # For SyncCancelledError
    old = threading.excepthook

    sink._put_nowait(-1, lambda: None, None)  # Force a TypeError
    sink2._put_nowait(-1, lambda: time.sleep(0.02), None)  # Force a TypeError
    sink3._put_nowait(-1, lambda: time.sleep(0.02), None)  # Force a TypeError
    fut = sink.sync_run(lambda: 1)
    afut = sink.run(lambda: 1)
    sink2.sync_run(lambda: 1)
    sink3.sync_run(lambda: 1)

    def hook(args):
        """Ignore unhandled thread exceptions"""
        if args.thread not in (sink._runner, sink2._runner, sink3._runner):
            old(args)
    threading.excepthook = hook
    sink.start()

    sink2.start()
    with pytest.raises(RuntimeError, match="cancelled"):
        await sink2.ajoin()

    sink3.start()
    with pytest.raises(RuntimeError, match="cancelled"):
        sink3.join()

    with pytest.raises(SyncCancelledError):
        fut.result()

    with pytest.raises(asyncio.exceptions.CancelledError):
        await afut

    time.sleep(0.02)  # Wait for the runner to die
    with pytest.raises(RuntimeError):
        sink.join()

    threading.excepthook = old

    with pytest.raises(RuntimeError, match="closed"):
        await sink.run(lambda: 9)

    with pytest.raises(RuntimeError, match="closed"):
        sink.sync_run(lambda: 9).result()


async def test_asinkrunner_wrappers():
    sink = AsinkRunner()

    def gen():
        for i in range(10):
            yield i

    agen = sink.to_async_gen(gen())

    n = 0
    async for i in agen:
        assert n == await sink.to_async(lambda: i)()
        assert n == i
        n += 1

    agen = sink.to_async_gen(gen())
    async for i in agen:
        await agen.aclose()
        with pytest.raises(StopAsyncIteration):
            await agen.asend(i)
        break

    def gen():
        with pytest.raises(ValueError):
            yield 1
            raise RuntimeError()

    agen = sink.to_async_gen(gen())
    with pytest.raises(StopAsyncIteration):
        await agen.asend(None)
        await agen.athrow(ValueError("TEST"))


def test_strchain():
    # Test initialization
    c1 = StrChain("abc")
    c2 = StrChain(["abc"])
    assert c1 == c2 and c1() == "abc"

    # Size is not the total chars but the number of strings
    assert len(c1) == 1

    # Test attribute concatenation
    c3 = c1.defg
    assert c3() == "abc.defg"
    assert len(c3) == 2

    with pytest.raises(AttributeError):
        c1._abc

    # Test customised separator
    c4 = StrChain(joint=":")
    assert c4["abc"].defg() == "abc:defg"

    # Test get item
    assert c3[1] == "defg"

    c3.wert.ttre.tt[1:5]() == "defg.wert.ttre.tt"

    assert (str(c3["This is not possible as attribute"])
            == "abc.defg.This is not possible as attribute")

    with pytest.raises(IndexError):
        c3[5]

    with pytest.raises(TypeError):
        c3[1.0]

    # Test __repr__
    assert repr(
        c3) == "StrChain(['abc', 'defg'], joint='.', callback=<class 'str'>, **{})"

    # Test magic methods

    # Test equality
    assert c1 == c2
    assert c1 != c3
    assert c4.abc() == c1() and c4.abc != c1  # Different separator
    assert c1 != "abc"  # Different type

    # Test hash
    assert hash(c1) == hash(c2)
    assert hash(c1) != hash(c3)

    # Test len
    assert len(c1) == 1
    assert len(c3) == 2

    # Test bool
    assert bool(c1)
    assert not bool(StrChain())

    # Test add
    assert c1 + c3 == StrChain(["abc", "abc", "defg"])
    assert c1 + "defg" == StrChain(["abc", "defg"])

    # Test radd
    assert "abcde" + c1 == StrChain(["abcde", "abc"])

    # Test iadd
    c9 = StrChain("abc")
    c9 += "defg"
    assert c9 == StrChain(["abc", "defg"])
    c9 += ["hijk", "lmno"]
    assert c9 == StrChain(["abc", "defg", "hijk", "lmno"])

    # Test mul
    assert c1 * 3 == StrChain(["abc", "abc", "abc"])
    assert c1 * 0 == StrChain()
    with pytest.raises(TypeError):
        c1 * "abc"

    # Test rmul
    assert 3 * c1 == StrChain(["abc", "abc", "abc"])
    assert 0 * c1 == StrChain()

    # Test imul
    c1_cp = c1
    c1_cp *= 3
    assert c1_cp == StrChain(["abc", "abc", "abc"])
    assert c1 is not c1_cp  # StrChain is immutable

    # Test contains
    assert "abc" in c1
    assert "defg" in c3
    assert "123" not in c3
    assert 123 not in c3

    # Test iter
    assert list(iter(c1)) == ["abc"]

    # Test reversed
    assert list(reversed(c1)) == ["abc"]
    assert list(reversed(c3)) == ["defg", "abc"]

    # Test callbacks
    def callback(s):
        return str(s).upper()

    c5 = StrChain(callback=callback)

    assert c5.abc() == "ABC"

    # Test kw
    c6 = StrChain(juicy=True)
    assert c6.abc._kw == {"juicy": True}
