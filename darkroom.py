import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from identity import identity_names


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _now_iso() -> str:
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def _clamp_completeness(value: float | int | str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return max(0.0, min(1.0, number))


def _split_tags(tags: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        raw = tags.split(",")
    else:
        raw = [str(item) for item in tags]
    clean: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = item.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        clean.append(tag[:40])
    return clean[:12]


def _normalize_mode(value: str | None) -> str:
    mode = str(value or "continue").strip().lower()
    if mode not in {"continue", "single"}:
        raise ValueError("invalid mode")
    return mode


def _normalize_visibility(value: str | None) -> str:
    visibility = str(value or "active").strip().lower()
    if visibility not in {"active", "archived", "retracted"}:
        raise ValueError("invalid visibility")
    return visibility


class DarkroomStore:
    """Private reflection storage: public status, private notes."""

    def __init__(self, config: dict):
        self.config = config
        state_dir = config.get("state_dir") or os.path.join(
            os.path.dirname(os.path.abspath(config.get("buckets_dir", "buckets"))),
            "state",
        )
        self.base_dir = Path(state_dir) / "darkroom"
        self.entries_path = self.base_dir / "entries.jsonl"
        self.release_log_path = self.base_dir / "releases.jsonl"
        self.state_path = self.base_dir / "state.json"
        self._lock = Lock()

    def enter(
        self,
        note: str,
        *,
        completeness: float | int | str | None = None,
        mood: str = "",
        tags: str | list[str] | tuple[str, ...] | None = None,
        source: str = "mcp",
        mode: str = "continue",
        visibility: str = "active",
    ) -> dict:
        text = str(note or "").strip()
        if not text:
            raise ValueError("note is empty")
        if len(text) > 12000:
            raise ValueError("note is too long")
        mode_key = _normalize_mode(mode)
        visibility_key = _normalize_visibility(visibility)

        with self._lock:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            previous = self._last_entry_unlocked()
            previous_completeness = previous.get("completeness") if previous else None
            state = self._status_unlocked()
            continuation_anchor = self._continuation_anchor_unlocked(mode_key)
            entry = {
                "id": self._new_entry_id(),
                "created_at": _now_iso(),
                "note": text,
                "mode": mode_key,
                "completeness": _clamp_completeness(completeness),
                "previous_entry_id": previous.get("id") if previous else "",
                "previous_completeness": previous_completeness,
                "continuation_anchor": continuation_anchor,
                "mood": str(mood or "").strip()[:80],
                "tags": _split_tags(tags),
                "source": str(source or "mcp").strip()[:80],
                "visibility": visibility_key,
            }
            self._append_jsonl_unlocked(self.entries_path, entry)
            state = self._active_state_unlocked(base_state=state)
            if not state.get("created_at"):
                state["created_at"] = entry["created_at"]
            self._write_json_unlocked(self.state_path, state)
            return self._public_enter_payload(entry, state)

    def status(self) -> dict:
        with self._lock:
            return self._status_unlocked()

    def release(self, entry_id: str = "latest", *, reason: str = "") -> dict:
        with self._lock:
            entry = self._find_entry_unlocked(entry_id)
            if not entry:
                raise KeyError("entry not found")
            release = {
                "id": f"rel_{secrets.token_hex(6)}",
                "entry_id": entry["id"],
                "created_at": _now_iso(),
                "reason": str(reason or "").strip()[:200],
            }
            self._append_jsonl_unlocked(self.release_log_path, release)
            state = self._status_unlocked()
            state["updated_at"] = release["created_at"]
            state["last_release_at"] = release["created_at"]
            state["released_count"] = int(state.get("released_count") or 0) + 1
            self._write_json_unlocked(self.state_path, state)
            return {
                "status": "released",
                "entry_id": entry["id"],
                "created_at": entry.get("created_at", ""),
                "completeness": entry.get("completeness"),
                "mood": entry.get("mood", ""),
                "tags": entry.get("tags", []),
                "content": entry.get("note", ""),
            }

    def _new_entry_id(self) -> str:
        return f"dr_{datetime.now(LOCAL_TZ).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"

    def _ai_name(self) -> str:
        return identity_names(self.config).get("ai_name") or "AI"

    def _door_text(self) -> str:
        return f"暗房存在。钥匙只给 {self._ai_name()}；门口只显示状态，不显示未显影正文。"

    def _public_enter_payload(self, entry: dict, state: dict) -> dict:
        ai_name = self._ai_name()
        return {
            "status": "entered",
            "entry_id": entry["id"],
            "entered_at": entry["created_at"],
            "mode": entry.get("mode", "continue"),
            "visibility": entry.get("visibility", "active"),
            "count": state.get("count", 0),
            "previous_entry_id": entry.get("previous_entry_id", ""),
            "continuation_anchor_entries": len(entry.get("continuation_anchor", {}).get("entry_ids", [])),
            "completeness": {
                "previous": entry.get("previous_completeness"),
                "current": entry.get("completeness"),
            },
            "mood": entry.get("mood", ""),
            "tags": entry.get("tags", []),
            "visible_note": f"{ai_name} 进入了暗房。",
        }

    def _status_unlocked(self) -> dict:
        stored_state: dict = {}
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    stored_state = data
            except (OSError, json.JSONDecodeError):
                pass
        return self._public_status(self._active_state_unlocked(base_state=stored_state))

    def _active_state_unlocked(self, *, base_state: dict | None = None) -> dict:
        base_state = base_state or {}
        count = 0
        last: dict | None = None
        for entry in self._iter_entries_unlocked(visibility="active"):
            count += 1
            last = entry
        last_active_at = last.get("created_at", "") if last else ""
        last_release_at = str(base_state.get("last_release_at") or "")
        state = {
            "version": 1,
            "created_at": str(base_state.get("created_at") or ""),
            "updated_at": max([item for item in [last_active_at, last_release_at] if item], default=""),
            "count": count,
            "last_entry_id": last.get("id", "") if last else "",
            "last_entered_at": last_active_at,
            "last_completeness": last.get("completeness") if last else None,
            "previous_completeness": last.get("previous_completeness") if last else None,
            "last_mood": last.get("mood", "") if last else "",
            "last_tags": last.get("tags", []) if last else [],
            "last_release_at": last_release_at,
            "released_count": int(base_state.get("released_count") or 0),
        }
        return state

    def _public_status(self, state: dict) -> dict:
        return {
            "status": "ok",
            "door": self._door_text(),
            "version": int(state.get("version") or 1),
            "created_at": str(state.get("created_at") or ""),
            "updated_at": str(state.get("updated_at") or ""),
            "count": int(state.get("count") or 0),
            "last_entry_id": str(state.get("last_entry_id") or ""),
            "last_entered_at": str(state.get("last_entered_at") or ""),
            "last_completeness": state.get("last_completeness"),
            "previous_completeness": state.get("previous_completeness"),
            "last_mood": str(state.get("last_mood") or ""),
            "last_tags": state.get("last_tags") if isinstance(state.get("last_tags"), list) else [],
            "last_release_at": str(state.get("last_release_at") or ""),
            "released_count": int(state.get("released_count") or 0),
        }

    def _last_entry_unlocked(self, *, visibility: str = "active") -> dict | None:
        last = None
        for entry in self._iter_entries_unlocked(visibility=visibility):
            last = entry
        return last

    def _recent_entries_unlocked(self, limit: int = 3, *, visibility: str = "active") -> list[dict]:
        recent: list[dict] = []
        for entry in self._iter_entries_unlocked(visibility=visibility):
            recent.append(entry)
            if len(recent) > limit:
                recent.pop(0)
        return recent

    def _continuation_anchor_unlocked(self, mode: str) -> dict:
        if mode != "continue":
            return {}
        recent = self._recent_entries_unlocked(limit=3)
        if not recent:
            return {}
        return {
            "kind": "local_continuation",
            "generated_at": _now_iso(),
            "entry_ids": [str(entry.get("id") or "") for entry in recent if entry.get("id")],
            "last_completeness": recent[-1].get("completeness"),
            "notes": [
                {
                    "created_at": str(entry.get("created_at") or ""),
                    "note": str(entry.get("note") or "")[:600],
                }
                for entry in recent
            ],
        }

    def _find_entry_unlocked(self, entry_id: str) -> dict | None:
        target = str(entry_id or "latest").strip()
        if target in {"", "latest"}:
            return self._last_entry_unlocked()
        for entry in self._iter_entries_unlocked(visibility="active"):
            if entry.get("id") == target:
                return entry
        return None

    def _iter_entries_unlocked(self, *, visibility: str | None = None):
        if not self.entries_path.exists():
            return
        with self.entries_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    if visibility is not None and str(data.get("visibility") or "active") != visibility:
                        continue
                    yield data

    def _append_jsonl_unlocked(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _write_json_unlocked(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)
