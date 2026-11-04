"""Local web page for requesting viewings.

Double-click "Open Viewing Page.bat", or run:  python viewing_page.py
It only runs while its window is open and can only be reached from this laptop.

Ticking a box does nothing by itself. Emails only go out after Submit and then
a final confirmation. Until live mode is on, they all go to your own inbox.
"""

import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import sys
import threading
import tomllib
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import house_hunter as h

HOST, PORT = "127.0.0.1", 8737
DETAILS_FILE = h.HERE / "viewing_details.json"
STATE_FILE = h.HERE / "viewing_state.json"
AGENTS_FILE = h.HERE / "agents.toml"
PAGE_FILE = h.HERE / "viewing_page.html"
LISTINGS_URL = ("https://raw.githubusercontent.com/matti19999/bristol-house-hunter/"
                "main/seen.json")
MAX_LIVE_REQUESTS_PER_DAY = 5
EMAIL_RE = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}")
DEFAULT_DETAILS = {
    "name": "", "phone": "", "availability": "",
    "group": "We're a group of 5 University of Bristol students",
    "year": "the 2027/28 academic year", "live": False,
}

TOKEN = secrets.token_urlsafe(32)
lock = threading.Lock()


# ---------------------------------------------------------------- stored data

def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_state():
    state = read_json(STATE_FILE, {})
    for k in ("removed", "requests", "tests", "custom", "recipients"):
        state.setdefault(k, {})
    return state


def load_details():
    return DEFAULT_DETAILS | read_json(DETAILS_FILE, {})


def normalise(name):
    """'Anthony James & Co' and Rightmove's 'Anthony-James-and-Co' both match."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower().replace("&", "and"))


def agent_book():
    with AGENTS_FILE.open("rb") as f:
        return {normalise(a["name"]): a["email"] for a in tomllib.load(f)["agent"]}


def fetch_listings():
    """The hunter's matches from GitHub, or the local copy if that's unreachable."""
    try:
        r = requests.get(LISTINGS_URL, params={"t": secrets.token_hex(4)}, timeout=15)
        r.raise_for_status()
        return r.json().get("matches", {}), True
    except (requests.RequestException, ValueError):
        return read_json(h.STATE_FILE, {}).get("matches", {}), False


def recipient_for(key, listing, state, book):
    return state["recipients"].get(key) or book.get(normalise(listing.get("agent"))) or ""


def all_listings():
    matches, online = fetch_listings()
    state = load_state()
    book = agent_book()
    out = []
    for key, l in {**matches, **state["custom"]}.items():
        out.append(l | {
            "key": key,
            "custom": key in state["custom"],
            "to": recipient_for(key, l, state, book),
            "removed": key in state["removed"],
            "requested": state["requests"].get(key),
            "tested": state["tests"].get(key),
        })
    return out, online


# ---------------------------------------------------------------- the email

def build_email(listing, details):
    address = " ".join(listing.get("address", "the property").split())
    availability = (f" We're usually free {details['availability'].strip().rstrip('.')}."
                    if details["availability"].strip() else "")
    phone = f" or call me on {details['phone'].strip()}" if details["phone"].strip() else ""
    subject = f"Viewing request: {address}"
    body = (f"Hello,\n\n"
            f"My name is {details['name'].strip()}. {details['group'].strip().rstrip('.')}, "
            f"and we'd like to view this property for {details['year'].strip()}:\n\n"
            f"{address}\n{listing.get('url', '')}\n\n"
            f"Is it still available, and if so, could we arrange a viewing?{availability}\n\n"
            f"You can reply to this email{phone}.\n\n"
            f"Thank you,\n{details['name'].strip()}\n")
    return subject, body


def still_listed(url):
    """False only when the site clearly says the listing has gone."""
    try:
        r = requests.get(url, headers=h.HEADERS, timeout=20)
    except requests.RequestException:
        return True  # can't tell, so don't block the request
    if r.status_code in (404, 410):
        return False
    text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
    return not re.search(r"removed by the agent|no longer on the market", text, re.I)


def sent_today(state):
    today = datetime.now().date().isoformat()
    return sum(r["at"].startswith(today) for r in state["requests"].values())


def missing_details(details):
    return [label for field, label in (("name", "your name"), ("phone", "your phone number"),
                                       ("availability", "when you're free"))
            if not details[field].strip()]


def preview(keys):
    listings, _ = all_listings()
    by_key = {l["key"]: l for l in listings}
    details = load_details()
    items = []
    for key in keys:
        l = by_key.get(key)
        if not l:
            continue
        subject, body = build_email(l, details)
        items.append({"key": key, "address": l.get("address", ""), "to": l["to"],
                      "subject": subject, "body": body, "image": l.get("image", ""),
                      "already": bool(l["requested"]) and details["live"]})
    return {"items": items, "live": details["live"], "missing": missing_details(details),
            "email_to": os.environ.get("EMAIL_TO", ""),
            "left_today": MAX_LIVE_REQUESTS_PER_DAY - sent_today(load_state())}


def submit(keys):
    listings, _ = all_listings()
    by_key = {l["key"]: l for l in listings}
    details = load_details()
    if missing_details(details):
        return {"error": "Please fill in " + ", ".join(missing_details(details)) + " first."}
    my_inbox = os.environ.get("EMAIL_TO", "")
    results = []
    for key in keys:
        l = by_key.get(key)
        if not l:
            results.append({"key": key, "ok": False, "why": "This listing has gone from the list."})
            continue
        address = l.get("address", "")
        if not l["to"]:
            results.append({"key": key, "address": address, "ok": False,
                            "why": "No email address for this agent."})
            continue
        if details["live"] and l["requested"]:
            results.append({"key": key, "address": address, "ok": False,
                            "why": "You've already requested this one."})
            continue
        if details["live"] and sent_today(load_state()) >= MAX_LIVE_REQUESTS_PER_DAY:
            results.append({"key": key, "address": address, "ok": False,
                            "why": f"Daily limit of {MAX_LIVE_REQUESTS_PER_DAY} reached."})
            continue
        if l.get("url") and not still_listed(l["url"]):
            results.append({"key": key, "address": address, "ok": False,
                            "why": "The site says this listing has been removed."})
            continue
        subject, body = build_email(l, details)
        name = details["name"].strip()
        if details["live"]:
            ok = h.send_email(subject, body, to=l["to"], from_name=name,
                              reply_to=my_inbox, cc=my_inbox)
        else:
            ok = h.send_email(f"[TEST, would go to {l['to']}] {subject}", body, to=my_inbox,
                              from_name=name, reply_to=my_inbox)
        if ok:
            with lock:
                state = load_state()
                record = {"to": l["to"], "at": datetime.now().isoformat(timespec="minutes"),
                          "address": address}
                state["requests" if details["live"] else "tests"][key] = record
                write_json(STATE_FILE, state)
        results.append({"key": key, "address": address, "ok": ok, "live": details["live"],
                        "to": l["to"],
                        "why": "" if ok else "Gmail didn't accept it. Check the email connection "
                                             "in Your details."})
    return {"results": results}


# ---------------------------------------------------------------- pasted links

def is_public_host(host):
    """Only fetch public websites, never anything on this laptop or home network."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)


def fetch_public(url):
    for _ in range(5):
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("That doesn't look like a web link.")
        if not is_public_host(parts.hostname):
            raise ValueError("That link isn't a public website.")
        r = requests.get(url, headers=h.HEADERS, timeout=20, allow_redirects=False)
        if r.is_redirect:
            url = urljoin(url, r.headers["location"])
            continue
        return r, url
    raise ValueError("That link redirects too many times.")


def read_listing(url):
    """Details for a pasted link. The email address only ever comes from your
    address book or from you, never from the page itself."""
    url = url.strip()
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    r, final = fetch_public(url)
    if r.status_code in (404, 410):
        raise ValueError("That listing no longer exists.")
    if r.status_code != 200:
        raise ValueError(f"The site wouldn't show that page (error {r.status_code}). "
                         "You can still enter the details by hand.")
    soup = BeautifulSoup(r.text, "html.parser")

    def meta(prop):
        tag = soup.find("meta", property=prop)
        return tag.get("content", "").strip() if tag else ""

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    host = (urlparse(final).hostname or "").lower()
    listing = {"url": final.split("#")[0], "source": host.removeprefix("www."),
               "image": meta("og:image"), "address": meta("og:title") or title or final,
               "agent": "", "agent_phone": "", "price_text": "", "beds": None}
    if m := re.search(r"(\d+)\s*(?:bed|bedroom)", title, re.I):
        listing["beds"] = int(m.group(1))
    if host.endswith("rightmove.co.uk"):
        listing["source"] = "Rightmove"
        if m := re.search(r"for rent in (.+)$", title, re.I):
            listing["address"] = m.group(1).strip()
        if m := re.search(r'data-testid="primaryPrice"><span>([^<]+)', r.text):
            listing["price_text"] = m.group(1)
        if m := re.search(r"/estate-agents/agent/([^/\"]+)/", r.text):
            listing["agent"] = m.group(1).replace("-", " ")
    elif host.endswith("accommodationforstudents.com"):
        listing["source"] = "AccommodationForStudents"
        if m := re.search(r'"accommodationProvider":\{[^}]*?"companyName":"([^"]+)"', r.text):
            listing["agent"] = m.group(1)
    elif host.endswith("unihomes.co.uk"):
        listing["source"] = "UniHomes"
        listing["agent"] = "UniHomes"
    return listing


def add_custom(data):
    listing = {k: data.get(k) for k in ("url", "source", "image", "address", "agent",
                                        "agent_phone", "price_text", "beds")}
    if not listing["url"] or not re.match(r"https?://", listing["url"], re.I):
        return {"error": "A link is needed."}
    if not (listing["address"] or "").strip():
        return {"error": "Please enter the address."}
    key = "custom:" + hashlib.sha1(listing["url"].encode()).hexdigest()[:12]
    email = (data.get("email") or "").strip()
    if email and not EMAIL_RE.fullmatch(email):
        return {"error": "That email address doesn't look right."}
    with lock:
        state = load_state()
        state["custom"][key] = listing | {"first_seen": datetime.now().isoformat(timespec="minutes")}
        state["removed"].pop(key, None)
        if email:
            state["recipients"][key] = email
        write_json(STATE_FILE, state)
    return {"key": key}


# ---------------------------------------------------------------- web server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_body(self, body, content_type="application/json", status=200, extra=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj, status=200):
        self.send_body(json.dumps(obj), status=status)

    def trusted(self):
        """Stops other websites open in your browser from using this page."""
        allowed = (f"{HOST}:{PORT}", f"localhost:{PORT}")
        if self.headers.get("Host") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return not origin or urlparse(origin).netloc in allowed

    def do_GET(self):
        if not self.trusted():
            return self.send_json({"error": "Not allowed"}, 403)
        path = urlparse(self.path).path
        if path == "/":
            nonce = secrets.token_urlsafe(16)
            page = PAGE_FILE.read_text(encoding="utf-8")
            page = page.replace("{{TOKEN}}", TOKEN).replace("{{NONCE}}", nonce)
            csp = (f"default-src 'none'; img-src https: data:; connect-src 'self'; "
                   f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                   f"base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            return self.send_body(page, "text/html", extra={"Content-Security-Policy": csp})
        if path == "/api/data":
            listings, online = all_listings()
            return self.send_json({
                "listings": listings, "online": online, "details": load_details(),
                "email_to": os.environ.get("EMAIL_TO", ""),
                "email_ready": bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD")),
                "has_tested": bool(load_state()["tests"]),
                "left_today": MAX_LIVE_REQUESTS_PER_DAY - sent_today(load_state()),
            })
        self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if not self.trusted() or self.headers.get("X-Token") != TOKEN:
            return self.send_json({"error": "Not allowed"}, 403)
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self.send_json(self.route(urlparse(self.path).path, data))
        except ValueError as e:
            self.send_json({"error": str(e)})
        except Exception as e:
            h.log(f"viewing page error: {e!r}")
            self.send_json({"error": "Something went wrong. Details are in hunter.log."})

    def route(self, path, data):
        if path == "/api/preview":
            return preview(data.get("keys", []))
        if path == "/api/submit":
            return submit(data.get("keys", []))
        if path == "/api/lookup":
            listing = read_listing(data.get("url", ""))
            listing["known_email"] = agent_book().get(normalise(listing["agent"]), "")
            return listing
        if path == "/api/custom":
            return add_custom(data)
        if path == "/api/test-connection":
            ok = h.send_email("House hunter: viewing page connected",
                              "Your viewing page can send email.")
            return {"ok": ok}
        with lock:
            state = load_state()
            key = data.get("key", "")
            if path == "/api/remove":
                state["removed"][key] = datetime.now().isoformat(timespec="minutes")
            elif path == "/api/restore":
                state["removed"].pop(key, None)
            elif path == "/api/delete-custom":
                state["custom"].pop(key, None)
                state["recipients"].pop(key, None)
            elif path == "/api/recipient":
                email = (data.get("email") or "").strip()
                if email and not EMAIL_RE.fullmatch(email):
                    return {"error": "That email address doesn't look right."}
                state["recipients"][key] = email
                if not email:
                    state["recipients"].pop(key)
            elif path == "/api/details":
                details = load_details()
                for field in ("name", "phone", "availability", "group", "year"):
                    if field in data:
                        details[field] = re.sub(r"[\r\n]+", " ", str(data[field]))[:300]
                if "live" in data:
                    if data["live"] and not state["tests"]:
                        return {"error": "Send yourself a test request before going live."}
                    details["live"] = bool(data["live"])
                write_json(DETAILS_FILE, details)
                return {"ok": True}
            else:
                return {"error": "Unknown action"}
            write_json(STATE_FILE, state)
        return {"ok": True}


def serve(open_browser=True):
    h.load_env()
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print("The viewing page is already running. Opening it in your browser.")
        if open_browser:
            webbrowser.open(f"http://{HOST}:{PORT}/")
        return
    print(f"Viewing page running at http://{HOST}:{PORT}/")
    print("Keep this window open while you use it. Close it to stop.")
    if open_browser:
        webbrowser.open(f"http://{HOST}:{PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve("--no-browser" not in sys.argv)
