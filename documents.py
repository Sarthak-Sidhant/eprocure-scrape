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
