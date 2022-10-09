"""Modifier class for TinyDB."""

import asyncio
from Crypto.Cipher import AES
from Crypto.Cipher._mode_gcm import GcmMode
from .storages import Storage
from .utils import get_executor


class Modifier:
    @staticmethod
    def add_encryption(s: Storage, key: str | bytes, encoding="utf-8", **kw) -> Storage:
        """
        ### Add AES-GCM Encryption to TinyDB Storage
        Hooks to `write.post` and `read.pre` to encrypt/decrypt data.
        Works on any storage class that store data as string or  bytes.

        * `s` - Storage to modify
        * `key` - Encryption key (must be 16, 24, or 32 bytes long)
        * `encoding` - Encoding to use for string data
        """

        if isinstance(key, str):
            key = key.encode("utf-8")
        kw["mode"] = AES.MODE_GCM
        dtype: type = bytes

        @s.on.write.post
        async def encrypt(ev: str, s: Storage, data: str | bytes):
            nonlocal dtype
            cipher: GcmMode = AES.new(key, **kw)  # type: ignore
            if isinstance(data, str):
                dtype = type(data)
                data = data.encode(encoding)
            loop = asyncio.get_event_loop()
            task = loop.run_in_executor(
                get_executor(), cipher.encrypt_and_digest, data)
            data, digest = await task
            data = len(digest).to_bytes(1, "little") + \
                digest + cipher.nonce + data

            return data

        @s.on.read.pre
        async def decrypt(ev: str, s: Storage, data: bytes):
            d_len = data[0]  # digest length
            digest = data[1: d_len+1]
            cipher: GcmMode = AES.new(
                key, nonce=data[d_len+1:d_len+17], **kw)  # type: ignore
            data = data[d_len+17:]
            loop = asyncio.get_event_loop()
            task = loop.run_in_executor(
                get_executor(), cipher.decrypt_and_verify, data, digest)
            ret = await task
            if dtype is bytes:
                return ret
            return dtype(ret, encoding=encoding)

        return s
