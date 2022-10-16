"""A Tiny Event Hook Framework"""
from __future__ import annotations
from abc import abstractmethod
from typing import Iterable, Any, Callable, Sequence, TypeVar
from typing import Iterator, overload, Mapping, Awaitable
from .utils import StrChain
import asyncio


__all__ = ["ActionCentipede", "ActionChain", "EventHook", "EventHint"]
ActionVar = TypeVar("ActionVar", bound=Callable)
AsyncActionType = Callable[..., Awaitable[Any]]
AsyncActionVar = TypeVar("AsyncActionVar", bound=AsyncActionType)
ActionChainVar = TypeVar("ActionChainVar", bound="BaseActionChain")


class BaseActionChain(Sequence[ActionVar]):
    """
    # Simple Event Hooks Framework
    Base class
    """

    def __init__(self, actions: Iterable[ActionVar] | None = None,
                 limit: int = 0) -> None:
        """#### Initialize the ActionChain.
        * `actions` is an iterable of actions to add to the chain.
        * `limit` is the maximum number of actions to add to the chain. 
        Set to 0 for unlimited.
        """
        self._seq = list[ActionVar](actions or [])
        self.limit = limit

    def append(self, action: ActionVar) -> None:
        if self.limit and len(self) >= self.limit:
            raise RuntimeError(f"ActionChain limit reached: {self.limit}")
        self._seq.append(action)

    def insert(self, index: int, action: ActionVar) -> None:
        if self.limit and len(self) >= self.limit:
            raise RuntimeError(f"ActionChain limit reached: {self.limit}")
        self._seq.insert(index, action)

    def extend(self, actions: Iterable[ActionVar]) -> None:
        other = list(actions)
        if self.limit and len(self) + len(other) > self.limit:
            raise RuntimeError(f"ActionChain limit reached: {self.limit}")
        self._seq.extend(other)

    def remove(self, action: ActionVar) -> None:
        self._seq.remove(action)

    def clear(self) -> None:
        self._seq.clear()

    @abstractmethod
    def trigger(self, event: str, *args: Any, **kw: Any) -> Any:
        """Trigger all actions in the chain."""
        raise NotImplementedError()

    @abstractmethod
    async def atrigger(self: BaseActionChain[AsyncActionVar],
                       event: str, *args: Any, **kw: Any) -> Any:
        """Asynchronously trigger all actions in the chain."""
        raise NotImplementedError()

    @property
    def actions(self) -> Sequence[ActionVar]:
        return tuple(self)

    def __iter__(self) -> Iterator[ActionVar]:
        return iter(self._seq)

    def __len__(self) -> int:
        return len(self._seq)

    def __bool__(self) -> bool:
        return bool(self._seq)

    def __contains__(self, value: object) -> bool:
        return value in self._seq

    def __reversed__(self) -> Iterator[ActionVar]:
        return reversed(self._seq)

    def __add__(self: ActionChainVar, other: ActionChainVar) -> ActionChainVar:
        if isinstance(other, BaseActionChain):
            return type(self)(self._seq + other._seq)
        return NotImplemented

    def __iadd__(self: ActionChainVar, other: ActionChainVar  # type: ignore[misc]
                 ) -> ActionChainVar:
        if isinstance(other, BaseActionChain):
            if self.limit and len(self) + len(other) > self.limit:
                raise RuntimeError(f"ActionChain limit reached: {self.limit}")
            self._seq += other._seq
            return self
        return NotImplemented

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BaseActionChain):
            return self._seq == other._seq
        return False

    @property
    def __hash__(self) -> None:  # type: ignore[override]
        return None

    def __str__(self) -> str:
        return str(self._seq)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._seq})"

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
        raise TypeError(f"Invalid index type: {type(x)}")


class ActionChain(BaseActionChain[ActionVar]):
    """
    # Simple Event Hooks Framework
    * First argument to all functions is the event name, 
    following the rest of the arguments.
    """

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


class ActionCentipede(BaseActionChain[ActionVar]):
    """
    # ActionCentipede Class
    The return values of an action are passed to the next action as arguments.
    """

    def __init__(self, actions: Iterable[ActionVar] | None = None,
                 limit: int = 0, reverse=False,
                 sentinel: Callable[..., Callable] = None) -> None:
        """### Initialize the ActionCentipede.
        * `actions` is an iterable of actions to add to the chain.
        * `limit` is the maximum number of actions to add to the chain. 
        Set to 0 for unlimited.
        * `reverse` is a boolean indicating whether to reverse the order of
        the execution chain.
        * `sentinel` is a function that is called when the centipede is triggered.
        It should return a function that preprocesses 
        the return values of the previous action, 
        and returns the arguments to be passed to the next action.

        `sentinel` Example:
        ```Python
        def first_action(event, operand, num):
            return num+operand

        def second_action(event, operand, num):
            return num*operand

        def sentinel(event, context, data):
            def preprocessor(return_value):
                return (event, context, return_value), {}  # args, kwargs
            return preprocessor

        centipede = ActionCentipede([first_action, second_action], sentinel=sentinel)
        centipede.trigger("add & multiply", 3, 2)  # returns 15
        ```
        """
        super().__init__(actions, limit)
        self.sentinel = sentinel
        self.reverse = reverse

    def trigger(self, event: str, *args: Any, **kw: Any) -> Any:
        """Trigger all actions in the chain."""
        if self.sentinel:
            preproc = self.sentinel(event, *args, **kw)
        else:
            def preproc(x): return (x,), {}

        ret = None
        seq = reversed(self) if self.reverse else self
        for action in seq:
            ret = action(event, *args, **kw)
            args, kw = preproc(ret)

        return ret

    async def atrigger(self: ActionCentipede[AsyncActionVar],
                       event: str, *args: Any, **kw: Any) -> Any:
        """Asynchronously trigger all actions in the chain."""
        if self.sentinel:
            preproc = self.sentinel(event, *args, **kw)
        else:
            def preproc(x): return (x,), {}

        ret = None
        seq = reversed(self) if self.reverse else self
        for action in seq:
            ret = await action(event, *args, **kw)
            args, kw = preproc(ret)

        return ret


class EventHook(dict[str, BaseActionChain]):
    """
    # Event Hook Class
    Binds events to action chains.
    """
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

    def hook(self, event: str, hook: BaseActionChain, force: bool = False) -> None:
        """Hook an event, equivalent to `self[event] = hook`"""
        if not force and event in self:
            raise ValueError(f"Event '{event}' already exists")
        self[event] = hook

    def unhook(self, event: str) -> BaseActionChain:
        """Unhook an event, equivalent to `del self[event]` or `pop()`"""
        return self.pop(event)

    def clear_actions(self):
        """Clear all actions from all events, but keep the events."""
        for event in self:
            self[event].clear()

    def emit(self, event: str, *args: Any, **kw: Any) -> tuple | Any:
        """Trigger an event"""
        if event not in self:
            raise ValueError(f"Event '{event}' not found, add it first")
        return self[event].trigger(event, *args, **kw)

    async def aemit(self, event: str, *args: Any, **kw: Any) -> tuple | Any:
        """Trigger an event, asynchronously"""
        if event not in self:
            raise ValueError(f"Event '{event}' not found, add it first")
        return await self[event].atrigger(event, *args, **kw)

    @property
    def events(self) -> tuple[str, ...]:
        return tuple(self.keys())

    @property
    def on(self) -> EventHint:
        return self._on

    def __getitem__(self, event: str) -> BaseActionChain:
        if event not in self:
            raise AttributeError(f"Event '{event}' not found, add it first")
        return super().__getitem__(event)


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

            def callback(event: StrChain, action: ActionVar) -> ActionVar:
                event_hook[str(event)].append(action)  # type: ignore
                return action
            self._chain = StrChain(joint='.', callback=callback)

        else:
            self._chain = strchain

    def __call__(self, *args, **kwargs):
        return self._chain(*args, **kwargs)

    def __getattr__(self, event: str) -> EventHint:
        return EventHint(strchain=self._chain[event])
