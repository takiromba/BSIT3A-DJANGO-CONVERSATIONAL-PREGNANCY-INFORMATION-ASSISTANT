from importlib import import_module

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Idempotently add the built-in pregnancy topics and FAQ content."

    def handle(self, *args, **options):
        migration = import_module("apps.core.migrations.0002_seed_pregnancy_library")
        migration.seed_library(django_apps, None)
        self.stdout.write(
            self.style.SUCCESS("Pregnancy topic and FAQ content is up to date.")
        )
