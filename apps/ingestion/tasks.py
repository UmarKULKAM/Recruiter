from celery import shared_task


@shared_task(name="apps.ingestion.tasks.ingest_fixture_feed")
def ingest_fixture_feed():
    """05:00 Africa/Kampala entry. Runs the fixture path until a real feed exists."""
    from apps.ingestion.feed import ingest_fixture_feed as run

    return run()
