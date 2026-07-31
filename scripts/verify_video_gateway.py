#!/usr/bin/env python
"""Verify the three video models on the company AI gateway.

Two levels of verification:

  --probe        route + auth only. Sends a deliberately invalid body and
                 expects HTTP 400 from the *upstream* provider — that proves the
                 gateway path is right and the key is accepted. Creates no task,
                 costs nothing.

  (default)      full round trip. Submits one short cheap clip (480p / 5s),
                 polls until it finishes, downloads the mp4. Costs money.

Usage:
    uv run python scripts/verify_video_gateway.py --probe
    uv run python scripts/verify_video_gateway.py --provider doubao
    uv run python scripts/verify_video_gateway.py            # all three, real

The API key is read from <PROVIDER>_VIDEO_API_KEY, else AI_GATEWAY_API_KEY,
else GEMINI_API_KEY — the gateway issues one key for every route.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clip_weave.adapters.video_gen import (  # noqa: E402
    PROVIDERS,
    VideoGenError,
    VideoRequest,
    get_model,
    resolve_project,
)


def _client(name: str):
    """Same construction the pipeline uses, incl. Vertex project auto-resolution."""
    if name != "vertex":
        return get_model(name)
    project, source = resolve_project()
    if project:
        print(f"  [vertex] GCP project {project} (from {source})")
    return get_model("vertex", PROJECT=project or "")

PROMPT = "a red sports car drives along a coastal road at sunset, cinematic"
OK, WARN, BAD = "PASS", "WARN", "FAIL"


def probe(name: str) -> tuple[str, str]:
    """Confirm path + auth without creating a task."""
    try:
        model = _client(name)
    except VideoGenError as exc:
        return BAD, str(exc)

    if name == "doubao":
        method, url, body, headers = "POST", model._tasks_url, {}, {}
    elif name == "ali":
        method, url, body = "POST", model._submit_url, {}
        headers = {"X-DashScope-Async": "enable"}
    else:
        # A real prompt is needed for Vertex to even look the model up ({"instances": []}
        # short-circuits to "Empty instances"), but durationSeconds=3 is illegal for
        # every Veo model, so a reachable model rejects it instead of starting a job.
        method, url, headers = "POST", model._url("predictLongRunning"), {}
        body = {"instances": [{"prompt": "probe"}], "parameters": {"durationSeconds": 3}}

    try:
        data = model._request(method, url, json=body, headers=headers)
    except VideoGenError as exc:
        msg = str(exc)
        if "RESOURCE_PROJECT_INVALID" in msg or "CONSUMER_INVALID" in msg:
            return WARN, (
                f"{url} reaches Vertex PredictLongRunning, but the resource path has no valid "
                "project — set VERTEX_VIDEO_PROJECT + VERTEX_VIDEO_LOCATION (or "
                "VERTEX_VIDEO_MODEL_PATH) to the GCP project behind the gateway"
            )
        if "Publisher model" in msg and "not found" in msg:
            return BAD, (
                "project accepted, but the Veo model is not available to it — "
                "ask ops to enable Veo for this project/region, or confirm the model id. "
                f"Upstream: {msg[msg.find('Publisher model'):][:180]}"
            )
        if "HTTP 400" in msg:
            # Upstream validation error = gateway routed us and accepted the key.
            return OK, f"{url} → 400 upstream validation error (route + key + model OK)"
        if "HTTP 404" in msg:
            return BAD, f"{url} → 404, wrong path for this gateway"
        if "HTTP 401" in msg or "HTTP 403" in msg:
            return BAD, f"{url} → auth rejected: {msg[:200]}"
        return WARN, msg[:300]
    return WARN, f"{url} accepted an empty body: {json.dumps(data)[:200]}"


def full(name: str, *, out_dir: Path, resolution: str, duration: int, max_wait: int) -> tuple[str, str]:
    """Submit → poll → download one cheap clip."""
    try:
        model = _client(name)
    except VideoGenError as exc:
        return BAD, str(exc)

    req = VideoRequest(prompt=PROMPT, duration=duration, ratio="16:9", resolution=resolution)
    started = time.time()
    try:
        task_id = model.submit(req)
    except VideoGenError as exc:
        return BAD, f"submit failed: {exc}"
    print(f"  [{name}] task {task_id}")

    status = model.wait(
        task_id,
        interval=10,
        max_wait=max_wait,
        on_state=lambda s: print(f"  [{name}] {s.state} ({int(time.time() - started)}s)"),
    )
    if status.state != "succeeded":
        return BAD, f"task ended {status.state}: {status.error}"

    dest = out_dir / f"{name}.mp4"
    try:
        model.download(status, dest)
    except Exception as exc:  # noqa: BLE001
        return WARN, f"generated but download failed ({status.video_url or 'inline bytes'}): {exc}"
    size = dest.stat().st_size
    return OK, f"{dest} ({size / 1024:.0f} KB) in {int(time.time() - started)}s, model={model.model}"


CANDIDATES = {
    "doubao": [
        "doubao-seedance-1-0-pro-250528",
        "doubao-seedance-1-0-lite-t2v-250428",
        "doubao-seedance-1-0-lite-i2v-250428",
        "doubao-seedance-1-5-pro-250528",
        "doubao-seedance-2-0-260128",
        "doubao-seedance-2-0-fast-260128",
    ],
    "ali": [
        "wan2.7-t2v",
        "wan2.6-t2v",
        "wan2.5-t2v-preview",
        "wan2.2-t2v-plus",
        "wanx2.1-t2v-turbo",
        "wanx2.1-t2v-plus",
        "wan2.5-i2v-preview",
        "wan2.2-i2v-plus",
    ],
    "vertex": [
        "veo-3.1-generate-001",
        "veo-3.1-fast-generate-001",
        "veo-3.1-lite-generate-001",
        "veo-3.0-generate-001",
        "veo-3.0-fast-generate-001",
        "veo-2.0-generate-001",
    ],
}


def list_models(name: str) -> None:
    """Report which candidate model ids the gateway actually serves.

    Each provider gets a request that can never produce a video:
      * doubao — `duration: 1` is out of range for every Seedance model, and Ark
        validates synchronously, so no task is created.
      * ali    — DashScope only checks the model id synchronously; everything else
        is async. An empty `input` means the task is created but always fails on
        "Field required: input.prompt", so nothing is generated or billed.
      * vertex — `durationSeconds: 3` is illegal for every Veo model.
    """
    import os

    for model_id in CANDIDATES[name]:
        os.environ[f"{name.upper()}_VIDEO_MODEL"] = model_id
        try:
            client = _client(name)
        except VideoGenError as exc:
            print(f"  {model_id:36} config error: {exc}")
            continue

        if name == "doubao":
            url, body, headers = client._tasks_url, {
                "model": model_id,
                "content": [{"type": "text", "text": "probe"}],
                "duration": 1,
            }, {}
        elif name == "ali":
            url, body = client._submit_url, {"model": model_id, "input": {}}
            headers = {"X-DashScope-Async": "enable"}
        else:
            url, headers = client._url("predictLongRunning"), {}
            body = {"instances": [{"prompt": "probe"}], "parameters": {"durationSeconds": 3}}

        try:
            data = client._request("POST", url, json=body, headers=headers)
        except VideoGenError as exc:
            msg = str(exc)
            unavailable = any(
                token in msg
                for token in ("NotFound", "not exist", "was not found", "does not exist")
            )
            verdict = "unavailable" if unavailable else "available"
            print(f"  {model_id:36} {verdict:12} {_tail(msg)}")
            continue
        # A 200 here means the model id was accepted (the task then fails validation).
        print(f"  {model_id:36} {'available':12} accepted (probe task fails validation)")
        _ = data


def _tail(msg: str) -> str:
    for marker in ("— ", ":: "):
        if marker in msg:
            msg = msg.split(marker, 1)[1]
    return msg.strip()[:110]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", action="append", choices=sorted(PROVIDERS), help="repeatable; default all")
    ap.add_argument("--probe", action="store_true", help="route + auth only, no generation, no cost")
    ap.add_argument(
        "--models",
        action="store_true",
        help="list which model ids the gateway exposes for each provider (no generation)",
    )
    ap.add_argument("--out-dir", default="/tmp/clip-weave-verify")
    ap.add_argument("--resolution", default="480p")
    ap.add_argument("--duration", type=int, default=5)
    ap.add_argument("--max-wait", type=int, default=600)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    load_dotenv()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    providers = args.provider or sorted(PROVIDERS)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.models:
        for name in providers:
            print(f"→ {name}")
            list_models(name)
            print()
        return 0

    mode = "probe (no generation)" if args.probe else f"full round trip ({args.resolution}, {args.duration}s)"
    print(f"Verifying {', '.join(providers)} — {mode}\n")

    results: list[tuple[str, str, str]] = []
    for name in providers:
        print(f"→ {name}")
        verdict, detail = (
            probe(name)
            if args.probe
            else full(
                name,
                out_dir=out_dir,
                resolution=args.resolution,
                duration=args.duration,
                max_wait=args.max_wait,
            )
        )
        print(f"  {verdict}: {detail}\n")
        results.append((name, verdict, detail))

    print("── summary ─────────────────────────────────────────────")
    for name, verdict, detail in results:
        print(f"{verdict:5} {name:8} {detail[:110]}")
    return 0 if all(v == OK for _, v, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
