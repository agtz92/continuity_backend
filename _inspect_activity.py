"""One-off inspection script — kept around for ad-hoc debugging."""
import os, django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "continuity.settings")
django.setup()

from django.db import connection
from django.db.models import Count
from core.models import Activity


def main() -> None:
    total = Activity.objects.count()
    print(f"Total Activity rows: {total}")
    for r in Activity.objects.values("kind").annotate(c=Count("id")).order_by("-c"):
        print(f"  {r['kind']:32s} {r['c']}")

    print("\nTables present:")
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name "
            "IN ('core_update', 'core_activitylog', 'core_activity')"
        )
        for (name,) in cur.fetchall():
            print(f"  - {name}")


if __name__ == "__main__":
    main()
