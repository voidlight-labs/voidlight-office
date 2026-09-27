"""On-demand konten turn & tool call: dibaca dari tabel message/part saat di-click."""

import json
import sqlite3
from pathlib import Path

CONTENT_CHAR_CAP = 5_000
TURN_MAX_MESSAGES = 20


def _open_readonly(db_path) -> sqlite3.Connection | None:
    path = Path(str(db_path))
    if not path.exists():
        return None
    uri = f"{path.resolve().as_uri()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _trim_text(value) -> dict | None:
    if value is None:
        return None
    text = str(value)
    return {"content": text[:CONTENT_CHAR_CAP], "truncated": len(text) > CONTENT_CHAR_CAP,
            "total_chars": len(text)}


def _trim_json(value) -> dict | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _trim_text(value)
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return {"content": text[:CONTENT_CHAR_CAP], "truncated": len(text) > CONTENT_CHAR_CAP,
            "total_chars": len(text)}


def tool_content(db_path, call_id: str) -> dict | None:
    """Isi input/output satu tool call, dari part dengan callID yang cocok."""
    if not call_id:
        return None
    try:
        con = _open_readonly(db_path)
        if con is None:
            return {"error": f"db tidak ditemukan: {db_path}"}
        try:
            row = con.execute(
                "SELECT data FROM part WHERE json_extract(data, '$.callID') = ? "
                "ORDER BY time_created DESC LIMIT 1",
                (call_id,),
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return {"error": f"konten tool tidak tersedia: {exc}"}
    if row is None:
        return None
    data = json.loads(row["data"])
    state = data.get("state", {})
    return {
        "kind": "tool",
        "call_id": call_id,
        "tool": data.get("tool"),
        "status": state.get("status"),
        "input": _trim_json(state.get("input")),
        "output": _trim_text(state.get("output")),
    }


def turn_content(db_path, turn_id: str) -> dict | None:
    """Isi satu turn: pesan user pembuka + rantai message assistant sampai turn berikutnya."""
    if not turn_id:
        return None
    try:
        con = _open_readonly(db_path)
        if con is None:
            return {"error": f"db tidak ditemukan: {db_path}"}
        try:
            trow = con.execute(
                "SELECT session_id, user_message_id FROM turn_usage WHERE turn_id = ? LIMIT 1",
                (turn_id,),
            ).fetchone()
            if trow is None:
                return None
            messages = con.execute(
                "SELECT id, data FROM message WHERE session_id = ?", (trow["session_id"],)
            ).fetchall()
            parts = con.execute(
                "SELECT message_id, data FROM part WHERE session_id = ? ORDER BY sequence",
                (trow["session_id"],),
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return {"error": f"konten turn tidak tersedia: {exc}"}

    by_id = {}
    children: dict[str, list] = {}
    for m in messages:
        data = json.loads(m["data"])
        by_id[m["id"]] = data
        parent = data.get("parentID")
        if parent:
            children.setdefault(parent, []).append(m["id"])

    parts_by_message: dict[str, list] = {}
    for p in parts:
        parts_by_message.setdefault(p["message_id"], []).append(json.loads(p["data"]))

    entries: list[dict] = []
    truncated_parts = False
    current_id: str | None = trow["user_message_id"]
    visited = 0
    while current_id and visited < TURN_MAX_MESSAGES:
        visited += 1
        msg = by_id.get(current_id)
        if msg is None:
            break
        role = msg.get("role")
        if current_id != trow["user_message_id"] and role == "user":
            break  # turn berikutnya mulai
        for part in parts_by_message.get(current_id, []):
            ptype = part.get("type")
            if ptype == "text":
                trimmed = _trim_text(part.get("text"))
                if trimmed:
                    entries.append({"kind": "text", "role": role,
                                    "content": trimmed["content"],
                                    "truncated": trimmed["truncated"]})
                    truncated_parts = truncated_parts or trimmed["truncated"]
            elif ptype == "reasoning":
                trimmed = _trim_text(part.get("text"))
                if trimmed:
                    entries.append({"kind": "reasoning", "content": trimmed["content"],
                                    "truncated": trimmed["truncated"]})
                    truncated_parts = truncated_parts or trimmed["truncated"]
            elif ptype == "tool":
                state = part.get("state", {})
                entries.append({
                    "kind": "tool",
                    "tool": part.get("tool"),
                    "status": state.get("status"),
                    "input": _trim_json(state.get("input")),
                    "output": _trim_text(state.get("output")),
                })
        kids = children.get(current_id) or []
        current_id = kids[0] if kids else None

    return {"kind": "turn", "turn_id": turn_id, "entries": entries,
            "truncated_parts": truncated_parts}
