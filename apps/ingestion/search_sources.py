"""Read the Ugandan sources named in prompts/job_search.txt.

Each sweeper returns listings copied from a page it fetched. Sitemap dates and
relative phrases such as "posted 6 days ago" only decide which pages to open.
"""

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time
from urllib.parse import urljoin, urlparse

from apps.ingestion.search_gate import (
    format_date,
    listing_qualifies,
    parse_clock,
    parse_explicit_date,
    posted_in_window,
    text_says_closed,
)
from apps.ingestion.search_http import Page

EMPTY_SENTENCE = "No active listings within the 14-day window."
UNREAD_SENTENCE = "The source page could not be read, so no listing was verified."

_LABELED = re.compile(r"(?:{labels})\s*[:\-]?\s*(.{{0,100}})", re.IGNORECASE)
_JSON_LD = re.compile(
    r'(?is)<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>'
)
_H1 = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>")
_TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_HREF = re.compile(r"""(?is)href=["']([^"'#]+)""")


@dataclass(frozen=True)
class VerifiedListing:
    title: str
    organization: str
    location: str
    posted: date
    deadline: date
    url: str
    deadline_time: time | None = None

    @property
    def organization_location(self) -> str:
        organization = self.organization.strip()
        location = self.location.strip()
        if not location or location.lower() in organization.lower():
            return organization
        return f"{organization}, {location}"


@dataclass(frozen=True)
class SweepOutcome:
    listings: tuple[VerifiedListing, ...] = ()
    unread: bool = False


def pooled(urls, fetch, *, workers=8):
    ordered = list(dict.fromkeys(urls))
    if not ordered:
        return []

    def one(url):
        try:
            return fetch(url)
        except Exception:
            return Page(url=url, status=0, text="", ok=False)

    with ThreadPoolExecutor(max_workers=min(workers, len(ordered))) as pool:
        return list(pool.map(one, ordered))


def html_to_text(source: str) -> str:
    without = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", source or "")
    without = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", without)
    without = re.sub(r"(?is)<[^>]+>", " ", without)
    without = html.unescape(without)
    return re.sub(r"\s+", " ", without).strip()


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def page_heading(source: str) -> str:
    match = _H1.search(source or "") or _TITLE.search(source or "")
    if not match:
        return ""
    return clean(re.sub(r"(?is)<[^>]+>", " ", match.group(1)))


def labeled_date(text: str, labels: str) -> date | None:
    pattern = _LABELED.pattern.format(labels=labels)
    for match in re.finditer(pattern, text or "", re.IGNORECASE):
        found = parse_explicit_date(match.group(1))
        if found:
            return found
    return None


def json_ld_objects(source: str):
    for match in _JSON_LD.finditer(source or ""):
        raw = html.unescape(match.group(1)).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        yield from _walk_json(payload)


def _walk_json(payload):
    if isinstance(payload, list):
        for item in payload:
            yield from _walk_json(item)
        return
    if not isinstance(payload, dict):
        return
    yield payload
    graph = payload.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            yield from _walk_json(item)


def links_in(source: str, base: str) -> list[str]:
    found = []
    for href in _HREF.findall(source or ""):
        absolute = urljoin(base, html.unescape(href)).split("#")[0]
        if absolute.startswith("http"):
            found.append(absolute)
    return list(dict.fromkeys(found))


def keep_listing(
    *,
    title: str,
    organization: str,
    location: str,
    posted: date | None,
    deadline: date | None,
    url: str,
    reference: date,
    now: datetime | None,
    deadline_time: time | None = None,
    closed: bool = False,
    text: str = "",
) -> VerifiedListing | None:
    if text_says_closed(text):
        closed = True
    if not listing_qualifies(
        posted,
        deadline,
        reference,
        closed=closed,
        deadline_time=deadline_time,
        now=now,
    ):
        return None
    title = clean(title)
    organization = clean(organization)
    location = clean(location)
    url = (url or "").strip()
    if not title or not organization or not url.startswith("https://"):
        return None
    return VerifiedListing(
        title=title,
        organization=organization,
        location=location,
        posted=posted,
        deadline=deadline,
        url=url,
        deadline_time=deadline_time,
    )


def _dedupe(listings: list[VerifiedListing]) -> tuple[VerifiedListing, ...]:
    seen = set()
    kept = []
    for item in sorted(listings, key=lambda row: (-row.posted.toordinal(), row.title.lower())):
        if item.url in seen:
            continue
        seen.add(item.url)
        kept.append(item)
    return tuple(kept)


def _outcome(listings: list[VerifiedListing]) -> SweepOutcome:
    return SweepOutcome(listings=_dedupe(listings))


def _unread() -> SweepOutcome:
    return SweepOutcome(unread=True)


# --- Aggregators -----------------------------------------------------------


def sweep_jobline(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    index_urls = (
        "https://theugandanjobline.com/",
        "https://theugandanjobline.com/jobs-in-uganda",
        "https://theugandanjobline.com/feeds/posts/default",
    )
    pages = [fetch(url) for url in index_urls]
    readable = [page for page in pages if page.ok]
    if not readable:
        return _unread()
    detail_urls = []
    listings = []
    for page in readable:
        listings.extend(_jobline_entries(page, reference, now))
        for link in links_in(page.text, page.url):
            host = urlparse(link).netloc.lower()
            if host.endswith("theugandanjobline.com") and re.search(r"/20\d\d/", link):
                detail_urls.append(link)
    details = pooled(detail_urls[:40], fetch)
    read_detail = False
    for page in details:
        if not page.ok:
            continue
        read_detail = True
        item = _one_vacancy_page(
            page,
            reference,
            now,
            organization="",
            require_organization_in_text=True,
        )
        if item:
            listings.append(item)
    if detail_urls and not read_detail and not listings:
        return _unread()
    return _outcome(listings)


def _jobline_entries(page: Page, reference: date, now: datetime | None) -> list[VerifiedListing]:
    if "<entry" not in page.text and "<item" not in page.text:
        return []
    listings = []
    chunks = re.findall(r"(?is)<(?:entry|item)\b.*?</(?:entry|item)>", page.text)
    for chunk in chunks:
        posted = parse_explicit_date(
            _tag_text(chunk, "published") or _tag_text(chunk, "pubDate") or ""
        )
        content = html_to_text(chunk)
        deadline = labeled_date(
            content,
            r"application deadline|apply by|closing date|deadline|closes",
        )
        title = _tag_text(chunk, "title")
        link = _tag_text(chunk, "link") or _attr(chunk, "link", "href")
        organization = _jobline_organization(content, title)
        item = keep_listing(
            title=title,
            organization=organization,
            location=_location_phrase(content),
            posted=posted,
            deadline=deadline,
            url=link,
            reference=reference,
            now=now,
            deadline_time=_deadline_clock(content),
            text=content,
        )
        if item and urlparse(item.url).netloc.lower().endswith("theugandanjobline.com"):
            listings.append(item)
    return listings


def _jobline_organization(content: str, title: str) -> str:
    match = re.search(
        r"(?:organisation|organization)\s*:\s*([^|.\n]{2,80})",
        content,
        re.IGNORECASE,
    )
    if match:
        return clean(match.group(1))
    parts = [clean(part) for part in re.split(r"\s+[–—-]\s+", title) if clean(part)]
    if len(parts) >= 2:
        return parts[-1]
    return ""


def sweep_fuzu(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    index = fetch("https://www.fuzu.com/uganda/sitemap-job-listings.xml.gz")
    urls = []
    read_index = index.ok
    if index.ok:
        children = [
            loc
            for loc in re.findall(r"<loc>(.*?)</loc>", index.text)
            if loc.endswith(".xml.gz") or loc.endswith(".xml")
        ]
        for child in pooled(children, fetch):
            if not child.ok:
                continue
            locs = re.findall(r"<loc>(.*?)</loc>", child.text)
            mods = re.findall(r"<lastmod>(.*?)</lastmod>", child.text)
            for loc, modified in zip(locs, mods or [""] * len(locs)):
                modified_on = parse_explicit_date((modified or "")[:10])
                if (
                    "/uganda/jobs/" in loc
                    and modified_on
                    and posted_in_window(modified_on, reference)
                ):
                    urls.append(loc.strip())
    board = fetch("https://www.fuzu.com/uganda/jobs")
    if board.ok:
        read_index = True
        urls.extend(
            link
            for link in links_in(board.text, board.url)
            if "/uganda/jobs/" in link
        )
    if not read_index:
        return _unread()
    urls = [url for url in dict.fromkeys(urls) if "/uganda/jobs/" in url]
    listings = []
    read_job = False
    for page in pooled(urls, fetch):
        if not page.ok:
            continue
        read_job = True
        item = _fuzu_listing(page, reference, now)
        if item:
            listings.append(item)
    if urls and not read_job:
        return _unread()
    return _outcome(listings)


def _fuzu_listing(page: Page, reference: date, now: datetime | None) -> VerifiedListing | None:
    posting = None
    for obj in json_ld_objects(page.text):
        kind = obj.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            posting = obj
            break
    if not posting:
        return None
    text = html_to_text(page.text)
    posted = labeled_date(text, r"date posted|posted")
    if posted is None:
        posted = parse_explicit_date(str(posting.get("datePosted") or ""))
    deadline = labeled_date(text, r"apply by|application deadline")
    if deadline is None:
        deadline = parse_explicit_date(str(posting.get("validThrough") or ""))
    hiring = posting.get("hiringOrganization")
    organization = ""
    if isinstance(hiring, dict):
        organization = str(hiring.get("name") or "")
    stated_url = str(posting.get("url") or "")
    url = stated_url if "/uganda/jobs/" in stated_url else page.url
    return keep_listing(
        title=str(posting.get("title") or page_heading(page.text)),
        organization=organization,
        location=_fuzu_location(posting, text),
        posted=posted,
        deadline=deadline,
        url=url,
        reference=reference,
        now=now,
        text=text,
    )


def _fuzu_location(posting: dict, text: str) -> str:
    place = posting.get("jobLocation")
    address = place.get("address") if isinstance(place, dict) else {}
    if not isinstance(address, dict):
        address = {}
    locality = clean(str(address.get("addressLocality") or ""))
    country_code = clean(str(address.get("addressCountry") or ""))
    country = ""
    if country_code.upper() in {"UG", "UGANDA"} and "uganda" in text.lower():
        country = "Uganda"
    elif country_code and country_code.upper() not in {"UG"}:
        country = country_code
    return ", ".join(part for part in (locality, country) if part)


def sweep_jobhunter(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    sitemap = fetch(
        "https://www.jobhunter-ug.com/dynamic-jobs_p_ceeed873_206d_4684_9124_3e8f6f91dcaa_0_5000-sitemap.xml"
    )
    if not sitemap.ok:
        home = fetch("https://www.jobhunter-ug.com/")
        if not home.ok:
            return _unread()
        return _outcome([])
    urls = []
    locs = re.findall(r"<loc>(.*?)</loc>", sitemap.text)
    mods = re.findall(r"<lastmod>(.*?)</lastmod>", sitemap.text)
    for loc, modified in zip(locs, mods or [""] * len(locs)):
        modified_on = parse_explicit_date((modified or "")[:10])
        if (
            "/jobs/" in loc
            and modified_on
            and posted_in_window(modified_on, reference)
        ):
            urls.append(loc.strip())
    listings = []
    read_job = False
    for page in pooled(urls, fetch):
        if not page.ok:
            continue
        read_job = True
        item = _jobhunter_listing(page, reference, now)
        if item:
            listings.append(item)
    if urls and not read_job:
        return _unread()
    return _outcome(listings)


def _jobhunter_listing(page: Page, reference: date, now: datetime | None) -> VerifiedListing | None:
    text = html_to_text(page.text)
    posted = labeled_date(text, r"date posted")
    deadline = labeled_date(text, r"date expiring|application deadline|apply by|closing date|deadline")
    organization = ""
    match = re.search(r"Company:\s*([A-Za-z0-9&.,'() /-]{2,80}?)\s+Location:", text)
    if match:
        organization = clean(match.group(1))
    if not organization:
        match = re.search(
            r"\b([A-Z][A-Za-z0-9&.' -]{2,60})\s+Location:\s*([A-Za-z][^:]{2,60}?)\s+(?:Company Size|Job Type|Date):",
            text,
        )
        if match:
            organization = clean(match.group(1))
    location = ""
    located = re.search(r"Location:\s*([A-Za-z][^:]{2,80}?)\s+(?:Company Size|Job Type|Date):", text)
    if located:
        location = clean(located.group(1).replace("&nbsp;", " "))
    title = page_heading(page.text)
    title = re.sub(r"\s*\|\s*JobHunter Ug\s*$", "", title).strip()
    return keep_listing(
        title=title,
        organization=organization,
        location=location,
        posted=posted,
        deadline=deadline,
        url=page.url if page.url.startswith("https://www.jobhunter-ug.com/jobs/") else "",
        reference=reference,
        now=now,
        deadline_time=_deadline_clock(text),
        text=text,
    )


def sweep_qsourcing(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    items = []
    for page_no in range(1, 6):
        page = fetch(
            "https://qsourcing.com/wp-json/wp/v2/job-listings"
            f"?per_page=20&orderby=date&order=desc&page={page_no}"
        )
        if not page.ok:
            if page_no == 1:
                return _unread()
            break
        try:
            batch = page.json()
        except json.JSONDecodeError:
            if page_no == 1:
                return _unread()
            break
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
    listings = []
    for item in items:
        listing = _qsourcing_listing(item, reference, now)
        if listing:
            listings.append(listing)
    return _outcome(listings)


def _qsourcing_listing(item: dict, reference: date, now: datetime | None) -> VerifiedListing | None:
    meta = item.get("meta") or {}
    if str(meta.get("_filled")).lower() in {"1", "true", "yes"}:
        return None
    title = clean((item.get("title") or {}).get("rendered") or "")
    content_html = (item.get("content") or {}).get("rendered") or ""
    content = html_to_text(content_html)
    posted = parse_explicit_date(str(item.get("date") or ""))
    deadline_sentence = ""
    match = re.search(
        r"deadline for applications is not later than.{0,90}",
        content,
        re.IGNORECASE,
    )
    if match:
        deadline_sentence = match.group(0)
    deadline = parse_explicit_date(deadline_sentence) or labeled_date(
        content,
        r"apply by|closing date",
    )
    url = str(item.get("link") or "")
    if not url.startswith("https://qsourcing.com/job/"):
        return None
    return keep_listing(
        title=title,
        organization=_qsourcing_organization(content),
        location=clean(str(meta.get("_job_location") or "")),
        posted=posted,
        deadline=deadline,
        url=url,
        reference=reference,
        now=now,
        deadline_time=parse_clock(deadline_sentence),
        text=content,
    )


def _qsourcing_organization(content: str) -> str:
    match = re.search(
        r"on behalf of our client\s+([A-Z][A-Za-z0-9&.\- ]{1,40})",
        content,
        re.IGNORECASE,
    )
    if match:
        name = re.split(r",|\s+to\s+|\s+we\s+", match.group(1))[0].strip(" .")
        if name and "sector" not in name.lower():
            return name
    return "Q-Sourcing Servtec"


# --- Public sector ---------------------------------------------------------


def sweep_psc(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    pages = [
        fetch(url)
        for url in (
            "https://vacancies.psc.go.ug/Advert/Adverts",
            "https://vacancies.psc.go.ug/",
            "https://www.psc.go.ug/",
        )
    ]
    readable = [page for page in pages if page.ok]
    if not readable:
        return _unread()
    combined = " ".join(html_to_text(page.text).lower() for page in readable)
    if "no adverts at the moment" in combined:
        return _outcome([])
    listings = []
    detail_urls = []
    for page in readable:
        for link in links_in(page.text, page.url):
            host = urlparse(link).netloc.lower()
            path = urlparse(link).path.lower()
            if host.endswith("psc.go.ug") and any(
                token in path for token in ("advert", "vacan", "job")
            ):
                detail_urls.append(link)
    for page in pooled(detail_urls[:20], fetch):
        if not page.ok:
            continue
        item = _one_vacancy_page(page, reference, now, organization="Public Service Commission")
        if item and "psc.go.ug" in urlparse(item.url).netloc:
            listings.append(item)
    return _outcome(listings)


def sweep_esc(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    page = fetch(
        "https://esc.go.ug/wp-json/wp/v2/posts?per_page=20&orderby=date&order=desc"
    )
    if not page.ok:
        return _unread()
    try:
        posts = page.json()
    except json.JSONDecodeError:
        return _unread()
    if not isinstance(posts, list):
        return _unread()
    listings = []
    for post in posts:
        title = clean((post.get("title") or {}).get("rendered") or "")
        content = html_to_text((post.get("content") or {}).get("rendered") or "")
        if not _esc_is_vacancy(title, content):
            continue
        deadline_sentence = ""
        match = re.search(
            r"(?:not later than|closing date|deadline).{0,80}",
            content,
            re.IGNORECASE,
        )
        if match:
            deadline_sentence = match.group(0)
        item = keep_listing(
            title=title,
            organization="Education Service Commission",
            location="Uganda" if "uganda" in content.lower() else "",
            posted=parse_explicit_date(str(post.get("date") or "")),
            deadline=parse_explicit_date(deadline_sentence),
            url=str(post.get("link") or ""),
            reference=reference,
            now=now,
            deadline_time=parse_clock(deadline_sentence),
            text=content,
        )
        if item and urlparse(item.url).netloc.lower().endswith("esc.go.ug"):
            listings.append(item)
    return _outcome(listings)


def _esc_is_vacancy(title: str, content: str) -> bool:
    blob = f"{title} {content}".lower()
    if any(
        marker in blob
        for marker in (
            "shortlist",
            "aptitude test",
            "oral interview",
            "corrigenda",
            "appointed",
            "confirmation",
            "retirement",
            "release of results",
        )
    ):
        return False
    return any(
        marker in blob
        for marker in (
            "applications are invited",
            "external advert",
            "vacant post",
            "vacant position",
        )
    )


DISTRICT_SITES = (
    "https://www.kcca.go.ug/",
    "https://wakiso.go.ug/",
    "https://jinja.go.ug/",
    "https://mukono.go.ug/",
    "https://www.mbarara.go.ug/",
    "https://gulu.go.ug/",
    "https://mbale.go.ug/",
    "https://masaka.go.ug/",
    "https://www.lyantonde.go.ug/",
    "https://ibanda.go.ug/",
    "https://hoima.go.ug/",
    "https://lira.go.ug/",
    "https://arua.go.ug/",
    "https://soroti.go.ug/",
    "https://www.entebbe.go.ug/",
    "https://kabale.go.ug/",
    "https://masindi.go.ug/",
)


def sweep_districts(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    homepages = pooled(DISTRICT_SITES, fetch, workers=6)
    readable = [page for page in homepages if page.ok]
    follow = []
    for page in readable:
        host = urlparse(page.url).netloc.lower()
        taken = 0
        for link in links_in(page.text, page.url):
            if taken >= 3:
                break
            parsed = urlparse(link)
            if parsed.netloc.lower() != host:
                continue
            if any(token in parsed.path.lower() for token in ("job", "advert", "vacan", "opportunit")):
                follow.append(link)
                taken += 1
    extras = [page for page in pooled(follow, fetch, workers=6) if page.ok]
    pages = readable + extras
    if not pages:
        return _unread()
    listings = []
    for page in pages:
        item = _district_listing(page, reference, now)
        if item:
            listings.append(item)
    return _outcome(listings)


def _district_listing(page: Page, reference: date, now: datetime | None) -> VerifiedListing | None:
    text = html_to_text(page.text)
    organization = ""
    match = re.search(
        r"([A-Z][A-Za-z .'-]{2,50}(?:District Service Commission|District Local Government|City Service Commission))",
        text,
    )
    if match:
        organization = clean(match.group(1))
    deadline_sentence = ""
    found = re.search(r"(?:not later than|closing date|deadline).{0,80}", text, re.IGNORECASE)
    if found:
        deadline_sentence = found.group(0)
    posted = labeled_date(text, r"date posted|posted on|published")
    return keep_listing(
        title=page_heading(page.text),
        organization=organization,
        location=_location_phrase(text),
        posted=posted,
        deadline=parse_explicit_date(deadline_sentence),
        url=page.url,
        reference=reference,
        now=now,
        deadline_time=parse_clock(deadline_sentence),
        text=text,
    )


# --- Corporate -------------------------------------------------------------


def sweep_mtn(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    api = (
        "https://ehle.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/"
        "recruitingCEJobRequisitions?onlyData=true&expand=requisitionList"
        "&finder=findReqs;siteNumber=CX_1,keyword=Uganda,limit=25,sortBy=POSTING_DATES_DESC"
    )
    page = fetch(api)
    if not page.ok:
        return _unread()
    try:
        payload = page.json()
    except json.JSONDecodeError:
        return _unread()
    items = payload.get("items") if isinstance(payload, dict) else None
    requisitions = []
    if isinstance(items, list) and items:
        requisitions = items[0].get("requisitionList") or []
    listings = []
    for job in requisitions:
        location = clean(str(job.get("PrimaryLocation") or ""))
        if "uganda" not in location.lower():
            continue
        posted = parse_explicit_date(str(job.get("PostedDate") or ""))
        deadline = parse_explicit_date(str(job.get("PostingEndDate") or ""))
        job_id = str(job.get("Id") or "")
        url = (
            "https://ehle.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/"
            f"CX_1/job/{job_id}"
        )
        detail = fetch(url) if job_id and deadline else None
        if detail is not None and not detail.ok:
            continue
        if detail is not None and clean(str(job.get("Title") or "")).lower() not in detail.text.lower():
            continue
        item = keep_listing(
            title=str(job.get("Title") or ""),
            organization="MTN",
            location=location,
            posted=posted,
            deadline=deadline,
            url=url if detail is not None else "",
            reference=reference,
            now=now,
            text=detail.text if detail is not None else "",
        )
        if item:
            listings.append(item)
    return _outcome(listings)


def sweep_airtel(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    page = fetch("https://www.airtel.co.ug/ug/about/careers")
    if not page.ok:
        return _unread()
    return _outcome(_single_job_if_dated(page, reference, now, organization="Airtel"))


def sweep_stanbic(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    pages = [
        fetch(url)
        for url in (
            "https://www.stanbicbank.co.ug/",
            "https://www.standardbank.com/sbg/standard-bank-group/careers",
        )
    ]
    readable = [page for page in pages if page.ok]
    workday = _workday_uganda_listings(
        fetch,
        reference,
        now,
        host="standardbank.wd3.myworkdayjobs.com",
        tenant="standardbank",
        site="StandardBank",
        organization="Stanbic",
    )
    if workday is None and not readable:
        return _unread()
    listings = list(workday or [])
    for page in readable:
        for link in links_in(page.text, page.url):
            host = urlparse(link).netloc.lower()
            if "stanbicbank.co.ug" not in host and "standardbank.com" not in host:
                continue
            if not any(token in urlparse(link).path.lower() for token in ("job", "vacan", "career")):
                continue
            detail = fetch(link)
            if not detail.ok:
                continue
            listings.extend(
                _single_job_if_dated(
                    detail,
                    reference,
                    now,
                    organization="Stanbic",
                    require_uganda=True,
                )
            )
    if workday is None and not readable:
        return _unread()
    return _outcome(listings)


def sweep_ncba(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    sitemap = fetch("https://ncbagroup.com/job-sitemap.xml")
    if not sitemap.ok:
        return _unread()
    urls = []
    locs = re.findall(r"<loc>(.*?)</loc>", sitemap.text)
    mods = re.findall(r"<lastmod>(.*?)</lastmod>", sitemap.text)
    for loc, modified in zip(locs, mods or [""] * len(locs)):
        modified_on = parse_explicit_date((modified or "")[:10])
        if modified_on and posted_in_window(modified_on, reference) and "/blog/job/" in loc:
            urls.append(html.unescape(loc.strip()))
    listings = []
    read_job = False
    for page in pooled(urls, fetch):
        if not page.ok:
            continue
        read_job = True
        item = _ncba_listing(page, reference, now)
        if item:
            listings.append(item)
    if urls and not read_job:
        return _unread()
    return _outcome(listings)


def _ncba_listing(page: Page, reference: date, now: datetime | None) -> VerifiedListing | None:
    text = html_to_text(page.text)
    country = ""
    match = re.search(r"Country:\s*([A-Za-z]+)", text)
    if match:
        country = clean(match.group(1))
    if country.lower() != "uganda":
        return None
    deadline_sentence = ""
    found = re.search(r"Closing on:\s*.{0,40}", text, re.IGNORECASE)
    if found:
        deadline_sentence = found.group(0)
    posted = None
    for obj in json_ld_objects(page.text):
        posted = parse_explicit_date(str(obj.get("datePublished") or ""))
        if posted:
            break
    title = page_heading(page.text)
    title = re.sub(r"\s+-\s+NCBA Group\s*$", "", title).strip()
    if "ncba" not in text.lower():
        return None
    return keep_listing(
        title=title,
        organization="NCBA Group",
        location=country,
        posted=posted,
        deadline=parse_explicit_date(deadline_sentence),
        url=page.url if "ncbagroup.com/blog/job/" in page.url else "",
        reference=reference,
        now=now,
        deadline_time=parse_clock(deadline_sentence),
        text=text,
    )


def sweep_centenary(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    page = fetch("https://centenarybank.co.ug/cente-careers")
    if not page.ok:
        return _unread()
    listings = _single_job_if_dated(page, reference, now, organization="Centenary Bank")
    detail_urls = [
        link
        for link in links_in(page.text, page.url)
        if "centenarybank.co.ug" in urlparse(link).netloc.lower()
        and "/cente-careers/" in urlparse(link).path.lower()
        and link.rstrip("/") != page.url.rstrip("/")
    ]
    for detail in pooled(detail_urls, fetch):
        if not detail.ok:
            continue
        listings.extend(
            _single_job_if_dated(detail, reference, now, organization="Centenary Bank")
        )
    return _outcome(listings)


def sweep_absa(reference: date, fetch, now: datetime | None) -> SweepOutcome:
    found = _workday_uganda_listings(
        fetch,
        reference,
        now,
        host="absa.wd3.myworkdayjobs.com",
        tenant="absa",
        site="ABSAcareersite",
        organization="ABSA",
    )
    if found is None:
        return _unread()
    return _outcome(found)


def _workday_uganda_listings(
    fetch,
    reference: date,
    now: datetime | None,
    *,
    host: str,
    tenant: str,
    site: str,
    organization: str,
) -> list[VerifiedListing] | None:
    endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    offset = 0
    paths = []
    saw_json = False
    while offset < 200:
        page = fetch(
            endpoint,
            method="POST",
            json_body={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""},
        )
        if not page.ok:
            return None if not saw_json else []
        try:
            payload = page.json()
        except json.JSONDecodeError:
            return None if not saw_json else []
        saw_json = True
        postings = payload.get("jobPostings") or []
        total = int(payload.get("total") or 0)
        for posting in postings:
            path = str(posting.get("externalPath") or "")
            blob = json.dumps(posting).lower()
            if not path.startswith("/job/"):
                continue
            if "uganda" in blob or "kampala" in blob or total <= 80:
                paths.append(path)
        offset += 20
        if not postings or offset >= total:
            break
    listings = []
    for path in paths:
        detail = fetch(f"https://{host}/wday/cxs/{tenant}/{site}{path}")
        if not detail.ok:
            continue
        item = _workday_detail(
            detail,
            reference,
            now,
            public_url=f"https://{host}/{site}{path}",
            organization=organization,
        )
        if item:
            listings.append(item)
    return listings


def _workday_detail(
    page: Page,
    reference: date,
    now: datetime | None,
    *,
    public_url: str,
    organization: str,
) -> VerifiedListing | None:
    try:
        payload = page.json()
    except json.JSONDecodeError:
        return None
    info = payload.get("jobPostingInfo") if isinstance(payload, dict) else None
    if not isinstance(info, dict):
        return None
    place = info.get("jobRequisitionLocation") if isinstance(info.get("jobRequisitionLocation"), dict) else {}
    country = ""
    country_obj = place.get("country") if isinstance(place, dict) else None
    if isinstance(country_obj, dict):
        country = clean(str(country_obj.get("descriptor") or ""))
    location = clean(str(info.get("location") or ""))
    descriptor = clean(str(place.get("descriptor") or "")) if isinstance(place, dict) else ""
    location_text = ", ".join(part for part in (descriptor, country) if part) or location
    if "uganda" not in f"{location_text} {info.get('jobDescription') or ''}".lower():
        return None
    posted = parse_explicit_date(str(info.get("startDate") or ""))
    deadline = parse_explicit_date(str(info.get("endDate") or "")) or parse_explicit_date(
        str(info.get("jobPostingEndDateAsText") or "")
    )
    stated_url = str(info.get("externalUrl") or public_url)
    if not stated_url.startswith("https://"):
        stated_url = public_url
    return keep_listing(
        title=str(info.get("title") or ""),
        organization=organization,
        location=location_text,
        posted=posted,
        deadline=deadline,
        url=stated_url,
        reference=reference,
        now=now,
        text=html_to_text(str(info.get("jobDescription") or "")),
    )


def _single_job_if_dated(
    page: Page,
    reference: date,
    now: datetime | None,
    *,
    organization: str,
    require_uganda: bool = False,
) -> list[VerifiedListing]:
    text = html_to_text(page.text)
    if require_uganda and "uganda" not in text.lower():
        return []
    headings = [
        clean(re.sub(r"(?is)<[^>]+>", " ", raw))
        for raw in re.findall(r"(?is)<h[12][^>]*>(.*?)</h[12]>", page.text)
    ]
    headings = [heading for heading in headings if heading and heading.lower() not in {"careers", "job openings", "join our network"}]
    if len(headings) > 1:
        return []
    item = _one_vacancy_page(page, reference, now, organization=organization)
    return [item] if item else []


def _one_vacancy_page(
    page: Page,
    reference: date,
    now: datetime | None,
    *,
    organization: str,
    require_organization_in_text: bool = False,
) -> VerifiedListing | None:
    text = html_to_text(page.text)
    posted = labeled_date(text, r"date posted|posted on|posted")
    if posted is None:
        for obj in json_ld_objects(page.text):
            kind = obj.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "JobPosting" in kinds:
                posted = parse_explicit_date(str(obj.get("datePosted") or ""))
                if posted:
                    break
    deadline_sentence = ""
    match = re.search(
        r"(?:application deadline|apply by|closing on|closing date|deadline|not later than).{0,80}",
        text,
        re.IGNORECASE,
    )
    if match:
        deadline_sentence = match.group(0)
    if require_organization_in_text and not organization:
        organization = _jobline_organization(text, page_heading(page.text))
    title = page_heading(page.text)
    if title.lower() in {"careers", "jobs", "home", "vacancies", "opportunities"}:
        return None
    return keep_listing(
        title=title,
        organization=organization,
        location=_location_phrase(text),
        posted=posted,
        deadline=parse_explicit_date(deadline_sentence),
        url=page.url,
        reference=reference,
        now=now,
        deadline_time=parse_clock(deadline_sentence),
        text=text,
    )


def _location_phrase(text: str) -> str:
    match = re.search(
        r"(?:duty station|location)\s*:\s*([^|.\n]{2,80})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    return clean(match.group(1))


def _deadline_clock(text: str) -> time | None:
    match = re.search(
        r"(?:deadline|apply by|closing on|not later than).{0,40}",
        text or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return parse_clock(match.group(0))


def _tag_text(chunk: str, tag: str) -> str:
    match = re.search(rf"(?is)<{tag}[^>]*>(.*?)</{tag}>", chunk)
    if not match:
        return ""
    return clean(re.sub(r"(?is)<[^>]+>", " ", match.group(1)))


def _attr(chunk: str, tag: str, attr: str) -> str:
    match = re.search(rf"(?is)<{tag}[^>]*\b{attr}=['\"]([^'\"]+)['\"]", chunk)
    return match.group(1).strip() if match else ""


TARGET_GROUPS = (
    (
        "Aggregators",
        (
            ("The Ugandan Jobline", sweep_jobline),
            ("Fuzu Uganda", sweep_fuzu),
            ("JobHunter Ug", sweep_jobhunter),
            ("Q-Sourcing Servtec", sweep_qsourcing),
        ),
    ),
    (
        "Public Sector",
        (
            ("Uganda Public Service Commission", sweep_psc),
            ("Education Service Commission", sweep_esc),
            ("District local government portals", sweep_districts),
        ),
    ),
    (
        "Corporate",
        (
            ("MTN", sweep_mtn),
            ("Airtel", sweep_airtel),
            ("Stanbic", sweep_stanbic),
            ("NCBA", sweep_ncba),
            ("Centenary", sweep_centenary),
            ("ABSA", sweep_absa),
        ),
    ),
)
