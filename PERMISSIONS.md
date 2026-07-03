# Permission Matrix (U-1/U-2) — enforced state

Roles: **Admin**, **Manager**, **Member**, **ReadOnly**. Visibility model (U-2):
record owner + owner's team manager + admins; queryset-scoped, so invisible records
return 404 (no existence leak). All rows below are covered by tests.

| Capability | Admin | Manager | Member | ReadOnly |
|---|---|---|---|---|
| View records | all | own team | own | own (read) |
| Create/edit own records | ✓ | ✓ | ✓ | ✗ (403) |
| Edit others' records | ✓ | team only (via visibility) | ✗ (404) | ✗ |
| Delete (soft) records | ✓ | ✓ (team-visible) | ✗ (403) | ✗ |
| Bulk edit (C-6) | ✓ | ✓ | ✗ | ✗ |
| Export CSV (I-3, audit-logged) | ✓ | ✓ | ✗ | ✗ |
| Import CSV (I-1, audit-logged) | ✓ | ✓ | ✗ | ✗ |
| Configure pipelines/stages | ✓ | ✗ | ✗ | ✗ |
| Configure custom fields / sources / reasons / products / activity types | ✓ | ✗ | ✗ | ✗ |
| Create users / set roles | ✓ | ✗ | ✗ | ✗ |
| Deactivate user (kills tokens) / transfer records (U-3) | ✓ | ✗ | ✗ | ✗ |
| Read audit log (U-4) | ✓ | ✗ | ✗ | ✗ |
| Saved views: create own / share with team | ✓ | ✓ | ✓ | ✓ (own) |
| Edit/delete others' saved views | ✓ | ✗ | ✗ | ✗ |
| Notifications: own only | ✓ | ✓ | ✓ | ✓ |

Notes:
- Deletes are **soft** everywhere (is_deleted flag); hard delete does not exist in the API.
- Products/config reads are open to all roles (reps need catalogue prices).
- Email digest goes to every active user with an email address.
