"""Modifier class for TinyDB."""

from __future__ import annotations
from typing import Any, Callable, TypeVar, overload
import datetime as dt
from warnings import warn
from functools import partial
from .storages import Storage, StorageWithWriteReadPrePostHooks
from .utils import async_run, FrozenDict, sort_class
from .database import TinyDB
from .table import Table, IncreID, Document, BaseDocument


T = TypeVar("T", bound=Table)
S = TypeVar('S', bound=Storage)
SWRPH = TypeVar("SWRPH", bound=StorageWithWriteReadPrePostHooks)


def _get_storage(item: S | TinyDB[S]) -> S:
    """Get the storage from a TinyDB or Storage object."""
    if isinstance(item, TinyDB):
        return item.storage
    return item


@overload
def _get_table(item: TinyDB) -> Table[IncreID, Document]: ...  # type: ignore[misc]
@overload
def _get_table(item: T) -> T: ...


def _get_table(item):
    """Get the table from a TinyDB or Table object."""
    if isinstance(item, TinyDB):
        return item.default_table
    return item


class Modifier:
    class Encryption:
        """
        ## Encryption Subclass
        Contains methods to add encryption to a TinyDB storage.
        """

        @staticmethod
        def AES_GCM(s: SWRPH | TinyDB[SWRPH], key: str | bytes, **kw) -> SWRPH:
            """
            ### Add AES-GCM Encryption to TinyDB Storage
            Hooks to `write.post` and `read.pre` to encrypt/decrypt data.
            Works on any storage class that store data as string or  bytes.

            * `s` - `Storage` or `TinyDB` to modify
            * `key` - Encryption key (must be 16, 24, or 32 bytes long)
            * `encoding` - Encoding to use for string data
            """

            try:
                from Crypto.Cipher import AES
                from Crypto.Cipher._mode_gcm import GcmMode
            except ImportError as e:
                raise ImportError(
                    "Dependencies not satisfied: "
                    "pip install async-tinydb[encryption]") from e

            s = _get_storage(s)

            if isinstance(key, str):
                key = key.encode("utf-8")
            kw["mode"] = AES.MODE_GCM
            dtype: type = bytes

            @s.on.write.post
            async def encrypt_aes_gcm(_: str, s: Storage, data: str | bytes):
                nonlocal dtype
                cipher: GcmMode = AES.new(key, **kw)  # type: ignore
                if isinstance(data, str):
                    dtype = str
                    data = data.encode("utf-8")
                task = async_run(cipher.encrypt_and_digest, data)
                data, digest = await task
                data = len(digest).to_bytes(1, "little") + \
                    digest + cipher.nonce + data

                return data

            @s.on.read.pre
            async def decrypt_aes_gcm(_: str, s: Storage, data: bytes):
                d_len = data[0]  # digest length
                digest = data[1: d_len + 1]
                cipher: GcmMode = AES.new(key,  # type: ignore
                                          nonce=data[d_len + 1:d_len + 17], **kw)
                data = data[d_len + 17:]
                task = async_run(cipher.decrypt_and_verify, data, digest)
                ret = await task

                if dtype is bytes:
                    return ret
                return dtype(ret, encoding="utf-8")

            return s

    @classmethod
    def add_encryption(cls, s: SWRPH | TinyDB[SWRPH], key: str | bytes,
                       encoding: str = None, **kw) -> SWRPH:
        """
        ### Add AES-GCM Encryption to TinyDB Storage
        **Deprecated, consider using Modifier.Encryption.AES_GCM**

        Hooks to `write.post` and `read.pre` to encrypt/decrypt data.
        Works on any storage class that store data as string or  bytes.

        * `s` - `Storage` or `TinyDB` to modify
        * `key` - Encryption key (must be 16, 24, or 32 bytes long)
        * `encoding` - Deprecated
        """

        warn("Modifier.add_encryption is deprecated, "
             "use Modifier.Encryption.AES_GCM instead",
             DeprecationWarning, stacklevel=2)
        if encoding:
            warn("Modifier.add_encryption: `encoding` is deprecated",
                 DeprecationWarning, stacklevel=2)
        return cls.Encryption.AES_GCM(s, key, **kw)

    class Compression:
        """
        ## Compression Subclass
        Contains methods to add compression to a TinyDB storage.
        """

        @staticmethod
        def brotli(s: SWRPH | TinyDB[SWRPH], quality=11, **kw) -> SWRPH:
            """
            ### Add Brotli Compression to TinyDB Storage
            Hooks to `write.post` and `read.pre` to compress/decompress data.
            Works on any storage class that store data as string or  bytes.

            * `s` - `Storage` or `TinyDB` to modify
            * `quality` - Compression quality [0-11], 
            higher is denser but slower
            """

            try:
                import brotli
            except ImportError as e:
                raise ImportError(
                    "Dependencies not satisfied: "
                    "pip install async-tinydb[compression]") from e

            s = _get_storage(s)
            kw["quality"] = quality
            dtype: type = bytes

            @s.on.write.post
            async def compress_brotli(ev: str, s: Storage, data: str | bytes):
                nonlocal dtype
                if isinstance(data, str):
                    dtype = str
                    data = data.encode("utf-8")
                return await async_run(brotli.compress, data, **kw)

            @s.on.read.pre
            async def decompress_brotli(ev: str, s: Storage, data: bytes):
                task = async_run(brotli.decompress, data)
                if dtype is bytes:
                    return await task
                return dtype(await task, encoding="utf-8")

            return s

        @staticmethod
        def blosc2(s: SWRPH | TinyDB[SWRPH], clevel=9, **kw) -> SWRPH:
            """
            ### Add Blosc2 Compression to TinyDB Storage
            Hooks to `write.post` and `read.pre` to compress/decompress data.
            Works on any storage class that store data as string or  bytes.

            * `s` - `Storage` or `TinyDB` to modify
            * `clevel` - Compression level [0-9], higher is denser but slower
            """

            try:
                import blosc2
            except ImportError as e:
                raise ImportError(
                    "Dependencies not satisfied: "
                    "pip install async-tinydb[compression]") from e

            s = _get_storage(s)
            kw["clevel"] = clevel
            dtype: type = bytes

            @s.on.write.post
            async def compress_blosc2(_: str, s: Storage, data: str | bytes):
                nonlocal dtype
                if isinstance(data, str):
                    dtype = str
                    data = data.encode("utf-8")
                return await async_run(blosc2.compress, data, **kw)

            @s.on.read.pre
            async def decompress_blosc2(_: str, s: Storage, data: bytes):
                task = async_run(blosc2.decompress, data)
                if dtype is bytes:
                    return await task
                return dtype(await task, encoding="utf-8")

            return s

    class Conversion:
        """
        ## Conversion Subclass
        Contains methods to convert TinyDB storage items.
        """

        @staticmethod
        def ExtendedJSON(s: SWRPH | TinyDB[SWRPH],
                         type_hooks: dict[type, None | Callable[[
                             Any, Callable[[Any], Any]], Any]] = None,
                         marker_hooks: dict[str, None | Callable[[
                             dict[str, Any], Callable[[Any], Any]],
                             Any]] = None) -> SWRPH:
            """
            ### Extend JSON Data Types

            Extended Types:
            * `uuid.UUID`
            * `datetime.datetime`: Converted to `ISO 8601` format.
            * `datetime.timestamp`
            * `bytes`: It is stored as a base64 string.
            * `complex`
            * `set`
            * `frozenset`
            * `tuple`
            * `re.Pattern`

            Parameters:
            * `s` - `Storage` or `TinyDB` to modify
            * `type_hooks` - Type hooks to use for converting, 
            should return a JSON serializable object. 
            Extended types are stored in such a `dict`: {"$<marker>": <data>}
            * `marker_hooks` - Marker hooks to use for recoverting.

            `type_hooks` example:
            First argument is the object to convert,
            second argument is the convert function.
            ```
            type_hooks = {
                uuid.UUID: lambda x,c: {"$uuid": str(x)},
                complex: lambda x,c: {"$complex": (x.real, x.imag)},
                set: None, # Set to None to disable conversion
            }
            ```

            `marker_hooks` example:
            First argument is a `dict` that may be restored, 
            second argument is the recovery function.
            ```
            marker_hooks = {
                "$uuid": lambda x, r: uuid.UUID(x["$uuid"]),
                "$complex": lambda x, r: complex(*x["$complex"]),
                "$set": None  # Disable recovery
            }
            ```
            """

            import re
            import uuid
            import base64
            from datetime import datetime, timedelta

            s = _get_storage(s)

            _type_hooks = {
                BaseDocument: lambda x, c: {k: c(v) for k, v in x.items()},
                dict: lambda x, c: {k: c(v) for k, v in x.items()},
                FrozenDict: lambda x, c: {k: c(v) for k, v in x.items()},
                list: lambda x, c: [c(v) for v in x],
                tuple: lambda x, c: {"$tuple": tuple(c(v) for v in x)},
                set: lambda x, c: {"$set": tuple(c(v) for v in x)},
                frozenset: lambda x, c: {"$frozenset": tuple(c(v) for v in x)},
                uuid.UUID: lambda x, c: {"$uuid": str(x)},
                datetime: lambda x, c: {"$date": x.isoformat()},
                timedelta: lambda x, c: {"$timedelta": x.total_seconds()},
                re.Pattern: lambda x, c: {"$regex": (x.pattern, x.flags)},
                bytes: lambda x, c: {"$bytes": base64.b64encode(x).decode()},
                complex: lambda x, c: {"$complex": (x.real, x.imag)},
            }

            if type_hooks:
                # Merge type hooks and sort classes from child to parent
                tmp: dict = {**_type_hooks, **type_hooks}
                keys = sort_class(tmp)
                _type_hooks = {k: tmp[k] for k in keys if tmp[k] is not None}

            _marker_hooks = {
                "$uuid": lambda x, r: uuid.UUID(x["$uuid"]),
                "$date": lambda x, r: datetime.fromisoformat(x["$date"]),
                "$timedelta": lambda x, r: timedelta(seconds=x["$timedelta"]),
                "$bytes": lambda x, r: base64.b64decode(x["$bytes"].encode()),
                "$complex": lambda x, r: complex(*x["$complex"]),
                "$set": lambda x, r: set(x["$set"]),
                "$frozenset": lambda x, r: frozenset(x["$frozenset"]),
                "$tuple": lambda x, r: tuple(x["$tuple"]),
                "$regex": lambda x, r: re.compile(*x["$regex"]),
            }

            if marker_hooks:
                for _k, _v in marker_hooks.items():
                    if _v is not None:
                        _marker_hooks[_k] = _v
                    else:
                        _marker_hooks.pop(_k, None)

            def convert(obj, memo: set = None):
                """
                ### Recursively Convert Function
                Performs a loop reference check and converts the object.
                """

                memo = memo.copy() if memo else set()  # Anti-recursion
                _id = id(obj)
                if _id in memo:
                    raise ValueError("Circular reference detected")
                memo.add(_id)
                _convert = partial(convert, memo=memo)

                # Try precise matching
                if type(obj) in _type_hooks:
                    obj = _type_hooks[type(obj)](obj, _convert)

                # General matching
                else:
                    for t, hook in _type_hooks.items():
                        if isinstance(obj, t):
                            obj = hook(obj, _convert)
                return obj

            def recover(obj) -> Any:
                """
                ### Recursively recovery object from extended JSON
                **No loop reference check**
                """

                if type(obj) is list:
                    obj = [recover(v) for v in obj]

                elif type(obj) is dict:
                    obj = {k: recover(v) for k, v in obj.items()}

                    for marker, hook in _marker_hooks.items():
                        if marker in obj:
                            return hook(obj, recover)
                return obj

            @s.on.write.pre
            async def convert_xjson(_: str, s: Storage, data: dict):
                return await async_run(convert, data)

            @s.on.read.post
            async def recover_xjson(_: str, s: Storage, data: dict):
                return await async_run(recover, data)

            return s

        @staticmethod
        def Timestamp(
                tab: T | TinyDB,
                fmt: str | None = "%Y-%m-%d %H:%M:%S%z",
                tz: dt.tzinfo | None = dt.timezone.utc,
                create: bool = True,
                modify: bool = True,
                access: bool = False,
                fields: dict = {  # skipcq: PYL-W0102
                    "create": "created",
                    "modify": "modified",
                    "access": "accessed",
                }) -> T | Table[IncreID, Document]:
            """
            ### Timestamp
            Add a timestamp field to the data.

            * `tab` - Table or TinyDB instance
            * `fmt` - Format string for `datetime.strftime`
            If `None`, use `datetime.datetime()` class
            (Recommended be used with `ExtendedJSON`).
            * `tz` - Timezone for timestamp
            * `create` - Add stamp when being created
            * `modify` - Add stamp when being modified
            * `access` - Add stamp when being accessed
            * `fields` - Field names for each timestamp
            """

            tab = _get_table(tab)

            def get_time():
                if fmt is None:
                    return dt.datetime.now(tz=tz)
                return dt.datetime.now(tz=tz).strftime(fmt)

            if create:
                @tab.on.create
                def create_time(_: str, tab: Table, doc: BaseDocument):
                    doc[fields["create"]] = get_time()

            if modify:
                @tab.on.update
                def modify_time(_: str, tab: Table, doc: BaseDocument):
                    doc[fields["modify"]] = get_time()

            if access:
                @tab.on.read
                def access_time(_: str, tab: Table, doc: BaseDocument):
                    doc[fields["access"]] = get_time()

            return tab
