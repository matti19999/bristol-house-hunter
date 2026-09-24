"""Bristol student house hunter.

Checks Rightmove, OpenRent, AccommodationForStudents and UniHomes for whole
2/3/4-bed properties within walking distance of the University of Bristol and
under a per-person-per-week budget, then emails you new ones.

    python house_hunter.py                one check
    python house_hunter.py --loop         check forever, every interval_minutes
    python house_hunter.py --dry-run      one check, print instead of emailing
    python house_hunter.py --test-email   send a test email and exit
"""

import argparse
import html
import json
import math
import os
import random
import re
import smtplib
import sys
import time
import tomllib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "seen.json"
MATCHES_FILE = HERE / "matches.html"
LOG_FILE = HERE / "hunter.log"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}
WEEKS_PER_MONTH = 52 / 12
# Text yourself once if a site has failed this many checks in a row.
FAILURE_ALERT_AFTER = 12


@dataclass
class Listing:
    source: str
    id: str
    url: str
    beds: int
    pppw: float
    bills_included: bool
    address: str
    walk_min: int | None = None
    note: str = ""

    @property
    def key(self):
        return f"{self.source}:{self.id}"


# ---------------------------------------------------------------- helpers

def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_env():
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config():
    with (HERE / "config.toml").open("rb") as f:
        return tomllib.load(f)


def get(url, **kw):
    r = requests.get(url, headers=HEADERS, timeout=30, **kw)
    r.raise_for_status()
    time.sleep(random.uniform(1.0, 2.5))  # be polite between page loads
    return r.text


def next_data(page):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise ValueError("page layout changed: no __NEXT_DATA__ found")
    return json.loads(m.group(1))


def walk_minutes(cfg, lat, lon):
    if lat is None or lon is None:
        return None
    loc = cfg["location"]
    r = 6371.0
    p1, p2 = math.radians(loc["uni_lat"]), math.radians(lat)
    dp, dl = p2 - p1, math.radians(lon - loc["uni_lon"])
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    km = 2 * r * math.asin(math.sqrt(a))
    return round(km * 1.3 / 4.8 * 60)


def max_pppw(cfg, bills_included):
    b = cfg["budget"]
    return b["max_pppw_bills_included"] if bills_included else b["max_pppw"]


def max_pcm(cfg):
    """Highest whole-property monthly rent that could possibly fit the budget."""
    return math.ceil(cfg["budget"]["max_pppw_bills_included"]
                     * max(cfg["property"]["bedrooms"]) * WEEKS_PER_MONTH)


def to_weekly(amount, frequency):
    return {
        "weekly": amount,
        "monthly": amount / WEEKS_PER_MONTH,
        "quarterly": amount / 13,
        "yearly": amount / 52,
        "daily": amount * 7,
    }.get(frequency, amount / WEEKS_PER_MONTH)


# ---------------------------------------------------------------- sources

def rightmove(cfg, first_run, seen):
    beds = cfg["property"]["bedrooms"]
    base = ("https://www.rightmove.co.uk/property-to-rent/find.html"
            "?locationIdentifier=REGION%5E219"  # Bristol
            f"&minBedrooms={min(beds)}&maxBedrooms={max(beds)}&maxPrice={max_pcm(cfg)}"
            "&sortType=6&dontShow=houseShare%2Cretirement&index={index}")
    max_pages = 42 if first_run else 4
    out = []
    for page in range(max_pages):
        data = next_data(get(base.replace("{index}", str(page * 24))))
        results = data["props"]["pageProps"]["searchResults"]
        props = results["properties"]
        if not props:
            break
        new_on_page = 0
        for p in props:
            key = f"rightmove:{p['id']}"
            if key not in seen:
                new_on_page += 1
            n = p.get("bedrooms") or 0
            if n not in beds:
                continue
            weekly = to_weekly(p["price"]["amount"], p["price"].get("frequency"))
            loc = p.get("location") or {}
            out.append(Listing(
                source="Rightmove", id=str(p["id"]),
                url="https://www.rightmove.co.uk/properties/" + str(p["id"]),
                beds=n, pppw=weekly / n, bills_included=False,
                address=p.get("displayAddress", ""),
                walk_min=walk_minutes(cfg, loc.get("latitude"), loc.get("longitude")),
            ))
        # Results are newest-first, so once a whole page is old news, stop.
        if not first_run and new_on_page == 0:
            break
        if (page + 1) * 24 >= int(str(results.get("resultCount", "0")).replace(",", "")):
            break
    return out


def openrent(cfg, first_run, seen):
    beds = cfg["property"]["bedrooms"]
    url = ("https://www.openrent.co.uk/properties-to-rent/bristol?term=Bristol"
           f"&prices_max={max_pcm(cfg)}&bedrooms_min={min(beds)}&bedrooms_max={max(beds)}"
           "&isLive=true")
    page = get(url)

    def arr(name):
        m = re.search(r"var %s\s*=\s*\[(.*?)\];" % name, page, re.S)
        if not m:
            raise ValueError(f"page layout changed: no {name} array")
        return [x.strip() for x in m.group(1).split(",") if x.strip()]

    ids, prices, nbeds = arr("PROPERTYIDS"), arr("prices"), arr("bedrooms")
    lats, lons = arr("PROPERTYLISTLATITUDES"), arr("PROPERTYLISTLONGITUDES")
    shared, students, live, bills = arr("isshared"), arr("students"), arr("islivelistBool"), arr("bills")
    titles = {m.group(2): m.group(1) for m in re.finditer(
        r'href="(/property-to-rent/[^"]+/(\d+))"', page)}

    out = []
    for i, pid in enumerate(ids):
        try:
            n = int(nbeds[i])
            if n not in beds or shared[i] == "1" or students[i] == "0" or live[i] == "0":
                continue
            slug = titles.get(pid, "").rsplit("/", 2)[-2] if pid in titles else ""
            out.append(Listing(
                source="OpenRent", id=pid, url=f"https://www.openrent.co.uk/{pid}",
                beds=n, pppw=float(prices[i]) / WEEKS_PER_MONTH / n,
                bills_included=bills[i] == "1",
                address=slug.replace("-", " ").title() or "Bristol",
                walk_min=walk_minutes(cfg, float(lats[i]), float(lons[i])),
            ))
        except (IndexError, ValueError):
            continue
    return out


def accommodation_for_students(cfg, first_run, seen):
    beds = cfg["property"]["bedrooms"]
    out = []
    for ptype in ("house", "flat"):
        page_no, page_count = 1, 1
        while page_no <= page_count and page_no <= 15:
            url = ("https://www.accommodationforstudents.com/search-results?location=Bristol"
                   f"&minBedrooms={min(beds)}&occupancy=min&minPrice=0"
                   f"&maxPrice={cfg['budget']['max_pppw_bills_included']}"
                   f"&geo=false&propertyType={ptype}&page={page_no}")
            il = next_data(get(url))["props"]["pageProps"]["initialListings"]
            page_count = il.get("pageCount") or 0
            for group in il["listings"].get("groups", []):
                for r in group.get("results", []):
                    p = r["property"]
                    occ = p.get("occupancy") or {}
                    n = occ.get("total") or 0
                    # Whole property only: every room must still be free.
                    if n not in beds or occ.get("available", 0) < n or p.get("isSoldOut"):
                        continue
                    terms = p.get("terms") or {}
                    a = p.get("address") or {}
                    c = p.get("coordinates") or {}
                    out.append(Listing(
                        source="AccommodationForStudents", id=str(p["id"]),
                        url="https://www.accommodationforstudents.com" + p["url"],
                        beds=n, pppw=float(terms["rentPpw"]["value"]),
                        bills_included=terms.get("billsIncluded") == "all",
                        address=", ".join(x for x in (a.get("address2") or a.get("address1"),
                                                      a.get("area")) if x),
                        walk_min=walk_minutes(cfg, c.get("lat"), c.get("lon")),
                        note=p.get("academicYearLabel", ""),
                    ))
            page_no += 1
    return out


def unihomes(cfg, first_run, seen):
    beds = cfg["property"]["bedrooms"]
    areas = [a.lower() for a in cfg["location"]["area_names"]]
    link_re = re.compile(r"/property/(\d+)/bristol/([^/]+)/(\d+)-bedroom")
    out, done = [], set()
    pages = [f"https://www.unihomes.co.uk/student-accommodation/bristol/{slug}?page={n}"
             for slug in cfg["location"]["unihomes_areas"] for n in (1, 2)]
    for url in pages:
        # Page 2 of a small area just repeats page 1, and the `done` check skips repeats.
        soup = BeautifulSoup(get(url), "html.parser")
        for a in soup.find_all("a", href=link_re):
            pid, area_slug, n = link_re.search(a["href"]).groups()
            n = int(n)
            area = area_slug.replace("-", " ")
            if pid in done or n not in beds or not any(x in area for x in areas):
                continue
            done.add(pid)
            # Widen to the card: the biggest ancestor that is still only about this property.
            card = a
            while (card.parent is not None and
                   len(set(re.findall(r"/property/(\d+)", str(card.parent)))) == 1):
                card = card.parent
            text = " ".join(card.get_text(" ", strip=True).split())
            pr = re.search(r"£\s*([\d,]+(?:\.\d+)?)\s*(?:pppw|per person per week)", text)
            if not pr:
                continue
            addr = re.search(r"\d+ Bedroom \w+ (.+?)(?: Bills included| £|$)", text, re.I)
            out.append(Listing(
                source="UniHomes", id=pid, url=a["href"] if a["href"].startswith("http")
                else "https://www.unihomes.co.uk" + a["href"],
                beds=n, pppw=float(pr.group(1).replace(",", "")),
                bills_included="bills included" in text.lower(),
                address=addr.group(1) if addr else area.title(),
            ))
    return out


SOURCES = {
    "Rightmove": rightmove,
    "OpenRent": openrent,
    "AccommodationForStudents": accommodation_for_students,
    "UniHomes": unihomes,
}


# ---------------------------------------------------------------- filtering

def matches(cfg, l: Listing):
    if l.pppw > max_pppw(cfg, l.bills_included):
        return False
    if l.walk_min is not None and l.walk_min > cfg["location"]["max_walk_minutes"]:
        return False
    return True


# ---------------------------------------------------------------- notifying

def describe(l: Listing):
    bills = " incl. bills" if l.bills_included else ""
    walk = f" · {l.walk_min} min walk" if l.walk_min is not None else ""
    return f"{l.beds} bed · £{l.pppw:.0f} pppw{bills}{walk}"


def listings_email(listings, intro):
    """Returns (plain_text, html) bodies listing each property with its link."""
    text = intro + "\n\n" + "\n\n".join(
        f"{describe(l)}\n{l.address}\n{l.source}{' (' + l.note + ')' if l.note else ''}\n{l.url}"
        for l in listings)
    cards = "".join(f"""
<div style="border:1px solid #ddd;border-radius:8px;padding:12px 14px;margin:0 0 12px">
  <div style="font-size:17px;font-weight:600">{html.escape(describe(l))}</div>
  <div style="margin:4px 0;color:#333">{html.escape(l.address)}</div>
  <div style="color:#777;font-size:13px">{l.source}{' · ' + html.escape(l.note) if l.note else ''}
  {'· ~£' + format(round(l.pppw * l.beds * WEEKS_PER_MONTH), ',') + ' pcm total' if not l.bills_included else ''}</div>
  <a href="{html.escape(l.url)}" style="display:inline-block;margin-top:10px;padding:8px 14px;
     background:#00a88f;color:#fff;border-radius:6px;text-decoration:none">View listing</a>
</div>""" for l in listings)
    body = f"""<div style="font-family:system-ui,Arial,sans-serif;max-width:560px">
<p>{html.escape(intro)}</p>{cards}</div>"""
    return text, body


def send_email(subject, text, body_html=None, dry_run=False):
    """Returns True if the email went out (or would have, in a dry run)."""
    if dry_run:
        print(f"\n--- would email: {subject} ---\n{text}\n------------------")
        return True
    user, password, to = (os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"))
    if not (user and password and to):
        log("WARNING: email not sent. Fill in SMTP_USER, SMTP_PASSWORD and EMAIL_TO in .env")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"House Hunter <{user}>", to
    msg.set_content(text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    try:
        host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
        return True
    except Exception as e:
        log(f"email failed: {e!r}")
        return False


def write_matches_page(listings):
    """listings: dicts from state["matches"], each a Listing plus first_seen."""
    rows = "\n".join(
        f"<tr><td>{l['first_seen'][:10]}</td><td>{l['beds']}</td>"
        f"<td>£{l['pppw']:.0f}{' (bills incl)' if l['bills_included'] else ''}</td>"
        f"<td>{html.escape(l['address'])}</td>"
        f"<td>{l['walk_min'] if l['walk_min'] is not None else '?'}</td>"
        f"<td>{l['source']} {html.escape(l['note'])}</td>"
        f"<td><a href='{html.escape(l['url'])}'>view</a></td></tr>"
        for l in sorted(listings, key=lambda l: (l["first_seen"], -l["pppw"]), reverse=True))
    MATCHES_FILE.write_text(f"""<!doctype html><meta charset="utf-8">
<title>House matches</title>
<style>body{{font-family:system-ui;margin:16px}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:6px 8px;border-bottom:1px solid #ddd;text-align:left}}</style>
<h1>{len(listings)} matches found</h1>
<p>Newest first. Some may have been let since. Updated {datetime.now():%d %b %Y %H:%M}</p>
<table><tr><th>Found</th><th>Beds</th><th>pppw</th><th>Address</th><th>Walk (min)</th>
<th>Site</th><th></th></tr>
{rows}</table>""", encoding="utf-8")


# ---------------------------------------------------------------- main loop

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return None


def check(cfg, dry_run=False):
    state = load_state()
    first_run = state is None
    state = state or {"seen": {}, "failures": {}}
    seen = state["seen"]

    found = []
    for name, fn in SOURCES.items():
        try:
            results = fn(cfg, first_run, seen)
            log(f"{name}: {len(results)} listings checked")
            found += results
            state["failures"][name] = 0
        except Exception as e:
            n = state["failures"].get(name, 0) + 1
            state["failures"][name] = n
            log(f"{name} FAILED ({n} in a row): {e!r}")
            if n == FAILURE_ALERT_AFTER:
                send_email(f"House hunter: {name} has stopped working",
                           f"{name} has failed {n} checks in a row, so you won't get "
                           f"listings from it. The site may have changed its layout; "
                           f"see hunter.log for details.\n\nLast error: {e!r}",
                           dry_run=dry_run)

    # The same house can appear twice on one site (featured + normal); dedupe.
    good = list({l.key: l for l in found if matches(cfg, l)}.values())
    new = [l for l in good if l.key not in seen]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for l in new:
        seen[l.key] = now
    all_matches = state.setdefault("matches", {})
    for l in good:
        all_matches[l.key] = asdict(l) | {"first_seen": seen[l.key]}
    log(f"{len(good)} matching, {len(new)} new")

    if all_matches:
        write_matches_page(all_matches.values())

    # Listings from earlier checks whose email failed to send go out with this one.
    pending = [Listing(**d) for d in state.pop("pending", [])]
    new = list({l.key: l for l in pending + new}.values())
    if new:
        new.sort(key=lambda l: (l.pppw, l.walk_min or 99))
        if first_run:
            subject = f"House hunter is running: {len(new)} places match right now"
            intro = (f"These {len(new)} places already match your search, cheapest first. "
                     f"From now on you'll get an email as soon as a new one is listed.")
        elif len(new) == 1:
            l = new[0]
            subject = f"New: {l.beds} bed £{l.pppw:.0f}pppw, {l.address}"
            intro = "A new place matching your search was just listed:"
        else:
            subject = f"{len(new)} new places from £{new[0].pppw:.0f}pppw"
            intro = f"{len(new)} new places matching your search were just listed:"
        if not send_email(subject, *listings_email(new, intro), dry_run=dry_run):
            state["pending"] = [asdict(l) for l in new]
            log(f"{len(new)} listings queued to email on the next check")

    if not dry_run:
        STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-email", action="store_true")
    args = ap.parse_args()
    load_env()

    if args.test_email:
        ok = send_email("House hunter test", "Emails are working. You're all set.")
        log("test email sent" if ok else "test email FAILED (see above)")
        return

    while True:
        cfg = load_config()
        try:
            check(cfg, dry_run=args.dry_run)
        except Exception as e:
            log(f"check crashed: {e!r}")
        if not args.loop:
            break
        # Jitter so requests don't land on an exact, bot-like schedule.
        time.sleep(cfg["schedule"]["interval_minutes"] * 60 * random.uniform(0.85, 1.15))


if __name__ == "__main__":
    sys.exit(main())
