"""Collector: query db ZCode read-only + fungsi murni agregasi snapshot."""

import hashlib
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

WORKSPACE_DIRNAME = ".zcode/workspace"

AGENT_NAME_POOL = [
    "Andra", "Bayu", "Citra", "Dewi", "Eka", "Fajar", "Gita", "Hana",
    "Ika", "Jaya", "Kiran", "Luna", "Maya", "Nia", "Oka", "Putri",
    "Rani", "Sari", "Teguh", "Umar", "Vina", "Wulan", "Yoga", "Zaki",
    "Aruna", "Binar", "Cakra", "Damar", "Elang", "Gemilang",
]


def room_name_for_directory(directory: str | None, home: str | None) -> str:
    if not directory:
        return "unknown"
    norm = directory.replace("\\", "/").rstrip("/")
    parts = [p for p in norm.split("/") if p]
    if not parts:
        return "unknown"
    if home:
        home_norm = home.replace("\\", "/").rstrip("/").lower()
        ws = home_norm + "/" + WORKSPACE_DIRNAME
        low = norm.lower()
        if low == ws or low.startswith(ws + "/"):
            return "zcode-workspace"
    return parts[-1]


def format_duration(ms: int | None) -> str:
    if ms is None:
        return "?"
    total_s = int(round(ms / 1000))
    if total_s < 60:
        return f"{total_s}s"
    m, s = divmod(total_s, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def agent_name_for_session(session_id: str, pool: list[str] = AGENT_NAME_POOL,
                           used: frozenset | set = frozenset()) -> str:
    """Nama agent deterministik dari session_id; kalau sudah dipakai, geser ke nama berikutnya."""
    start = int(hashlib.sha1(session_id.encode()).hexdigest(), 16) % len(pool)
    for offset in range(len(pool)):
        name = pool[(start + offset) % len(pool)]
        if name not in used:
            return name
    return pool[start]


ROLE_PREFIX = "zcode-"


def derive_role(models: list) -> str | None:
    """Role agent dari model_usage.agent terakhir yang terisi, tanpa prefix zcode-."""
    for row in sorted(models, key=lambda r: r.get("started_at") or 0, reverse=True):
        raw = row.get("agent")
        if raw:
            return raw[len(ROLE_PREFIX):] if raw.startswith(ROLE_PREFIX) else raw
    return None


def _row_ts(row: dict) -> int | None:
    return row.get("completed_at") or row.get("started_at")


def compute_activity_ts(time_updated: int | None, turns: list, models: list, tools: list) -> int | None:
    candidates = [time_updated] if time_updated is not None else []
    for rows in (turns, models, tools):
        candidates += [ts for ts in (_row_ts(r) for r in rows) if ts is not None]
    return max(candidates) if candidates else None


def is_last_turn_errored(turns: list) -> bool:
    if not turns:
        return False
    last = max(turns, key=lambda r: r.get("started_at") or 0)
    return last.get("error_type") is not None or bool(last.get("cancelled_by_user"))


def derive_status(last_activity_ms: int | None, errored: bool, now_ms: int,
                  working_max_seconds: int, idle_max_seconds: int) -> tuple[str, str]:
    if errored:
        return "error", "error"
    if last_activity_ms is None:
        return "quiet", "diam"
    age_s = max(0, (now_ms - last_activity_ms) // 1000)
    if age_s < working_max_seconds:
        return "kerja", "kerja"
    if age_s <= idle_max_seconds:
        return "idle", f"idle {max(1, age_s // 60)}m"
    if age_s < 3600:
        return "quiet", f"diam {age_s // 60}m"
    return "quiet", f"diam {age_s // 3600}h"


USAGE_STATUS_MAP = {"completed": "ok", "error": "error"}
TOOL_STATUS_MAP = {"completed": "ok", "error": "error"}


def _status_of(raw: str | None) -> str:
    return USAGE_STATUS_MAP.get(raw, "running")


def current_tool_line(tools: list, turns: list) -> str | None:
    if tools:
        last = max(tools, key=lambda r: r.get("started_at") or 0)
        name = last.get("tool_name") or "?"
        if last.get("status") == "running":
            return f"{name} (jalan)"
        return f"{name} ({format_duration(last.get('duration_ms'))})"
    if turns:
        last = max(turns, key=lambda r: r.get("started_at") or 0)
        if last.get("completed_at") is None:
            return "mikir..."
        return "nunggu input"
    return None


def build_agent(session: dict, turns: list, models: list, tools: list, targets: list,
                *, now_ms: int, status_cfg: dict) -> dict:
    turns = sorted(turns, key=lambda r: r.get("started_at") or 0)
    models = sorted(models, key=lambda r: r.get("started_at") or 0)
    tools = sorted(tools, key=lambda r: r.get("started_at") or 0)
    targets = sorted(targets, key=lambda r: r.get("time_updated") or 0)
    target = targets[-1] if targets else None

    activity_ts = compute_activity_ts(session.get("time_updated"), turns, models, tools)
    errored = is_last_turn_errored(turns)
    status, detail = derive_status(
        activity_ts, errored, now_ms,
        status_cfg["working_max_seconds"], status_cfg["idle_max_seconds"],
    )

    per_model: dict = {}
    for m in models:
        mid = m.get("model_id") or "unknown"
        per_model[mid] = per_model.get(mid, 0) + (m.get("computed_total_tokens") or 0)

    return {
        "id": session["id"],
        "title": session.get("title"),
        "name": None,
        "role": derive_role(models),
        "short_name": None,
        "parent_id": session.get("parent_id"),
        "status": status,
        "status_detail": detail,
        "last_activity": activity_ts,
        "current_tool": current_tool_line(tools, turns),
        "model": models[-1].get("model_id") if models else None,
        "tokens": sum(t.get("computed_total_tokens") or 0 for t in turns),
        "tool_calls": len(tools),
        "sparkline": [t.get("output_tokens") or 0 for t in turns[-20:]],
        "objective": target.get("objective") if target else None,
        "target_used": (target.get("tokens_used") or 0) if target else 0,
        "target_budget": (target.get("token_budget") or 0) if target else 0,
        "turns": [
            {"at": t.get("started_at"), "output_tokens": t.get("output_tokens") or 0,
             "status": _status_of(t.get("status")), "turn_id": t.get("turn_id"),
             "user_message_id": t.get("user_message_id")}
            for t in turns[-10:]
        ],
        "tools": [
            {"tool": t.get("tool_name"), "duration_ms": t.get("duration_ms"),
             "status": TOOL_STATUS_MAP.get(t.get("status"), "running"),
             "at": t.get("started_at"), "call_id": t.get("tool_call_id")}
            for t in tools[-10:]
        ],
        "models": per_model,
        "subagents": [],
    }


ACTIVITY_FEED_LIMIT = 30
SPARKLINE_TURNS = 20
PANEL_ROWS = 10


def _sorted_index(rows: list, sort_key: str) -> dict:
    idx: dict = {}
    for r in rows:
        idx.setdefault(r.get("session_id"), []).append(r)
    for lst in idx.values():
        lst.sort(key=lambda r: r.get(sort_key) or 0)
    return idx


def _flatten_agents(agents: list) -> list:
    out = []
    for a in agents:
        out.append(a)
        out.extend(_flatten_agents(a["subagents"]))
    return out


def build_snapshot(sessions, targets, turns, models, tools, *,
                   now_ms: int, midnight_ms: int, home: str,
                   rooms_cfg: dict, status_cfg: dict, db_path: str,
                   errors: list | None = None, partial: bool = False) -> dict:
    ttl_ms = status_cfg["agent_ttl_hours"] * 3_600_000
    session_turns = _sorted_index(turns, "started_at")
    session_models = _sorted_index(models, "started_at")
    session_tools = _sorted_index(tools, "started_at")
    session_targets = _sorted_index(targets, "time_updated")

    activity: dict = {}
    for s in sessions:
        activity[s["id"]] = compute_activity_ts(
            s.get("time_updated"),
            session_turns.get(s["id"], []),
            session_models.get(s["id"], []),
            session_tools.get(s["id"], []),
        )

    visible = [
        s for s in sessions
        if s.get("time_archived") is None
        and activity[s["id"]] is not None
        and activity[s["id"]] >= now_ms - ttl_ms
    ]
    visible_ids = {s["id"] for s in visible}

    grouped: dict = {}
    for s in visible:
        derived = room_name_for_directory(s.get("directory"), home)
        if derived in rooms_cfg.get("hidden", []):
            continue
        display = rooms_cfg.get("rename", {}).get(derived, derived)
        grouped.setdefault(display, []).append(s)

    room_dicts = []
    working_count = 0
    agent_by_id: dict = {}
    used_names: set = set()
    for display, members in grouped.items():
        members = sorted(members, key=lambda s: s.get("time_created") or 0)
        initial = display[:1].upper()
        for i, s in enumerate(members, start=1):
            agent = build_agent(
                s,
                session_turns.get(s["id"], []),
                session_models.get(s["id"], []),
                session_tools.get(s["id"], []),
                session_targets.get(s["id"], []),
                now_ms=now_ms, status_cfg=status_cfg,
            )
            agent["short_name"] = f"{initial}{i}"
            agent["name"] = agent_name_for_session(s["id"], used=used_names)
            used_names.add(agent["name"])
            agent_by_id[s["id"]] = agent

        tops, subs = [], []
        for s in members:
            a = agent_by_id[s["id"]]
            if s.get("parent_id") is not None and s["parent_id"] in visible_ids:
                subs.append(a)
            else:
                tops.append(a)
        for a in subs:
            parent = agent_by_id.get(a["parent_id"])
            if parent is not None:
                parent["subagents"].append(a)
        for top in tops:
            counts: dict = {}
            for sub in top["subagents"]:
                if sub.get("role"):
                    counts[sub["role"]] = counts.get(sub["role"], 0) + 1
            top["sub_roles"] = counts

        everyone = _flatten_agents(tops)
        working_count += sum(1 for a in everyone if a["status"] == "kerja")

        objective, newest_target_at = None, -1
        for s in members:
            for t in session_targets.get(s["id"], []):
                if t.get("objective") and (t.get("time_updated") or 0) >= newest_target_at:
                    newest_target_at = t.get("time_updated") or 0
                    objective = t["objective"]

        newest = max(members, key=lambda s: activity[s["id"]] or 0)
        room_dicts.append({
            "name": display,
            "directory": newest.get("directory"),
            "objective": objective,
            "tokens": sum(a["tokens"] for a in everyone),
            "last_activity": max((a["last_activity"] or 0) for a in everyone),
            "agents": tops,
        })

    room_dicts.sort(key=lambda r: r["last_activity"], reverse=True)
    for r in room_dicts:
        r.pop("last_activity")

    feed = []
    for r in room_dicts:
        for a in _flatten_agents(r["agents"]):
            for t in session_tools.get(a["id"], []):
                feed.append({
                    "room": r["name"],
                    "agent": a["name"] or a["short_name"],
                    "tool": t.get("tool_name"),
                    "status": TOOL_STATUS_MAP.get(t.get("status"), "running"),
                    "duration_ms": t.get("duration_ms"),
                    "at": t.get("started_at"),
                })
    feed.sort(key=lambda r: r["at"] or 0, reverse=True)

    per_model: dict = {}
    for m in models:
        if (m.get("started_at") or 0) >= midnight_ms:
            mid = m.get("model_id") or "unknown"
            per_model[mid] = per_model.get(mid, 0) + (m.get("computed_total_tokens") or 0)

    return {
        "version": 1,
        "generated_at": now_ms,
        "meta": {"db_path": db_path, "partial": partial, "errors": errors or []},
        "rooms": room_dicts,
        "activity": feed[:ACTIVITY_FEED_LIMIT],
        "usage": {
            "today_total": sum(per_model.values()),
            "per_model": per_model,
            "working_count": working_count,
        },
    }


QUERIES = {
    "sessions": (
        "SELECT id, parent_id, directory, title, time_created, time_updated, time_archived "
        "FROM session"
    ),
    "targets": (
        "SELECT session_id, target_id, objective, status, token_budget, tokens_used, "
        "time_created, time_updated FROM session_target ORDER BY time_updated"
    ),
    "turns": (
        "SELECT session_id, turn_id, user_message_id, status, started_at, completed_at, "
        "output_tokens, computed_total_tokens, error_type, cancelled_by_user "
        "FROM turn_usage ORDER BY started_at"
    ),
    "models": (
        "SELECT session_id, model_id, provider_id, agent, started_at, completed_at, "
        "computed_total_tokens, error_type, cancelled_by_user FROM model_usage ORDER BY started_at"
    ),
    "tools": (
        "SELECT session_id, turn_id, tool_call_id, tool_name, status, started_at, completed_at, "
        "duration_ms, error_type, cancelled_by_user FROM tool_usage ORDER BY started_at"
    ),
}


def _local_midnight_ms() -> int:
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * 1000)


def load_snapshot(db_path, config: dict, now_ms: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    db_path = str(db_path)
    errors: list[str] = []
    data: dict[str, list] = {}

    path = Path(db_path)
    con = None
    if not path.exists():
        errors.append(f"db tidak ditemukan: {db_path}")
    else:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        try:
            con = sqlite3.connect(uri, uri=True)
            con.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            errors.append(f"db tidak bisa dibuka: {db_path} ({exc})")

    if con is not None:
        try:
            for name, sql in QUERIES.items():
                try:
                    data[name] = [dict(row) for row in con.execute(sql).fetchall()]
                except sqlite3.Error as exc:
                    errors.append(f"query {name} gagal: {exc}")
        finally:
            con.close()

    return build_snapshot(
        data.get("sessions", []), data.get("targets", []), data.get("turns", []),
        data.get("models", []), data.get("tools", []),
        now_ms=now_ms, midnight_ms=_local_midnight_ms(), home=str(Path.home()),
        rooms_cfg=config["rooms"], status_cfg=config["status"], db_path=db_path,
        errors=errors, partial=bool(errors),
    )


class Collector:
    def __init__(self, db_path, config: dict, interval_seconds: float | None = None):
        self.db_path = db_path
        self.config = config
        self.interval = interval_seconds or config["server"]["poll_interval_seconds"]
        self._snapshot = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def snapshot(self) -> dict | None:
        with self._lock:
            return self._snapshot

    def tick(self) -> None:
        try:
            snap = load_snapshot(self.db_path, self.config)
        except Exception:
            return  # fail soft: pertahankan snapshot terakhir
        with self._lock:
            self._snapshot = snap

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self.tick()
        while not self._stop.wait(self.interval):
            self.tick()
