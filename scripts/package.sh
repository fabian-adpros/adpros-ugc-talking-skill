#!/usr/bin/env bash
# Build dist/ugc-talking-head.zip and dist/ugc-talking-head.skill.
# Both archives contain ugc-talking-head/SKILL.md at the top, not a root SKILL.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$ROOT/skills/ugc-talking-head"
DIST="$ROOT/dist"
STAGE="$DIST/.stage"

if [[ ! -f "$SKILL/SKILL.md" ]]; then
  echo "Missing $SKILL/SKILL.md" >&2
  exit 1
fi

rm -rf "$STAGE"
mkdir -p "$STAGE"
# Copy the skill folder, then drop files that do not belong in the upload.
tar -C "$ROOT/skills" \
  --exclude 'ugc-talking-head/.venv' \
  --exclude 'ugc-talking-head/template/node_modules' \
  --exclude 'ugc-talking-head/template/out' \
  --exclude 'ugc-talking-head/template/public/input.mp4' \
  --exclude 'ugc-talking-head/template/public/music.m4a' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  -cf - ugc-talking-head | tar -C "$STAGE" -xf -

python3 - "$SKILL/SKILL.md" <<'PY'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8")
if not text.startswith("---\n"):
    sys.exit("SKILL.md is missing YAML frontmatter")
end = text.find("\n---", 4)
block = text[4:end]
name = ""
desc = ""
for line in block.splitlines():
    if line.startswith("name:"):
        name = line.split(":", 1)[1].strip().strip('"')
    if line.startswith("description:"):
        desc = line.split(":", 1)[1].strip()
if name != "ugc-talking-head":
    sys.exit(f"name must be ugc-talking-head, got {name!r}")
if not desc or len(desc) > 1024:
    sys.exit(f"description length {len(desc)} is outside 1..1024")
print(f"frontmatter ok, description {len(desc)} chars")
PY

rm -f "$DIST/ugc-talking-head.zip" "$DIST/ugc-talking-head.skill"
(cd "$STAGE" && zip -r -X "$DIST/ugc-talking-head.zip" ugc-talking-head -x '*.DS_Store')
cp "$DIST/ugc-talking-head.zip" "$DIST/ugc-talking-head.skill"
rm -rf "$STAGE"

python3 - "$DIST/ugc-talking-head.zip" <<'PY'
import sys
import zipfile
path = sys.argv[1]
with zipfile.ZipFile(path) as zf:
    names = zf.namelist()
if "ugc-talking-head/SKILL.md" not in names:
    sys.exit("zip is missing ugc-talking-head/SKILL.md")
if "SKILL.md" in names:
    sys.exit("SKILL.md must not sit at the archive root")
if any(name.startswith("ugc-talking-head/template/node_modules/") for name in names):
    sys.exit("node_modules leaked into the archive")
print(f"{len(names)} entries, layout ok")
PY

ls -lh "$DIST/ugc-talking-head.zip" "$DIST/ugc-talking-head.skill"
