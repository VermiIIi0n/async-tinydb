"""
Contains the :class:`base class <tinydb.storages.Storage>` for storages and
implementations.
"""

import io
import ujson as json
import os
import asyncio
from aiofiles import open as aopen
import aiofiles.os as aos
from aiofiles.threadpool.text import AsyncTextIOWrapper as AWrapper
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

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

async def atouch(path: str, create_dirs: bool):
    """
    Create a file if it doesn't exist yet.

    :param path: The file to create.
    :param create_dirs: Whether to create all missing parent directories.
    """
    if create_dirs:
        base_dir = os.path.dirname(path)

        # Check if we need to create missing parent directories
        if not await aos.path.exists(base_dir):
            await aos.makedirs(base_dir)

    # Create the file by opening it in 'a' mode which creates the file if it
    # does not exist yet but does not modify its contents
    async with aopen(path, 'a'):
        pass


class Storage(ABC):
    """
    The abstract base class for all Storages.

    A Storage (de)serializes the current state of the database and stores it in
    some place (memory, file on disk, ...).
    """

    # Using ABCMeta as metaclass allows instantiating only storages that have
    # implemented read and write

    @abstractmethod
    async def read(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """
        Read the current state.

        Any kind of deserialization should go here.

        Return ``None`` here to indicate that the storage is empty.
        """

        raise NotImplementedError('To be overridden!')

    @abstractmethod
    async def write(self, data: Dict[str, Dict[str, Any]]) -> None:
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

        pass


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
        if any([character in self._mode for character in ('+', 'w', 'a')]):  # any of the writing modes
            touch(path, create_dirs=create_dirs)

        # Open the file for reading/writing
        self._handle: AWrapper | None = None
        self._path = path
        self._encoding = encoding

    async def close(self) -> None:
        if self._handle is not None:
            await self._handle.close()

    async def read(self) -> Optional[Dict[str, Dict[str, Any]]]:
        if self._handle is None:
            self._handle = await aopen(self._path, self._mode, encoding=self._encoding)
        # Get the file size by moving the cursor to the file end and reading
        # its location
        await self._handle.seek(0, os.SEEK_END)
        size = await self._handle.tell()

        if not size:
            # File is empty, so we return ``None`` so TinyDB can properly
            # initialize the database
            return None
        else:
            # Return the cursor to the beginning of the file
            await self._handle.seek(0)

            # Load the JSON contents of the file
            raw = await self._handle.read()
            return json.loads(raw)

    async def write(self, data: Dict[str, Dict[str, Any]]):
        if self._handle is None:
            self._handle = await aopen(self._path, self._mode, encoding=self._encoding)
        # Move the cursor to the beginning of the file just in case
        await self._handle.seek(0)

        # Serialize the database state using the user-provided arguments
        serialized = json.dumps(data, **self.kwargs)

        # Write the serialized data to the file
        try:
            await self._handle.write(serialized)
        except io.UnsupportedOperation:
            raise IOError('Cannot write to the database. Access mode is "{0}"'.format(self._mode))

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

    async def read(self) -> Optional[Dict[str, Dict[str, Any]]]:
        return self.memory

    async def write(self, data: Dict[str, Dict[str, Any]]):
        self.memory = data
