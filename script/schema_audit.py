"""
Gate I4 schema audit — HealthPay trial-1.

Compares every field of every installed Django model against the physical
PostgreSQL schema (information_schema via Django introspection), then asserts
the Egypt localization seeds. Exit code 0 = gate green; 1 = gate red with a
printed defect list. `django_migrations` is never consulted — per plan v3 §4,
migration state is not schema evidence.

Run inside the backend container (does NOT need to be baked into the image):

  docker compose cp schema_audit.py backend:/tmp/schema_audit.py
  docker compose exec backend python manage.py shell -c "exec(open('/tmp/schema_audit.py').read())"

Run it first against the rehearsal database (point DB_NAME at IMIS_rehearsal),
then against the real one.
"""
import sys

from django.apps import apps
from django.db import connection

failures = []
checked_models = 0
checked_fields = 0

with connection.cursor() as cursor:
    table_names = set(connection.introspection.table_names(cursor))

    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if not meta.managed or meta.proxy:
            continue
        table = meta.db_table
        checked_models += 1
        if table not in table_names:
            failures.append(f"MISSING TABLE: {table} (model {meta.label})")
            continue
        try:
            desc = connection.introspection.get_table_description(cursor, table)
        except Exception as e:  # noqa: BLE001
            failures.append(f"DESCRIBE FAILED: {table}: {e}")
            continue
        physical_cols = {c.name for c in desc}
        for field in meta.local_concrete_fields:
            checked_fields += 1
            col = field.column
            if col and col not in physical_cols:
                failures.append(
                    f"MISSING COLUMN: {table}.{col} (model {meta.label}, field {field.name})"
                )

print(f"[audit] models checked: {checked_models}, fields checked: {checked_fields}")

# --- Egypt localization assertions -----------------------------------------
try:
    from core.models import Language

    ar = Language.objects.filter(code="ar").first()
    if not ar:
        failures.append("SEED: Language 'ar' not registered in core Language table")
    else:
        print(f"[audit] Language 'ar' present: {ar.name}")
except Exception as e:  # noqa: BLE001
    failures.append(f"SEED CHECK FAILED (Language): {e}")

try:
    from location.models import Location

    n = Location.objects.filter(type="R", validity_to__isnull=True).count()
    if n != 27:
        failures.append(f"SEED: expected exactly 27 active type-R governorates, found {n}")
    else:
        sample = list(
            Location.objects.filter(type="R", validity_to__isnull=True)
            .values_list("name", flat=True)[:3]
        )
        print(f"[audit] 27 governorates seeded (sample: {sample})")
except Exception as e:  # noqa: BLE001
    failures.append(f"SEED CHECK FAILED (governorates): {e}")

try:
    from egypt_localization.validators import parse_national_id

    parse_national_id("29001011234567")  # must pass
    try:
        parse_national_id("19001011234567")  # must fail (century)
        failures.append("VALIDATOR: bad-century National ID was accepted")
    except Exception:
        pass
    print("[audit] National ID validator behaves as expected")
except Exception as e:  # noqa: BLE001
    failures.append(f"VALIDATOR CHECK FAILED: {e}")

# --- History tables for historical models (django-simple-history pattern) ---
hist_missing = [f for f in failures if "historical" in f.lower()]
# (historical models are included in apps.get_models(); no extra pass needed)

print("=" * 60)
if failures:
    print(f"GATE I4: RED — {len(failures)} defects")
    for f in failures:
        print("  -", f)
    sys.exit(1)
else:
    print("GATE I4: GREEN — physical schema matches models; Egypt seeds verified")
