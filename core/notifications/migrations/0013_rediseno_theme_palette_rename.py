"""Rediseño 2026 — renombra temas y reduce las paletas a cinco curadas.

Una sola pasada sobre NotificationSettings:

  continuuit → continuu        dark → carbon        (light y system no cambian)

  default·continuuit → ocre    green·turquoise → salvia
  pink·cute·complimentary → ciruela
  business·midnight·retro → hielo
  neon·sunset·boho → oxido

El mapa es el de PLAN_REDISENO.md §4, espejado en
frontend/src/design/tokens.json (legacyPalettes) y en
frontend/src/palette/config.ts (LEGACY_PALETTE_MAP).

Los nombres viejos siguen siendo entrada VÁLIDA en el schema (ver
SUPPORTED_THEMES / SUPPORTED_PALETTES): la app nativa queda fuera del rediseño
y aún los manda. Esta migración solo reescribe lo ya guardado; retirar los
valores viejos es trabajo de la ola de limpieza, y no antes de migrar móvil.

`palette` cambia de default a "ocre" para que las cuentas nuevas no nazcan con
un valor retirado. La reversa deja los datos en el equivalente más cercano,
no en el valor original: la migración no es informativa en sentido inverso
(tres paletas viejas colapsan en una nueva).
"""

from django.db import migrations, models

THEME_FORWARD = {"continuuit": "continuu", "dark": "carbon"}
THEME_BACKWARD = {"continuu": "continuuit", "carbon": "dark"}

PALETTE_FORWARD = {
    "default": "ocre",
    "continuuit": "ocre",
    "green": "salvia",
    "turquoise": "salvia",
    "pink": "ciruela",
    "cute": "ciruela",
    "complimentary": "ciruela",
    "business": "hielo",
    "midnight": "hielo",
    "retro": "hielo",
    "neon": "oxido",
    "sunset": "oxido",
    "boho": "oxido",
}
PALETTE_BACKWARD = {
    "ocre": "default",
    "salvia": "green",
    "ciruela": "pink",
    "hielo": "business",
    "oxido": "neon",
}


def _remap(apps, theme_map, palette_map):
    Settings = apps.get_model("notifications", "NotificationSettings")
    for old, new in theme_map.items():
        Settings.objects.filter(theme=old).update(theme=new)
    for old, new in palette_map.items():
        Settings.objects.filter(palette=old).update(palette=new)


def forward(apps, schema_editor):
    _remap(apps, THEME_FORWARD, PALETTE_FORWARD)


def backward(apps, schema_editor):
    _remap(apps, THEME_BACKWARD, PALETTE_BACKWARD)


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0012_notificationsettings_calendar_feed_token_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notificationsettings",
            name="palette",
            field=models.CharField(default="ocre", max_length=20),
        ),
        migrations.RunPython(forward, backward),
    ]
