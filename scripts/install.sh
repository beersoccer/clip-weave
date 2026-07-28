#!/usr/bin/env bash
# One-command setup for clip-weave + all HyperFrames dependencies.
# Run from the clip-weave project root: bash scripts/install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Step 1: HyperFrames skills → ~/.claude/skills/ ==="
# skills update exits non-zero if GitHub is unreachable — treat as a soft failure
npx hyperframes skills update && echo "HyperFrames skills updated." || \
    echo "⚠️  skills update failed (network?). Skills already on disk will be used."

echo ""
echo "=== Step 2: clip-weave Python package (Rule Guard, Asset Matcher) ==="
cd "$PROJECT_ROOT"
if command -v uv &>/dev/null; then
    uv pip install -e ".[dev]"
else
    pip install -e ".[dev]"
fi
echo "Python package installed."

echo ""
echo "=== Setup complete ==="
echo "Verify:"
echo "  uv run python -m clip_weave --help    # Rule Guard + Asset Matcher available"
echo ""
echo "Audio (TTS + BGM) requires HeyGen network access — see docs/architecture.md § 10."
