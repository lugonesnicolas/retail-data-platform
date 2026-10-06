#!/usr/bin/env bash
# Renders docs/assets/social-preview.svg to a 1280x640 PNG (GitHub / LinkedIn social preview).
#
# Needs Node.js and Playwright's Chromium (`npx playwright install chromium` once). Playwright is
# used instead of a bare `chromium --screenshot` because it pins the viewport to exactly 1280x640.
# Run from anywhere:
#   scripts/render-social-preview.sh
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
svg="$root/docs/assets/social-preview.svg"
png="$root/docs/assets/social-preview.png"

npx --yes playwright screenshot --viewport-size=1280,640 "file://$svg" "$png"
echo "wrote $png"
