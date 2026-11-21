#!/usr/bin/env python3
"""Unified OpenCode V2 SQLite telemetry, repo hygiene, and Playwright visual-audit extractor."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
from typing import Any


def discover_db(db_override: str | pathlib.Path | None = None) -> pathlib.Path:
    if db_override:
        return pathlib.Path(db_override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return pathlib.Path(xdg).expanduser() / "opencode" / "opencode.db"
    return pathlib.Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def _classify_pw_action(pw: dict[str, Any], action: str, inp: dict[str, Any] | None = None) -> None:
    pw["total_calls"] += 1
    if "navigate" in action:
        pw["navigate"] += 1
    elif "snapshot" in action:
        pw["snapshot"] += 1
    elif "screenshot" in action:
        pw["screenshot"] += 1
    elif "resize" in action:
        pw["resize"] += 1
        if isinstance(inp, dict) and "width" in inp and "height" in inp:
            pw["viewports"].append(f"{inp.get('width')}x{inp.get('height')}")
    elif "console" in action:
        pw["console"] += 1
    elif any(k in action for k in ("click", "type", "press_key", "fill", "hover", "evaluate", "select")):
        pw["interact"] += 1


def _count_pw_from_code(pw: dict[str, Any], code: str) -> None:
    # Match both direct browser_* calls (e.g., pw.browser_snapshot()) and tools.playwright.<fn>()
    for m in re.finditer(r"(?:\b(browser_\w+)|tools\.playwright\.(\w+))\s*\(", code):
        fn = m.group(1) or m.group(2)
        if fn:
            _classify_pw_action(pw, fn, None)
    for w, h in re.findall(r"width\s*:\s*(\d+)\s*,\s*height\s*:\s*(\d+)", code):
        pw["viewports"].append(f"{w}x{h}")


def _extract_error_message(state: dict[str, Any]) -> str:
    err = state.get("error")
    if isinstance(err, str) and err:
        return err[:160]
    if isinstance(err, dict):
        msg = err.get("message") or json.dumps(err)
        return str(msg)[:160]
    out = state.get("output")
    if isinstance(out, str) and out:
        return out[:160]
    return "tool error"


def inspect_session(
    session_id: str,
    turn_slice: str = "all",
    db_path: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    """Extract opencode.db telemetry + Playwright verification discipline metrics.

    turn_slice: 'all', 'first_user', 'second_user', or 'round:<N>' (1-based).
    """
    resolved_db = discover_db(db_path)
    if not resolved_db.exists():
        return {"error": f"Database not found: {resolved_db}", "session_id": session_id}

    conn = sqlite3.connect(f"file:{resolved_db}?mode=ro", uri=True)
    try:
        srow = conn.execute(
            """SELECT id, agent, model, time_created, time_busy, time_idle, time_updated,
                      tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, cost
               FROM session_v2 WHERE id = ?""",
            (session_id,),
        ).fetchone()

        msgs = conn.execute(
            """SELECT id, type, seq, time_created, time_updated, data
               FROM session_message WHERE session_id = ? ORDER BY seq""",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    if not msgs:
        return {"error": f"No messages for {session_id}", "session_id": session_id}

    # Partition messages by user turns
    rounds: list[list[Any]] = []
    cur: list[Any] = []
    for m in msgs:
        if m[1] == "user" and cur:
            rounds.append(cur)
            cur = []
        cur.append(m)
    if cur:
        rounds.append(cur)

    if turn_slice == "all":
        selected = msgs
    elif turn_slice == "first_user":
        selected = rounds[0] if len(rounds) >= 1 else []
    elif turn_slice == "second_user":
        selected = rounds[1] if len(rounds) >= 2 else []
    elif turn_slice.startswith("round:"):
        try:
            idx = int(turn_slice.split(":", 1)[1])
        except ValueError:
            return {"error": f"Invalid slice '{turn_slice}'", "session_id": session_id}
        selected = rounds[idx - 1] if 1 <= idx <= len(rounds) else []
    else:
        return {"error": f"Unknown slice '{turn_slice}'", "session_id": session_id}

    assistant_turns = 0
    llm_ms = 0
    max_turn_ms = 0
    first_t = None
    last_t = None
    msg_models: set[str] = set()
    sum_input = sum_output = sum_reasoning = sum_cache = 0
    sum_cost = 0.0
    tool_calls = tool_errors = 0
    tool_names: dict[str, int] = {}

    pw: dict[str, Any] = {
        "total_calls": 0,
        "navigate": 0,
        "snapshot": 0,
        "screenshot": 0,
        "resize": 0,
        "console": 0,
        "interact": 0,
        "viewports": [],
        "png_reads": 0,
        "errors": [],
    }

    for _, mtype, _, tc, tu, data_raw in selected:
        if tc and (first_t is None or tc < first_t):
            first_t = tc
        if tu and (last_t is None or tu > last_t):
            last_t = tu
        if mtype == "assistant":
            assistant_turns += 1
            if tc and tu and tu >= tc:
                dur = tu - tc
                llm_ms += dur
                if dur > max_turn_ms:
                    max_turn_ms = dur
            if data_raw:
                d = json.loads(data_raw)
                m = d.get("model") or {}
                if m:
                    msg_models.add(f"{m.get('providerID')}/{m.get('id')}#{m.get('variant')}")
                toks = d.get("tokens") or {}
                sum_input += toks.get("input", 0) or 0
                sum_output += toks.get("output", 0) or 0
                sum_reasoning += toks.get("reasoning", 0) or 0
                cache = toks.get("cache") or {}
                sum_cache += cache.get("read", 0) or 0
                sum_cost += d.get("cost", 0.0) or 0.0

                for item in d.get("content") or []:
                    if isinstance(item, dict) and item.get("type") == "tool":
                        tool_calls += 1
                        tname = item.get("name") or item.get("tool") or "unknown"
                        tool_names[tname] = tool_names.get(tname, 0) + 1
                        state = item.get("state") or {}
                        if state.get("status") == "error" or state.get("error"):
                            tool_errors += 1
                            pw["errors"].append({
                                "tool": tname,
                                "message": _extract_error_message(state),
                            })

                        inp = state.get("input") or item.get("input") or {}
                        if "playwright" in tname or tname.startswith("browser_"):
                            _classify_pw_action(pw, tname, inp if isinstance(inp, dict) else None)
                        elif tname == "execute" and isinstance(inp, dict):
                            code = inp.get("code") or ""
                            if "playwright" in code or "browser_" in code:
                                _count_pw_from_code(pw, code)
                        elif tname == "read" and isinstance(inp, dict):
                            fpath = str(inp.get("path") or inp.get("filePath") or "").lower()
                            if fpath.endswith((".png", ".jpg", ".jpeg", ".webp")):
                                pw["png_reads"] += 1

    wall_ms: int
    if turn_slice == "all" and srow and srow[4] and srow[5] and srow[5] >= srow[4]:
        wall_ms = srow[5] - srow[4]
    elif first_t and last_t and last_t >= first_t:
        wall_ms = last_t - first_t
    else:
        wall_ms = llm_ms

    if turn_slice == "all" and srow:
        tokens_input = sum_input or (srow[7] or 0)
        tokens_output = sum_output or (srow[8] or 0)
        tokens_reasoning = sum_reasoning or (srow[9] or 0)
        tokens_cache_read = sum_cache or (srow[10] or 0)
        cost = round(sum_cost or (srow[11] or 0.0), 4)
    else:
        tokens_input = sum_input
        tokens_output = sum_output
        tokens_reasoning = sum_reasoning
        tokens_cache_read = sum_cache
        cost = round(sum_cost, 4)

    gen_toks = tokens_output + tokens_reasoning
    llm_s = llm_ms / 1000.0
    tps = round(gen_toks / llm_s, 1) if llm_s > 0 else 0.0

    return {
        "session_id": session_id,
        "agent": srow[1] if srow else None,
        "slice": turn_slice,
        "rounds_total": len(rounds),
        "msg_models": sorted(msg_models),
        "wall_s": round(wall_ms / 1000.0, 2),
        "llm_s": round(llm_s, 2),
        "max_turn_s": round(max_turn_ms / 1000.0, 2),
        "tok_s": tps,
        "turns": assistant_turns,
        "tool_calls": tool_calls,
        "tool_errors": tool_errors,
        "tool_names": tool_names,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "tokens_reasoning": tokens_reasoning,
        "tokens_cache_read": tokens_cache_read,
        "cost": cost,
        "playwright": pw,
    }


def repo_hygiene(run_dir: str | pathlib.Path) -> dict[str, Any]:
    run_path = pathlib.Path(run_dir)
    if not run_path.exists():
        return {"error": f"Directory not found: {run_path}"}

    st = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=run_path,
        capture_output=True,
        text=True,
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "--numstat"],
        cwd=run_path,
        capture_output=True,
        text=True,
    ).stdout.strip()

    untracked = [l[3:] for l in st.splitlines() if l.startswith("?? ")]
    stray_artifacts = [
        f for f in untracked if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".pdf"))
    ]
    add = dele = 0
    files = []
    for l in diff.splitlines():
        p = l.split("\t")
        if len(p) == 3:
            add += int(p[0]) if p[0].isdigit() else 0
            dele += int(p[1]) if p[1].isdigit() else 0
            files.append(p[2])
    return {
        "changed_files": files,
        "untracked_files": untracked,
        "stray_screenshots": stray_artifacts,
        "repo_clean": len(stray_artifacts) == 0,
        "additions": add,
        "deletions": dele,
    }


def _load_slice_map(slice_map_arg: str | None) -> dict[str, Any]:
    if not slice_map_arg:
        return {}
    p = pathlib.Path(slice_map_arg)
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return json.loads(slice_map_arg)


def inspect_batch(
    sessions_path: str | pathlib.Path,
    slice_map_arg: str | None = None,
    db_path: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    sessions = json.loads(pathlib.Path(sessions_path).read_text(encoding="utf-8"))
    slice_map = _load_slice_map(slice_map_arg)
    out: dict[str, Any] = {}
    for ch, cfg_map in sessions.items():
        if not isinstance(cfg_map, dict):
            continue
        out[ch] = {}
        ch_slice = slice_map.get(ch)
        for cfg, sid in cfg_map.items():
            sl = "all"
            if isinstance(ch_slice, dict):
                sl = ch_slice.get(cfg, "all")
            elif isinstance(ch_slice, str):
                sl = ch_slice
            elif sid in slice_map and isinstance(slice_map[sid], str):
                sl = slice_map[sid]
            out[ch][cfg] = inspect_session(sid, turn_slice=sl, db_path=db_path)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenCode V2 SQLite telemetry & hygiene tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ses = sub.add_parser("session", help="Inspect a single OpenCode session")
    p_ses.add_argument("session_id", help="Session ID (e.g. ses_...)")
    p_ses.add_argument("--slice", default="all", help="all|first_user|second_user|round:<N>")
    p_ses.add_argument("--db", default=None, help="Path to opencode.db")

    p_hyg = sub.add_parser("hygiene", help="Check git repo hygiene of a run directory")
    p_hyg.add_argument("run_dir", help="Path to git run directory")

    p_bat = sub.add_parser("batch", help="Inspect all sessions in a nested sessions.json")
    p_bat.add_argument("sessions_json", help="Path to {challenge: {config: session_id}} JSON")
    p_bat.add_argument("--slice-map", default=None, help="JSON string or file mapping challenge/config/sid -> slice")
    p_bat.add_argument("--db", default=None, help="Path to opencode.db")

    args = parser.parse_args(argv)
    if args.cmd == "session":
        print(json.dumps(inspect_session(args.session_id, turn_slice=args.slice, db_path=args.db), indent=2))
    elif args.cmd == "hygiene":
        print(json.dumps(repo_hygiene(args.run_dir), indent=2))
    elif args.cmd == "batch":
        print(json.dumps(inspect_batch(args.sessions_json, slice_map_arg=args.slice_map, db_path=args.db), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
