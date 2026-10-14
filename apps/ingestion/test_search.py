import json
from datetime import date, datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.ingestion.models import EmploymentPosting, JobSearchRun, ProcurementTender
from apps.ingestion.search import (
    MODEL_ID,
    build_search_body,
    build_user_message,
    reference_date_from_user_message,
    render_listing,
)
from apps.ingestion.search_gate import (
    format_date,
    listing_qualifies,
    parse_explicit_date,
)
from apps.ingestion.search_http import Page
from apps.ingestion.search_sources import (
    EMPTY_SENTENCE,
    UNREAD_SENTENCE,
    TARGET_GROUPS,
    VerifiedListing,
    sweep_fuzu,
    sweep_ncba,
    sweep_qsourcing,
)
from apps.recruiting.models import ApplicationEvaluation

REFERENCE = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 9, 0)


def _page(url, text, status=200):
    return Page(url=url, status=status, text=text, ok=200 <= status < 300)


class DateGateTests(TestCase):
    def test_relative_phrase_and_missing_year_are_not_dates(self):
        self.assertIsNone(parse_explicit_date("Posted 6 Days Ago"))
        self.assertIsNone(parse_explicit_date("Closes 26 Oct"))
        self.assertIsNone(parse_explicit_date(""))

    def test_explicit_dates(self):
        self.assertEqual(parse_explicit_date("9 Oct 2026"), date(2026, 10, 9))
        self.assertEqual(parse_explicit_date("October 18TH, 2026"), date(2026, 10, 18))
        self.assertEqual(parse_explicit_date("10 th January, 2026"), date(2026, 1, 10))
        self.assertEqual(parse_explicit_date("2026-10-05T08:54:14+00:00"), date(2026, 10, 5))

    def test_window_and_deadline(self):
        self.assertTrue(listing_qualifies(date(2026, 9, 30), date(2026, 10, 18), REFERENCE))
        self.assertFalse(listing_qualifies(date(2026, 9, 29), date(2026, 10, 18), REFERENCE))
        self.assertFalse(listing_qualifies(None, date(2026, 10, 18), REFERENCE))
        self.assertFalse(listing_qualifies(date(2026, 10, 9), None, REFERENCE))
        self.assertFalse(listing_qualifies(date(2026, 10, 9), date(2026, 10, 13), REFERENCE))
        self.assertTrue(listing_qualifies(date(2026, 10, 9), date(2026, 10, 14), REFERENCE))
        self.assertFalse(
            listing_qualifies(
                date(2026, 10, 14),
                date(2026, 10, 14),
                REFERENCE,
                deadline_time=datetime.strptime("08:00", "%H:%M").time(),
                now=datetime(2026, 10, 14, 9, 0),
            )
        )
        self.assertTrue(
            listing_qualifies(
                date(2026, 10, 9),
                date(2026, 10, 18),
                REFERENCE,
                deadline_time=datetime.strptime("08:00", "%H:%M").time(),
                now=NOW,
            )
        )
        self.assertFalse(
            listing_qualifies(
                date(2026, 10, 9),
                date(2026, 10, 20),
                REFERENCE,
                closed=True,
            )
        )

    def test_reference_date_is_read_from_the_user_message(self):
        message = build_user_message(REFERENCE)
        self.assertEqual(message, "System reference date: 14 October 2026")
        self.assertEqual(reference_date_from_user_message(message), REFERENCE)


FUZU_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"http://schema.org","@type":"JobPosting","title":"Laboratory Officer",
 "datePosted":"2026-10-09","validThrough":"2026-10-18T00:00:00+00:00",
 "hiringOrganization":{"@type":"Organization","name":"Infectious Disease Institute"},
 "jobLocation":{"@type":"Place","address":{"addressLocality":"Kampala","addressCountry":"UG"}},
 "url":"https://www.fuzu.com/uganda/jobs/laboratory-officer"}
</script>
<title>Laboratory Officer at Infectious Disease Institute | Fuzu</title>
</head><body>
<p>Posted: 9 Oct 2026</p>
<p>Apply by: 17 Oct 2026</p>
<p>Kampala Uganda</p>
</body></html>
"""

OLD_FUZU_HTML = FUZU_HTML.replace("9 Oct 2026", "1 Sep 2026").replace(
    "2026-10-09", "2026-09-01"
)

UNDATED_FUZU_HTML = """
<html><head>
<script type="application/ld+json">
{"@type":"JobPosting","title":"Mystery Role","hiringOrganization":{"name":"Someone"},
 "url":"https://www.fuzu.com/uganda/jobs/mystery-role"}
</script></head><body><p>Posted 6 Days Ago</p></body></html>
"""


class SourceParserTests(TestCase):
    def test_fuzu_keeps_a_dated_open_role_and_uses_the_apply_by_line(self):
        job_url = "https://www.fuzu.com/uganda/jobs/laboratory-officer"

        def fetch(url, method="GET", json_body=None, timeout=25):
            if url.endswith("sitemap-job-listings.xml.gz"):
                return _page(
                    url,
                    "<sitemapindex><sitemap><loc>https://www.fuzu.com/uganda/sitemap-health.xml.gz</loc></sitemap></sitemapindex>",
                )
            if url.endswith("sitemap-health.xml.gz"):
                return _page(
                    url,
                    "<urlset><url><loc>"
                    + job_url
                    + "</loc><lastmod>2026-10-09T00:00:00+00:00</lastmod></url></urlset>",
                )
            if url == "https://www.fuzu.com/uganda/jobs":
                return _page(url, f'<a href="{job_url}">Laboratory Officer</a>')
            if url == job_url:
                return _page(job_url, FUZU_HTML)
            return _page(url, "", status=404)

        outcome = sweep_fuzu(REFERENCE, fetch, NOW)
        self.assertFalse(outcome.unread)
        self.assertEqual(len(outcome.listings), 1)
        item = outcome.listings[0]
        self.assertEqual(item.title, "Laboratory Officer")
        self.assertEqual(item.organization, "Infectious Disease Institute")
        self.assertEqual(item.location, "Kampala, Uganda")
        self.assertEqual(item.posted, date(2026, 10, 9))
        self.assertEqual(item.deadline, date(2026, 10, 17))
        self.assertEqual(item.url, job_url)
        text = render_listing(item)
        self.assertIn("Job Title: Laboratory Officer", text)
        self.assertIn(
            "Hiring Organization & Location: Infectious Disease Institute, Kampala, Uganda",
            text,
        )
        self.assertIn("Date Posted | Application Deadline: 9 Oct 2026 | 17 Oct 2026", text)
        self.assertIn(f"URL: {job_url}", text)

    def test_fuzu_drops_old_and_undated_pages(self):
        old_url = "https://www.fuzu.com/uganda/jobs/old-role"
        bare_url = "https://www.fuzu.com/uganda/jobs/mystery-role"

        def fetch(url, method="GET", json_body=None, timeout=25):
            if url.endswith("sitemap-job-listings.xml.gz"):
                return _page(
                    url,
                    "<sitemapindex><sitemap><loc>https://www.fuzu.com/child.xml.gz</loc></sitemap></sitemapindex>",
                )
            if url.endswith("child.xml.gz"):
                return _page(
                    url,
                    "<urlset>"
                    f"<url><loc>{old_url}</loc><lastmod>2026-10-02</lastmod></url>"
                    f"<url><loc>{bare_url}</loc><lastmod>2026-10-12</lastmod></url>"
                    "</urlset>",
                )
            if url == "https://www.fuzu.com/uganda/jobs":
                return _page(url, "")
            if url == old_url:
                return _page(url, OLD_FUZU_HTML)
            if url == bare_url:
                return _page(url, UNDATED_FUZU_HTML)
            return _page(url, "", status=404)

        outcome = sweep_fuzu(REFERENCE, fetch, NOW)
        self.assertFalse(outcome.unread)
        self.assertEqual(outcome.listings, ())

    def test_qsourcing_uses_the_stated_deadline_and_skips_a_filled_role(self):
        def fetch(url, method="GET", json_body=None, timeout=25):
            self.assertIn("job-listings", url)
            return _page(
                url,
                json.dumps(
                    [
                        {
                            "date": "2026-10-13T08:10:43",
                            "link": "https://qsourcing.com/job/junior-accountant/",
                            "title": {"rendered": "Junior Accountant"},
                            "content": {
                                "rendered": (
                                    "<p>On behalf of our client in the manufacturing sector. "
                                    "The deadline for applications is not later than "
                                    "8:00AM SUNDAY October 18TH, 2026 Only shortlisted.</p>"
                                )
                            },
                            "meta": {"_filled": 0, "_job_location": "Kampala"},
                        },
                        {
                            "date": "2026-10-08T19:36:26",
                            "link": "https://qsourcing.com/job/eacop-logistics-officer/",
                            "title": {"rendered": "Logistics Officer"},
                            "content": {
                                "rendered": (
                                    "<p>On behalf of our client EACOP , we are looking for a "
                                    "Logistics Officer. The deadline for applications is not "
                                    "later than 21 October 2026.</p>"
                                )
                            },
                            "meta": {"_filled": 0, "_job_location": "Uganda"},
                        },
                        {
                            "date": "2026-10-12T08:10:43",
                            "link": "https://qsourcing.com/job/filled-role/",
                            "title": {"rendered": "Filled Role"},
                            "content": {
                                "rendered": "deadline for applications is not later than 21 October 2026"
                            },
                            "meta": {"_filled": 1, "_job_location": "Kampala"},
                        },
                    ]
                ),
            )

        outcome = sweep_qsourcing(REFERENCE, fetch, NOW)
        self.assertEqual(len(outcome.listings), 2)
        item = outcome.listings[0]
        self.assertEqual(item.title, "Junior Accountant")
        self.assertEqual(item.organization, "Q-Sourcing Servtec")
        self.assertEqual(item.location, "Kampala")
        self.assertEqual(item.deadline, date(2026, 10, 18))
        self.assertEqual(item.url, "https://qsourcing.com/job/junior-accountant/")
        client = outcome.listings[1]
        self.assertEqual(client.organization, "EACOP")
        self.assertEqual(client.location, "Uganda")
        self.assertEqual(client.deadline, date(2026, 10, 21))

    def test_ncba_keeps_a_uganda_role_and_drops_one_without_a_country(self):
        uganda = "https://ncbagroup.com/blog/job/trade-finance-officer/"
        other = "https://ncbagroup.com/blog/job/other-role/"

        def fetch(url, method="GET", json_body=None, timeout=25):
            if url.endswith("job-sitemap.xml"):
                return _page(
                    url,
                    "<urlset>"
                    f"<url><loc>{uganda}</loc><lastmod>2026-10-05T08:54:14+00:00</lastmod></url>"
                    f"<url><loc>{other}</loc><lastmod>2026-10-06T00:00:00+00:00</lastmod></url>"
                    "</urlset>",
                )
            if url == uganda:
                return _page(
                    uganda,
                    """
                    <html><head>
                    <script type="application/ld+json">
                    {"@type":"WebPage","datePublished":"2026-10-05T08:54:14+00:00"}
                    </script>
                    <title>Trade Finance Officer - NCBA Group</title>
                    </head><body>
                    <h1>Trade Finance Officer</h1>
                    <p>Country: Uganda Closing on: 19 October 2026</p>
                    </body></html>
                    """,
                )
            if url == other:
                return _page(
                    other,
                    "<html><body><h1>Relationship Manager</h1>"
                    "<p>Country: Tanzania Closing on: 20 October 2026</p></body></html>",
                )
            return _page(url, "", status=404)

        outcome = sweep_ncba(REFERENCE, fetch, NOW)
        self.assertEqual([item.title for item in outcome.listings], ["Trade Finance Officer"])
        self.assertEqual(outcome.listings[0].organization_location, "NCBA Group, Uganda")
        self.assertEqual(outcome.listings[0].posted, date(2026, 10, 5))
        self.assertEqual(outcome.listings[0].deadline, date(2026, 10, 19))


class ReportAndApiTests(TestCase):
    def test_prompt_names_every_target(self):
        from django.conf import settings

        prompt = (settings.BASE_DIR / "prompts" / "job_search.txt").read_text()
        self.assertIn(EMPTY_SENTENCE, prompt)
        for group_name, targets in TARGET_GROUPS:
            self.assertIn(group_name.split()[0], prompt)
            for label, _sweeper in targets:
                self.assertIn(label, prompt)

    def test_failed_reads_do_not_invent_listings_or_posting_rows(self):
        def fetch(url, method="GET", json_body=None, timeout=25):
            return Page(url=url, status=0, text="", ok=False)

        body = build_search_body(REFERENCE, now=NOW, fetch=fetch)
        self.assertEqual(EmploymentPosting.objects.count(), 0)
        self.assertEqual(ProcurementTender.objects.count(), 0)
        for group_name, targets in TARGET_GROUPS:
            self.assertIn(group_name, body)
            for label, _sweeper in targets:
                self.assertIn(f"{label}\n{UNREAD_SENTENCE}", body)
        self.assertNotIn("Job Title:", body)

    def test_empty_target_uses_the_required_sentence(self):
        item = VerifiedListing(
            title="Office Attendant",
            organization="Q-Sourcing Servtec",
            location="Namanve",
            posted=date(2026, 10, 12),
            deadline=date(2026, 10, 18),
            url="https://qsourcing.com/job/office-attendant/",
        )
        rendered = render_listing(item)
        self.assertIn(format_date(item.posted), rendered)
        self.assertIn(EMPTY_SENTENCE, "No active listings within the 14-day window.")

    def test_post_stores_text_and_does_not_create_posts_or_scores(self):
        staff = User.objects.create_user("staffer", password="pw", is_staff=True)
        client = APIClient()
        client.force_authenticate(user=staff)

        def fetch(url, method="GET", json_body=None, timeout=25):
            return Page(url=url, status=0, text="", ok=False)

        with patch("apps.ingestion.search.live_fetch", fetch):
            response = client.post(reverse("job-search-runs"))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(JobSearchRun.objects.count(), 1)
        run = JobSearchRun.objects.get()
        self.assertEqual(run.model_id, MODEL_ID)
        self.assertEqual(run.user_message, response.data["user_message"])
        self.assertEqual(
            run.reference_date,
            reference_date_from_user_message(run.user_message),
        )
        self.assertEqual(run.body, response.data["body"])
        self.assertIn("Aggregators", run.body)
        self.assertIn("Public Sector", run.body)
        self.assertIn("Corporate", run.body)
        self.assertEqual(EmploymentPosting.objects.count(), 0)
        self.assertEqual(ProcurementTender.objects.count(), 0)
        self.assertEqual(ApplicationEvaluation.objects.count(), 0)

    def test_get_does_not_run_a_search_or_score(self):
        staff = User.objects.create_user("reader", password="pw", is_staff=True)
        JobSearchRun.objects.create(
            body="Aggregators\n\nThe Ugandan Jobline\n" + EMPTY_SENTENCE + "\n",
            model_id=MODEL_ID,
            reference_date=REFERENCE,
            user_message=build_user_message(REFERENCE),
        )
        client = APIClient()
        client.force_authenticate(user=staff)
        client.force_login(staff)
        with patch("apps.ingestion.search.live_fetch") as fetch:
            listed = client.get(reverse("job-search-runs"))
            page = client.get(reverse("staff-job-search"))
        fetch.assert_not_called()
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data["results"]), 1)
        self.assertEqual(JobSearchRun.objects.count(), 1)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Run job search")
        self.assertContains(page, "/api/ingestion/search-runs/")
        self.assertEqual(ApplicationEvaluation.objects.count(), 0)

    def test_a_candidate_cannot_run_the_search(self):
        person = User.objects.create_user("person", password="pw", is_staff=False)
        client = APIClient()
        client.force_authenticate(user=person)
        with patch("apps.ingestion.search.live_fetch") as fetch:
            response = client.post(reverse("job-search-runs"))
        fetch.assert_not_called()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(JobSearchRun.objects.count(), 0)
