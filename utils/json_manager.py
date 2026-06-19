import json
import os
import threading
from typing import Any, Optional


class JsonManager:
    _locks: dict[str, threading.Lock] = {}
    _locks_meta = threading.Lock()

    def __init__(self, filepath: str, default: Any = None):
        self.filepath = filepath
        self.default = default if default is not None else {}
        with JsonManager._locks_meta:
            if filepath not in JsonManager._locks:
                JsonManager._locks[filepath] = threading.Lock()
        self._lock = JsonManager._locks[filepath]
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.filepath):
            self._write_raw(self.default)

    def _read_raw(self) -> Any:
        with open(self.filepath, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return self.default

    def _write_raw(self, data: Any):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.filepath)

    def read(self) -> Any:
        with self._lock:
            return self._read_raw()

    def write(self, data: Any):
        with self._lock:
            self._write_raw(data)

    def get(self, key: str, default: Any = None) -> Any:
        data = self.read()
        if isinstance(data, dict):
            return data.get(key, default)
        return default

    def set(self, key: str, value: Any):
        with self._lock:
            data = self._read_raw()
            if not isinstance(data, dict):
                data = {}
            data[key] = value
            self._write_raw(data)

    def delete(self, key: str) -> bool:
        with self._lock:
            data = self._read_raw()
            if isinstance(data, dict) and key in data:
                del data[key]
                self._write_raw(data)
                return True
            return False

    def update(self, key: str, fields: dict) -> bool:
        with self._lock:
            data = self._read_raw()
            if isinstance(data, dict) and key in data:
                if isinstance(data[key], dict):
                    data[key].update(fields)
                    self._write_raw(data)
                    return True
            return False

    def exists(self, key: str) -> bool:
        data = self.read()
        return isinstance(data, dict) and key in data

    def all_keys(self) -> list[str]:
        data = self.read()
        return list(data.keys()) if isinstance(data, dict) else []

    def all_values(self) -> list[Any]:
        data = self.read()
        return list(data.values()) if isinstance(data, dict) else []

    def all_items(self) -> list[tuple[str, Any]]:
        data = self.read()
        return list(data.items()) if isinstance(data, dict) else []

    def find(self, field: str, value: Any) -> Optional[tuple[str, Any]]:
        for key, item in self.all_items():
            if isinstance(item, dict) and item.get(field) == value:
                return key, item
        return None

    def find_all(self, field: str, value: Any) -> list[tuple[str, Any]]:
        return [
            (key, item)
            for key, item in self.all_items()
            if isinstance(item, dict) and item.get(field) == value
        ]

    def append_to_list(self, key: str, subkey: str, item: Any) -> bool:
        with self._lock:
            data = self._read_raw()
            if isinstance(data, dict) and key in data:
                if isinstance(data[key], dict):
                    if subkey not in data[key] or not isinstance(data[key][subkey], list):
                        data[key][subkey] = []
                    data[key][subkey].append(item)
                    self._write_raw(data)
                    return True
            return False

    def remove_from_list(self, key: str, subkey: str, item: Any) -> bool:
        with self._lock:
            data = self._read_raw()
            if isinstance(data, dict) and key in data:
                if isinstance(data[key], dict) and isinstance(data[key].get(subkey), list):
                    try:
                        data[key][subkey].remove(item)
                        self._write_raw(data)
                        return True
                    except ValueError:
                        return False
            return False

    def count(self) -> int:
        data = self.read()
        return len(data) if isinstance(data, dict) else 0

    def clear(self):
        self.write(self.default if isinstance(self.default, dict) else {})
