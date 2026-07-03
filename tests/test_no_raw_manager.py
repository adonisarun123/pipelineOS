"""§7 lint rule as a test: `.unscoped` forbidden outside tenants/, migrations, tests."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALLOWED = {"tenants", "tests"}
# api/capture.py: L-7 capture must resolve a tenant FROM the source token —
# the one reviewed, deliberate cross-tenant lookup (see its module docstring).
ALLOWED_FILES = {"api/capture.py"}
PATTERN = re.compile(r"\.unscoped\b")


def test_no_unscoped_manager_outside_allowlist():
    violations = []
    for py in ROOT.rglob("*.py"):
        rel = py.relative_to(ROOT)
        top = rel.parts[0]
        if top in ALLOWED or "migrations" in rel.parts \
                or str(rel).replace("\\", "/") in ALLOWED_FILES:
            continue
        for lineno, line in enumerate(py.read_text().splitlines(), 1):
            if PATTERN.search(line) and not line.strip().startswith("#"):
                violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, "Unscoped manager use forbidden:\n" + "\n".join(violations)
