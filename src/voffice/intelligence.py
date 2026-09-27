"""Token intelligence: ranking session/turn/tool paling boros + breakdown penyebab bengkak."""

import sqlite3
import time
from datetime import datetime
from pathlib import Path

from voffice.collector import agent_name_for_session, room_name_for_directory
from voffice.content import _open_readonly

INTELLIGENCE_LIMIT = 10

SESSIONS_SQL = """
SELECT tu.session_id AS session_id, s.title AS title, s.directory AS directory,
       SUM(tu.computed_total_tokens) AS total,
       SUM(tu.input_tokens) AS input_tokens,
       SUM(tu.output_tokens) AS output_tokens,
       SUM(tu.cache_creation_input_tokens) AS cache_creation,
       SUM(tu.cache_read_input_tokens) AS cache_read,
       COUNT(*) AS turns
FROM turn_usage tu LEFT JOIN session s ON s.id = tu.session_id
{where}
GROUP BY tu.session_id
ORDER BY total DESC
LIMIT {limit}
"""

TURNS_SQL = """
SELECT tu.session_id AS session_id, tu.turn_id AS turn_id, tu.started_at AS started_at,
       tu.computed_total_tokens AS total,
       tu.input_tokens AS input_tokens,
       tu.output_tokens AS output_tokens,
       tu.cache_creation_input_tokens AS cache_creation,
       tu.cache_read_input_tokens AS cache_read,
       tu.tool_call_count AS tool_calls,
       tu.duration_ms AS duration_ms
FROM turn_usage tu
{where}
ORDER BY tu.computed_total_tokens DESC
LIMIT {limit}
"""

TOOLS_SQL = """
SELECT session_id AS session_id, turn_id AS turn_id, tool_name AS tool,
       COALESCE(output_bytes, 0) AS output_bytes,
       COALESCE(stdout_bytes, 0) AS stdout_bytes,
       COALESCE(stderr_bytes, 0) AS stderr_bytes,
       COALESCE(duration_ms, 0) AS duration_ms
FROM tool_usage
{where}
"""

TURN_TOKENS_SQL = """
SELECT session_id AS session_id, turn_id AS turn_id,
       computed_total_tokens AS total, tool_call_count AS tool_calls
FROM turn_usage
{where}
"""


def _where(scope: str, now_ms: int) -> str:
    if scope != "today":
        return ""
    midnight = int(datetime.fromtimestamp(now_ms / 1000)
                   .replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    return f"WHERE started_at >= {midnight}"


def _g(row: dict, *keys):
    """Ambil nilai pertama yang ada di antara alias kolom (row SQL vs row fixture)."""
    for k in keys:
        v = row.get(k)
        if v is not None:
            return v
    return 0


def build_intelligence(session_rows, turn_rows, tool_rows, turn_token_rows, *,
                       scope: str, home: str, limit: int = INTELLIGENCE_LIMIT,
                       errors=None) -> dict:
    session_out = []
    for r in sorted(session_rows, key=lambda r: _g(r, "total"), reverse=True)[:limit]:
        sid = r.get("session_id") or r.get("id")
        session_out.append({
            "id": sid,
            "name": agent_name_for_session(sid),
            "room": room_name_for_directory(r["directory"], home),
            "title": r["title"],
            "total": _g(r, "total"),
            "input": _g(r, "input_tokens"),
            "output": _g(r, "output_tokens"),
            "cache_creation": _g(r, "cache_creation"),
            "cache_read": _g(r, "cache_read"),
            "turns": _g(r, "turns"),
        })

    max_total = max((r["total"] or 0 for r in session_out), default=0)
    for r in session_out:
        r["share"] = round(r["total"] / max_total * 100) if max_total else 0

    ranked_turns = sorted(turn_rows,
                          key=lambda r: _g(r, "total", "computed_total_tokens"),
                          reverse=True)
    turns_out = [{
        "session_id": r["session_id"],
        "name": agent_name_for_session(r["session_id"]),
        "turn_id": r["turn_id"],
        "at": r.get("started_at"),
        "total": _g(r, "total", "computed_total_tokens"),
        "input": _g(r, "input_tokens"),
        "output": _g(r, "output_tokens"),
        "cache_creation": _g(r, "cache_creation", "cache_creation_input_tokens"),
        "cache_read": _g(r, "cache_read", "cache_read_input_tokens"),
        "tool_calls": _g(r, "tool_calls", "tool_call_count"),
        "duration_ms": r.get("duration_ms"),
    } for r in ranked_turns[:limit]]

    # normalisasi tool rows (alias SQL `tool` vs fixture `tool_name`)
    norm = [{
        "session_id": tl.get("session_id"),
        "turn_id": tl.get("turn_id"),
        "tool": tl.get("tool") or tl.get("tool_name"),
        "bytes": ((tl.get("output_bytes") or 0) + (tl.get("stdout_bytes") or 0)
                  + (tl.get("stderr_bytes") or 0)),
        "duration_ms": tl.get("duration_ms") or 0,
    } for tl in tool_rows]

    # agregasi per tool + estimasi token: token turn dibagi rata ke tool call di turn itu
    agg: dict = {}
    tools_by_turn: dict = {}
    for tl in norm:
        a = agg.setdefault(tl["tool"], {"tool": tl["tool"], "calls": 0, "output_bytes": 0,
                                        "duration_ms": 0})
        a["calls"] += 1
        a["output_bytes"] += tl["bytes"]
        a["duration_ms"] += tl["duration_ms"]
        tools_by_turn.setdefault((tl["session_id"], tl["turn_id"]), []).append(tl)
    est: dict = {}
    for sid, tid, total, calls in turn_token_rows:
        rows = tools_by_turn.get((sid, tid)) or []
        n = len(rows) or calls or 0
        if n <= 0:
            continue
        share = (total or 0) / n
        for tl in rows:
            est[tl["tool"]] = est.get(tl["tool"], 0) + share

    ranked_tools = sorted(agg.values(), key=lambda r: r["output_bytes"], reverse=True)
    max_bytes = max((r["output_bytes"] for r in ranked_tools), default=0)
    tools_out = []
    for r in ranked_tools[:limit]:
        tools_out.append({
            "tool": r["tool"],
            "calls": r["calls"],
            "output_bytes": r["output_bytes"],
            "duration_ms": r["duration_ms"],
            "est_tokens": int(est.get(r["tool"], 0)),
            "share": round(r["output_bytes"] / max_bytes * 100) if max_bytes else 0,
        })

    return {
        "kind": "intelligence",
        "scope": scope,
        "limit": limit,
        "partial": bool(errors),
        "errors": errors or [],
        "sessions": session_out,
        "turns": turns_out,
        "tools": tools_out,
    }


def intelligence_report(db_path, scope: str = "all", now_ms: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    scope = scope if scope in ("all", "today") else "all"
    where = _where(scope, now_ms)
    errors: list[str] = []
    data: dict[str, list] = {}

    path = Path(str(db_path))
    con = None
    if not path.exists():
        errors.append(f"db tidak ditemukan: {db_path}")
    else:
        try:
            con = _open_readonly(db_path)
        except sqlite3.Error as exc:
            errors.append(f"db tidak bisa dibuka: {db_path} ({exc})")

    if con is not None:
        queries = {
            "sessions": SESSIONS_SQL.format(where=where, limit=INTELLIGENCE_LIMIT),
            "turns": TURNS_SQL.format(where=where, limit=INTELLIGENCE_LIMIT),
            "tools": TOOLS_SQL.format(where=where),
            "turn_tokens": TURN_TOKENS_SQL.format(where=where),
        }
        try:
            for name, sql in queries.items():
                try:
                    data[name] = [dict(row) for row in con.execute(sql).fetchall()]
                except sqlite3.Error as exc:
                    errors.append(f"query {name} gagal: {exc}")
        finally:
            con.close()

    return build_intelligence(
        data.get("sessions", []), data.get("turns", []), data.get("tools", []),
        [(r["session_id"], r["turn_id"], r["total"], r["tool_calls"])
         for r in data.get("turn_tokens", [])],
        scope=scope, home=str(Path.home()), errors=errors,
    )
