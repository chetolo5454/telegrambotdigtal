"""
Data Storage & Persistence for Case Tracker.
Manages client names, case snapshots, detected changes, audit history, and configuration.
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

NAMES_FILE = os.path.join(DATA_DIR, "client_names.json")
SNAPSHOT_FILE = os.path.join(DATA_DIR, "snapshot.json")
CHANGES_FILE = os.path.join(DATA_DIR, "changes.json")
AUDIT_FILE = os.path.join(DATA_DIR, "audit_log.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def _read_json(path: str, default: Any = None) -> Any:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default if default is not None else {}
    return default if default is not None else {}


def _write_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[خطأ في حفظ {os.path.basename(path)}]: {e}")


class StorageManager:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    # ------------------ أسماء الموكلين (Client Names) ------------------
    def get_names(self) -> Dict[str, str]:
        return _read_json(NAMES_FILE, default={})

    def set_name(self, request_number: str, name: str) -> Dict[str, str]:
        names = self.get_names()
        req_num = str(request_number).strip()
        val = str(name or "").strip()
        if val:
            names[req_num] = val
        else:
            names.pop(req_num, None)
        _write_json(NAMES_FILE, names)
        return names

    def delete_name(self, request_number: str) -> Dict[str, str]:
        return self.set_name(request_number, "")

    def backup_names(self, export_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Exports names in JSON format compatible with the browser extension.
        """
        names = self.get_names()
        data = {
            "type": "case-names",
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "count": len(names),
            "names": names
        }
        if export_path:
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        return data

    def restore_names(self, source: Union[str, Dict[str, Any]]) -> int:
        """
        Restores names from either a file path or a dictionary.
        """
        if isinstance(source, str):
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = source

        if not isinstance(data, dict):
            raise ValueError("الملف غير صالح (ليس كائن JSON)")

        imported = data.get("names", {})
        if not isinstance(imported, dict):
            raise ValueError("لا توجد قائمة أسماء صالحة داخل الملف")

        current = self.get_names()
        count = 0
        for k, v in imported.items():
            if v and isinstance(v, str):
                current[str(k).strip()] = v.strip()
                count += 1

        _write_json(NAMES_FILE, current)
        return count

    # ------------------ اللقطة والتغييرات (Snapshot & Changes) ------------------
    def get_snapshot(self) -> Optional[Dict[str, Any]]:
        return _read_json(SNAPSHOT_FILE, default=None)

    def save_snapshot(self, snapshot: Dict[str, Any]):
        _write_json(SNAPSHOT_FILE, snapshot)

    def get_changes(self) -> Dict[str, Any]:
        return _read_json(CHANGES_FILE, default={})

    def save_changes(self, changes: Dict[str, Any]):
        _write_json(CHANGES_FILE, changes)

    def acknowledge_changes(self):
        _write_json(CHANGES_FILE, {})

    # ------------------ سجل التدقيق (Audit Log) ------------------
    def get_audit_log(self, request_number: Optional[str] = None) -> List[Dict[str, Any]]:
        entries = _read_json(AUDIT_FILE, default=[])
        if request_number:
            req_str = str(request_number).strip()
            return [e for e in entries if str(e.get("requestNumber")) == req_str]
        return entries

    def log_audit_entries(self, new_entries: List[Dict[str, Any]], max_entries: int = 5000):
        if not new_entries:
            return
        entries = self.get_audit_log()
        entries.extend(new_entries)
        # Keep last N entries
        if len(entries) > max_entries:
            entries = entries[-max_entries:]
        _write_json(AUDIT_FILE, entries)

    # ------------------ الإعدادات (Settings) ------------------
    def get_settings(self) -> Dict[str, Any]:
        defaults = {
            "auto_refresh_minutes": 10,
            "filter": "fees",
            "civil_only": True,
            "enable_notifications": True
        }
        loaded = _read_json(SETTINGS_FILE, default={})
        defaults.update(loaded)
        return defaults

    def update_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        settings = self.get_settings()
        settings.update(updates)
        _write_json(SETTINGS_FILE, settings)
        return settings
