#!/usr/bin/env python3
import argparse
import base64
import concurrent.futures
import importlib.util
import json
import mimetypes
import pathlib
import random
import shutil
import subprocess
import sys
import urllib.parse

CHALLENGE_SPECS = [
    {
        "id": "d1-bughunt",
        "short": "D1 · Bug Hunt",
        "title": "PulseGrid Billing & Usage",
        "subtitle": "8 planted CSS/JS/a11y bugs fixed + unprompted visual polish",
        "turn_slice": "all",
        "views": [
            {"id": "desktop", "label": "Desktop 1280", "file": "desktop-1280.png"},
            {"id": "tablet", "label": "Tablet 768", "file": "tablet-768.png"},
            {"id": "mobile", "label": "Mobile 375", "file": "mobile-375.png"},
            {"id": "drawer", "label": "Drawer 1280", "file": "drawer-1280.png"},
        ],
    },
    {
        "id": "d2-greenfield",
        "short": "D2 · Greenfield",
        "title": "Kestrel F2 Product Showcase",
        "subtitle": "Machined 6061-T6 32-bit float field recorder marketing & configurator page",
        "turn_slice": "first_user",
        "views": [
            {"id": "desktop", "label": "Desktop 1280", "file": "desktop-1280.png"},
            {"id": "tablet", "label": "Tablet 768", "file": "tablet-768.png"},
            {"id": "mobile", "label": "Mobile 375", "file": "mobile-375.png"},
        ],
    },
    {
        "id": "d4-nudge",
        "short": "D4 · Follow-Up Nudge",
        "title": "Kestrel F2 Critique Pass",
        "subtitle": "Hero breathing room + spec strip + mobile bottom sheet + Studio Light / Night Field theme toggle",
        "turn_slice": "second_user",
        "views": [
            {"id": "default", "label": "Default Theme 1280", "file": "desktop-default-1280.png"},
            {"id": "alt", "label": "Alt Theme 1280", "file": "desktop-alt-theme-1280.png"},
            {"id": "mobile", "label": "Mobile 375", "file": "mobile-375.png"},
            {"id": "nav", "label": "Mobile Sheet 375", "file": "mobile-nav-375.png"},
        ],
    },
    {
        "id": "d3-interactive",
        "short": "D3 · Interactive App",
        "title": "TraceDeck Triage Workspace",
        "subtitle": "Keyboard-first incident triage, multi-facet filters, Ctrl+K command palette, split pane → mobile drawer",
        "turn_slice": "all",
        "views": [
            {"id": "desktop", "label": "Desktop 1280", "file": "desktop-1280.png"},
            {"id": "palette", "label": "Cmd Palette 1280", "file": "palette-1280.png"},
            {"id": "tablet", "label": "Tablet 768", "file": "tablet-768.png"},
            {"id": "mobile", "label": "Mobile 375", "file": "mobile-375.png"},
            {"id": "drawer", "label": "Mobile Drawer 375", "file": "mobile-drawer-375.png"},
        ],
    },
]


def blind_label_for_index(idx: int) -> str:
    if idx < 26:
        return f"Model {chr(65 + idx)}"
    first = chr(65 + (idx // 26) - 1)
    second = chr(65 + (idx % 26))
    return f"Model {first}{second}"


def load_telemetry_fn(work_dir: pathlib.Path):
    candidates = [
        pathlib.Path(__file__).resolve().parent.parent / "telemetry.py",
        pathlib.Path(__file__).resolve().parent / "telemetry.py",
        work_dir / "telemetry.py",
    ]
    for cand in candidates:
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("designer_telemetry", cand)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "inspect_session"):
                    return mod.inspect_session
                if hasattr(mod, "inspect_designer_session"):
                    return mod.inspect_designer_session
    return None


def load_models_meta(models_json_path: pathlib.Path | None) -> tuple[dict[str, dict], str | None]:
    if not models_json_path or not models_json_path.is_file():
        return {}, None
    raw = json.loads(models_json_path.read_text(encoding="utf-8"))
    meta: dict[str, dict] = {}
    file_bench_id: str | None = None
    if isinstance(raw, dict):
        if isinstance(raw.get("benchmarkId"), str):
            file_bench_id = raw["benchmarkId"]
        if "models" in raw and isinstance(raw["models"], dict):
            for k, v in raw["models"].items():
                if isinstance(v, dict):
                    meta[k] = v
        elif "configs" in raw and isinstance(raw["configs"], list):
            for item in raw["configs"]:
                if isinstance(item, dict):
                    cid = item.get("configId") or item.get("id")
                    if cid:
                        meta[cid] = item
        else:
            for k, v in raw.items():
                if isinstance(v, dict):
                    meta[k] = v
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                cid = item.get("configId") or item.get("id")
                if cid:
                    meta[cid] = item
    return meta, file_bench_id


def count_loc(run_dir: pathlib.Path) -> int:
    if not run_dir.is_dir():
        return 0
    total = 0
    for ext in ("*.html", "*.css", "*.js", "*.mjs"):
        for f in run_dir.glob(ext):
            try:
                total += len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                pass
    return total


def assemble_gallery_data(
    work_dir: pathlib.Path,
    screenshots_dir: pathlib.Path,
    models_json_path: pathlib.Path | None,
    seed: int,
    benchmark_id: str | None,
) -> dict:
    results_dir = work_dir / "results"
    if not results_dir.is_dir():
        raise SystemExit(f"Error: results directory not found: {results_dir}")

    models_meta, file_bench_id = load_models_meta(models_json_path)
    inspect_session = load_telemetry_fn(work_dir)

    configs_file = work_dir / "configs.json"
    known_configs: list[str] = list(models_meta.keys())
    if not known_configs and configs_file.is_file():
        raw_cfgs = json.loads(configs_file.read_text(encoding="utf-8"))
        if isinstance(raw_cfgs, list):
            known_configs = [str(c) for c in raw_cfgs]

    challenges_out = []
    for ch_spec in CHALLENGE_SPECS:
        ch_id = ch_spec["id"]
        entries = []

        # Discover result files for this challenge
        result_files = sorted(results_dir.glob(f"{ch_id}_*.json"))
        if not result_files:
            continue

        for rf in result_files:
            res = json.loads(rf.read_text(encoding="utf-8"))
            cfg = res.get("config") or rf.stem[len(ch_id) + 1 :]
            if models_meta and cfg not in models_meta:
                continue
            m = models_meta.get(cfg, {})

            tel = {}
            session_id = res.get("session_id")
            if session_id and inspect_session is not None:
                try:
                    tel = inspect_session(session_id, ch_spec["turn_slice"]) or {}
                    if ch_spec["turn_slice"] == "second_user" and (tel.get("rounds_total") or 0) < 2:
                        tel = inspect_session(session_id, "all") or {}
                except Exception as exc:
                    print(f"Warning: telemetry lookup failed for {ch_id}/{cfg}: {exc}", file=sys.stderr)
                    tel = {}

            pw = tel.get("playwright") or {}
            msg_models = tel.get("msg_models") or []
            inferred_model_id = m.get("modelId") or m.get("model") or (msg_models[0] if msg_models else cfg)
            inferred_family = m.get("family") or (cfg.split("-")[0].capitalize() if "-" in cfg else cfg)
            inferred_tier = m.get("tier") or (cfg.split("-")[-1] if "-" in cfg else "")
            inferred_name = m.get("modelName") or m.get("name") or (f"{inferred_family} · {inferred_tier}" if inferred_tier else inferred_family)

            run_dir_name = "d2-greenfield" if ch_id == "d4-nudge" else ch_id
            loc = res.get("loc") or count_loc(work_dir / "runs" / run_dir_name / cfg)

            images = {}
            for v in ch_spec["views"]:
                img_path = screenshots_dir / ch_id / cfg / v["file"]
                images[v["id"]] = img_path.resolve().as_uri()

            entries.append({
                "configId": cfg,
                "modelName": inferred_name,
                "modelId": inferred_model_id,
                "family": inferred_family,
                "tier": inferred_tier,
                "score": str(res.get("score", "—")),
                "wallS": float(res.get("wallS", tel.get("wall_s", 0.0)) or 0.0),
                "tokS": float(res.get("tokS", tel.get("tok_s", 0.0)) or 0.0),
                "turns": int(res.get("turns", tel.get("turns", 0)) or 0),
                "cost": float(res.get("cost", tel.get("cost", 0.0)) or 0.0),
                "pngReads": int(res.get("pngReads", res.get("png_reads", pw.get("png_reads", 0))) or 0),
                "pwScreenshots": int(res.get("pwScreenshots", pw.get("screenshot", 0)) or 0),
                "loc": int(loc),
                "images": images,
            })

        if not entries:
            continue

        # Sort deterministically by configId first, then shuffle deterministically per challenge
        order_index = {c: i for i, c in enumerate(known_configs)}
        entries.sort(key=lambda e: (order_index.get(e["configId"], 9999), e["configId"]))

        rng = random.Random(f"{seed}:{ch_id}")
        rng.shuffle(entries)
        for idx, entry in enumerate(entries):
            entry["blindLabel"] = blind_label_for_index(idx)

        challenges_out.append({
            "id": ch_id,
            "short": ch_spec["short"],
            "title": ch_spec["title"],
            "subtitle": ch_spec["subtitle"],
            "views": ch_spec["views"],
            "entries": entries,
        })

    if not challenges_out:
        raise SystemExit(f"Error: no challenge results found in {results_dir}")

    return {
        "benchmarkId": benchmark_id or file_bench_id or work_dir.name,
        "challenges": challenges_out,
    }


def file_uri_to_path(uri: str) -> pathlib.Path | None:
    if not uri.startswith("file://"):
        return None
    parsed = urllib.parse.urlparse(uri)
    return pathlib.Path(urllib.parse.unquote(parsed.path))


def encode_image_inline(src_path: pathlib.Path, use_magick: bool, webp_quality: int) -> str:
    if not src_path.is_file():
        raise FileNotFoundError(f"Missing screenshot: {src_path}")

    if use_magick:
        proc = subprocess.run(
            [
                "magick",
                str(src_path),
                "-quality",
                str(webp_quality),
                "-define",
                "webp:method=6",
                "-define",
                "webp:sharp-yuv=true",
                "webp:-",
            ],
            capture_output=True,
            check=True,
        )
        b64 = base64.b64encode(proc.stdout).decode("ascii")
        return f"data:image/webp;base64,{b64}"

    mime, _ = mimetypes.guess_type(str(src_path))
    if not mime:
        mime = "image/png"
    b64 = base64.b64encode(src_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def inline_standalone_images(data: dict, webp_quality: int, workers: int) -> dict:
    has_magick = shutil.which("magick") is not None
    if not has_magick:
        print(
            "Warning: 'magick' (ImageMagick) not found on PATH; falling back to raw PNG base64 for --standalone.",
            file=sys.stderr,
        )

    tasks: list[tuple[dict, str, pathlib.Path]] = []
    for ch in data.get("challenges", []):
        for entry in ch.get("entries", []):
            images = entry.get("images") or {}
            for view_id, url in images.items():
                if isinstance(url, str) and url.startswith("file://"):
                    p = file_uri_to_path(url)
                    if p is not None:
                        tasks.append((images, view_id, p))

    if not tasks:
        return data

    unique_paths = sorted({p for _, _, p in tasks})
    encoded_cache: dict[pathlib.Path, str] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_map = {
            pool.submit(encode_image_inline, p, has_magick, webp_quality): p
            for p in unique_paths
        }
        for fut in concurrent.futures.as_completed(future_map):
            p = future_map[fut]
            try:
                encoded_cache[p] = fut.result()
            except Exception as exc:
                print(f"Warning: failed to encode {p}: {exc}", file=sys.stderr)

    for images, view_id, p in tasks:
        if p in encoded_cache:
            images[view_id] = encoded_cache[p]

    return data


def format_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} B"


def main():
    default_template = pathlib.Path(__file__).resolve().parent.parent.parent / "assets" / "gallery_template.html"

    parser = argparse.ArgumentParser(description="Build blind visual review HTML gallery for Designer benchmark.")
    parser.add_argument("--data", default=None, help="Pre-built gallery_data.json path")
    parser.add_argument("--work-dir", default=None, help="Benchmark work directory (for auto-assembly from results/*.json)")
    parser.add_argument("--screenshots-dir", default="/tmp/opencode/playwright-mcp/designer-bench", help="Screenshots root directory")
    parser.add_argument("--models-json", default=None, help="Optional JSON metadata mapping configId -> modelName/family/tier/modelId")
    parser.add_argument("--seed", type=int, default=20261120, help="Deterministic seed for blind permutation (default: 20261120)")
    parser.add_argument("--benchmark-id", default=None, help="Optional benchmarkId for localStorage vote isolation")
    parser.add_argument("--out", required=True, help="Output HTML file path")
    parser.add_argument("--template", default=str(default_template), help="Path to gallery_template.html")
    parser.add_argument("--standalone", action="store_true", help="Inline screenshots as base64 WebP (or PNG fallback)")
    parser.add_argument("--webp-quality", type=int, default=86, help="WebP quality for --standalone (default: 86)")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers for --standalone image encoding (default: 8)")
    parser.add_argument("--key-out", default=None, help="Optional path to save blind mapping key JSON")
    args = parser.parse_args()

    if args.data:
        data = json.loads(pathlib.Path(args.data).read_text(encoding="utf-8"))
        if args.benchmark_id:
            data["benchmarkId"] = args.benchmark_id
    elif args.work_dir:
        data = assemble_gallery_data(
            work_dir=pathlib.Path(args.work_dir).resolve(),
            screenshots_dir=pathlib.Path(args.screenshots_dir).resolve(),
            models_json_path=pathlib.Path(args.models_json).resolve() if args.models_json else None,
            seed=args.seed,
            benchmark_id=args.benchmark_id,
        )
    else:
        raise SystemExit("Error: provide either --data <gallery_data.json> or --work-dir <dir>")

    if args.standalone:
        data = inline_standalone_images(data, webp_quality=args.webp_quality, workers=args.workers)

    template_path = pathlib.Path(args.template)
    if not template_path.is_file():
        raise SystemExit(f"Error: template not found: {template_path}")

    template_html = template_path.read_text(encoding="utf-8")
    token = "__GALLERY_DATA_JSON__"
    if token not in template_html:
        raise SystemExit(f"Error: template missing placeholder token {token}")

    # Escape '</' as '<\/' to prevent premature </script> termination inside HTML
    serialized = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    output_html = template_html.replace(token, serialized, 1)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output_html, encoding="utf-8")

    # Build blind mapping key
    blind_key = {}
    print("\nBlind Mapping Key:", file=sys.stderr)
    for ch in data.get("challenges", []):
        ch_map = {}
        pairs = []
        for entry in ch.get("entries", []):
            bl = entry.get("blindLabel", "?")
            cid = entry.get("configId", "?")
            mname = entry.get("modelName", cid)
            ch_map[bl] = {"configId": cid, "modelName": mname}
            pairs.append(f"{bl}={cid}")
        blind_key[ch.get("id", "?")] = ch_map
        print(f"  {ch.get('id')}: " + ", ".join(pairs), file=sys.stderr)

    if args.key_out:
        key_path = pathlib.Path(args.key_out)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(json.dumps(blind_key, indent=2) + "\n", encoding="utf-8")

    size_bytes = out_path.stat().st_size
    print(f"Wrote {out_path} ({format_size(size_bytes)})", file=sys.stderr)


if __name__ == "__main__":
    main()
