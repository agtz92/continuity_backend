"""Señal en vivo para las preferencias (tema, paleta, idioma…).

`NotificationSettings` guarda también las preferencias generales del usuario.
Sin este trigger, cambiar el tema en una pestaña o en el móvil no avisaba a las
demás: `core_live_change_signals` (core 0036) solo cubría las tablas del
dashboard. Reutiliza la misma función `notify_user_change()`, con sus mismos
blindajes (la escritura nunca falla por el aviso, interruptor `app.live_off`).

Apagado de emergencia, sin deploy:
``alter table notifications_notificationsettings disable trigger notifications_notificationsettings_live;``
"""

from django.db import migrations

from core.migrations._pg import postgres_only

TABLE = "notifications_notificationsettings"

TRIGGER_SQL = f"""
drop trigger if exists {TABLE}_live on public.{TABLE};
create trigger {TABLE}_live
  after insert or update or delete on public.{TABLE}
  for each row execute function public.notify_user_change();
"""

DROP_TRIGGER_SQL = f"drop trigger if exists {TABLE}_live on public.{TABLE};"


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0014_stalled_alert_label"),
        ("core", "0036_live_change_signals"),
    ]

    operations = [
        postgres_only(TRIGGER_SQL, DROP_TRIGGER_SQL),
    ]
