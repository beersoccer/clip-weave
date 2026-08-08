# T2V Follow-up Fixes Implementation Plan（历史，2026-08-01）

> 已完成的实施计划；不作为当前待办。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two defects surfaced by the independent follow-up review of tasks 4b/5/6/7/8 on branch `feat/rule-guard-soundness-and-t2v-routing`: a GSAP-ease leak in the primary T2V prompt path, and zero test coverage for `VideoModel.download()` plus dead code in `VideoModel.wait()`.

**Architecture:** Two independent tasks touching disjoint files. Task 1 extends `t2v_prompt.py`'s token-scrubbing regex and adds a regression test built from the review's own repro. Task 2 adds offline tests for `VideoModel.download()`'s four branches, then deletes the unreferenced `wait()` method (confirmed dead by grep — `video_pipeline.py` implements its own inline poll loop).

**Tech Stack:** Python 3.11+, pytest 8, `requests` (mocked via a fake `Session`), no new dependencies.

## Global Constraints

- Same branch as the parent plan: `feat/rule-guard-soundness-and-t2v-routing`. Do not create a new branch.
- No new runtime dependencies.
- All tests must be offline — no real HTTP requests, no real `npx`/`ffmpeg`/`gcloud` invocations.
- Keep the existing Chinese-comment / English-docstring style used elsewhere in `src/clip_weave/`.
- Run `.venv/bin/python -m pytest -q` at the end of each task — must be fully green. Baseline going into this plan is 257 passed.
- Conventional Commits, consistent with this branch's history (`fix(scope):` / `test(scope):`).

---

## Task 1: Fix the `power3.out`-style GSAP-ease leak in `t2v_prompt._clean()`

**Where this came from:** The independent review of Task 4b (a prior fix to `storyboard.build_prompt()`'s narrative fallback) found that `core/t2v_prompt.py`'s own token-scrubber has the same class of bug, one level less severe: `_clean()` only strips GSAP vocabulary that appears *inside parentheses or backticks*. A bare ease name like `power3.out` sitting outside any bracket survives untouched and reaches `T2V-PROMPTS.md` — the file a user is meant to hand to a video model.

**Files:**
- Modify: `src/clip_weave/core/t2v_prompt.py`
- Test: `tests/test_t2v_prompt.py`

**Interfaces:**
- Consumes: nothing new — `_clean(text: str) -> str` already exists (module-private, used inside `_build_spec`).
- Produces: no signature change. `_clean` still takes and returns `str`.

- [ ] **Step 1: Reproduce the leak exactly as the reviewer did**

Run this once manually to confirm the starting point (not a commit, just a sanity check — do not skip it, the fix must be verified against a real repro, not assumed):

```bash
cd /Users/beersoccer/workspace/clip-weave
.venv/bin/python - <<'PY'
from pathlib import Path
import tempfile
from clip_weave.core.storyboard import parse_storyboard
from clip_weave.core.t2v_prompt import build_doc

body = """---
format: 1920x1080
message: "theme"
---

## Frame 1 - Chassis
- duration: 6s
- blueprint: dataviz-countup
- sfx: riser

Scene 1 (0-2s): asset scales in (gsap-effects, spring-pop-entrance), counter counts up with power3.out.
"""
d = Path(tempfile.mkdtemp()); p = d / "STORYBOARD.md"; p.write_text(body, encoding="utf-8")
sb = parse_storyboard(p)
doc = build_doc(sb)
print(doc.specs[0].scene)
PY
```

Expected output contains `power3.out` (the bug). If it does not, stop and re-read `_clean()` — something else has already changed and this task's premise may be stale.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_t2v_prompt.py`. First read the top of that file to check whether it
already has a `_write`/`_storyboard`-style helper that writes a storyboard body to a temp
file and returns a parsed `Storyboard` — if one exists, use it instead of the inline
`tmp_path.write_text(...)` + `parse_storyboard(path)` shown below. Also check whether
`build_doc` is already imported from `clip_weave.core.t2v_prompt` at the top of the file;
if not, add it to the existing import block there rather than adding a new import line.

```python
def test_clean_strips_bare_gsap_ease_names_outside_parens(tmp_path):
    """_clean() must not leak GSAP vocabulary that isn't inside parens/backticks.

    Regression for a leak found while reviewing a sibling fix in storyboard.py:
    _clean()'s regex only scrubbed tokens INSIDE (...) or `...`, so a bare ease
    name like `power3.out` sitting outside any bracket reached T2V-PROMPTS.md,
    the file handed to a video model.
    """
    from clip_weave.core.storyboard import parse_storyboard

    body = """---
format: 1920x1080
message: "theme"
---

## Frame 1 - Chassis
- duration: 6s
- blueprint: dataviz-countup
- sfx: riser

Scene 1 (0-2s): asset scales in (gsap-effects, spring-pop-entrance), counter counts up with power3.out.
"""
    path = tmp_path / "STORYBOARD.md"
    path.write_text(body, encoding="utf-8")
    sb = parse_storyboard(path)

    doc = build_doc(sb)
    scene = doc.specs[0].scene

    for leaked in ("power3.out", "gsap-effects", "spring-pop-entrance"):
        assert leaked not in scene, f"{leaked!r} leaked into the T2V scene slot: {scene!r}"
```

Note: `build_doc` must already be imported at the top of `tests/test_t2v_prompt.py` (it is used elsewhere in that file to build docs) — if not, add it to the existing `from clip_weave.core.t2v_prompt import (...)` block rather than adding a new import line.

- [ ] **Step 2b: Confirm the test fails for the right reason**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_t2v_prompt.py::test_clean_strips_bare_gsap_ease_names_outside_parens -v`

Expected: FAIL, with `power3.out` present in the asserted string (matches Step 1's repro).

- [ ] **Step 3: Fix `_clean()` in `src/clip_weave/core/t2v_prompt.py`**

Current implementation:

```python
def _clean(text: str) -> str:
    """Strip HF implementation vocabulary that means nothing to a video model."""
    text = re.sub(r"\(([^)]*(?:gsap|spring-pop|sine-wave|stagger|scaleX|tween)[^)]*)\)", "", text,
                  flags=re.IGNORECASE)
    text = re.sub(r"`[^`]*`", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()
```

The bug: the first `re.sub` only fires when the matched vocabulary is *inside* a parenthesized group — it deletes the whole parenthetical, tokens and all, but only when a trigger token is present in that same group. A bare `power3.out` with no surrounding parens never enters that branch at all.

Replace the function with a version that scrubs the same vocabulary set wherever it appears — inside parens (delete the whole parenthetical, preserving existing behavior for that case) and standalone (delete just the matched word, preserving the surrounding sentence):

```python
# GSAP/motion vocabulary that means nothing to a video model. Matches both a
# bare token (`power3.out`, `spring-pop-entrance`) and one embedded in a longer
# hyphenated/dotted identifier, so it must be word-bounded on a non-identifier
# character rather than \b (which does not treat `.`/`-` as boundaries).
_GSAP_VOCAB = r"(?:gsap[\w.\-]*|power\d\.\w+|spring-pop[\w-]*|sine-wave[\w-]*|stagger\w*|scaleX\w*|tween\w*)"


def _clean(text: str) -> str:
    """Strip HF implementation vocabulary that means nothing to a video model.

    Two passes: first delete an entire parenthetical/backtick span that
    CONTAINS the vocabulary (preserves the original "drop the whole aside"
    behavior for `(gsap-effects, spring-pop-entrance)`), then delete any
    remaining bare occurrence of the vocabulary that was never bracketed at
    all (`power3.out` sitting directly in a sentence).
    """
    text = re.sub(rf"\([^)]*{_GSAP_VOCAB}[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(rf"(?<![\w.\-]){_GSAP_VOCAB}(?![\w])", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip()
```

Do not change anything else in this file — `_camera_line`, `_style_line`, `_build_spec`, and every other function are out of scope for this task.

- [ ] **Step 4: Run the new test and confirm it passes**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_t2v_prompt.py::test_clean_strips_bare_gsap_ease_names_outside_parens -v`

Expected: PASS.

- [ ] **Step 5: Confirm the existing `_clean`-adjacent tests still pass**

Read `tests/test_t2v_prompt.py` for any existing test that exercises `_clean` indirectly (search for `gsap`, `spring-pop`, or `_clean` in that file) and run the whole file:

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_t2v_prompt.py -v`

Expected: all pass, including any pre-existing test that asserts the parenthetical `(gsap-effects, spring-pop-entrance)` form is stripped — that behavior must be unchanged by this fix (Step 3's first `re.sub` line preserves it verbatim, just with the token list moved into `_GSAP_VOCAB`).

- [ ] **Step 6: Run the full suite**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q`

Expected: 258 passed (257 baseline + 1 new test).

- [ ] **Step 7: Commit**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add src/clip_weave/core/t2v_prompt.py tests/test_t2v_prompt.py
git commit -m "fix(t2v-prompt): scrub bare GSAP ease names, not just parenthesized ones

_clean() only stripped GSAP/motion vocabulary when it appeared inside parens
or backticks. A bare ease name like power3.out sitting directly in a Scene
line survived into T2V-PROMPTS.md — the file handed to a video model.

Found while independently reviewing a sibling fix in storyboard.py that had
the same class of bug in the fallback prompt path; this is the primary path."
```

---

## Task 2: Cover `VideoModel.download()`, then delete the dead `VideoModel.wait()`

**Where this came from:** The independent follow-up review of Tasks 5+6 found `VideoModel.download()` (the `gs://` URL rewrite, streaming write, base64-decode branch, and no-payload error) has zero test coverage across Tasks 5, 6, and 7 — Task 7's `FakeModel.download()` is a hand-rolled stand-in that never exercises the real method. The same review found `VideoModel.wait()` has no caller anywhere in `src/` — `video_pipeline.py` implements its own inline poll loop instead.

**Files:**
- Test: `tests/test_video_gen_providers.py`
- Modify: `src/clip_weave/adapters/video_gen/base.py`

**Interfaces:**
- Consumes: the existing `FakeSession`/`FakeResponse` pattern already defined at the top of `tests/test_video_gen_providers.py` (from Task 5) — reuse it rather than inventing a second fake HTTP layer.
- Produces: no new public interface. `VideoModel.download(status: TaskStatus, dest: Path) -> Path` keeps its exact signature. `VideoModel.wait(...)` is removed entirely.

- [ ] **Step 1: Confirm `wait()` is genuinely dead before touching it**

Run: `cd /Users/beersoccer/workspace/clip-weave && grep -rn "\.wait(" src/clip_weave/ tests/`

Expected: the only hits are the method's own definition (`base.py`) and possibly its `def wait(` signature — no call site anywhere in `src/` or `tests/`. If you find a real call site, STOP — do not delete `wait()`, report back instead; the review's dead-code finding would be wrong and the task needs re-scoping.

- [ ] **Step 2: Write failing tests for `download()`'s four branches**

`VideoModel.download()` currently:

```python
def download(self, status: TaskStatus, dest: Path) -> Path:
    """Persist a finished task's video to `dest`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if status.video_url:
        url = status.video_url
        if url.startswith("gs://"):
            # Only works for publicly readable objects; otherwise use gsutil.
            url = "https://storage.googleapis.com/" + url[len("gs://") :]
        with self.session.get(url, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
        return dest
    if status.video_b64:
        import base64

        dest.write_bytes(base64.b64decode(status.video_b64))
        return dest
    raise VideoGenError(f"{self.cfg.name}: task finished without a video payload")
```

Four branches to cover: (a) an `https://` URL downloads via streaming `session.get`, (b) a `gs://` URL gets rewritten to the `storage.googleapis.com` form before the same streaming download, (c) inline base64 bytes are decoded and written directly with no HTTP call at all, (d) neither `video_url` nor `video_b64` is set → raises `VideoGenError`.

Append to `tests/test_video_gen_providers.py` (it already has `FakeSession`/`FakeResponse`/`_cfg` helpers and imports `TaskStatus` is NOT currently imported there — check the top of the file; if `TaskStatus` and `VideoModel` are not imported, add them to the existing `from clip_weave.adapters.video_gen... import (...)` lines rather than new import statements):

```python
# ── VideoModel.download ───────────────────────────────────────────────────────

class FakeStreamResponse:
    """A context-manager response for `session.get(..., stream=True)`."""

    def __init__(self, chunks, status_code=200):
        self._chunks = chunks
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def iter_content(self, chunk_size=None):
        yield from self._chunks


class FakeGetSession:
    """Only implements the `.get(url, stream=True, timeout=...)` path download() uses."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_download_streams_an_https_url(tmp_path):
    session = FakeGetSession(FakeStreamResponse([b"abc", b"def"]))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    status = TaskStatus(state="succeeded", raw={}, video_url="https://cdn.example.com/v.mp4")

    dest = tmp_path / "out.mp4"
    result = vm.download(status, dest)

    assert result == dest
    assert dest.read_bytes() == b"abcdef"
    assert session.calls[0]["url"] == "https://cdn.example.com/v.mp4"
    assert session.calls[0]["stream"] is True


def test_download_rewrites_gs_url_before_streaming(tmp_path):
    session = FakeGetSession(FakeStreamResponse([b"payload"]))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    status = TaskStatus(state="succeeded", raw={}, video_url="gs://my-bucket/videos/v.mp4")

    dest = tmp_path / "out.mp4"
    vm.download(status, dest)

    assert session.calls[0]["url"] == "https://storage.googleapis.com/my-bucket/videos/v.mp4"
    assert dest.read_bytes() == b"payload"


def test_download_creates_missing_parent_directories(tmp_path):
    session = FakeGetSession(FakeStreamResponse([b"x"]))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    status = TaskStatus(state="succeeded", raw={}, video_url="https://cdn/v.mp4")

    dest = tmp_path / "nested" / "dir" / "out.mp4"
    vm.download(status, dest)

    assert dest.exists()


def test_download_decodes_inline_base64_without_any_http_call(tmp_path):
    import base64

    session = FakeGetSession(FakeStreamResponse([b"should never be read"]))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    payload = base64.b64encode(b"raw video bytes").decode()
    status = TaskStatus(state="succeeded", raw={}, video_b64=payload)

    dest = tmp_path / "out.mp4"
    vm.download(status, dest)

    assert dest.read_bytes() == b"raw video bytes"
    assert session.calls == []  # no HTTP call for the base64 path


def test_download_raises_when_neither_url_nor_b64_is_present(tmp_path):
    session = FakeGetSession(FakeStreamResponse([]))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    status = TaskStatus(state="succeeded", raw={})

    with pytest.raises(VideoGenError, match="without a video payload"):
        vm.download(status, tmp_path / "out.mp4")
```

Note the design of `FakeGetSession`/`FakeStreamResponse`: `download()` uses `self.session.get(url, stream=True, timeout=600)` as a context manager (`with ... as resp:`), which is different from `_request()`'s `self.session.request(...)` used by every other test in this file (that one is not a context manager). Do not try to reuse `FakeSession` for this — it only implements `.request()`, not `.get()`. This is why a separate fake is needed here.

- [ ] **Step 3: Run the new tests and confirm they pass against the CURRENT (unmodified) `download()`**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_video_gen_providers.py -k download -v`

Expected: all 5 new tests PASS. This step is deliberately *not* a red step — `download()` is not being changed, only tested. If any of these fail, the test itself is wrong (re-read the real `download()` source above and fix the test, do not touch `download()`).

- [ ] **Step 4: Delete the dead `wait()` method**

In `src/clip_weave/adapters/video_gen/base.py`, remove the entire `wait()` method (from `def wait(` through the final `)` of its return statement, i.e. everything between `clamp_duration`/`_request` and `download`):

```python
    def wait(
        self,
        task_id: str,
        *,
        interval: int = DEFAULT_POLL_INTERVAL,
        max_wait: int = DEFAULT_MAX_WAIT,
        on_state: Any = None,
    ) -> TaskStatus:
        """Poll until the task reaches a terminal state or `max_wait` elapses."""
        deadline = time.time() + max_wait
        status = TaskStatus(state="pending", raw={})
        while time.time() < deadline:
            status = self.poll(task_id)
            if on_state:
                on_state(status)
            if status.state in ("succeeded", "failed"):
                return status
            time.sleep(interval)
        return TaskStatus(
            state="failed",
            raw=status.raw,
            error=f"timed out after {max_wait}s (last state: {status.state})",
        )
```

After removing it, check whether `time` is still used elsewhere in `base.py` (run `grep -n "^import time\|time\." src/clip_weave/adapters/video_gen/base.py`). If `time` becomes unused, remove the `import time` line too. Do the same check for `DEFAULT_POLL_INTERVAL` and `DEFAULT_MAX_WAIT` — if either constant is now unreferenced anywhere in `base.py`, `doubao.py`, `ali.py`, or `vertex.py` (grep all four files), remove the unused one(s); if either is still used (e.g. as a default in another function's signature), leave it.

- [ ] **Step 5: Run the full suite**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q`

Expected: 263 passed (258 after Task 1 + 5 new download tests). No failures — deleting `wait()` must not break anything, since Step 1 confirmed no caller exists.

- [ ] **Step 6: Commit**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add tests/test_video_gen_providers.py src/clip_weave/adapters/video_gen/base.py
git commit -m "test(video-gen): cover VideoModel.download(), delete dead wait()

download() had zero coverage across tasks 5-7 — its four branches (https
streaming, gs:// URL rewrite, inline base64 decode, no-payload error) were
never exercised by any test; Task 7's FakeModel.download() was a hand-rolled
stand-in with none of the real logic.

wait() has no caller anywhere in src/ — video_pipeline.py implements its own
inline poll loop instead. Confirmed dead via grep before deleting.

Found by the independent follow-up review of tasks 5+6."
```

---

## Self-Review

**Spec coverage:** Both findings from the review round are addressed — the `power3.out` leak (Task 1) and the `download()`/`wait()` gap (Task 2). No other findings from that round required code changes (the other Minor findings were explicitly deferred as out-of-scope or low-impact by the reviewers themselves, and are already recorded in the SDD ledger).

**Placeholder scan:** No TBD/TODO markers. Every step has literal code, not descriptions of code.

**Type consistency:** `_clean(text: str) -> str` signature unchanged in Task 1. `download(self, status: TaskStatus, dest: Path) -> Path` signature unchanged in Task 2 — only its test coverage changes; `wait()` is deleted, not modified, so no signature drift to check against downstream consumers (Step 1 confirms there are none).

Fixed during self-review: Task 1 Step 2 originally contained a broken draft snippet referencing a non-existent helper (`tmp_path_factory_stub`). Replaced with a single clean test using `tmp_path.write_text` directly, with instructions to prefer an existing helper if the test file already has one.
