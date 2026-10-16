#!/usr/bin/env bash
# Runs flatpak-builder-lint. Errors caused only by the patsinclair1 placeholder / unpublished
# repo are advisory until patsinclair1 is replaced; any other error fails the job.
set -uo pipefail
kind="$1"; target="$2"
if command -v flatpak-builder-lint >/dev/null; then LINT=(flatpak-builder-lint)
else LINT=(flatpak run --command=flatpak-builder-lint org.flatpak.Builder); fi
out=$("${LINT[@]}" --exceptions "$kind" "$target" 2>&1); rc=$?
echo "$out"
[ $rc -eq 0 ] && exit 0
python3 - "$out" <<'EOF'
import json, sys, re
raw = sys.argv[1]
try:
    d = json.loads(raw[raw.index("{"):])
except Exception:
    print("::error::flatpak-builder-lint did not return JSON"); sys.exit(1)
import os
known = {"appid-url-not-reachable", "appstream-missing-screenshots",
         "appstream-screenshots-not-mirrored-in-ostree", "appid-code-hosting-too-few-components"}
if os.environ.get("LINT_STRICT") == "1":
    known = set()  # strict once patsinclair1 is replaced
errs = set(d.get("errors", []))
real = errs - known
for e in sorted(errs & known):
    print(f"::warning::advisory until patsinclair1 is set and the repo is public: {e}")
if real:
    for e in sorted(real): print(f"::error::flatpak-builder-lint: {e}")
    sys.exit(1)
EOF
