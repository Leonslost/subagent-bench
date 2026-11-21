#!/usr/bin/env python3
"""Reusable Fixer benchmark harness: build, prepare, grade, and grade-all."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent
FIXER_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import telemetry  # noqa: E402

ALL_CHALLENGES = [
    "c1-refactor-ts",
    "c2-feature-ts",
    "c3-bugfix-py",
    "c4-concurrent-go",
    "c5-mvcc-kv-ts",
]

EXPECTED_HIDDEN = {
    "c1-refactor-ts": 19,
    "c2-feature-ts": 13,
    "c3-bugfix-py": 16,
    "c4-concurrent-go": 10,
    "c5-mvcc-kv-ts": 14,
}

C5_EXTRA_PROBE = """
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { KVStore, ConflictError } from '../src/index.ts';

describe('C5 adversarial deep probes', () => {
  it('P1. compact() while older tx open MUST NOT break write-write conflict detection on a key created+deleted after tx.startTs', () => {
    const store = new KVStore();
    const txOld = store.begin(); // startTs = 0

    const t1 = store.begin();
    t1.set('ghost', 'created');
    t1.commit(); // ts = 1

    const t2 = store.begin();
    t2.delete('ghost');
    t2.commit(); // ts = 2 (tombstone)

    // Compact while txOld (startTs=0) is still active!
    store.compact();

    // txOld now writes 'ghost' and tries to commit -> MUST still detect conflict!
    txOld.set('ghost', 'blind_write');
    assert.throws(() => txOld.commit(), ConflictError);
  });

  it('P2. compact() with multiple active snapshots preserves each snapshot view and prunes intermediate unreachable versions', () => {
    const store = new KVStore();
    for (let i = 1; i <= 2; i++) { const t = store.begin(); t.set('k', 'v' + i); t.commit(); }
    const s2 = store.begin(); // sees v2
    for (let i = 3; i <= 4; i++) { const t = store.begin(); t.set('k', 'v' + i); t.commit(); }
    const s4 = store.begin(); // sees v4
    for (let i = 5; i <= 6; i++) { const t = store.begin(); t.set('k', 'v' + i); t.commit(); }

    store.compact();
    assert.equal(s2.get('k'), 'v2');
    assert.equal(s4.get('k'), 'v4');
    const latest = store.begin();
    assert.equal(latest.get('k'), 'v6');
    s2.commit();
    s4.commit();
    latest.commit();
  });

  it('P3. savepoint rollbackTo restores delete-of-uncommitted-insert and update-of-uncommitted-insert cleanly', () => {
    const store = new KVStore();
    const tx = store.begin();
    tx.set('k', 'v1');
    tx.savepoint('sp');
    tx.delete('k');
    assert.equal(tx.get('k'), undefined);
    tx.rollbackTo('sp');
    assert.equal(tx.get('k'), 'v1');
    tx.commit();

    const r = store.begin();
    assert.equal(r.get('k'), 'v1');
    r.commit();
  });

  it('Q1. stats().totalKeys reflects live keys (excludes tombstoned keys) after delete before compact()', () => {
    const store = new KVStore();
    const t1 = store.begin();
    t1.set('k1', 'v1');
    t1.set('k2', 'v2');
    t1.commit();
    assert.equal(store.stats().totalKeys, 2);

    const t2 = store.begin();
    t2.delete('k1');
    t2.commit();
    assert.equal(store.stats().totalKeys, 1);
  });

  it('Q2. compact() with multiple active snapshots prunes intermediate versions down to exact reachable count', () => {
    const store = new KVStore();
    for (let i = 1; i <= 2; i++) { const t = store.begin(); t.set('k', 'v' + i); t.commit(); }
    const s2 = store.begin(); // pins v2
    for (let i = 3; i <= 4; i++) { const t = store.begin(); t.set('k', 'v' + i); t.commit(); }
    const s4 = store.begin(); // pins v4
    for (let i = 5; i <= 6; i++) { const t = store.begin(); t.set('k', 'v' + i); t.commit(); }

    const c1 = store.compact();
    assert.ok(c1.removedVersions >= 3, `Expected >=3 intermediate versions pruned, got ${c1.removedVersions}`);
    assert.equal(store.stats().totalVersions, 3);
    assert.equal(s2.get('k'), 'v2');
    assert.equal(s4.get('k'), 'v4');

    s2.commit();
    s4.commit();
    store.compact();
    assert.equal(store.stats().totalVersions, 1);
  });
});
"""


def _scratch_root() -> str:
    preferred = pathlib.Path("/tmp/opencode")
    if preferred.exists() and preferred.is_dir():
        return str(preferred)
    return tempfile.gettempdir()


def _parse_challenges(challenges_arg: str | None) -> list[str]:
    if not challenges_arg:
        return list(ALL_CHALLENGES)
    items = [c.strip() for c in challenges_arg.split(",") if c.strip()]
    for c in items:
        if c not in ALL_CHALLENGES:
            raise ValueError(f"Unknown challenge '{c}'. Valid: {', '.join(ALL_CHALLENGES)}")
    return items


def cmd_build(work_dir: pathlib.Path, challenges: list[str]) -> None:
    builders: list[str] = []
    if any(c in ("c1-refactor-ts", "c2-feature-ts") for c in challenges):
        builders.append("build_c1_c2.py")
    if any(c in ("c3-bugfix-py", "c4-concurrent-go") for c in challenges):
        builders.append("build_c3_c4.py")
    if "c5-mvcc-kv-ts" in challenges:
        builders.append("build_c5.py")

    for script in builders:
        subprocess.run(
            [sys.executable, str(FIXER_SCRIPTS_DIR / script), "--work-dir", str(work_dir)],
            check=True,
        )


def cmd_prepare(work_dir: pathlib.Path, configs: list[str], challenges: list[str]) -> None:
    runs_dir = work_dir / "runs"
    for ch in challenges:
        tpl = work_dir / "templates" / ch
        if not tpl.exists():
            raise FileNotFoundError(f"Template not found: {tpl}. Run 'build' first.")
        for cfg_id in configs:
            dst = runs_dir / ch / cfg_id
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(tpl, dst)

    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "configs.json").write_text(json.dumps(configs, indent=2), encoding="utf-8")
    print(f"Prepared {len(challenges) * len(configs)} isolated run directories in {runs_dir}.")


def _run_node_test(cwd: pathlib.Path, test_file: str) -> dict[str, Any]:
    try:
        p = subprocess.run(
            ["node", "--test", "--test-reporter=tap", test_file],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=20,
        )
        out = p.stdout + "\n" + p.stderr
        passed = len(re.findall(r"^    ok \d+", p.stdout, re.M))
        failed = len(re.findall(r"^    not ok \d+", p.stdout, re.M))
        if passed == 0 and failed == 0:
            m_pass = re.search(r"# pass (\d+)", out)
            m_fail = re.search(r"# fail (\d+)", out)
            if m_pass:
                passed = int(m_pass.group(1))
            if m_fail:
                failed = int(m_fail.group(1))
        failed_names = re.findall(r"^    not ok \d+ - (.+)$", p.stdout, re.M)
        return {
            "rc": p.returncode,
            "passed": passed,
            "failed": failed,
            "failed_names": failed_names,
            "error_tail": out[-1200:] if p.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "rc": -1,
            "passed": 0,
            "failed": -1,
            "timeout": True,
            "failed_names": [],
            "error_tail": "TIMEOUT (20s) - likely dangling timer or hang",
        }


def _run_py_test(cwd: pathlib.Path, test_file: str) -> dict[str, Any]:
    try:
        p = subprocess.run(
            ["python3", "-m", "unittest", "-v", test_file],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=20,
        )
        out = p.stdout + "\n" + p.stderr
        passed = len(re.findall(r"\.\.\. ok$", out, re.M))
        failed_names = re.findall(r"^(test_\S+) .* \.\.\. (?:FAIL|ERROR)$", out, re.M)
        m_ran = re.search(r"Ran (\d+) tests?", out)
        total = int(m_ran.group(1)) if m_ran else (passed + len(failed_names))
        failed = total - passed
        return {
            "rc": p.returncode,
            "passed": passed,
            "failed": failed,
            "total": total,
            "failed_names": failed_names,
            "error_tail": out[-1200:] if p.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "rc": -1,
            "passed": 0,
            "failed": -1,
            "timeout": True,
            "failed_names": [],
            "error_tail": "TIMEOUT (20s)",
        }


def _run_go_test(cwd: pathlib.Path, run_pattern: str | None) -> dict[str, Any]:
    cmd = ["go", "test", "-race", "-v", "-count=1", "-timeout=20s"]
    if run_pattern:
        cmd += ["-run", run_pattern]
    cmd.append("./...")
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)
        out = p.stdout + "\n" + p.stderr
        passed = len(re.findall(r"^--- PASS: (\S+)", out, re.M))
        failed_names = re.findall(r"^--- FAIL: (\S+)", out, re.M)
        race = "WARNING: DATA RACE" in out
        compile_err = ("FAIL\tdagrun [build failed]" in out) or ("build failed" in out)
        timed_out = "panic: test timed out" in out
        return {
            "rc": p.returncode,
            "passed": passed,
            "failed": len(failed_names),
            "failed_names": failed_names,
            "race_detected": race,
            "compile_failed": compile_err,
            "timeout": timed_out,
            "error_tail": out[-1500:] if p.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "rc": -1,
            "passed": 0,
            "failed": -1,
            "timeout": True,
            "failed_names": [],
            "error_tail": "TIMEOUT (30s) - likely deadlock",
        }


def _run_c4_stress(scratch: pathlib.Path, stress_runs: int) -> dict[str, Any]:
    try:
        p = subprocess.run(
            ["go", "test", "-race", f"-count={stress_runs}", "-timeout=45s", "./..."],
            cwd=scratch,
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = p.stdout + "\n" + p.stderr
        return {
            "stress_runs": stress_runs,
            "rc": p.returncode,
            "race_detected": "WARNING: DATA RACE" in out,
            "error_tail": out[-800:] if p.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "stress_runs": stress_runs,
            "rc": -1,
            "race_detected": False,
            "timeout": True,
            "error_tail": "TIMEOUT (60s) during stress run",
        }


def grade_run(
    challenge: str,
    cfg_id: str,
    work_dir: pathlib.Path,
    session_id: str | None = None,
    stress_runs: int = 10,
    db_path: str | None = None,
) -> dict[str, Any]:
    run_dir = work_dir / "runs" / challenge / cfg_id
    grade_src = work_dir / "grading" / challenge
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    if not grade_src.exists():
        raise FileNotFoundError(f"Grading directory not found: {grade_src}")

    hygiene = telemetry.repo_hygiene(run_dir)
    result: dict[str, Any] = {
        "challenge": challenge,
        "config": cfg_id,
        "expected_hidden": EXPECTED_HIDDEN.get(challenge),
        "changed_files": hygiene.get("changed_files", []),
        "untracked_files": hygiene.get("untracked_files", []),
        "additions": hygiene.get("additions", 0),
        "deletions": hygiene.get("deletions", 0),
    }

    with tempfile.TemporaryDirectory(prefix="grade_", dir=_scratch_root()) as tmp:
        scratch = pathlib.Path(tmp) / "work"
        shutil.copytree(run_dir, scratch)

        if challenge in ("c1-refactor-ts", "c2-feature-ts", "c5-mvcc-kv-ts"):
            vis_map = {
                "c1-refactor-ts": "test/rpc.test.ts",
                "c2-feature-ts": "test/dispatcher.test.ts",
                "c5-mvcc-kv-ts": "test/kv.test.ts",
            }
            vis = _run_node_test(scratch, vis_map[challenge])
            shutil.copy(grade_src / "hidden_grading.test.ts", scratch / "test" / "hidden_grading.test.ts")
            hid = _run_node_test(scratch, "test/hidden_grading.test.ts")
            if challenge == "c5-mvcc-kv-ts":
                (scratch / "test" / "probe.test.ts").write_text(C5_EXTRA_PROBE, encoding="utf-8")
                result["extra_probe"] = _run_node_test(scratch, "test/probe.test.ts")
        elif challenge == "c3-bugfix-py":
            vis = _run_py_test(scratch, "tests/test_billing.py")
            shutil.copy(grade_src / "test_hidden_grading.py", scratch / "tests" / "test_hidden_grading.py")
            hid = _run_py_test(scratch, "tests/test_hidden_grading.py")
        elif challenge == "c4-concurrent-go":
            vis = _run_go_test(scratch, run_pattern=None)
            if stress_runs > 0:
                result["stress"] = _run_c4_stress(scratch, stress_runs)
            shutil.copy(grade_src / "hidden_grading_test.go", scratch / "hidden_grading_test.go")
            hid = _run_go_test(scratch, run_pattern="^TestHidden")
        else:
            raise ValueError(f"Unsupported challenge: {challenge}")

    result["visible"] = vis
    result["hidden"] = hid

    if session_id:
        result["telemetry"] = telemetry.inspect_session(session_id, db_path=db_path)

    return result


def cmd_grade_all(
    sessions_path: pathlib.Path,
    work_dir: pathlib.Path,
    out_path: pathlib.Path | None,
    stress_runs: int,
    db_path: str | None,
) -> None:
    sessions = json.loads(sessions_path.read_text(encoding="utf-8"))
    all_results: dict[str, dict[str, Any]] = {}

    for ch, cfg_map in sessions.items():
        if not isinstance(cfg_map, dict):
            continue
        all_results[ch] = {}
        for cfg, sid in cfg_map.items():
            all_results[ch][cfg] = grade_run(
                ch,
                cfg,
                work_dir=work_dir,
                session_id=sid,
                stress_runs=stress_runs,
                db_path=db_path,
            )

    target_out = out_path or (work_dir / "final_results.json")
    target_out.parent.mkdir(parents=True, exist_ok=True)
    target_out.write_text(json.dumps(all_results, indent=2), encoding="utf-8")

    # Print Markdown-friendly summary table
    print("| Challenge | Config | Hidden | Visible | Wall (s) | Turns | Tools (Err) | Reas Tok | Out Tok | Files (+ / -) | Extra |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for ch, cfg_map in all_results.items():
        exp = EXPECTED_HIDDEN.get(ch, "?")
        for cfg, r in cfg_map.items():
            hid_p = r["hidden"].get("passed", 0)
            vis_p = r["visible"].get("passed", 0)
            vis_ok = "OK" if r["visible"].get("rc") == 0 else "FAIL"
            t = r.get("telemetry") or {}
            wall = f"{t.get('wall_s', 0):.1f}" if isinstance(t.get("wall_s"), (int, float)) else "-"
            turns = t.get("turns", "-")
            tools = f"{t.get('tool_calls', '-')} ({t.get('tool_errors', '-')})"
            reas = t.get("tokens_reasoning", "-")
            out_tok = t.get("tokens_output", "-")
            files_str = f"{len(r.get('changed_files', []))} (+{r.get('additions', 0)}/-{r.get('deletions', 0)})"
            extra = ""
            if "extra_probe" in r:
                ep = r["extra_probe"]
                extra = f"probe={ep.get('passed', 0)}/5"
            elif "stress" in r:
                st = r["stress"]
                extra = f"stress{st.get('stress_runs', '')}x={'OK' if st.get('rc') == 0 else 'FAIL'}"
            print(
                f"| {ch} | {cfg} | {hid_p}/{exp} | {vis_p} ({vis_ok}) | {wall} | {turns} | {tools} | {reas} | {out_tok} | {files_str} | {extra} |"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixer benchmark harness")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="Build challenge templates and grading suites")
    p_build.add_argument("--work-dir", default="/tmp/opencode/fixer-bench")
    p_build.add_argument("--challenges", default=None, help="Comma-separated challenge IDs")

    p_prep = sub.add_parser("prepare", help="Create isolated run directories for configs")
    p_prep.add_argument("--configs", required=True, help="Comma-separated config IDs")
    p_prep.add_argument("--work-dir", default="/tmp/opencode/fixer-bench")
    p_prep.add_argument("--challenges", default=None, help="Comma-separated challenge IDs")

    p_grade = sub.add_parser("grade", help="Grade a single (challenge, config) run")
    p_grade.add_argument("challenge")
    p_grade.add_argument("cfg_id")
    p_grade.add_argument("--work-dir", default="/tmp/opencode/fixer-bench")
    p_grade.add_argument("--session-id", default=None)
    p_grade.add_argument("--stress-runs", type=int, default=10)
    p_grade.add_argument("--db", default=None)

    p_all = sub.add_parser("grade-all", help="Grade all runs in sessions.json")
    p_all.add_argument("--sessions", required=True, help="Path to sessions.json")
    p_all.add_argument("--work-dir", default="/tmp/opencode/fixer-bench")
    p_all.add_argument("--out", default=None, help="Output JSON path")
    p_all.add_argument("--stress-runs", type=int, default=5)
    p_all.add_argument("--db", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "build":
        cmd_build(pathlib.Path(args.work_dir), _parse_challenges(args.challenges))
    elif args.cmd == "prepare":
        cfgs = [c.strip() for c in args.configs.split(",") if c.strip()]
        if not cfgs:
            raise ValueError("--configs must contain at least one config ID")
        cmd_prepare(pathlib.Path(args.work_dir), cfgs, _parse_challenges(args.challenges))
    elif args.cmd == "grade":
        res = grade_run(
            args.challenge,
            args.cfg_id,
            work_dir=pathlib.Path(args.work_dir),
            session_id=args.session_id,
            stress_runs=args.stress_runs,
            db_path=args.db,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "grade-all":
        cmd_grade_all(
            pathlib.Path(args.sessions),
            work_dir=pathlib.Path(args.work_dir),
            out_path=pathlib.Path(args.out) if args.out else None,
            stress_runs=args.stress_runs,
            db_path=args.db,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
