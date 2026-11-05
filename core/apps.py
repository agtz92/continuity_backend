from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _lock_new_tables(sender, using, **kwargs):
    # Re-applies the deny-all RLS posture after every migrate so tables added
    # by any app's future migrations are covered automatically (core/rls.py).
    from django.db import connections

    from core.rls import apply_rls_posture

    apply_rls_posture(connections[using])


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # dispatch_uid: run once per migrate, not once per app.
        post_migrate.connect(_lock_new_tables, dispatch_uid="core.rls.lock_new_tables")
