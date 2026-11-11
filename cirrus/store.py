"""A tiny key-value store for e-mail subscribers.

Upstash Redis over its REST API is used when its variables are set (free tier, no driver needed, plain HTTPS).
In demo mode and in tests an in-memory store stands in, so the whole subscribe flow can be tried offline.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from . import config


class StoreError(RuntimeError):
    pass


class MemoryStore:
    def __init__(self) -> None:
        self._kv: dict[str, tuple[float | None, str]] = {}
        self._sets: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._kv.get(key)
            if item and (item[0] is None or item[0] > time.time()):
                return item[1]
            self._kv.pop(key, None)
            return None

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        with self._lock:
            self._kv[key] = (time.time() + ex if ex else None, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._kv.pop(key, None)

    def incr(self, key: str, ex: int | None = None) -> int:
        with self._lock:
            item = self._kv.get(key)
            if item and (item[0] is None or item[0] > time.time()):
                n, exp = int(item[1]) + 1, item[0]
            else:
                n, exp = 1, (time.time() + ex if ex else None)
            self._kv[key] = (exp, str(n))
            return n

    def sadd(self, name: str, member: str) -> None:
        with self._lock:
            self._sets.setdefault(name, set()).add(member)

    def srem(self, name: str, member: str) -> None:
        with self._lock:
            self._sets.get(name, set()).discard(member)

    def smembers(self, name: str) -> list[str]:
        with self._lock:
            return sorted(self._sets.get(name, set()))


class UpstashStore:
    def __init__(self, url: str, token: str) -> None:
        self.url, self.token = url.rstrip("/"), token

    def _cmd(self, *args):
        req = urllib.request.Request(self.url, data=json.dumps(list(args)).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise StoreError(f"The subscriber store could not be reached: {exc}") from exc
        if isinstance(data, dict) and data.get("error"):
            raise StoreError(f"The subscriber store refused a command: {data['error']}")
        return data.get("result") if isinstance(data, dict) else None

    def get(self, key: str) -> str | None:
        return self._cmd("GET", key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._cmd(*(("SET", key, value, "EX", ex) if ex else ("SET", key, value)))

    def delete(self, key: str) -> None:
        self._cmd("DEL", key)

    def incr(self, key: str, ex: int | None = None) -> int:
        n = int(self._cmd("INCR", key))
        if n == 1 and ex:
            self._cmd("EXPIRE", key, ex)
        return n

    def sadd(self, name: str, member: str) -> None:
        self._cmd("SADD", name, member)

    def srem(self, name: str, member: str) -> None:
        self._cmd("SREM", name, member)

    def smembers(self, name: str) -> list[str]:
        return sorted(self._cmd("SMEMBERS", name) or [])


_store = None


def get_store():
    """The configured store, or None when e-mail alerts are not set up. Demo mode gets a throwaway in-memory one."""
    global _store
    if _store is None:
        if config.STORE_URL and config.STORE_TOKEN and not config.DEMO:
            _store = UpstashStore(config.STORE_URL, config.STORE_TOKEN)
        elif config.DEMO:
            _store = MemoryStore()
    return _store
