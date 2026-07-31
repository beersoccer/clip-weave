"""Semantic workflow routing — offline tests (no gateway calls)."""

import json

import pytest

from clip_weave.core import workflow_router
from clip_weave.core.intent_router import (
    detect_workflow,
    detect_workflow_by_keywords,
    route,
)

_GATEWAY_VARS = (
    "ROUTER_BASE_URL",
    "ROUTER_API_KEY",
    "ROUTER_MODEL",
    "VIDEO_ANALYSIS_BASE_URL",
    "VIDEO_ANALYSIS_API_KEY",
    "VIDEO_ANALYSIS_MODEL",
    "HTML_GEN_BASE_URL",
    "HTML_GEN_API_KEY",
    "HTML_GEN_MODEL",
)


@pytest.fixture
def no_gateway(monkeypatch):
    for var in _GATEWAY_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def gateway(monkeypatch):
    for var in _GATEWAY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ROUTER_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setenv("ROUTER_API_KEY", "k")
    monkeypatch.setenv("ROUTER_MODEL", "test-model")


def _fake_post(content: str, monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    def _post(url, **kwargs):
        _post.calls.append((url, kwargs))
        return _Resp()

    _post.calls = []
    import requests

    monkeypatch.setattr(requests, "post", _post)
    return _post


# ── answer parsing ────────────────────────────────────────────────────────────

def test_parses_plain_json():
    parsed = workflow_router._parse(
        '{"workflow": "music-to-video", "confidence": 0.9, "reason": "beat-driven"}'
    )
    assert parsed == ("music-to-video", 0.9, "beat-driven")


def test_parses_fenced_json_with_prose():
    parsed = workflow_router._parse(
        'Sure!\n```json\n{"workflow": "slideshow", "confidence": 1}\n```\n'
    )
    assert parsed is not None
    assert parsed[0] == "slideshow"


def test_rejects_unknown_workflow():
    assert workflow_router._parse('{"workflow": "make-a-movie", "confidence": 1}') is None


def test_rejects_non_json():
    assert workflow_router._parse("I think slideshow is best") is None


def test_clamps_confidence():
    parsed = workflow_router._parse('{"workflow": "general-video", "confidence": 7}')
    assert parsed[1] == 1.0


# ── classify() ────────────────────────────────────────────────────────────────

def test_classify_without_gateway_falls_back_to_keyword(no_gateway):
    decision = workflow_router.classify("讲讲 RAG", "text", keyword_fallback="faceless-explainer")
    assert decision.workflow == "faceless-explainer"
    assert decision.method == "keyword"


def test_classify_uses_semantic_answer(gateway, monkeypatch):
    post = _fake_post(
        json.dumps({"workflow": "music-to-video", "confidence": 0.9, "reason": "beat"}),
        monkeypatch,
    )
    decision = workflow_router.classify(
        "用这首歌的节拍剪网站素材", "text", keyword_fallback="product-launch-video"
    )
    assert decision.workflow == "music-to-video"
    assert decision.method == "semantic"
    assert decision.confidence == pytest.approx(0.9)
    url, kwargs = post.calls[0]
    assert url == "http://gateway.test/v1/chat/completions"
    assert kwargs["json"]["model"] == "test-model"


def test_classify_falls_back_when_llm_errors(gateway, monkeypatch):
    import requests

    def _boom(*a, **kw):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(requests, "post", _boom)
    decision = workflow_router.classify(
        "随便做个视频", "text", keyword_fallback="general-video"
    )
    assert decision.workflow == "general-video"
    assert decision.method == "keyword-fallback"


def test_classify_falls_back_on_unparseable_answer(gateway, monkeypatch):
    _fake_post("probably a slideshow", monkeypatch)
    decision = workflow_router.classify("做个 deck", "text", keyword_fallback="slideshow")
    assert decision.method == "keyword-fallback"
    assert decision.workflow == "slideshow"


# ── intent_router integration ────────────────────────────────────────────────

def test_semantic_overrides_keyword_pick(gateway, monkeypatch):
    _fake_post(json.dumps({"workflow": "faceless-explainer", "confidence": 1}), monkeypatch)
    text = "我们不做产品广告,只想讲清楚什么是向量数据库"
    assert detect_workflow_by_keywords(text, "text") == "product-launch-video"
    assert detect_workflow(text, "text") == "faceless-explainer"


def test_semantic_can_be_disabled(gateway, monkeypatch):
    _fake_post(json.dumps({"workflow": "faceless-explainer", "confidence": 1}), monkeypatch)
    text = "我们不做产品广告,只想讲清楚什么是向量数据库"
    assert detect_workflow(text, "text", semantic=False) == "product-launch-video"


def test_route_records_method(gateway, monkeypatch):
    _fake_post(json.dumps({"workflow": "pr-to-video", "confidence": 0.8, "reason": "diff"}), monkeypatch)
    result = route("把这个改动讲清楚 https://github.com/foo/bar/pull/12")
    assert result.workflow == "pr-to-video"
    assert result.routing_method == "semantic"
    assert result.routing_confidence == pytest.approx(0.8)
    assert result.source_type == "url"


def test_route_without_gateway_is_deterministic(no_gateway):
    result = route("帮我做个产品宣传视频")
    assert result.workflow == "product-launch-video"
    assert result.routing_method == "keyword"
