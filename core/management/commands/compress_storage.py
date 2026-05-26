"""Re-encode existing images in Supabase Storage as WebP and update DB references.

One-shot backfill. Walks the `avatars` and/or `blog` buckets, downloads each
image, recompresses it as WebP, uploads the new file alongside the original
(`foo.png` -> `foo.webp`), and rewrites any `cover_image_url` columns that
pointed at the old URL.

Originals are left in place. Verify the result in Studio and delete them
manually when satisfied — the script is intentionally non-destructive.

Talks to Storage via raw HTTP rather than supabase-py because the SDK's
constructor rejects the new `sb_secret_*` key format (its regex still
requires a JWT shape). Endpoints are stable since storage-api v0.x.

Usage:
    python manage.py compress_storage                       # dry-run, all buckets
    python manage.py compress_storage --apply               # actually upload + UPDATE
    python manage.py compress_storage --bucket avatars      # one bucket only
    python manage.py compress_storage --quality 75 --max-width 1600
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Iterator

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image, ImageOps

from core.cms.models import BlogPost, HelpResource, Page

BUCKET_AVATARS = "avatars"
BUCKET_BLOG = "blog"
SUPPORTED_BUCKETS = (BUCKET_AVATARS, BUCKET_BLOG)

# Extensions we will attempt to re-encode. Everything else is skipped.
# GIF stays out because Pillow→WebP loses animation unless we go through a
# dedicated animated-webp encoder, and SVG is text we don't want to rasterize.
SOURCE_EXTS = {".png", ".jpg", ".jpeg"}

REQUEST_TIMEOUT = 60  # seconds


@dataclass
class Result:
    processed: int = 0
    skipped: int = 0
    errors: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    url_updates: dict[str, int] = field(default_factory=dict)


class Command(BaseCommand):
    help = "Recompress avatars and blog covers to WebP; update DB URL columns."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually upload + update DB. Default is dry-run.",
        )
        parser.add_argument(
            "--bucket",
            choices=(*SUPPORTED_BUCKETS, "all"),
            default="all",
        )
        parser.add_argument("--quality", type=int, default=80)
        parser.add_argument(
            "--max-width",
            type=int,
            default=1920,
            help="Max width for blog covers. Avatars are never resized.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Stop after N files per bucket (0 = no limit). For testing.",
        )

    def handle(self, *args, **opts):
        url = settings.SUPABASE_URL
        key = getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            raise CommandError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in backend/.env "
                "(loaded via python-decouple)."
            )

        apply = bool(opts["apply"])
        quality = int(opts["quality"])
        max_width = int(opts["max_width"])
        limit = int(opts["limit"])
        buckets = (
            SUPPORTED_BUCKETS if opts["bucket"] == "all" else (opts["bucket"],)
        )

        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(self.style.WARNING(f"[{mode}] quality={quality} max-width={max_width}"))

        client = _StorageClient(url, key)
        total = Result()

        for bucket in buckets:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== bucket: {bucket} ==="))
            resize = max_width if bucket == BUCKET_BLOG else 0
            result = self._process_bucket(
                client, bucket, quality=quality, max_width=resize, limit=limit, apply=apply
            )
            self._merge(total, result)
            self._print_bucket_summary(bucket, result)

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== total ==="))
        self._print_bucket_summary("all", total)

        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    "\nDry-run: nothing uploaded, nothing updated. Re-run with --apply."
                )
            )

    # ------------------------------------------------------------------ bucket

    def _process_bucket(
        self,
        client: "_StorageClient",
        bucket: str,
        *,
        quality: int,
        max_width: int,
        limit: int,
        apply: bool,
    ) -> Result:
        result = Result()
        url_mapping: dict[str, str] = {}

        count = 0
        for path in client.walk(bucket, ""):
            ext = _ext(path)
            if ext == ".webp":
                continue  # already converted
            if ext not in SOURCE_EXTS:
                result.skipped += 1
                self.stdout.write(f"  skip (unsupported ext): {path}")
                continue

            count += 1
            if limit and count > limit:
                self.stdout.write(f"  (limit {limit} reached)")
                break

            new_path = path[: -len(ext)] + ".webp"

            try:
                original = client.download(bucket, path)
            except Exception as exc:
                result.errors += 1
                self.stderr.write(f"  download FAILED {path}: {exc}")
                continue

            try:
                compressed = _to_webp(original, quality=quality, max_width=max_width)
            except Exception as exc:
                result.errors += 1
                self.stderr.write(f"  encode FAILED {path}: {exc}")
                continue

            before = len(original)
            after = len(compressed)
            result.bytes_before += before
            result.bytes_after += after
            result.processed += 1

            pct = (1 - after / before) * 100 if before else 0
            self.stdout.write(
                f"  {path} -> {new_path}  "
                f"{_fmt_bytes(before)} -> {_fmt_bytes(after)}  (-{pct:.0f}%)"
            )

            if not apply:
                continue

            try:
                client.upload(bucket, new_path, compressed)
            except Exception as exc:
                result.errors += 1
                self.stderr.write(f"  upload FAILED {new_path}: {exc}")
                continue

            url_mapping[client.public_url(bucket, path)] = client.public_url(bucket, new_path)

        if apply and bucket == BUCKET_BLOG and url_mapping:
            self._update_cover_urls(url_mapping, result)

        return result

    # ------------------------------------------------------------------ db

    def _update_cover_urls(self, mapping: dict[str, str], result: Result) -> None:
        models = [
            ("BlogPost", BlogPost),
            ("Page", Page),
            ("HelpResource", HelpResource),
        ]
        for label, model in models:
            count = 0
            for old, new in mapping.items():
                count += model.objects.filter(cover_image_url=old).update(
                    cover_image_url=new
                )
            result.url_updates[label] = count
            self.stdout.write(f"  DB: updated {count} {label}.cover_image_url rows")

    # ------------------------------------------------------------------ output

    def _print_bucket_summary(self, name: str, r: Result) -> None:
        saved = r.bytes_before - r.bytes_after
        pct = (saved / r.bytes_before * 100) if r.bytes_before else 0
        self.stdout.write(
            f"  [{name}] processed={r.processed} skipped={r.skipped} errors={r.errors}  "
            f"saved={_fmt_bytes(saved)} ({pct:.0f}%)"
        )
        for label, n in r.url_updates.items():
            self.stdout.write(f"    {label}: {n} URL(s) updated")

    def _merge(self, total: Result, other: Result) -> None:
        total.processed += other.processed
        total.skipped += other.skipped
        total.errors += other.errors
        total.bytes_before += other.bytes_before
        total.bytes_after += other.bytes_after
        for k, v in other.url_updates.items():
            total.url_updates[k] = total.url_updates.get(k, 0) + v


# ---------------------------------------------------------------------- HTTP


class _StorageClient:
    """Tiny wrapper around the storage-v1 REST API.

    Service-role JWT *or* `sb_secret_*` key both work — the gateway only cares
    that the apikey header has admin privileges; it never parses the key.
    """

    def __init__(self, base_url: str, service_key: str):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
            }
        )

    def walk(self, bucket: str, prefix: str) -> Iterator[str]:
        endpoint = f"{self.base}/storage/v1/object/list/{bucket}"
        offset = 0
        page_size = 1000
        while True:
            body = {
                "prefix": prefix,
                "limit": page_size,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            }
            r = self.session.post(endpoint, json=body, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            entries = r.json() or []
            if not entries:
                break

            for entry in entries:
                name = entry.get("name")
                if not name or name == ".emptyFolderPlaceholder":
                    continue
                sub = f"{prefix}/{name}" if prefix else name
                # Folder entries report id=None.
                if entry.get("id") is None:
                    yield from self.walk(bucket, sub)
                else:
                    yield sub

            if len(entries) < page_size:
                break
            offset += page_size

    def download(self, bucket: str, path: str) -> bytes:
        url = f"{self.base}/storage/v1/object/{bucket}/{path}"
        r = self.session.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.content

    def upload(self, bucket: str, path: str, body: bytes) -> None:
        url = f"{self.base}/storage/v1/object/{bucket}/{path}"
        headers = {
            "Content-Type": "image/webp",
            "Cache-Control": "max-age=31536000",
            "x-upsert": "true",
        }
        r = self.session.post(url, data=body, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()

    def public_url(self, bucket: str, path: str) -> str:
        return f"{self.base}/storage/v1/object/public/{bucket}/{path}"


# ---------------------------------------------------------------------- helpers


def _ext(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:].lower() if dot >= 0 else ""


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def _to_webp(data: bytes, *, quality: int, max_width: int) -> bytes:
    img = Image.open(io.BytesIO(data))
    # Honor EXIF orientation so portraits don't end up sideways.
    img = ImageOps.exif_transpose(img)

    # WebP supports RGBA; convert palette/CMYK to a mode it can encode.
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGBA" if "A" in img.mode else "RGB")

    if max_width and img.width > max_width:
        ratio = max_width / img.width
        new_size = (max_width, max(1, round(img.height * ratio)))
        img = img.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()
