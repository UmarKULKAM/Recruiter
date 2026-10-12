from django.core.management.base import BaseCommand

from apps.ingestion.feed import ingest_fixture_feed


class Command(BaseCommand):
    help = (
        "Parse the local fixture feed with JOB_PARSER and save employment "
        "posts and procurement tenders."
    )

    def handle(self, *args, **options):
        counts = ingest_fixture_feed()
        self.stdout.write(
            "Saved {employment} employment post(s) and {tenders} "
            "procurement tender(s).".format(**counts)
        )
