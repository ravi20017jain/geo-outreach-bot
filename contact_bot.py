# -*- coding: utf-8 -*-
"""
AI-Powered Contact Form Bot
- Claude Vision API: form analyze karta hai
- 2captcha: captcha automatically solve karta hai
- Google Sheets: real-time status update
- GitHub Actions: scheduled cloud run
"""
import os
import json
import base64
import time
import logging
import sys
from datetime import datetime

import anthropic
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
import twocaptcha

# ------------------------------------------
#  CONFIGURATION — GitHub Secrets se aata hai
# ------------------------------------------

ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
CAPTCHA_API_KEY     = os.environ["CAPTCHA_API_KEY"]
GOOGLE_SHEET_ID     = os.environ["GOOGLE_SHEET_ID"]       # Sheet URL se ID
GOOGLE_CREDS_JSON   = os.environ["GOOGLE_CREDS_JSON"]     # Service account JSON

FIRST_NAME  = "Salman"
LAST_NAME   = "Khan"
FULL_NAME   = "Salman Khan"
COMPANY     = "Zevahit"
EMAIL       = "sales@zevahit.com"
PHONE       = "+918109201842"
SUBJECT     = "Is Your Client's Brand Invisible to ChatGPT?"

MESSAGE = "Hi,\n\nQuick question - when someone asks ChatGPT or Perplexity about your client's niche, does their brand show up?\n\nFor most businesses, the answer is no. And as more buyers shift to AI for research, that's a growing problem every month.\n\nWe help brands get cited by LLMs like ChatGPT, Gemini, and Perplexity through strategic guest posts on high-authority, niche-relevant sites. The logic is simple - AI models pull from trusted published content, so more quality mentions = higher chance of being recommended by AI.\n\nThis isn't traditional link building. It's Generative Engine Optimization (GEO) - and agencies offering it now will have a serious edge.\n\nWould love to show you how this fits into your client offerings. Open to a quick chat?\n\nWarm Regards,\nSalman\nZevahit.com\nClient Reviews: https://clutch.co/profile/zevahit#reviews"

PROCESS_LIMIT = None  # None = sab sites ek hi run mein

CONTACT_KEYWORDS = ["contact", "contact-us", "get-in-touch", "reach-us", "write-to-us"]

# ------------------------------------------
#  LOGGING
# ------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

# ------------------------------------------
#  GOOGLE SHEETS SETUP
# ------------------------------------------

def init_sheets():
    """Google Sheets connection initialize karo."""
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)

    # Websites sheet
    try:
        ws = sh.worksheet("websites")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("websites", rows=1000, cols=6)
        ws.update("A1:F1", [["website", "status", "submitted_at", "notes", "fields_filled", "ai_actions"]])

    return ws


def get_all_rows(ws):
    """Saari rows fetch karo."""
    return ws.get_all_records()


def update_sheet_row(ws, row_num, status, notes="", fields_filled="", ai_actions=""):
    """Single row update karo — row_num is 1-based (header = row 1, data starts row 2)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # row_num + 1 because header is row 1
    excel_row = row_num + 1
    ws.update("B{}:F{}".format(excel_row, excel_row),
              [[status, now, notes, fields_filled, ai_actions]])
    log.info("  [Sheets] Row {} -> {}".format(excel_row, status))


def get_pending_rows(ws):
    """
    Sirf pending rows return karo (status empty ya error).
    Returns list of (row_index_1based, website_url)
    """
    rows = ws.get_all_records()
    pending = []
    for i, row in enumerate(rows):
        url     = str(row.get("website", "")).strip()
        status  = str(row.get("status", "")).strip().lower()
        if url and status not in ("submitted",):
            pending.append((i + 1, url))   # i+1 = 1-based data row index
    return pending

# ------------------------------------------
#  URL HELPERS
# ------------------------------------------

def normalise_url(url):
    url = str(url).strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


def find_contact_page(page, base_url):
    current_url = page.url

    # Step 1: Scan links — click FIRST match only, then return immediately
    try:
        links = page.locator("a").all()
        for link in links:
            try:
                href = link.get_attribute("href") or ""
                if any(kw in href.lower() for kw in CONTACT_KEYWORDS):
                    # Skip if already on contact page
                    if any(kw in current_url.lower() for kw in CONTACT_KEYWORDS):
                        log.info("  Already on contact page: {}".format(current_url))
                        return True
                    log.info("  Contact link: {}".format(href))
                    try:
                        link.click()
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass  # timeout ho to bhi aage badho
                    time.sleep(0.5)
                    return True  # immediately return — no loop
            except Exception:
                pass
    except Exception:
        pass

    # Step 2: Already on contact page check
    if any(kw in current_url.lower() for kw in CONTACT_KEYWORDS):
        log.info("  Already on contact page: {}".format(current_url))
        return True

    # Step 3: Guess common paths
    for kw in CONTACT_KEYWORDS:
        candidate = "{}/{}".format(base_url, kw)
        try:
            resp = page.goto(candidate, timeout=10000, wait_until="domcontentloaded")
            title = page.title().lower()
            if resp and resp.status < 400 and "404" not in title and "not found" not in title:
                log.info("  Contact page: {}".format(candidate))
                return True
        except Exception:
            pass
    return False

# ------------------------------------------
#  CAPTCHA SOLVER (2captcha)
# ------------------------------------------

def solve_captcha(page, website):
    """
    Detect aur automatically solve karo:
    - reCAPTCHA v2
    - hCaptcha
    - Cloudflare Turnstile
    """
    solver = twocaptcha.TwoCaptcha(CAPTCHA_API_KEY)

    # --- reCAPTCHA v2 ---
    try:
        frame = page.locator('iframe[src*="recaptcha"]').first
        if frame.is_visible(timeout=1000):
            src = frame.get_attribute("src") or ""
            # Extract sitekey from iframe src
            sitekey = ""
            for part in src.split("&"):
                if "k=" in part:
                    sitekey = part.split("k=")[1].split("&")[0]
                    break
            if not sitekey:
                # Try from div
                div = page.locator('.g-recaptcha').first
                sitekey = div.get_attribute("data-sitekey") or ""

            if sitekey:
                log.info("  [CAPTCHA] reCAPTCHA detected, solving via 2captcha...")
                result = solver.recaptcha(sitekey=sitekey, url=website)
                token = result["code"]
                # Inject token
                page.evaluate("""(token) => {
                    document.getElementById('g-recaptcha-response').innerHTML = token;
                    if (typeof ___grecaptcha_cfg !== 'undefined') {
                        Object.entries(___grecaptcha_cfg.clients).forEach(([key, client]) => {
                            Object.entries(client).forEach(([k, v]) => {
                                if (typeof v === 'object' && v !== null && 'callback' in v) {
                                    try { v.callback(token); } catch(e) {}
                                }
                            });
                        });
                    }
                }""", token)
                log.info("  [CAPTCHA] reCAPTCHA solved!")
                return True
    except Exception as e:
        log.debug("  reCAPTCHA solve attempt: {}".format(e))

    # --- hCaptcha ---
    try:
        frame = page.locator('iframe[src*="hcaptcha.com"]').first
        if frame.is_visible(timeout=1000):
            div = page.locator('.h-captcha').first
            sitekey = div.get_attribute("data-sitekey") or ""
            if sitekey:
                log.info("  [CAPTCHA] hCaptcha detected, solving...")
                result = solver.hcaptcha(sitekey=sitekey, url=website)
                token = result["code"]
                page.evaluate("""(token) => {
                    document.querySelector('[name="h-captcha-response"]').value = token;
                    document.querySelector('[name="g-recaptcha-response"]') &&
                        (document.querySelector('[name="g-recaptcha-response"]').value = token);
                }""", token)
                log.info("  [CAPTCHA] hCaptcha solved!")
                return True
    except Exception as e:
        log.debug("  hCaptcha solve attempt: {}".format(e))

    # --- Cloudflare Turnstile ---
    try:
        div = page.locator('.cf-turnstile').first
        if div.is_visible(timeout=1000):
            sitekey = div.get_attribute("data-sitekey") or ""
            if sitekey:
                log.info("  [CAPTCHA] Cloudflare Turnstile detected, solving...")
                result = solver.turnstile(sitekey=sitekey, url=website)
                token = result["code"]
                page.evaluate("""(token) => {
                    document.querySelector('[name="cf-turnstile-response"]').value = token;
                }""", token)
                log.info("  [CAPTCHA] Turnstile solved!")
                return True
    except Exception as e:
        log.debug("  Turnstile solve attempt: {}".format(e))

    return False

# ------------------------------------------
#  AI FORM ANALYSIS (Claude Vision)
# ------------------------------------------

def get_page_html(page):
    try:
        return page.evaluate("""() => {
            const els = document.querySelectorAll(
                'input, textarea, button, select, label, form'
            );
            return Array.from(els).map(el => el.outerHTML).join('\\n');
        }""")[:8000]
    except Exception:
        return ""


def ask_claude(page, website):
    """Claude Vision se form actions lao."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Screenshot lo — retry ke saath (kabhi-kabhi Chrome capture fail karta hai)
    screenshot_bytes = None
    # Viewport chhota fix karo taaki screenshot kabhi 8000px se badi na ho
    try:
        page.set_viewport_size({"width": 1280, "height": 1024})
    except Exception:
        pass
    for attempt in range(3):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
            time.sleep(1)
            screenshot_bytes = page.screenshot(full_page=False, timeout=15000)
            break
        except Exception as e:
            log.warning("  [Screenshot] attempt {} failed: {}".format(attempt + 1, e))
            time.sleep(2)

    # Resize using PIL if image too large — Claude limit 8000px
    if screenshot_bytes:
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(screenshot_bytes))
            # Resize if larger than 1280px width
            if img.width > 1280 or img.height > 1280:
                img.thumbnail((1280, 1280), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            screenshot_bytes = buf.getvalue()
        except Exception as e:
            # PIL fail hua / resize nahi hua to image SKIP karo (oversized image 400 deta hai)
            log.warning("  [Screenshot] resize failed, image skip: {}".format(e))
            screenshot_bytes = None

    # Screenshot mila to base64 banao, warna khali (image optional)
    img_b64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8") if screenshot_bytes else ""

    page_html = get_page_html(page)
    # HTML bahut bada ho to trim karo — warna API 400 deta hai
    if len(page_html) > 50000:
        page_html = page_html[:50000]

    prompt = """You are a web automation expert. Fill this contact form on: {website}

Form HTML:
{html}

Details to fill:
- Full Name: {full_name}
- First Name: {first_name}
- Last Name: {last_name}
- Company: {company}
- Email: {email}
- Phone: {phone}
- Subject/Title: {subject}
- Message (copy EXACTLY, keep all line breaks):
{message}

IMPORTANT: Fill the message field with the COMPLETE text above. Do not truncate or summarize.

Return ONLY a JSON array of actions. Each action:
  "action": "fill" | "check" | "click" | "select"
  "selector": CSS selector (prefer name/id/type attributes)
  "value": value to use

Rules:
- Only include fields that exist in the HTML
- For checkboxes (terms/agree/consent/privacy) use "check"
- For submit button use "click" — include it last
- Message field: use the FULL message text provided
- Return ONLY JSON, no markdown, no explanation""".format(
        website=website,
        html=page_html,
        full_name=FULL_NAME,
        first_name=FIRST_NAME,
        last_name=LAST_NAME,
        company=COMPANY,
        email=EMAIL,
        phone=PHONE,
        subject=SUBJECT,
        message=MESSAGE
    )

    content = []
    if img_b64:  # screenshot mila tabhi image bhejo
        content.append({"type": "image", "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": img_b64
        }})
    content.append({"type": "text", "text": prompt})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": content}]
    )

    raw = response.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ------------------------------------------
#  EXECUTE ACTIONS
# ------------------------------------------

def scroll_to(page, locator):
    try:
        locator.scroll_into_view_if_needed(timeout=2000)
        time.sleep(0.2)
    except Exception:
        pass


def execute_actions(page, actions):
    filled = []
    submitted = False

    for action in actions:
        act      = action.get("action", "").lower()
        selector = action.get("selector", "")
        value    = action.get("value", "")

        if not selector:
            continue

        try:
            locator = page.locator(selector).first
            scroll_to(page, locator)

            if act == "fill":
                if locator.is_visible(timeout=1000):
                    locator.fill(value)
                    log.info("  [OK] fill: {}".format(selector[:50]))
                    filled.append(selector[:30])

            elif act == "check":
                if locator.is_visible(timeout=1000) and not locator.is_checked():
                    locator.check()
                    log.info("  [OK] check: {}".format(selector[:50]))

            elif act == "select":
                if locator.is_visible(timeout=1000):
                    locator.select_option(value)
                    log.info("  [OK] select: {}".format(selector[:50]))

            elif act == "click":
                if locator.is_visible(timeout=1000):
                    url_before = page.url
                    locator.click()
                    time.sleep(3)
                    # Submit sach me hua ya nahi — verify karo
                    page_text = ""
                    try:
                        page_text = page.inner_text("body", timeout=3000).lower()
                    except Exception:
                        pass
                    success_words = ["thank you", "thanks", "message sent", "we'll be in touch",
                                     "we have received", "submitted successfully", "your message",
                                     "successfully sent", "received your", "get back to you"]
                    url_changed = page.url != url_before
                    if any(w in page_text for w in success_words) or url_changed:
                        submitted = True
                        log.info("  [OK] submit confirmed: {}".format(selector[:50]))
                    else:
                        log.warning("  [??] clicked but NO confirmation: {}".format(selector[:50]))

        except Exception as e:
            log.warning("  [--] {}: {} -> {}".format(act, selector[:50], e))

    return filled, submitted

# ------------------------------------------
#  MAIN
# ------------------------------------------

def main():
    # Google Sheets init
    log.info("Connecting to Google Sheets...")
    ws = init_sheets()

    pending = get_pending_rows(ws)
    log.info("Pending sites: {}".format(len(pending)))

    if not pending:
        log.info("No pending sites. Done!")
        return

    # Process only PROCESS_LIMIT sites per run
    to_process = pending[:PROCESS_LIMIT]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,   # Cloud pe headless=True
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )

        # Block sirf images/media for speed — CSS/JS chalne do (warna form submit toot jaata hai)
        pg = context.new_page()
        pg.route("**/*", lambda route: route.abort()
            if route.request.resource_type in ("image", "media")
            else route.continue_())

        for row_idx, website_raw in to_process:
            website = normalise_url(website_raw)
            log.info("\nOpening: {}".format(website))

            try:
                pg.goto(website, timeout=30000, wait_until="domcontentloaded")
                time.sleep(1)

                contact_found = find_contact_page(pg, website)
                if not contact_found:
                    log.warning("  No contact page")
                    update_sheet_row(ws, row_idx, "no_contact_page", "No contact page found")
                    continue

                time.sleep(1)

                # Solve captcha if present
                solve_captcha(pg, website)

                # Claude analyzes form
                try:
                    actions = ask_claude(pg, website)
                    log.info("  [AI] {} actions".format(len(actions)))
                except Exception as e:
                    log.error("  [AI] Error: {}".format(e))
                    update_sheet_row(ws, row_idx, "error", "AI error: {}".format(str(e)[:80]))
                    continue

                # Execute
                filled, submitted = execute_actions(pg, actions)
                time.sleep(1)

                # Captcha after submit
                if not submitted and solve_captcha(pg, website):
                    _, submitted = execute_actions(pg,
                        [a for a in actions if a.get("action") == "click"])

                # Screenshot BEFORE submit — form filled dikhega
                try:
                    import re, os
                    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', website)[:50]
                    os.makedirs("screenshots/before_submit", exist_ok=True)
                    screenshot_path = "screenshots/before_submit/{}.png".format(safe_name)
                    pg.screenshot(path=screenshot_path, full_page=False)
                    log.info("  [Screenshot] Before submit saved: {}".format(screenshot_path))
                except Exception as e:
                    log.warning("  [Screenshot] Failed: {}".format(e))

                status = "submitted" if submitted else "filled_not_submitted"

                # Screenshot AFTER submit — confirmation page dikhega
                try:
                    import re, os
                    # submit ke baad page settle hone do (redirect / thank-you page)
                    try:
                        pg.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    time.sleep(2)
                    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', website)[:50]
                    os.makedirs("screenshots/after_submit", exist_ok=True)
                    screenshot_path = "screenshots/after_submit/{}.png".format(safe_name)
                    pg.screenshot(path=screenshot_path, full_page=False)
                    log.info("  [Screenshot] After submit saved: {}".format(screenshot_path))
                except Exception as e:
                    log.warning("  [Screenshot] Failed: {}".format(e))

                update_sheet_row(
                    ws, row_idx, status,
                    notes="OK" if submitted else "Submit failed",
                    fields_filled=", ".join(filled),
                    ai_actions=str(len(actions))
                )

                log.info("  Status: {}".format(status))
                time.sleep(1)

            except Exception as e:
                log.error("  ERROR: {}".format(e))
                update_sheet_row(ws, row_idx, "error", str(e)[:100])

        browser.close()

    log.info("\nRun complete!")


if __name__ == "__main__":
    main()
