"""
Contains the :class:`base class <tinydb.storages.Storage>` for storages and
implementations.
"""
from __future__ import annotations
import io
import ujson as json
import os
import asyncio
from functools import partial
from aiofiles import open as aopen
from aiofiles.threadpool.text import AsyncTextIOWrapper as TWrapper
from aiofiles.threadpool.binary import AsyncFileIO as BWrapper
from .event_hooks import EventHook, AsyncActionChain, EventHint
from .utils import get_executor, ensure_async
from Crypto.Cipher import AES
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable, TypeVar

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
    async def read(self) -> dict[str, Any] | None:
        """
        Read the current state.

        Any kind of deserialization should go here.

        Return ``None`` here to indicate that the storage is empty.
        """

        raise NotImplementedError('To be overridden!')

    @abstractmethod
    async def write(self, data: dict) -> None:
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

        if encoding is None and 'b' not in self._mode:
            encoding = "utf-8"

        # Open the file for reading/writing
        self._handle: TWrapper | BWrapper | None = None
        self._path = path
        self._encoding = encoding
        self._data_lock = asyncio.Lock()

        # Initialize event hooks
        self.event_hook.hook("write.pre", AsyncActionChain())
        self.event_hook.hook("write.post", AsyncActionChain(limit=1))
        self.event_hook.hook("read.pre", AsyncActionChain(limit=1))
        self.event_hook.hook("read.post", AsyncActionChain())
        self.event_hook.hook("close", AsyncActionChain())
        self._on = StorageHints(self._event_hook)  # Add hints for event hooks

    @property
    def closed(self) -> bool:
        return self._handle is not None and self._handle.closed

    async def close(self) -> None:
        await self._event_hook.aemit('close', self)
        if self._handle is not None:
            await self._handle.close()

    async def read(self) -> dict[str, Any] | None:
        """Read data from the storage."""
        if self._handle is None:
            self._handle = await aopen(self._path, self._mode, encoding=self._encoding)

        # Get the file size by moving the cursor to the file end and reading
        # its location
        if self._handle.closed:
            raise IOError("File is closed")
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
        pre: tuple[str | bytes] = await self._event_hook.aemit("read.pre", self, raw)
        if pre and pre[0] is not None:
            raw = pre[0]

        loop = asyncio.get_event_loop()
        task = loop.run_in_executor(get_executor(), json.loads, raw or "{}")
        data = await task
        await self._event_hook.aemit("read.post", self, data)
        return data

    async def write(self, data: dict):
        """Write data to the storage."""
        loop = asyncio.get_running_loop()
        async with self._data_lock:
            task = loop.run_in_executor(
                get_executor(), self._stringify_keys, data)
            data = await task
        if self._handle is None:
            self._handle = await aopen(self._path, self._mode, encoding=self._encoding)
        if self._handle.closed:
            raise IOError('File is closed')
        # Move the cursor to the beginning of the file just in case
        await self._handle.seek(0)

        # Trigger write events
        await self._event_hook.aemit("write.pre", self, data)

        # Serialize the database state using the user-provided arguments
        task = loop.run_in_executor(get_executor(), partial(
            json.dumps, data or {}, **self.kwargs))
        serialized: bytes | str = await task

        # Post-process the serialized data
        if 'b' in self._mode and isinstance(serialized, str):
            serialized = serialized.encode()
        post = await self._event_hook.aemit("write.post", self, serialized)
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
        await ensure_async(os.fsync)(self._handle.fileno())

        # Remove data that is behind the new cursor in case the file has
        # gotten shorter
        await self._handle.truncate()

    @classmethod
    def _stringify_keys(cls, data, memo: dict = None):
        if memo is None:
            memo = {}
        if type(data) is dict:
            if id(data) in memo:
                return memo[id(data)]
            memo[id(data)] = {}  # Placeholder in case of recursion
            memo[id(data)].update({str(k): cls._stringify_keys(v, memo)
                                   for k, v in data.items()})
            return memo[id(data)]
        elif type(data) is list or type(data) is tuple:
            return [cls._stringify_keys(v, memo) for v in data]
        return data


class EncryptedJSONStorage(JSONStorage):
    """
    Store the data in an encrypted JSON file.

    Equivalent to passing a normal JSONStorage instance to
    `modifier.Modifier.add_encryption`.  

    Use with `TinyDB` as follows:
    ```
    db = TinyDB("db.json", storage=EncryptedJSONStorage["Your Key"])
    ```  

    To run in blocking mode:
    ```
    db = TinyDB("db.json", storage=EncryptedJSONStorage["Your Key", blocking=True])
    ```
    """

    def __init__(self, path: str, create_dirs=False, encoding=None, access_mode='rb+',
                 key: str | bytes | None = None, encrypt_mode=AES.MODE_GCM, encrypt_extra: dict = None, **kwargs):
        """
        Create a new instance.

        Also creates the storage file, if it doesn't exist and the access mode is appropriate for writing.

        * `path`: Where to store the JSON data.
        * `key`: The key to use for encryption.
        * `access_mode`: mode in which the file is opened (r, r+, w, a, x, b, t, +, U)
        * `access_mode`: str
        * `encrypt_mode`: The mode to use for encryption.
        * `encrypt_extra`: Extra arguments to pass to the encryption function.
        * `blocking` - If `True`, will block until encryption/decryption is complete, 
        otherwise will run in `ProcessPoolExecutor` (Requires program entry protection)
        """

        from .modifier import Modifier  # avoid circular import
        if key is None:
            raise ValueError("key must be provided")
        if 'b' not in access_mode:
            raise ValueError("access_mode must be binary")

        super().__init__(path=path, create_dirs=create_dirs,
                         encoding=encoding, access_mode=access_mode, **kwargs)

        Modifier.add_encryption(self, key, encrypt_mode,
                                **(encrypt_extra or {}))


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

    async def read(self) -> dict[str, Any] | None:
        return self.memory

    async def write(self, data: dict):
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
