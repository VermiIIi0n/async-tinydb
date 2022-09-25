"""
Contains the :class:`base class <tinydb.storages.Storage>` for storages and
implementations.
"""
from __future__ import annotations
import io
import ujson as json
import os
import asyncio
from aiofiles import open as aopen
from aiofiles.threadpool.text import AsyncTextIOWrapper as TWrapper
from aiofiles.threadpool.binary import AsyncFileIO as BWrapper
from .event_hooks import EventHook, AsyncActionChain, EventHint
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable, Mapping, TypeVar

__all__ = ('Storage', 'JSONStorage', 'MemoryStorage')


def touch(path: str, create_dirs: bool):
    """
    Create a file if it doesn't exist yet.

    :param path: The file to create.
    :param create_dirs: Whether to create all missing parent directories.
    """
    if create_dirs:
        base_dir = os.path.dirname(path)

        # Check if we need to create missing parent directories
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)

    # Create the file by opening it in 'a' mode which creates the file if it
    # does not exist yet but does not modify its contents
    with open(path, 'a'):
        pass


class Storage(ABC):
    """
    The abstract base class for all Storages.

    A Storage (de)serializes the current state of the database and stores it in
    some place (memory, file on disk, ...).
    """

    # Using ABCMeta as metaclass allows instantiating only storages that have
    # implemented read and write

    def __init__(self):
        # Create event hook
        self._event_hook = EventHook()
        self._on = EventHint(self._event_hook)

    @property
    def on(self) -> StorageHints:
        """
        Event hook for storage events.
        """
        return self._on

    @property
    def event_hook(self) -> EventHook:
        """
        The event hook for this storage.
        """
        return self._event_hook

    @property
    @abstractmethod
    def closed(self) -> bool:
        """
        Whether the storage is closed.
        """

    @abstractmethod
    async def read(self) -> dict[str, Mapping[str, Mapping]] | None:
        """
        Read the current state.

        Any kind of deserialization should go here.

        Return ``None`` here to indicate that the storage is empty.
        """

        raise NotImplementedError('To be overridden!')

    @abstractmethod
    async def write(self, data: dict[str, Mapping[Any, Mapping]]) -> None:
        """
        Write the current state of the database to the storage.

        Any kind of serialization should go here.

        :param data: The current state of the database.
        """

        raise NotImplementedError('To be overridden!')

    async def close(self) -> None:
        """
        Optional: Close open file handles, etc.
        """


class JSONStorage(Storage):
    """
    Store the data in a JSON file.
    """

    def __init__(self, path: str, create_dirs=False, encoding=None, access_mode='r+', **kwargs):
        """
        Create a new instance.

        Also creates the storage file, if it doesn't exist and the access mode is appropriate for writing.

        :param path: Where to store the JSON data.
        :param access_mode: mode in which the file is opened (r, r+, w, a, x, b, t, +, U)
        :type access_mode: str
        """

        super().__init__()

        self._mode = access_mode
        self.kwargs = kwargs

        # Create the file if it doesn't exist and creating is allowed by the
        # access mode
        if any(character in self._mode for character in ('+', 'w', 'a')):  # any of the writing modes
            touch(path, create_dirs=create_dirs)

        # Open the file for reading/writing
        self._handle: TWrapper | BWrapper | None = None
        self._path = path
        self._encoding = encoding

        # Initialize event hooks
        self.event_hook.hook('write.pre', AsyncActionChain())
        self.event_hook.hook('write.post', AsyncActionChain(limit=1))
        self.event_hook.hook('read.pre', AsyncActionChain(limit=1))
        self.event_hook.hook('read.post', AsyncActionChain())
        self.event_hook.hook('close', AsyncActionChain())
        self._on = StorageHints(self._event_hook)  # Add hints for event hooks

    @property
    def closed(self) -> bool:
        return self._handle is not None and self._handle.closed

    async def close(self) -> None:
        await self._event_hook.aemit('close', self)
        if self._handle is not None:
            await self._handle.close()

    async def read(self) -> dict[str, Mapping[str, Mapping]] | None:
        if self._handle is None:
            self._handle = await aopen(self._path, self._mode, encoding=self._encoding)
        # Get the file size by moving the cursor to the file end and reading
        # its location
        if self._handle.closed:
            raise IOError('File is closed')
        await self._handle.seek(0, os.SEEK_END)
        size = await self._handle.tell()

        if not size:
            # File is empty, so we return ``None`` so TinyDB can properly
            # initialize the database
            return None
        
        # Return the cursor to the beginning of the file
        await self._handle.seek(0)

        # Load the JSON contents of the file
        raw = await self._handle.read()
        # Trigger read events
        pre = await self._event_hook.aemit('read.pre', self, raw)
        if pre and pre[0] is not None:
            raw = pre[0]
        data = json.loads(raw or "{}")
        await self._event_hook.aemit('read.post', self, data)
        return data

    async def write(self, data: dict[str, Mapping[Any, Mapping]]):
        data = {k: ({str(_id): v for _id, v in tab.items()} 
                    if hasattr(tab, "items") else tab) 
                for k, tab in data.items()}
        if self._handle is None:
            self._handle = await aopen(self._path, self._mode, encoding=self._encoding)
        if self._handle.closed:
            raise IOError('File is closed')
        # Move the cursor to the beginning of the file just in case
        await self._handle.seek(0)

        # Trigger write events
        await self._event_hook.aemit('write.pre', self, data)
        # Serialize the database state using the user-provided arguments
        serialized: bytes | str = json.dumps(data or {}, **self.kwargs)
        if 'b' in self._mode:
            serialized = serialized.encode()  # type: ignore
        post = await self._event_hook.aemit('write.post', self, serialized)
        if post and post[0] is not None:  # if action returned something
            serialized = post[0]

        # Write the serialized data to the file
        try:
            await self._handle.write(serialized)  # type: ignore
        except io.UnsupportedOperation:
            raise IOError(
                f"Cannot write to the database. Access mode is '{self._mode}'")

        # Ensure the file has been written
        await self._handle.flush()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, os.fsync, self._handle.fileno())

        # Remove data that is behind the new cursor in case the file has
        # gotten shorter
        await self._handle.truncate()


class MemoryStorage(Storage):
    """
    Store the data as JSON in memory.
    """

    def __init__(self):
        """
        Create a new instance.
        """

        super().__init__()
        self.memory = None

    @property
    def closed(self) -> bool:
        return False

    async def read(self) -> dict[str, Mapping[str, Mapping]] | None:
        return self.memory

    async def write(self, data: dict[str, Mapping[Any, Mapping]]):
        self.memory = data


############# Event Hints #############

_W = TypeVar('_W', bound=Callable[[
             str, Storage, dict[str, dict[str, Any]]], Awaitable[None]])
_R = TypeVar('_R', bound=Callable[[str, Storage, Any], Awaitable[Any | None]])
_C = TypeVar('_C', bound=Callable[[str, Storage], Awaitable[None]])


class _write_hint(EventHint):
    @property
    def pre(self) -> Callable[[_W], _W]:
        """Action Type: (event_name: str, Storage, data: dict[str, dict[str, Any]]) -> None"""
    @property
    def post(self) -> Callable[[_R], _R]:
        """Action Type: (event_name: str, Storage, data: str|bytes) -> str|bytes|None"""


class _read_hint(EventHint):
    @property
    def pre(self) -> Callable[[_R], _R]:
        """Action Type: (event_name: str, Storage, data: str|bytes) -> str|bytes|None"""
    @property
    def post(self) -> Callable[[_W], _W]:
        """Action Type: (event_name: str, Storage, data: dict[str, dict[str, Any]]) -> None"""


class StorageHints(EventHint):
    """
    Event hints for the storage class.
    """
    @property
    def write(self) -> _write_hint:
        return self._chain.write  # type: ignore

    @property
    def read(self) -> _read_hint:
        return self._chain.read  # type: ignore

    @property
    def close(self) -> Callable[[_C], _C]:
        return self._chain.close

############# Event Hints #############
