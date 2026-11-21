"""
Delete unidentified scans (and their photos) older than the retention period.

Visitor photos can show people, so they are not kept forever. Run this regularly:
    python manage.py purge_unidentified_scans              # older than 90 days
    python manage.py purge_unidentified_scans --days 30
    python manage.py purge_unidentified_scans --dry-run    # only count them
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from portal.models import StoredFile, UnidentifiedScan

DEFAULT_DAYS = 90


class Command(BaseCommand):
    help = "Delete unidentified scans and their photos older than --days (default 90)"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, days, dry_run, **opts):
        if days < 1:
            self.stderr.write("--days must be at least 1.")
            return
        cutoff = timezone.now() - timedelta(days=days)
        old = UnidentifiedScan.objects.filter(scanned_at__lt=cutoff)
        photo_names = list(old.values_list("photo", flat=True))
        if dry_run:
            self.stdout.write(f"{len(photo_names)} scan(s) older than {days} days would be deleted.")
            return
        old.delete()
        names = [n for n in photo_names if n]
        for i in range(0, len(names), 500):     # SQL Server allows ~2100 parameters per query
            StoredFile.objects.filter(name__in=names[i:i + 500]).delete()
        self.stdout.write(f"Deleted {len(photo_names)} scan(s) older than {days} days.")
