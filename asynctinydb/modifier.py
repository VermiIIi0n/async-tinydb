"""Modifier class for TinyDB."""

from typing import Any, Callable
from warnings import warn
from functools import partial
from .storages import Storage
from .utils import arun_parallel
from .database import TinyDB


def _get_storage(item: Storage | TinyDB) -> Storage:
    """Get the storage from a TinyDB or Storage object."""
    if isinstance(item, TinyDB):
        return item.storage
    return item


class Modifier:
    class Encryption:
        """
        ## Encryption Subclass
        Contains methods to add encryption to a TinyDB storage.
        """

        @staticmethod
        def AES_GCM(s: Storage | TinyDB, key: str | bytes,
                    encoding="utf-8", **kw) -> Storage:
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
            except ImportError:
                raise ImportError(
                    "Dependencies not satisfied: "
                    "pip install async-tinydb[encryption]")

            s = _get_storage(s)

            if isinstance(key, str):
                key = key.encode("utf-8")
            kw["mode"] = AES.MODE_GCM
            dtype: type = bytes

            @s.on.write.post
            async def encrypt_aes_gcm(ev: str, s: Storage, data: str | bytes):
                nonlocal dtype
                cipher: GcmMode = AES.new(key, **kw)  # type: ignore
                if isinstance(data, str):
                    dtype = type(data)
                    data = data.encode(encoding)
                task = arun_parallel(cipher.encrypt_and_digest, data)
                data, digest = await task
                data = len(digest).to_bytes(1, "little") + \
                    digest + cipher.nonce + data

                return data

            @s.on.read.pre
            async def decrypt_aes_gcm(ev: str, s: Storage, data: bytes):
                d_len = data[0]  # digest length
                digest = data[1: d_len + 1]
                cipher: GcmMode = AES.new(
                    key, nonce=data[d_len + 1:d_len + 17], **kw)  # type: ignore
                data = data[d_len + 17:]
                task = arun_parallel(cipher.decrypt_and_verify, data, digest)
                ret = await task

                if dtype is bytes:
                    return ret
                return dtype(ret, encoding=encoding)

            return s

    @classmethod
    def add_encryption(cls, s: Storage | TinyDB, key: str | bytes,
                       encoding="utf-8", **kw) -> Storage:
        """
        ### Add AES-GCM Encryption to TinyDB Storage
        **Deprecated, consider using Modifier.Encryption.AES_GCM**

        Hooks to `write.post` and `read.pre` to encrypt/decrypt data.
        Works on any storage class that store data as string or  bytes.

        * `s` - `Storage` or `TinyDB` to modify
        * `key` - Encryption key (must be 16, 24, or 32 bytes long)
        * `encoding` - Encoding to use for string data
        """

        warn("Modifier.add_encryption is deprecated, "
             "use Modifier.Encryption.AES_GCM instead",
             DeprecationWarning, stacklevel=2)
        return cls.Encryption.AES_GCM(s, key, encoding, **kw)

    class Compression:
        """
        ## Compression Subclass
        Contains methods to add compression to a TinyDB storage.
        """

        @staticmethod
        def brotli(s: Storage | TinyDB, quality=11, **kw) -> Storage:
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
            except ImportError:
                raise ImportError(
                    "Dependencies not satisfied: "
                    "pip install async-tinydb[compression]")

            s = _get_storage(s)
            kw["quality"] = quality

            @s.on.write.post
            async def compress_brotli(ev: str, s: Storage, data: str | bytes):
                if isinstance(data, str):
                    data = data.encode("utf-8")
                ret: bytes = await arun_parallel(brotli.compress, data, **kw)
                return ret

            @s.on.read.pre
            async def decompress_brotli(ev: str, s: Storage, data: bytes):
                task = arun_parallel(brotli.decompress, data)
                return await task

            return s

        @staticmethod
        def blosc2(s: Storage | TinyDB, clevel=9, **kw) -> Storage:
            """
            ### Add Blosc2 Compression to TinyDB Storage
            Hooks to `write.post` and `read.pre` to compress/decompress data.
            Works on any storage class that store data as string or  bytes.

            * `s` - `Storage` or `TinyDB` to modify
            * `clevel` - Compression level [0-9], higher is denser but slower
            """

            try:
                import blosc2
            except ImportError:
                raise ImportError(
                    "Dependencies not satisfied: "
                    "pip install async-tinydb[compression]")

            s = _get_storage(s)
            kw["clevel"] = clevel

            @s.on.write.post
            async def compress_blosc2(ev: str, s: Storage, data: str | bytes):
                if isinstance(data, str):
                    data = data.encode("utf-8")
                task = arun_parallel(partial(blosc2.compress, data, **kw))
                ret: str | bytes = await task
                return ret

            @s.on.read.pre
            async def decompress_blosc2(ev: str, s: Storage, data: bytes):
                task = arun_parallel(blosc2.decompress, data)
                return await task

            return s

    class Conversion:
        """
        ## Conversion Subclass
        Contains methods to convert TinyDB storage items.
        """

        @staticmethod
        def ExtendedJSON(s: Storage,
                         type_hooks: dict[type, None | Callable[[
                             Any, Callable[[Any], Any]],
                             dict[str, Any]]] = None,
                         marker_hooks: dict[str, None | Callable[[
                             dict[str, Any], Callable[[Any], Any]],
                             Any]] = None):
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
                uuid.UUID: lambda x, c: {"$uuid": str(x)},
                datetime: lambda x, c: {"$date": x.isoformat()},
                timedelta: lambda x, c: {"$timedelta": x.total_seconds()},
                bytes: lambda x, c: {"$bytes": base64.b64encode(x).decode()},
                complex: lambda x, c: {"$complex": (x.real, x.imag)},
                set: lambda x, c: {"$set": tuple(x)},
                frozenset: lambda x, c: {"$frozenset": tuple(x)},
                tuple: lambda x, c: {"$tuple": x},
                re.Pattern: lambda x, c: {"$regex": (x.pattern, x.flags)},
            }

            if type_hooks:
                for k, v in type_hooks.items():
                    if v:
                        _type_hooks[k] = v
                    else:
                        _type_hooks.pop(k, None)

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
                    if _v:
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
                    raise RecursionError("Loop reference detected")
                memo.add(_id)
                _convert = partial(convert, memo=memo)

                if type(obj) is dict:
                    obj = {k: _convert(v) for k, v in obj.items()}
                elif type(obj) in (list, tuple, set, frozenset):
                    obj = type(obj)(_convert(v) for v in obj)

                ret = obj

                # Try precise match
                if type(obj) in _type_hooks:
                    ret = _type_hooks[type(obj)](obj, _convert)

                # General match
                else:
                    for t, hook in _type_hooks.items():
                        if isinstance(obj, t):
                            ret = hook(obj, _convert)
                return ret

            def recover(obj):
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
            async def convert_exjson(ev: str, s: Storage, data: dict):
                return await arun_parallel(convert, data)

            @s.on.read.post
            async def recover_exjson(ev: str, s: Storage, data: dict):
                return await arun_parallel(recover, data)
