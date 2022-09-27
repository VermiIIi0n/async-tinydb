"""A Tiny Event Hook Framework"""
from __future__ import annotations
from typing import Iterable, Any, Callable, Sequence, TypeVar
from typing import Iterator, overload, Mapping, Awaitable
from .utils import StrChain
import asyncio


__all__ = ["AsyncActionChain", "ActionChain", "EventHook", "EventHint"]
ActionVar = TypeVar('ActionVar', bound=Callable)
AsyncActionVar = TypeVar('AsyncActionVar', bound=Callable[..., Awaitable[Any]])
ActionChainVar = TypeVar('ActionChainVar', bound="ActionChain")


class ActionChain(Sequence[ActionVar]):
    """
    # Simple Event Hooks Framework
    * First argument to all functions is the event name, 
    following the rest of the arguments.
    """

    def __init__(self, actions: Iterable[ActionVar] | None = None, limit: int = 0) -> None:
        """#### Initialize the ActionChain.
        * `actions` is an iterable of actions to add to the chain.
        * `limit` is the maximum number of actions to add to the chain. Set to 0 for unlimited.
        """
        self._seq = list[ActionVar](actions or [])
        self._limit = limit

    def append(self, action: ActionVar) -> None:
        if self._limit and len(self) >= self._limit:
            raise RuntimeError(f"ActionChain limit reached: {self._limit}")
        self._seq.append(action)

    def insert(self, index: int, action: ActionVar) -> None:
        if self._limit and len(self) >= self._limit:
            raise RuntimeError(f"ActionChain limit reached: {self._limit}")
        self._seq.insert(index, action)

    def extend(self, actions: Iterable[ActionVar]) -> None:
        other = list(actions)
        if self._limit and len(self) + len(other) > self._limit:
            raise RuntimeError(f"ActionChain limit reached: {self._limit}")
        self._seq.extend(other)

    def remove(self, action: ActionVar) -> None:
        self._seq.remove(action)

    def clear(self) -> None:
        self._seq.clear()

    def trigger(self, event: str, *args: Any, **kw: Any) -> tuple:
        """Trigger all actions in the chain."""
        return tuple(action(event, *args, **kw) for action in self)

    async def atrigger(self: ActionChain[AsyncActionVar],
                       event: str, *args: Any, **kw: Any) -> tuple:
        """Asynchronously trigger all actions in the chain."""
        return tuple(await asyncio.gather(*(
            action(event, *args, **kw) for action in self)))

    async def ordered_atrigger(self: ActionChain[AsyncActionVar],
                               event: str, *args: Any, **kw: Any) -> tuple:
        """Asynchronously trigger all actions in the chain in order."""
        ls: list[Any] = []
        for action in self:
            ls.append(await action(event, *args, **kw))
        return tuple(ls)

    @property
    def actions(self) -> Sequence[ActionVar]:
        return tuple(self)

    def __iter__(self) -> Iterator[ActionVar]:
        return iter(self._seq)

    def __len__(self) -> int:
        return len(self._seq)

    def __contains__(self, value: object) -> bool:
        return value in self._seq

    def __reversed__(self) -> Iterator[ActionVar]:
        return reversed(self._seq)

    def __add__(self: ActionChainVar, other: ActionChainVar) -> ActionChainVar:
        return type(self)(self._seq + other._seq)

    def __iadd__(self: ActionChainVar, other: ActionChainVar) -> ActionChainVar:# type: ignore[misc]
        if self._limit and len(self) + len(other) > self._limit:
            raise RuntimeError(f"ActionChain limit reached: {self._limit}")
        self._seq += other._seq
        return self

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ActionChain):
            return self._seq == other._seq
        return False

    @property
    def __hash__(self) -> None: # type: ignore[override]
        return None

    def __str__(self) -> str:
        return str(self._seq)

    def __repr__(self) -> str:
        return '{'+f"{type(self).__name__} : {self._seq}"+'}'

    @overload
    def __getitem__(self: ActionChainVar, index: int) -> ActionVar:
        ...

    @overload
    def __getitem__(self: ActionChainVar, s: slice) -> ActionChainVar:
        ...

    def __getitem__(self: ActionChainVar, x: int | slice
                    ) -> ActionVar | ActionChainVar:
        if isinstance(x, int):
            return self._seq[x]
        if isinstance(x, slice):
            return type(self)(self._seq[x])


class EventHook(dict[str, ActionChain]):
    def __init__(self, chain: Mapping[str, Iterable[ActionVar]] | None = None):
        dict.__init__(self)
        if chain is not None:
            chain = dict(chain)
            for event, actions in chain.items():
                if isinstance(actions, ActionChain):
                    self[event] = type(actions)(actions)
                else:
                    self[event] = ActionChain[ActionVar](actions)

        self._on = EventHint(self)

    def hook(self, event: str, hook: ActionChain, force: bool = False) -> None:
        """Hook an event, equivalent to `self[event] = hook`"""
        if not force and event in self:
            raise ValueError(f"Event '{event}' already exists")
        self[event] = hook

    def unhook(self, event: str) -> ActionChain:
        """Unhook an event, equivalent to `del self[event]` or `pop()`"""
        return self.pop(event)

    def clear_actions(self):
        """Clear all actions from all events, but keep the events."""
        for event in self:
            self[event].clear()

    def emit(self, event: str, *args: Any, **kw: Any) -> tuple:
        """Trigger an event"""
        if event not in self:
            raise ValueError(f"Event '{event}' not found, add it first")
        return self[event].trigger(event, *args, **kw)

    async def aemit(self, event: str, *args: Any, **kw: Any) -> tuple:
        """Trigger an event, asynchronously"""
        if event not in self:
            raise ValueError(f"Event '{event}' not found, add it first")
        return await self[event].atrigger(event, *args, **kw)

    async def ordered_aemit(self, event: str, *args: Any, **kw: Any) -> tuple:
        """Trigger an event, asynchronously, one by one in order"""
        if event not in self:
            raise ValueError(f"Event '{event}' not found, add it first")
        return await self[event].ordered_atrigger(event, *args, **kw)

    @property
    def events(self) -> tuple[str, ...]:
        return tuple(self.keys())

    @property
    def on(self) -> EventHint:
        return self._on

    def __getitem__(self, event: str) -> ActionChain:
        if event not in self:
            raise AttributeError(f"Event '{event}' not found, add it first")
        return super().__getitem__(event)


class AsyncActionChain(ActionChain[AsyncActionVar]):
    """
    # Simple Async Event Hooks Framework
    * First argument to all functions is the event name, 
    following the rest of the arguments.
    * Only accepts async functions, 
    but the sync version of `aemit`: `emit` is kept.
    """

    def __init__(self, actions: Iterable[AsyncActionVar] | None = None, limit: int = 0) -> None:
        super().__init__(actions=actions, limit=limit)


class EventHint:
    """### Event Hint
    * This class is used to hint the event name to the event hook.
    * It is also used to prevent typos in the event name.
    * Inherit this class and add the event names as class attributes."""

    def __init__(self, event_hook: EventHook = None, strchain: StrChain = None):
        if strchain is None:
            if event_hook is None:
                raise ValueError(
                    "Either event_hook or strchain must be provided")

            def wrap(hook: EventHook):
                def callback(event: StrChain, action: ActionVar) -> ActionVar:
                    hook[str(event)].append(action)
                    return action
                return callback
            self._chain = StrChain(joint='.', callback=wrap(event_hook))
        else:
            self._chain = strchain

    def __call__(self, *args, **kwargs):
        return self._chain(*args, **kwargs)

    def __getattr__(self, event: str) -> EventHint:
        return EventHint(strchain=self._chain[event])
