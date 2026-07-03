"""CSV import (I-1): map → dedupe → dry-run → import with per-row errors.

Phase 1 scope: People (with organization auto-create) CSV. Synchronous;
moves to Celery when the async infra lands in Phase 2 (spec §7).
"""
import csv
import io
from dataclasses import dataclass, field

from django.db import transaction

from accounts.models import User

from .models import Organization, Person, PersonEmail, PersonPhone
from .services import normalize_phone

PERSON_FIELDS = ["first_name", "last_name", "email", "phone", "organization", "job_title"]

# Header aliases for auto-mapping (I-1 "auto-detect columns")
ALIASES = {
    "first_name": {"first name", "firstname", "first", "name"},
    "last_name": {"last name", "lastname", "last", "surname"},
    "email": {"email", "e-mail", "email address", "mail"},
    "phone": {"phone", "mobile", "phone number", "contact", "whatsapp"},
    "organization": {"organization", "organisation", "company", "org", "account"},
    "job_title": {"job title", "title", "designation", "role"},
}
DEDUPE_STRATEGIES = ("skip", "update", "create")


def auto_map(headers: list[str]) -> dict[str, str | None]:
    """Guess field for each CSV header; None = ignored."""
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for h in headers:
        key = h.strip().lower()
        hit = next((f for f, names in ALIASES.items() if key in names and f not in used), None)
        if hit:
            used.add(hit)
        mapping[h] = hit
    return mapping


@dataclass
class ImportReport:
    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)  # dry-run only

    def as_dict(self) -> dict:
        return self.__dict__


def _find_existing(email: str, phone_norm: str) -> Person | None:
    if email:
        hit = PersonEmail.objects.filter(email__iexact=email).select_related("person").first()
        if hit:
            return hit.person
    if phone_norm:
        hit = PersonPhone.objects.filter(normalized=phone_norm).select_related("person").first()
        if hit:
            return hit.person
    return None


def import_people_csv(*, content: str, mapping: dict[str, str | None], strategy: str,
                      user: User, dry_run: bool) -> ImportReport:
    """Row-by-row so one bad row never kills the batch (per-row error report)."""
    if strategy not in DEDUPE_STRATEGIES:
        raise ValueError(f"strategy must be one of {DEDUPE_STRATEGIES}")
    reader = csv.DictReader(io.StringIO(content))
    report = ImportReport()
    org_cache: dict[str, Organization] = {}

    for i, raw_row in enumerate(reader, start=2):  # row 1 = header
        report.total += 1
        row = {f: (raw_row.get(h) or "").strip()
               for h, f in mapping.items() if f}
        if not row.get("first_name"):
            report.errors.append({"row": i, "error": "first_name is required"})
            continue
        email = row.get("email", "")
        if email and "@" not in email:
            report.errors.append({"row": i, "error": f"invalid email: {email}"})
            continue
        phone_norm = normalize_phone(row.get("phone", "")) if row.get("phone") else ""
        existing = _find_existing(email, phone_norm)

        action = "create"
        if existing is not None:
            action = {"skip": "skip", "update": "update", "create": "create"}[strategy]
        if dry_run:
            report.preview.append({"row": i, "action": action, **row})
            _count(report, action)
            continue
        try:
            with transaction.atomic():
                _apply(row, email, phone_norm, existing if action == "update" else None,
                       action, org_cache, user)
            _count(report, action)
        except Exception as exc:  # per-row isolation; error carries context
            report.errors.append({"row": i, "error": str(exc)})
    return report


def _count(report: ImportReport, action: str) -> None:
    if action == "create":
        report.created += 1
    elif action == "update":
        report.updated += 1
    else:
        report.skipped += 1


def _apply(row: dict, email: str, phone_norm: str, existing: Person | None,
           action: str, org_cache: dict, user: User) -> None:
    if action == "skip":
        return
    org = None
    org_name = row.get("organization", "")
    if org_name:
        org = org_cache.get(org_name.lower()) or Organization.objects.filter(
            name__iexact=org_name).first()
        if org is None:
            org = Organization(name=org_name, created_by=user)
            org.save()
        org_cache[org_name.lower()] = org

    if existing is not None:  # update
        existing.first_name = row.get("first_name") or existing.first_name
        existing.last_name = row.get("last_name") or existing.last_name
        existing.job_title = row.get("job_title") or existing.job_title
        if org:
            existing.organization = org
        existing.save()
        person = existing
    else:
        person = Person(first_name=row["first_name"], last_name=row.get("last_name", ""),
                        job_title=row.get("job_title", ""), organization=org,
                        owner=user, created_by=user)
        person.save()
    if email and not person.emails.filter(email__iexact=email).exists():
        PersonEmail(person=person, email=email).save()
    if phone_norm and not person.phones.filter(normalized=phone_norm).exists():
        PersonPhone(person=person, raw=row.get("phone", ""), normalized=phone_norm).save()
