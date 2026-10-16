"""Turn a tender's three portal pages into the same structured fields your September database had.

A faithful port of parse_single_tender() from the September build script (build_sqlite_and_json_dataset.py), but working on
page text instead of files, so it can run inside the scraper. Values are kept as the portal wrote them (strings, with the same
handful of integers) so the output can be compared field for field with the original. Typed columns (dates, amounts) are made
in Postgres by the views in sql/tenders.sql.
"""
import json

from bs4 import BeautifulSoup

COLUMNS = [
    "tender_id", "org_id", "org_name", "org_chain", "tender_ref_no", "tender_title", "stage", "sno", "view_link",
    "tender_type", "form_of_contract", "tender_category", "no_of_covers", "payment_mode",
    "is_multi_currency_boq", "is_multi_currency_fee", "allow_two_stage_bidding", "withdrawal_allowed",
    "general_tech_eval_allowed", "itemwise_tech_eval_allowed",
    "tender_fee", "fee_payable_to", "fee_payable_at", "tender_fee_exemption_allowed",
    "emd_amount", "emd_fee_type", "emd_percentage", "emd_exemption_allowed", "emd_payable_to", "emd_payable_at",
    "work_description", "pre_qualification", "iem_remarks", "tender_value", "product_category", "sub_category", "contract_type",
    "bid_validity_days", "period_of_work_days", "location", "pincode",
    "pre_bid_meeting_place", "pre_bid_meeting_address", "pre_bid_meeting_date", "bid_opening_place",
    "published_date", "bid_opening_date", "bid_download_start_date", "bid_download_end_date",
    "clarification_start_date", "clarification_end_date", "bid_submission_start_date", "bid_submission_end_date",
    "tia_name", "tia_address",
    "bids_count", "qualified_bids_count", "winner_bidder_name", "awarded_value", "award_date", "has_boq_chart", "has_tech_summary",
]

COMMERCIAL_KEYWORDS = ["BOQ", "Comparative", "technical", "finance", "finsummary", "techsummary", "corrigendum", "cancel"]


def _soup(html):
    return BeautifulSoup(html or "", "lxml")


def procurement_details(details_html):
    """Every label/value pair on the Tender Details page (first occurrence of a label wins)."""
    d2 = {}
    for tr in _soup(details_html).find_all("tr"):
        cells = tr.find_all(["td", "th"], recursive=False)
        i = 0
        while i < len(cells) - 1:
            k = cells[i].text.strip().replace(":", "").strip()
            v = cells[i + 1].text.strip()
            if 0 < len(k) < 60 and "\n" not in k:
                if k not in d2:
                    d2[k] = v
                i += 2
            else:
                i += 1
    return d2


def commercial_outcomes(tender_id, bids_list, status_html, summary_html, file_names):
    outcomes = {"tender_id": tender_id, "bids_list": bids_list, "stages": [], "technical_opening": {}, "technical_evaluation": {},
                "finance_opening": {}, "finance_evaluation": {}, "aoc": {}, "commercial_files": [], "additional_sections": {}}
    tbl = _soup(status_html).find("table", class_="list_table")
    if tbl:
        for r in tbl.find_all("tr")[1:]:
            cs = [c.text.strip().replace("\n", " ") for c in r.find_all(["td", "th"]) if c.text.strip()]
            if len(cs) >= 2:
                outcomes["stages"].append({"process_or_stage": cs[0], "status": cs[1]})
    for tbl in _soup(summary_html).find_all("table", class_="table_list"):
        rows = tbl.find_all("tr")
        if not rows:
            continue
        title = rows[0].text.strip().replace("\n", " ")
        target = None
        if "Technical Bid Opening" in title:
            target = outcomes["technical_opening"]
        elif "Technical Evaluation" in title:
            target = outcomes["technical_evaluation"]
        elif "Finance Bid Opening" in title or "Financial Bid Opening" in title:
            target = outcomes["finance_opening"]
        elif "Financial Evaluation" in title:
            target = outcomes["finance_evaluation"]
        elif "Award of Contract" in title or "AOC" in title:
            target = outcomes["aoc"]
        if target is not None:
            for r in rows[1:]:
                cs = [c.text.strip().replace("\n", " ") for c in r.find_all(["td", "th"]) if c.text.strip()]
                if len(cs) == 2:
                    target[cs[0].replace(":", "").strip()] = cs[1]
        elif "Bids List" not in title and "Organisation Chain" not in title:
            sec_rows = []
            for r in rows[1:]:
                cs = [c.text.strip().replace("\n", " ") for c in r.find_all(["td", "th"]) if c.text.strip()]
                if cs:
                    sec_rows.append(cs)
            if sec_rows:
                outcomes["additional_sections"][title] = sec_rows
    outcomes["commercial_files"] = [f for f in file_names if any(kw in f for kw in COMMERCIAL_KEYWORDS)]
    return outcomes


def parse_tender(tender_id, org_id, org_name, dj, status_html, details_html, summary_html, file_names):
    """dj: what the old details.json held (the scraper's details dict plus stage, sno, view_link, tender_id).

    Returns (fields, procurement_details, outcomes). `fields` has the COLUMNS above.
    """
    bids_list = dj.get("bids", [])
    tender_id = dj.get("tender_id") or tender_id
    tender_ref_no = dj.get("Tender Ref No") or dj.get("tender_ref_no") or ""
    tender_title = dj.get("Tender Title") or dj.get("tender_title") or ""
    org_chain = dj.get("Organisation Chain") or dj.get("org_chain") or ""
    d2 = procurement_details(details_html)

    def g(patterns, default=""):
        for pat in patterns:
            for k, val in d2.items():
                if pat.lower() in k.lower():
                    return val
        return default

    def as_int(s):
        return int(s) if s.isdigit() else None

    if not tender_ref_no:
        tender_ref_no = g(["Tender Reference Number", "Tender Ref No"])
    if not tender_title:
        tender_title = g(["Title", "Work Description"])
    out = commercial_outcomes(tender_id, bids_list, status_html, summary_html, file_names)
    aoc = out["aoc"]
    f = {
        "tender_id": tender_id, "org_id": org_id, "org_name": org_name, "org_chain": org_chain, "tender_ref_no": tender_ref_no,
        "tender_title": tender_title, "stage": dj.get("stage") or "", "sno": dj.get("sno") or "", "view_link": dj.get("view_link") or "",
        "tender_type": g(["Tender Type"]), "form_of_contract": g(["Form of contract"]), "tender_category": g(["Tender Category"]),
        "no_of_covers": as_int(g(["No. of Covers", "No of Covers"])), "payment_mode": g(["Payment Mode"]),
        "is_multi_currency_boq": g(["Is Multi Currency Allowed For BOQ"]), "is_multi_currency_fee": g(["Is Multi Currency Allowed For Fee"]),
        "allow_two_stage_bidding": g(["Allow Two Stage Bidding"]), "withdrawal_allowed": g(["Withdrawal Allowed"]),
        "general_tech_eval_allowed": g(["General Technical Evaluation Allowed"]), "itemwise_tech_eval_allowed": g(["ItemWise Technical Evaluation Allowed"]),
        "tender_fee": g(["Total Fee in", "Tender Fee in"]), "fee_payable_to": g(["Fee Payable To"]), "fee_payable_at": g(["Fee Payable At"]),
        "tender_fee_exemption_allowed": g(["Tender Fee Exemption Allowed"]),
        "emd_amount": g(["EMD Amount in", "EMD Amount"]), "emd_fee_type": g(["EMD Fee Type"]), "emd_percentage": g(["EMD Percentage"]),
        "emd_exemption_allowed": g(["EMD Exemption Allowed"]), "emd_payable_to": g(["EMD Payable To"]), "emd_payable_at": g(["EMD Payable At"]),
        "work_description": g(["Work Description"]) or tender_title, "pre_qualification": g(["Pre Qualification Details"]),
        "iem_remarks": g(["Independent External Monitor/Remarks"]), "tender_value": g(["Tender Value in", "Tender Value"]),
        "product_category": g(["Product Category"]), "sub_category": g(["Sub category", "Sub-category"]), "contract_type": g(["Contract Type"]),
        "bid_validity_days": as_int(g(["Bid Validity(Days)", "Bid Validity"])), "period_of_work_days": as_int(g(["Period Of Work(Days)", "Period Of Work"])),
        "location": g(["Location"]), "pincode": g(["Pincode", "Pin Code"]),
        "pre_bid_meeting_place": g(["Pre Bid Meeting Place"]), "pre_bid_meeting_address": g(["Pre Bid Meeting Address"]),
        "pre_bid_meeting_date": g(["Pre Bid Meeting Date"]), "bid_opening_place": g(["Bid Opening Place"]),
        "published_date": g(["Publish Date"]), "bid_opening_date": g(["Bid Opening Date"]),
        "bid_download_start_date": g(["Document Download / Sale Start Date", "Document Download Start Date"]),
        "bid_download_end_date": g(["Document Download / Sale End Date", "Document Download End Date"]),
        "clarification_start_date": g(["Clarification Start Date"]), "clarification_end_date": g(["Clarification End Date"]),
        "bid_submission_start_date": g(["Bid Submission Start Date"]), "bid_submission_end_date": g(["Bid Submission End Date"]),
        "tia_name": g(["Name"]), "tia_address": g(["Address"]),
        "bids_count": len(bids_list),
        "qualified_bids_count": sum(1 for b in bids_list if any(w in str(b.get("status", "")).lower() for w in ["admit", "qualified", "accepted"])),
        "winner_bidder_name": aoc.get("Contractor Name") or aoc.get("Selected Bidder") or aoc.get("Contractor") or "",
        "awarded_value": aoc.get("Contract Value") or aoc.get("Awarded Value") or "",
        "award_date": aoc.get("Contract Date") or aoc.get("Award Date") or "",
        "has_boq_chart": 1 if any("BOQ" in x or "Comparative" in x for x in out["commercial_files"]) else 0,
        "has_tech_summary": 1 if any("techsummary" in x or "technical" in x for x in out["commercial_files"]) else 0,
    }
    assert list(f) == COLUMNS
    return f, d2, out
