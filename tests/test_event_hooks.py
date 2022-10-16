import pytest
from asynctinydb.event_hooks import EventHook, ActionCentipede, ActionChain, EventHint


def test_action_chain_as_seq():
    chain = ActionChain()
    assert len(chain) == 0

    def mul2(x): return x * 2
    def mul3(x): return x * 3

    chain.append(mul2)
    assert len(chain) == 1
    chain.insert(0, mul3)
    chain.append(mul3)
    assert len(chain) == 3

    assert chain[-1] is mul3
    assert chain[0] is mul3
    assert chain[0:2] == ActionChain([mul3, mul2])
    with pytest.raises(TypeError):
        chain["shit"]

    chain2 = ActionChain([mul2, mul3])

    chain.extend(chain2)
    assert len(chain) == 5

    chain.remove(mul2)
    assert len(chain) == 4

    chain.clear()
    assert len(chain) == 0

    # Test magic methods

    # Test equality
    assert chain == ActionChain()
    assert chain != ActionChain([mul2])
    assert chain != ActionChain([mul2, mul2])
    assert chain2 == ActionChain([mul2, mul3])
    assert chain2 != [mul2, mul3]

    def mul4(x): return x * 4

    # Test contains
    assert mul2 in chain2
    assert mul3 in chain2
    assert mul4 not in chain2

    # Test bool
    assert not bool(chain)
    assert bool(chain2)

    # Test add
    assert chain + chain2 == ActionChain([mul2, mul3])
    chain += chain2
    assert chain == ActionChain([mul2, mul3])

    # Test hash
    with pytest.raises(TypeError):
        hash(chain)

    chain.clear()
    # Test repr
    assert repr(chain) == "ActionChain([])"

    # Test str
    assert str(chain) == "[]"

    # Test iter
    assert list(chain) == []
    assert list(chain2) == [mul2, mul3]

    # Test reversed
    assert list(reversed(chain2)) == [mul3, mul2]


def test_action_chain():
    def mul2(_, x): return x * 2
    def mul3(_, x): return x * 3

    chain = ActionChain([mul2, mul3])
    assert chain.actions == (mul2, mul3)

    ret = chain.trigger("test", 2)
    assert ret == (4, 6)

    # Test limit
    chain = ActionChain([mul2, mul3], limit=3)
    chain2 = ActionChain([mul2, mul3])
    chain.append(mul2)
    with pytest.raises(RuntimeError):
        chain.append(mul2)
    with pytest.raises(RuntimeError):
        chain.extend(chain2)
    with pytest.raises(RuntimeError):
        chain.insert(0, mul2)
    with pytest.raises(RuntimeError):
        chain += chain2


async def test_action_chain_async():
    async def mul2(ev, x): return x * 2
    async def mul3(ev, x): return x * 3

    chain = ActionChain([mul2, mul3])
    assert chain.actions == (mul2, mul3)

    assert (4, 6) == await chain.atrigger("test", 2)
    assert (4, 6) == await chain.ordered_atrigger("test", 2)


async def test_action_centipede():
    async def mul2(ev, x): return x * 2
    async def add3(ev, x): return x + 3

    centipede = ActionCentipede([mul2, add3])
    assert centipede.actions == (mul2, add3)

    assert 7 == await centipede.atrigger("test", 2)

    centipede = ActionCentipede([mul2, add3], reverse=True)

    assert 10 == await centipede.atrigger("test", 2)

    def sentinel(ev, x):
        def preprocess(x):
            return (x + 1,), {}
        return preprocess

    centipede = ActionCentipede([mul2, add3], sentinel=sentinel)

    assert 8 == await centipede.atrigger("test", 2)

    # Test sync funcs
    def mul2(ev, x): return x * 2
    def add3(ev, x): return x + 3

    centipede = ActionCentipede([mul2, add3])
    assert centipede.actions == (mul2, add3)
    assert 7 == centipede.trigger("test", 2)

    centipede = ActionCentipede([mul2, add3], sentinel=sentinel)
    assert 8 == centipede.trigger("test", 2)


def test_event_hint():
    with pytest.raises(ValueError):
        EventHint()

    eh = EventHint(EventHook())


def test_event_hook():
    hook = EventHook()
    hook.hook("test1", ActionChain())

    @hook.on.test1
    def mul2(ev, x): return x * 2

    @hook.on.test1
    def mul3(ev, x): return x * 3

    assert (4, 6) == hook.emit("test1", 2)

    hook.clear_actions()
    assert () == hook.emit("test1", 2)

    with pytest.raises(ValueError):
        hook.hook("test1", ActionChain())
    hook.hook("test1", ActionChain(), force=True)
    hook.unhook("test1")
    with pytest.raises(ValueError):
        hook.emit("test1", 2)

    dict_hook = {
        "test1": ActionChain(),
        "test2": [mul3, mul2]
    }
    hook = EventHook(dict_hook)

    class MyChain(ActionChain):
        pass

    assert () == hook.emit("test1", 2)
    assert (6, 4) == hook.emit("test2", 2)
    assert hook["test1"] == MyChain()
    assert hook["test2"] == ActionChain([mul3, mul2])

    assert hook.events == ("test1", "test2")

    hook.unhook("test1")
    assert hook.events == ("test2",)


async def test_event_hook_async():
    hook = EventHook()
    hook.hook("test1", ActionChain())

    @hook.on.test1
    async def mul2(ev, x): return x * 2

    @hook.on.test1
    async def mul3(ev, x): return x * 3

    assert (4, 6) == await hook.aemit("test1", 2)

    hook.clear_actions()
    assert () == await hook.aemit("test1", 2)

    hook.unhook("test1")
    with pytest.raises(ValueError):
        await hook.aemit("test1", 2)
