"""Which GePNIC portal this process works on, chosen by the PORTAL environment variable (default eprocure.gov.in).

Every module builds its URLs from here, so the same crawler, counter and parser serve all the state, central and PSU portals in
data/gepnic_portals.json (the hub's registry, copied). eprocure.gov.in keeps its original project names and storage paths; any other
portal gets the projects gepnic-<slug> (tenders) and gepnic-<slug>-plan (count tasks) and stores files by organisation code.
"""
import json
import os
import re
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "data", "gepnic_portals.json")
LEGACY_NAME = "eprocure.gov.in"


def registry():
    return {p["portal"]: p for p in json.load(open(REGISTRY))["portals"]}


def slug(name):
    """wbtenders.gov.in -> wbtenders, eproc.rajasthan.gov.in -> eproc-rajasthan, eprocure.gov.in/epublish -> eprocure-epublish."""
    s = re.sub(r"\.(gov|nic|co)\.in", "", name.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


NAME = os.environ.get("PORTAL", LEGACY_NAME).strip() or LEGACY_NAME
_P = registry().get(NAME)
if _P is None:
    raise SystemExit(f"unknown portal {NAME!r}: pick one from data/gepnic_portals.json")
if _P.get("ui") == "gepnic2":
    raise SystemExit(f"{NAME} runs the new GePNIC 2.0 interface; this crawler only speaks the classic one")

LEGACY = NAME == LEGACY_NAME
APP = _P["app_url"]                                  # e.g. https://wbtenders.gov.in/nicgep/app
_u = urllib.parse.urlsplit(APP)
ORIGIN = f"{_u.scheme}://{_u.netloc}"                # https://wbtenders.gov.in
HOST = _u.netloc
APP_PATH = _u.path                                   # /nicgep/app or /eprocure/app
SEARCH_URL = APP + "?page=WebTenderStatusLists&service=page"
TITLE = _P["title"]
TENDERS = "eprocure-tenders" if LEGACY else f"gepnic-{slug(NAME)}"
PLAN = "eprocure-plan" if LEGACY else f"gepnic-{slug(NAME)}-plan"
PROBE = "eprocure" if LEGACY else f"gepnic:{NAME}"   # the hub's uptime check for this portal; runners hold while it fails
MIN_ORGS = 500 if LEGACY else 1                      # sanity check on the organisation dropdown


def url(href):
    """Absolute URL on this portal for a link found on one of its pages."""
    return urllib.parse.urljoin(ORIGIN, href.replace("&amp;", "&"))


def app_url(query):
    return f"{APP}?{query}"


def cookie(session):
    session.cookies.set("cookieWorked", "yes", domain=HOST, path="/")
