"""
Quick connectivity test for both LLM endpoints.
Run from project root: uv run python scripts/test_api_connectivity.py
"""
import sys
import os

# Load .env before importing clip_weave
from dotenv import load_dotenv
load_dotenv()

from clip_weave.config import load_config

_PASS = "\033[32mPASS\033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_INFO = "\033[33mINFO\033[0m"


def test_gemini(cfg) -> bool:
    from openai import OpenAI

    base_url = cfg.video_analysis_base_url or "https://generativelanguage.googleapis.com/v1beta/openai/"
    model = cfg.video_analysis_model
    api_key = cfg.video_analysis_api_key

    # OpenAI SDK appends /chat/completions — base_url must include /v1 for gateways
    url_preview = base_url.rstrip("/") + "/chat/completions"
    print(f"  [{_INFO}] URL  : {url_preview}")
    print(f"  [{_INFO}] Model: {model}")
    if cfg.video_analysis_base_url and not cfg.video_analysis_base_url.rstrip("/").endswith("v1"):
        fixed = cfg.video_analysis_base_url.rstrip("/") + "/v1"
        print(f"  [{_INFO}] HINT : base_url missing /v1 — try VIDEO_ANALYSIS_BASE_URL={fixed}")

    client = OpenAI(base_url=base_url, api_key=api_key or "missing")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=64,
        )
        reply = resp.choices[0].message.content or ""
        print(f"  [{_PASS}] Response: {reply!r}")
        return True
    except Exception as exc:
        print(f"  [{_FAIL}] {exc}")
        return False


def test_claude(cfg) -> bool:
    from anthropic import Anthropic

    base_url = cfg.html_gen_base_url
    model = cfg.html_gen_model
    api_key = cfg.html_gen_api_key

    # Show the exact URL the SDK will hit
    if base_url:
        url_preview = base_url.rstrip("/") + "/v1/messages"
        client = Anthropic(base_url=base_url, auth_token=api_key or "missing")
    else:
        url_preview = "https://api.anthropic.com/v1/messages"
        client = Anthropic(api_key=api_key or "missing")

    print(f"  [{_INFO}] URL  : {url_preview}")
    print(f"  [{_INFO}] Model: {model}")

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=64,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        )
        reply = resp.content[0].text
        print(f"  [{_PASS}] Response: {reply!r}")
        return True
    except Exception as exc:
        print(f"  [{_FAIL}] {exc}")
        return False


def main():
    cfg = load_config()

    results = {}

    print("\n── Stage 1: Gemini (video analysis) ──────────────────────────────")
    results["gemini"] = test_gemini(cfg)

    print("\n── Stage 2a: Claude (HTML generation) ────────────────────────────")
    results["claude"] = test_claude(cfg)

    print("\n──────────────────────────────────────────────────────────────────")
    all_pass = all(results.values())
    for name, ok in results.items():
        status = _PASS if ok else _FAIL
        print(f"  [{status}] {name}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
