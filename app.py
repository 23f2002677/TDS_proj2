# app.py
import os
import json
import time
import base64
import tempfile
from flask import Flask, request, jsonify
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
import pandas as pd

# Playwright imports
from playwright.sync_api import sync_playwright

# PDF parsing
import pdfplumber

APP = Flask(__name__)

# Configuration (set these as environment variables in deployment)
EMAIL = os.environ.get("QUIZ_EMAIL", "23f2002677@ds.study.iitm.ac.in")
SECRET = os.environ.get("QUIZ_SECRET", "S2_xA9_quiz_4421")

# Helper: validate JSON and secret
def validate_payload(req_json):
    if not isinstance(req_json, dict):
        return False, ("bad json", 400)
    if "secret" not in req_json or "email" not in req_json or "url" not in req_json:
        return False, ("bad json", 400)
    if req_json.get("secret") != SECRET:
        return False, ("forbidden", 403)
    return True, None

# Helper: download file
def download_file(session, file_url):
    r = session.get(file_url, timeout=60)
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(r.content)
    tmp.flush()
    return tmp.name

# Heuristic solver for the typical quiz patterns
def solve_quiz_page(page_content, page_url, session, browser_page):
    soup = BeautifulSoup(page_content, "html.parser")

    # 1) Try to find direct JSON payloads inside <pre> or scripts (often quizzes embed JSON)
    pre = soup.find("pre")
    if pre:
        try:
            j = json.loads(pre.get_text())
            # sample heuristic: if asks sum of "value" column etc.
            if isinstance(j, dict) and "answer" in j:
                return j["answer"]
        except Exception:
            pass

    # 2) Look for download links to PDF or CSV (common)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # resolve relative links
        file_url = urljoin(page_url, href)
        if file_url.lower().endswith((".pdf", ".csv", ".xls", ".xlsx")):
            try:
                local = download_file(session, file_url)
                if local.lower().endswith(".pdf"):
                    # try to extract tables from PDFs and sum numeric columns
                    with pdfplumber.open(local) as pdf:
                        # If quiz said "page 2", try that; otherwise scan all pages
                        all_tables = []
                        for p in pdf.pages:
                            try:
                                tables = p.extract_tables()
                                for t in tables:
                                    df = pd.DataFrame(t[1:], columns=t[0])
                                    all_tables.append(df)
                            except Exception:
                                continue
                        # basic heuristic: find numeric columns and sum
                        for df in all_tables:
                            # try to coerce all columns to numeric where possible
                            for col in df.columns:
                                try:
                                    col_num = pd.to_numeric(df[col].str.replace(r'[^\d.-]', '', regex=True), errors='coerce')
                                    if col_num.notna().sum() > 0:
                                        s = float(col_num.sum(skipna=True))
                                        # we return first numeric sum found (reasonable heuristic)
                                        return s
                                except Exception:
                                    continue
                else:
                    # CSV or Excel
                    df = pd.read_csv(local) if local.endswith(".csv") else pd.read_excel(local)
                    # heuristic: sum the first numeric column
                    numeric_cols = df.select_dtypes(include="number").columns
                    if len(numeric_cols) > 0:
                        return float(df[numeric_cols[0]].sum())
            except Exception as e:
                continue

    # 3) If the page contains an explicit instruction and a submit URL (common pattern)
    # Try to find a JSON payload in a script tag (base64 or text)
    scripts = soup.find_all("script")
    for s in scripts:
        text = s.get_text()
        # look for base64 inside atob(`...`)
        if "atob(" in text:
            import re
            m = re.search(r'atob\(\s*[\'"]([^\'"]+)[\'"]\s*\)', text)
            if m:
                try:
                    decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="ignore")
                    # if decoded looks like JSON or contains "answer" or "sum"
                    try:
                        js = json.loads(decoded)
                        # basic heuristic
                        if "answer" in js:
                            return js["answer"]
                    except Exception:
                        # fallback: search for phrases like "sum of" etc.
                        if "sum of" in decoded.lower():
                            # try to find numbers and sum them
                            nums = [float(x) for x in re.findall(r"[-+]?\d*\.\d+|\d+", decoded)]
                            if nums:
                                return sum(nums)
                except Exception:
                    pass

    # 4) Fallback: try to inspect the rendered DOM via Playwright page (handles JS)
    # If we have a browser_page (Playwright), attempt to query known container ids
    try:
        # example: many quizzes put result in #result or #question
        for qid in ["#result", "#question", "#content", "#root"]:
            try:
                el = browser_page.query_selector(qid)
                if el:
                    txt = el.inner_text()
                    # heuristic: find numbers
                    import re
                    nums = re.findall(r"[-+]?\d*\.\d+|\d+", txt)
                    if nums:
                        # return sum of the numbers (heuristic)
                        numsf = [float(n) for n in nums]
                        return sum(numsf)
                    # if text contains "true" or "false"
                    if "true" in txt.lower():
                        return True
                    if "false" in txt.lower():
                        return False
            except Exception:
                continue
    except Exception:
        pass

    # If nothing matched, return a fallback: the page text (as a string) so you can inspect.
    return {"unresolved_text_snippet": soup.get_text()[:1000]}

# Extract submit URL from page (heuristic)
def find_submit_url(soup, page_url):
    # look for form action
    form = soup.find("form", action=True)
    if form:
        return urljoin(page_url, form["action"])
    # look for explicit text "submit to" or direct endpoints in scripts
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/submit" in href or "submit" in href.lower():
            return urljoin(page_url, href)
    # find JS fetch() strings
    scripts = soup.find_all("script")
    import re
    for s in scripts:
        matches = re.findall(r'["\'](https?://[^"\']+/submit[^"\']*)["\']', s.get_text())
        if matches:
            return matches[0]
    return None

# Main solver flow: visits the page and attempts solve
def visit_and_solve(url, timeout_seconds=120):
    session = requests.Session()
    session.headers.update({"User-Agent": "quiz-solver-bot/1.0"})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        page = context.new_page()
        page.set_default_navigation_timeout(timeout_seconds * 1000)
        page.goto(url)
        # wait network idle briefly for JS to render
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        content = page.content()
        soup = BeautifulSoup(content, "html.parser")

        # find submit URL
        submit_url = find_submit_url(soup, url)

        # Solve using heuristics
        answer = solve_quiz_page(content, url, session, page)

        browser.close()
    return answer, submit_url

# POST answer to submit_url with required payload
def post_answer(submit_url, payload):
    headers = {"Content-Type": "application/json"}
    r = requests.post(submit_url, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()

# Endpoint required by assignment
@APP.route("/api/quiz-webhook", methods=["POST"])
def quiz_webhook():
    try:
        req_json = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "invalid json"}), 400

    ok, err = validate_payload(req_json)
    if not ok:
        msg, code = err
        return jsonify({"error": msg}), code

    # Immediately respond 200 to the quiz system (this is allowed by spec)
    # The spec requires respond 200 JSON if secret matches; we also start solving synchronously here.
    response_ack = {"status": "accepted"}
    # But we must still solve and submit within 3 minutes; do it synchronously now.
    client_email = req_json["email"]
    client_secret = req_json["secret"]
    quiz_url = req_json["url"]

    try:
        # Visit page and attempt to solve
        answer, submit_url = visit_and_solve(quiz_url)
    except Exception as e:
        return jsonify({"error": "failed to visit url", "detail": str(e)}), 500

    # If submit_url not found: return the answer as part of response so the caller can inspect (still 200)
    if not submit_url:
        return jsonify({"status": "no_submit_url", "answer_candidate": answer}), 200

    # Build payload for submission
    submit_payload = {
        "email": client_email,
        "secret": client_secret,
        "url": quiz_url,
        "answer": answer
    }

    try:
        result = post_answer(submit_url, submit_payload)
    except Exception as e:
        return jsonify({"status": "submit_failed", "detail": str(e), "submit_payload": submit_payload}), 502

    # Return final result from submit endpoint
    return jsonify({"status": "submitted", "submit_result": result}), 200

if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
