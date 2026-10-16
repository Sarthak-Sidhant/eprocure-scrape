import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import documents  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(tid):
    return open(os.path.join(FIX, f"summary_{tid}.html"), encoding="utf-8", errors="ignore").read()


def test_corrigendum_and_summary_are_kept_and_certificate_icons_dropped():
    docs = documents.extract_documents(load("2018_NTA_366797_1"))
    assert [(d["name"], d["kind"]) for d in docs] == [("Cor.pdf", "document"), ("techsummary_385179.pdf", "evaluation_summary")]


def test_stated_size_is_read_from_the_document_row():
    docs = {d["name"]: d for d in documents.extract_documents(load("2018_NTA_366797_1"))}
    assert abs(docs["techsummary_385179.pdf"]["declared_bytes"] - 606.33 * 1024) < 2          # the real file is 620,886 bytes


def test_boq_chart_is_found_and_bidder_number_links_are_ignored():
    docs = documents.extract_documents(load("2021_NTA_628462_1"))
    kinds = {d["name"]: d["kind"] for d in docs}
    assert kinds == {"techsummary_661270.pdf": "evaluation_summary", "BOQ_Comparative_Chart": "boq_comparative_chart"}


def test_technical_and_financial_summaries_both_found():
    names = [d["name"] for d in documents.extract_documents(load("2019_NTA_454225_1"))]
    assert names == ["techsummary_475760.pdf", "finsummary_475760.pdf"]


def test_no_link_is_a_digital_signature_page():
    for p in glob.glob(os.path.join(FIX, "summary_*.html")):
        for d in documents.extract_documents(open(p, encoding="utf-8", errors="ignore").read()):
            assert not d["name"].startswith("doc_") and d["name"]


def test_sniff_identifies_real_content_not_file_names():
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")
    assert documents.sniff(b"%PDF-1.4\n...") == "pdf"
    assert documents.sniff(buf.getvalue()) == "xlsx"
    assert documents.sniff(b"<html><body>Document Digital Signature</body></html>") == "html"
    assert documents.sniff(b"\x00\x01\x02") == "unknown"


def test_verify_rejects_html_posing_as_a_pdf_and_flags_a_wrong_size():
    doc = {"name": "doc_1.pdf", "declared_bytes": None}
    bad = documents.verify_download(doc, b"<html>Document Digital Signature</html>")
    assert bad["ok"] is False and "html" in bad["reason"]
    pdf = b"%PDF-1.4 " + b"x" * 10000
    good = documents.verify_download({"name": "techsummary_1.pdf", "declared_bytes": len(pdf)}, pdf)
    assert good["ok"] and good["size_ok"] and good["filename"] == "techsummary_1.pdf" and len(good["sha256"]) == 64
    off = documents.verify_download({"name": "x.pdf", "declared_bytes": 500000}, pdf)
    assert off["ok"] and off["size_ok"] is False


def test_an_excel_chart_named_pdf_is_saved_with_its_real_extension():
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")
    v = documents.verify_download({"name": "BOQ_Comparative_Chart", "declared_bytes": None}, buf.getvalue())
    assert v["ok"] and v["content_type"] == "xlsx" and v["filename"] == "BOQ_Comparative_Chart.xlsx"


def test_attach_documents_replaces_the_old_list_and_keeps_no_dead_urls():
    details = {"Tender ID": "x", "pdf_documents": [{"filename": "x_doc_1.pdf", "url": "https://eprocure.gov.in/?sp=dead"}]}
    out = documents.attach_documents(details, load("2018_NTA_366797_1"))
    assert "pdf_documents" not in out
    assert [d["name"] for d in out["documents"]] == ["Cor.pdf", "techsummary_385179.pdf"]
    assert all("url" not in d for d in out["documents"])           # session-bound URLs are useless once the session ends
    assert out["Tender ID"] == "x"
