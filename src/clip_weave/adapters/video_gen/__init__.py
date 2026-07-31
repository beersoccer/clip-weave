"""Gateway-hosted video generation models (豆包 / 阿里万相 / Vertex Veo)."""

from __future__ import annotations

from .ali import AliVideoModel, load_config as load_ali_config
from .base import (
    ProviderConfig,
    TaskStatus,
    VideoGenError,
    VideoModel,
    VideoRequest,
)
from .doubao import DoubaoVideoModel, load_config as load_doubao_config
from .gcp_project import looks_like_project_id, resolve_project
from .vertex import VertexVideoModel, load_config as load_vertex_config

PROVIDERS = {
    "doubao": (DoubaoVideoModel, load_doubao_config),
    "ali": (AliVideoModel, load_ali_config),
    "vertex": (VertexVideoModel, load_vertex_config),
}


def get_model(provider: str, **overrides: str) -> VideoModel:
    """Build a configured `VideoModel` for `provider` (doubao | ali | vertex).

    `overrides` patch `ProviderConfig.extra`, e.g. `get_model("vertex",
    PROJECT="my-gcp-project")`.
    """
    key = provider.strip().lower()
    if key not in PROVIDERS:
        raise VideoGenError(
            f"unknown provider {provider!r} — choose one of {', '.join(PROVIDERS)}"
        )
    model_cls, load_cfg = PROVIDERS[key]
    cfg = load_cfg()
    for name, value in overrides.items():
        if value:
            cfg.extra[name] = value
    return model_cls(cfg)


__all__ = [
    "AliVideoModel",
    "DoubaoVideoModel",
    "PROVIDERS",
    "ProviderConfig",
    "TaskStatus",
    "VertexVideoModel",
    "VideoGenError",
    "VideoModel",
    "VideoRequest",
    "get_model",
    "looks_like_project_id",
    "resolve_project",
]
