"""Scans the source tree for calls that would write or transmit raw image
data, and fails if any are found outside tests/ and scripts/dev_only/.

This is the automated enforcement of the Zero-Frame Architecture invariant
described in CLAUDE.md.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

BANNED_PATTERNS = [
    re.compile(r"cv2\.imwrite\s*\("),
    re.compile(r"cv2\.VideoWriter\s*\("),
    re.compile(r"\.save\s*\(.*\.(jpg|jpeg|png|bmp)", re.IGNORECASE),
    re.compile(r"imencode\s*\("),
]

ALLOWED_DIRS = {"tests", "scripts/dev_only"}
SCAN_DIRS = ["storesmart", "scripts", "dashboard"]


def _is_allowed(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    return any(rel.startswith(allowed) for allowed in ALLOWED_DIRS)


def test_no_image_writes_outside_allowed_dirs():
    violations = []
    for scan_dir in SCAN_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if _is_allowed(path):
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in BANNED_PATTERNS:
                if pattern.search(text):
                    violations.append(f"{path.relative_to(REPO_ROOT)}: matched {pattern.pattern!r}")
    assert not violations, "Found image-writing calls outside tests/ and scripts/dev_only/:\n" + "\n".join(violations)
