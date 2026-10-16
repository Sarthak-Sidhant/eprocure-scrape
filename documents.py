"""Find a tender's real documents on its summary page, and check what a download actually is.

The summary page links several things that are NOT documents:
  * a certificate icon (images/certificate.png, empty text) after every document row opens a "Document Digital Signature"
    pop-up (signer name and date). The old extractor saved these as `doc_N.pdf`: 43% of all captured links were these.
  * bidder-number links open that bidder's bid details.
Real documents are links whose text is a file name; each document row states its size, e.g. "Document : x.pdf ( 606.33 KB )".
The BOQ comparative chart is an Excel workbook even though it was saved with a .pdf name.
"""
import hashlib
import re
import urllib.parse
import zipfile
import io

from bs4 import BeautifulSoup

BASE = "https://eprocure.gov.in"
DOC_EXT = (".pdf", ".xls", ".xlsx", ".zip", ".rar", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".txt", ".csv", ".tif", ".tiff")
SIZE_RE = re.compile(r"\(\s*([\d.,]+)\s*(B|KB|MB|GB)\s*\)", re.I)
UNIT = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}
SUMMARY_NAMES = re.compile(r"(techsummary|finsummary|technical|finance|financial|evaluation|summary)", re.I)


def declared_bytes(row_text):
    m = SIZE_RE.search(row_text or "")
    if not m:
        return None
    return int(float(m.group(1).replace(",", "")) * UNIT[m.group(2).upper()])


def extract_documents(summary_html):
    """Real documents on a tender's summary page: [{name, kind, url, declared_bytes}]. Certificate icons and bidder links are skipped."""
    soup = BeautifulSoup(summary_html or "", "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].replace("&amp;", "&")
        if "SummaryDetailsPrint" not in href:
            continue
        if a.find("img", src=re.compile("certificate", re.I)):
            continue                                         # digital-signature pop-up, not a document
        text = a.get_text(" ", strip=True)
        comp = (re.search(r"component=([^&]+)", href) or [None, ""])[1]
        is_boq = comp == "BOQ"
        if not is_boq and (not text or text.isdigit() or not text.lower().endswith(DOC_EXT)):
            continue                                         # bidder number or an unnamed link
        url = urllib.parse.urljoin(BASE, href)
        if url in seen:
            continue
        seen.add(url)
        row = a.find_parent("tr")
        name = "BOQ_Comparative_Chart" if is_boq else text
        kind = "boq_comparative_chart" if is_boq else ("evaluation_summary" if SUMMARY_NAMES.search(text) else "document")
        out.append({"name": name, "kind": kind, "url": url, "declared_bytes": declared_bytes(row.get_text(" ", strip=True) if row else "")})
    return out


def sniff(content):
    """What the bytes really are: pdf, xlsx, docx, zip, xls/doc (OLE), html, image or unknown."""
    head = content[:1024]
    if b"%PDF" in head:
        return "pdf"
    if head[:2] == b"PK":
        try:
            names = zipfile.ZipFile(io.BytesIO(content)).namelist()
        except zipfile.BadZipFile:
            return "zip"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("word/") for n in names):
            return "docx"
        return "zip"
    if head[:4] == b"\xd0\xcf\x11\xe0":
        return "ole"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    low = head.lower()
    if b"<html" in low or b"<!doctype" in low:
        return "html"
    return "unknown"


EXT_FOR = {"pdf": ".pdf", "xlsx": ".xlsx", "docx": ".docx", "zip": ".zip", "ole": ".xls", "jpeg": ".jpg", "png": ".png"}


def verify_download(doc, content):
    """Check a downloaded file against its link. Never trusts the file name.

    ok is False for HTML/unknown content (a portal error or pop-up page), or a name that says PDF whose bytes are not one.
    size_ok compares with the size the page stated (1% or 2 KB tolerance); it is a warning, not a rejection.
    """
    ctype = sniff(content)
    ok, reason = ctype not in ("html", "unknown"), ""
    if not ok:
        reason = f"downloaded {ctype} content, not a document"
    elif doc["name"].lower().endswith(".pdf") and ctype != "pdf":
        ok, reason = False, f"named .pdf but the content is {ctype}"
    d = doc.get("declared_bytes")
    size_ok = None if d is None else abs(len(content) - d) <= max(2048, d * 0.01)
    base = doc["name"].rsplit(".", 1)[0] if doc["name"].lower().endswith(DOC_EXT) else doc["name"]
    return {"ok": ok, "reason": reason, "content_type": ctype, "ext": EXT_FOR.get(ctype, ""), "filename": base + EXT_FOR.get(ctype, ""),
            "bytes": len(content), "declared_bytes": d, "size_ok": size_ok, "sha256": hashlib.sha256(content).hexdigest()}


def attach_documents(details, summary_html):
    """Replace the old `pdf_documents` list (which included digital-signature pop-ups and had no sizes) with the real documents.

    The download URLs are not kept: they only work inside the portal session that produced them, so a stored one is dead.
    Documents are fetched during the scrape itself, and some tenders' documents are refused by the portal (reported as unavailable).
    """
    details.pop("pdf_documents", None)
    details["documents"] = [{k: d[k] for k in ("name", "kind", "declared_bytes")} for d in extract_documents(summary_html)]
    return details


# ---- storing what we fetched: object paths, the raw-pages bundle, and the live download of each document

import gzip  # noqa: E402
import json  # noqa: E402

MIME = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "zip": "application/zip",
        "ole": "application/vnd.ms-excel", "jpeg": "image/jpeg", "png": "image/png"}
MAX_DOC_BYTES = 200 * 1024 * 1024


def safe_part(s):
    """Letters, digits . _ - only (the hub rejects anything else in a storage path)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s or "").strip("._") or "file"


def tender_prefix(tender_id, org_id):
    """year/org/tender, e.g. 2018/204/2018_NTA_366797_1. Tender ids start with their year."""
    year = tender_id[:4] if tender_id[:4].isdigit() else "unknown"
    return f"{year}/{safe_part(str(org_id))}/{safe_part(tender_id)}"


def pages_bundle(status_html, details_html, summary_html):
    """The tender's three portal pages, gzipped as one JSON file, so every field can be re-parsed later without re-scraping."""
    return gzip.compress(json.dumps({"status": status_html, "details": details_html, "summary": summary_html}).encode("utf-8"), 6)


PORTAL_ERROR = ("the portal's download service failed for this file (it redirects to its generic error page, which says 'session "
                "expired'; a real browser gets the same page, so it is not something the scraper can fix)")


def download_documents(session, docs, timeout=90):
    """Fetch each document on the live portal session. Returns [(doc, content_or_None, verdict_or_None, error_or_None)].

    Must run right after the summary page was loaded, inside the same session: the links only work there. A portal refusal
    (the 'session expired' page it returns for restricted tenders) comes back as a verdict with ok=False, not as an exception.
    """
    out = []
    for d in docs:
        try:
            r = session.get(d["url"], timeout=timeout)
            if len(r.content) > MAX_DOC_BYTES:
                out.append((d, None, None, f"larger than {MAX_DOC_BYTES // 1048576} MB, skipped"))
                continue
            v = verify_download(d, r.content)
            if not v["ok"] and ("CommonErrorPage" in getattr(r, "url", "") or b"session in the client area has expired" in r.content.lower()):
                v["reason"] = PORTAL_ERROR
            out.append((d, r.content, v, None))
        except Exception as e:
            out.append((d, None, None, f"{type(e).__name__}: {str(e)[:100]}"))
    return out
