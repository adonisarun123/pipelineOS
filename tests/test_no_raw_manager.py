"""§7 lint rule as a test: `.unscoped` forbidden outside tenants/, migrations, tests."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALLOWED = {"tenants", "tests"}
PATTERN = re.compile(r"\.unscoped\b")


def test_no_unscoped_manager_outside_allowlist():
    violations = []
    for py in ROOT.rglob("*.py"):
        rel = py.relative_to(ROOT)
        top = rel.parts[0]
        if top in ALLOWED or "migrations" in rel.parts:
            continue
        for lineno, line in enumerate(py.read_text().splitlines(), 1):
            if PATTERN.search(line) and not line.strip().startswith("#"):
                violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, "Unscoped manager use forbidden:\n" + "\n".join(violations)
