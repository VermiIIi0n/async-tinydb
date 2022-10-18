"""
Contains the :class:`base class <tinydb.storages.Storage>` for storages and
implementations.
"""
from __future__ import annotations
import io
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable, Mapping, MutableMapping, TypeVar
import os
from tempfile import NamedTemporaryFile
import ujson as json
from .event_hooks import EventHook, ActionChain, EventHint, ActionCentipede
from .event_hooks import AsyncActionType
from .utils import AsinkRunner

__all__ = ("Storage", "JSONStorage", "MemoryStorage")


def touch(path: str, create_dirs: bool):
    """
    Create a file if it doesn't exist yet.

    :param path: The file to create.
    :param create_dirs: Whether to create all missing parent directories.
    """
    if create_dirs:
        base_dir = os.path.dirname(path)

        # Check if we need to create missing parent directories
        os.makedirs(base_dir, exist_ok=True)

    # Create the file by opening it in 'a' mode which creates the file if it
    # does not exist yet but does not modify its contents
    with open(path, 'a', encoding="utf-8"):
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
    async def read(self) -> MutableMapping[str, Any] | None:
        """
        Read the current state.

        Any kind of deserialization should go here.

        Return ``None`` here to indicate that the storage is empty.
        """

        raise NotImplementedError('To be overridden!')

    @abstractmethod
    async def write(self, data: Mapping) -> None:
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

    def __init__(self, path: str, create_dirs=False,
                 encoding=None, access_mode="r+", **kwargs):
        """
        Create a new instance.

        Also creates the storage file, if it doesn't exist 
        and the access mode is appropriate for writing.

        * `path`: Where to store the JSON data.
        * `create_dirs`: Whether to create all missing parent directories.
        * `encoding`: The encoding to use when reading/writing the file.
        * `access_mode`: mode in which the file is opened
         (r, r+, w, a, x, b, t, +, U)
        """

        super().__init__()

        self._mode = access_mode
        self.kwargs = kwargs

        if encoding is None and 'b' not in self._mode:
            encoding = "utf-8"

        # Open the file for reading/writing
        self._closed = False
        self._path = path
        self._encoding = encoding
        self._create_dirs = create_dirs
        self._sink = AsinkRunner()

        # Initialize event hooks

        def sentinel(_: str, storage: Storage, data: str | bytes):
            prev_ret = data

            def preprocess(data: str | bytes | None):
                nonlocal prev_ret
                data = prev_ret if data is None else data
                prev_ret = data
                return (storage, data), {}
            return preprocess

        _chain = ActionCentipede[AsyncActionType]
        self.event_hook.hook("write.pre", _chain(sentinel=sentinel))
        self.event_hook.hook("write.post", _chain(sentinel=sentinel))
        self.event_hook.hook("read.pre", _chain(reverse=True, sentinel=sentinel))
        self.event_hook.hook("read.post", _chain(reverse=True, sentinel=sentinel))
        self.event_hook.hook("close", ActionChain[AsyncActionType]())
        self._on = StorageHints(self._event_hook)  # Add hints for event hooks

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        if not self.closed:
            await self._prep()
            await self._sink.aclose()
            self._closed = True
            await self._event_hook.aemit("close", self)

    async def read(self) -> dict[str, Any] | None:
        """Read data from the storage."""
        await self._prep()

        def _atomic_read():
            """Read data from the file."""
            with open(self._path, mode=self._mode, encoding=self._encoding) as f:
                return f.read()

        # Load the JSON contents of the file
        raw: str | bytes = await self._sink.run(_atomic_read)

        if not raw:
            return None

        # Pre-process data
        pre: str | bytes = await self._event_hook.aemit("read.pre", self, raw)
        raw = pre if pre is not None else raw or "{}"

        # Deserialize the data
        data = await self._sink.run(json.loads, raw)  # type: ignore

        # Post-process data
        post = await self._event_hook.aemit("read.post", self, data)
        data = post if post is not None else data
        return data

    async def write(self, data: Mapping):
        """Write data to the storage."""
        await self._prep()

        # Pre-process data
        pre = await self._event_hook.aemit("write.pre", self, data)
        data = pre if pre is not None else data
        # Convert keys to strings
        data = await self._sink.run(self._stringify_keys, data)

        # Serialize the database state using the user-provided arguments
        task = self._sink.run(json.dumps, data or {}, **self.kwargs)
        serialized: bytes | str = await task

        # Post-process the serialized data
        if 'b' in self._mode and isinstance(serialized, str):
            serialized = serialized.encode("utf-8")
        post: str | bytes = await self._event_hook.aemit(
            "write.post", self, serialized)
        serialized = post if post is not None else serialized

        # Write the serialized data to the file
        try:
            await self._sink.run(self._atomic_write, serialized)
        except io.UnsupportedOperation as e:
            raise IOError(
                f"Cannot write to the file. Access mode is '{self._mode}'") from e

    async def _prep(self):
        if self.closed:
            raise IOError("Storage is closed")
        # Create the file if it doesn't exist and creating is allowed by the
        # access mode
        if any(character in self._mode for character in ('+', 'w', 'a')):
            await self._sink.run(touch, self._path, create_dirs=self._create_dirs)

    def _atomic_write(self, data):
        # Open the temp file
        with NamedTemporaryFile(mode=self._mode, encoding=self._encoding,
                                delete=False) as f:

            f.write(data)

            # Remove data that is behind the new cursor in case the file has
            # gotten shorter
            f.truncate()

            # Ensure the file has been written
            f.flush()
            os.fsync(f.fileno())
            f.close()

            # Use os.replace to ensure atomicity
            os.replace(f.name, self._path)

    @classmethod
    def _stringify_keys(cls, data, memo: dict = None):
        if memo is None:
            memo = {}
        if isinstance(data, MutableMapping):
            if id(data) in memo:
                return memo[id(data)]
            memo[id(data)] = {}  # Placeholder in case of loop references
            memo[id(data)].update((str(k), cls._stringify_keys(v, memo))
                                  for k, v in data.items())
            return memo[id(data)]
        if isinstance(data, list | tuple):
            return [cls._stringify_keys(v, memo) for v in data]
        return data

    def __del__(self):
        try:
            self._sink.close()
        except RuntimeError as e:  # pragma: no cover # Hard to test
            raise RuntimeError("Storage was not closed properly") from e


class EncryptedJSONStorage(JSONStorage):
    """
    Store the data in an encrypted JSON file.

    Equivalent to passing a normal JSONStorage instance to
    `modifier.Modifier.add_encryption`.  

    Use with `TinyDB` as follows:
    ```
    db = TinyDB("db.json", key="some keys", storage=EncryptedJSONStorage)
    ```

    To add compression
    ```
    from asynctinydb import Modifier
    db = TinyDB("db.json", key="some keys", 
                compression=Modifier.Compression.blosc2, 
                storage=EncryptedJSONStorage)
    ```
    """

    def __init__(self, path: str, key: str | bytes | None = None,
                 create_dirs=False, encoding=None, access_mode='rb+',
                 encryption=None, encrypt_extra: dict = None,
                 compression=None, compress_extra: dict = None, **kwargs):
        """
        Create a new instance.

        Also creates the storage file, if it doesn't exist 
        and the access mode is appropriate for writing.

        * `path`: Where to store the JSON data.
        * `key`: The key to use for encryption.
        * `create_dirs`: Whether to create all missing parent directories.
        * `encoding`: The encoding to use when reading/writing the file.
        * `access_mode`: mode in which the file is opened (e.g. `"r+"`, `"rb+"`)
        * `encryption`: The method in `Modifier.Encryption` to use for encryption.
        * `encrypt_extra`: Extra arguments to pass to the encryption function.
        * `compression`: The method in `Modifier.Compression` to use for compression.
        * `compress_extra`: Extra arguments to pass to the compression function.
        """

        super().__init__(path=path, create_dirs=create_dirs,
                         encoding=encoding, access_mode=access_mode, **kwargs)

        from .modifier import Modifier  # avoid circular import
        if key is None:
            raise ValueError("key must be provided")
        if encryption is None:
            encryption = Modifier.Encryption.AES_GCM
        if 'b' not in access_mode:
            raise ValueError("access_mode must be binary")

        if compression:
            compression(self, **(compress_extra or {}))
        encryption(self, key, **(encrypt_extra or {}))


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

    async def read(self) -> MutableMapping[str, Any] | None:
        return self.memory

    async def write(self, data: Mapping):
        self.memory = data


############# Event Hints #############

_D = TypeVar('_D', bound=Callable[[str, Storage, dict[str, dict]], Awaitable])
_S = TypeVar('_S', bound=Callable[[str, Storage, Any], Awaitable])
_C = TypeVar('_C', bound=Callable[[str, Storage], Awaitable[None]])


class _write_hint(EventHint):
    @property
    def pre(self) -> Callable[[_D], _D]:
        """
        Action Type: (event_name: str, Storage, 
        data: dict[str, dict]) -> None
        """
    @property
    def post(self) -> Callable[[_S], _S]:
        """
        Action Type: (event_name: str, Storage, 
        data: str|bytes) -> str|bytes|None
        """


class _read_hint(EventHint):
    @property
    def pre(self) -> Callable[[_S], _S]:
        """
        Action Type: (event_name: str, Storage, 
        data: str|bytes) -> str|bytes|None
        """
    @property
    def post(self) -> Callable[[_D], _D]:
        """
        Action Type: (event_name: str, Storage, 
        data: dict[str, dict]) -> None
        """


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
