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
import json
import sys
import zipfile

path = sys.argv[1]
required = {
    "ugc-talking-head/assets/fonts/Inter-Bold.ttf": 10_000,
    "ugc-talking-head/assets/fonts/OFL.txt": 500,
    "ugc-talking-head/assets/music/bed.m4a": 1_000,
    "ugc-talking-head/template/public/fonts/Inter-Bold.ttf": 10_000,
    "ugc-talking-head/template/public/placeholder.mp4": 1_000,
    "ugc-talking-head/template/package-lock.json": 1_000,
}
with zipfile.ZipFile(path) as zf:
    names = zf.namelist()
    info = {item.filename: item for item in zf.infolist()}
    if "ugc-talking-head/SKILL.md" not in names:
        sys.exit("zip is missing ugc-talking-head/SKILL.md")
    if "SKILL.md" in names:
        sys.exit("SKILL.md must not sit at the archive root")
    if any(name.startswith("ugc-talking-head/template/node_modules/") for name in names):
        sys.exit("node_modules leaked into the archive")
    missing = [name for name in required if name not in info]
    if missing:
        sys.exit("zip missing runtime files: " + ", ".join(missing))
    small = [
        f"{name} ({info[name].file_size} bytes)"
        for name, minimum in required.items()
        if info[name].file_size < minimum
    ]
    if small:
        sys.exit("runtime files look like placeholders: " + ", ".join(small))
    font = zf.read("ugc-talking-head/assets/fonts/Inter-Bold.ttf")
    font_public = zf.read("ugc-talking-head/template/public/fonts/Inter-Bold.ttf")
    if font[:4] != b"\x00\x01\x00\x00":
        sys.exit("assets font is not a TrueType file")
    if font != font_public:
        sys.exit("template font does not match assets/fonts/Inter-Bold.ttf")
    for media in (
        "ugc-talking-head/assets/music/bed.m4a",
        "ugc-talking-head/template/public/placeholder.mp4",
    ):
        if zf.read(media)[4:8] != b"ftyp":
            sys.exit(f"{media} is not an ISO BMFF file")
    lock = json.loads(zf.read("ugc-talking-head/template/package-lock.json"))
    deps = lock.get("packages", {}).get("", {}).get("dependencies", {})
    if lock.get("lockfileVersion") != 3 or lock.get("name") != "ugc-talking-head-template":
        sys.exit("package-lock.json is not the Remotion template lock")
    if deps.get("remotion") != "4.0.541" or deps.get("@remotion/cli") != "4.0.541":
        sys.exit("package-lock.json does not pin Remotion 4.0.541")
print(f"{len(names)} entries, layout and runtime assets ok")
PY

ls -lh "$DIST/ugc-talking-head.zip" "$DIST/ugc-talking-head.skill"
