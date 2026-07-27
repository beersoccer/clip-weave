"""clip-weave pipeline — Intent → Factory → Asset Match → Guard → Delegate.

This is the top-level orchestrator. HF skills handle everything after BRIEF.md
is written and the project directory is assembled; clip-weave does not rebuild
storyboard generation, composition authoring, lint, check, or render.
"""

import logging
from pathlib import Path

from clip_weave.config import Config, load_config
from clip_weave.core.intent_router import route, write_brief
from clip_weave.core.project_factory import setup as factory_setup
from clip_weave.core.delegator import print_delegation_instructions
from clip_weave.adapters.asset_matcher import match_assets
from clip_weave.adapters.rule_guard import scan as guard_scan, save_history

logger = logging.getLogger(__name__)


def run(
    user_input: str,
    project_name: str,
    videos_dir: Path = Path("videos"),
    uploaded_files: list[Path] | None = None,
    message: str = "",
    cfg: Config | None = None,
) -> Path:
    """Full pipeline: route → init → brief → asset-match → delegate.

    Returns project_dir. Caller should then invoke the HF workflow skill.
    """
    if cfg is None:
        cfg = load_config()

    project_dir = videos_dir / project_name

    # ① Intent Router
    result = route(user_input, uploaded_files=uploaded_files, message=message)
    logger.info("Routed to workflow=%s flow=%s source=%s",
                result.workflow, result.flow, result.source_type)

    # ② Project Factory (init + capture)
    factory_setup(project_dir, source_url=result.source_url, uploaded_files=uploaded_files)

    # ③ Write BRIEF.md
    brief_path = write_brief(result, project_dir)
    logger.info("BRIEF.md written: %s", brief_path)

    # ④ Asset Matcher (pre-populate candidates if capture/ has assets)
    desc_file = project_dir / "capture" / "extracted" / "asset-descriptions.md"
    if desc_file.exists():
        logger.info("Running Asset Matcher …")
        # Pass the core message as the single query; storyboard beats are added later by HF
        candidates = match_assets(project_dir, [result.message])
        if candidates and candidates[0]:
            logger.info("Top asset candidate: %s", candidates[0][0].get("filename"))

    # ⑤ Delegate to HF workflow
    print_delegation_instructions(project_dir)
    return project_dir


def guard(compositions_dir: Path, project_dir: Path | None = None) -> bool:
    """Run Rule Guard on compositions_dir. Returns True if no unknown violations."""
    result = guard_scan(compositions_dir)
    if result.fixed:
        logger.info("Rule Guard fixed %d violation(s)", len(result.fixed))
    if result.unknown:
        logger.warning("Rule Guard: %d unknown violation(s) need manual fix:", len(result.unknown))
        for v in result.unknown:
            logger.warning("  [%s] %s:%d — %s", v.rule_id, v.file.name, v.line, v.detail)
    if project_dir:
        save_history(project_dir, result)
    return result.ok
