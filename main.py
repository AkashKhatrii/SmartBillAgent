from flask import Flask, request, jsonify, render_template_string, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from threading import Thread
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
import os
import anthropic
import pytz
from xhtml2pdf import pisa
import logging
logging.basicConfig(level=logging.DEBUG)

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN") # Replace with your token
ANIL_KIRYANA_BOT_TOKEN = os.environ.get("ANIL_KIRYANA_BOT_TOKEN")
RS_VEGETABLES_BOT_TOKEN = os.environ.get("RS_VEGETABLES_BOT_TOKEN")
PDF_API = os.environ.get("PDF_API")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")
GENERATE_API_KEY = os.environ.get("GENERATE_API_KEY")

anthropic_client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))

# DeepSeek (OpenAI-compatible API). Best model right now: v4-pro.
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")


ROWS_PER_PAGE = 17

# Setup Jinja2
env = Environment(
    loader=FileSystemLoader('templates'),
    autoescape=select_autoescape()
)
anil_kiryana_template = env.get_template('AnilKiryanaReceipt.html')
rs_vegetables_template = env.get_template('RsVegetablesReceipt.html')

def load_system_prompt(path="prompts/system_prompt.txt"):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()
    
SYSTEM_PROMPT = load_system_prompt()

# def call_claude(user_message):
#     try:
#         message = anthropic_client.messages.create(
#             model="claude-sonnet-4-5-20250929",
#             max_tokens=2000,
#             temperature=0,
#             system=SYSTEM_PROMPT,
#             messages=[
#                 {
#                     "role": "user",
#                     "content": [{"type": "text", "text": user_message}]
#                 }
#             ]
#         )
#         content = message.content[0].text
#         return json.loads(content)
#     except Exception as e:
#         print("Claude error:", e)
#         return []

def _clean_json_text(content):
    # Strip markdown code blocks if present
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]  # Remove ```json
    if content.startswith("```"):
        content = content[3:]   # Remove ```
    if content.endswith("```"):
        content = content[:-3]  # Remove trailing ```
    return content.strip()


def call_claude(user_message):
    try:
        logging.debug(f"Sending to Claude: {user_message[:200]}...")

        message = anthropic_client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_message}]
                }
            ]
        )
        content = message.content[0].text
        logging.debug(f"Claude response: {content}")

        content = _clean_json_text(content)

        logging.debug(f"Cleaned content: {content[:200]}...")

        parsed = json.loads(content)
        logging.debug(f"✅ Parsed {len(parsed)} items")

        return parsed
    except json.JSONDecodeError as e:
        logging.error(f"JSON parsing error: {e}")
        logging.error(f"Content was: {content}")
        return []
    except Exception as e:
        logging.error(f"Claude error: {e}")
        return []

def call_deepseek(user_message):
    """Same contract as call_claude, but via DeepSeek's OpenAI-compatible API."""
    try:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            logging.error("DEEPSEEK_API_KEY not set")
            return []
        logging.debug(f"Sending to DeepSeek: {user_message[:200]}...")

        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0,
                "max_tokens": 2000,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        logging.debug(f"DeepSeek response: {content}")

        content = _clean_json_text(content)

        logging.debug(f"Cleaned content: {content[:200]}...")

        parsed = json.loads(content)
        logging.debug(f"DeepSeek parsed {len(parsed)} items")

        return parsed
    except json.JSONDecodeError as e:
        logging.error(f"DeepSeek JSON parsing error: {e}")
        return []
    except Exception as e:
        logging.error(f"DeepSeek error: {e}")
        return []


def highlight_devanagari(name):
    import re
    return re.sub(r'\(([^()]+)\)$', r'(<span class="devanagari">\1</span>)', name)

def chunk_items(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


app = Flask(__name__)

def render_receipt_html(items, receipt):
    # Build table rows with correct highlighting
    rows = ""
    for item in items:
        rows += f"""<tr>
          <td>{highlight_devanagari(item.get('item_name', ''))}</td>
          <td>{item.get('quantity', '')}</td>
          <td></td>
        </tr>"""

    with open(f"templates/{receipt}.html", encoding="utf-8") as f:
        template = f.read()

    now = datetime.now()
    date_str = now.strftime("%d-%b-%Y %H:%M:%S")
    return render_template_string(template, date=date_str, rows=rows)

def process_order_and_generate_pdf_for_anil_kiryana(user_message, parse_fn=call_claude):
    # 1. Parse order text into items (Claude or DeepSeek)
    items_list = parse_fn(user_message)

    if not items_list:
        logging.error("No items parsed from message!")
        return None

    # 2. Chunk items and render per page
    chunks = list(chunk_items(items_list, ROWS_PER_PAGE))
    total_pages = len(chunks)
    ist = pytz.timezone("Asia/Kolkata")
    date_str = datetime.now(ist).strftime("%d-%b-%Y %H:%M:%S")
    final_html = ""
    serial_no = 1

    for page_idx, chunk in enumerate(chunks, 1):
        # Prepare table rows as a list of dicts for Jinja2
        rows = []
        for item in chunk:
            rows.append({
                'no': serial_no,
                'item_name': highlight_devanagari(item.get('item_name', '')),
                'quantity': item.get('quantity', '')
            })
            serial_no += 1

        html_page = anil_kiryana_template.render(
            date=date_str,
            rows=rows,
            page=page_idx,
            total_pages=total_pages
        )

        final_html += html_page
        if page_idx < total_pages:
            final_html += '<div style="page-break-after: always"></div>'

    # 3. Convert HTML to PDF
    res_pdf = requests.post(PDF_API, json={"html": final_html})
    return res_pdf.content


# def process_order_and_generate_pdf_for_rs_vegetables(user_message):
#     # 1. Send to OpenAI and parse
#     items_list = call_claude(user_message)

#     # 2. Chunk items and render per page
#     chunks = list(chunk_items(items_list, ROWS_PER_PAGE))
#     total_pages = len(chunks)
#     ist = pytz.timezone("Asia/Kolkata")
#     date_str = datetime.now(ist).strftime("%d-%b-%Y %H:%M:%S")
#     final_html = ""
#     serial_no = 1

#     for page_idx, chunk in enumerate(chunks, 1):
#         # Prepare table rows as a list of dicts for Jinja2
#         rows = []
#         for item in chunk:
#             rows.append({
#                 'no': serial_no,
#                 'item_name': highlight_devanagari(item.get('item_name', '')),
#                 'quantity': item.get('quantity', '')
#             })
#             serial_no += 1

#         html_page = rs_vegetables_template.render(
#             date=date_str,
#             rows=rows,
#             page=page_idx,
#             total_pages=total_pages
#         )

#         final_html += html_page
#         if page_idx < total_pages:
#             final_html += '<div style="page-break-after: always"></div>'

#     # 3. Convert HTML to PDF
#     res_pdf = requests.post(PDF_API, json={"html": final_html})
#     return res_pdf.content

def process_order_and_generate_pdf_for_rs_vegetables(user_message, parse_fn=call_claude):
    try:
        # 1. Parse order text into items (Claude or DeepSeek)
        items_list = parse_fn(user_message)

        # CHECK: If no items, return error
        if not items_list:
            logging.error("No items parsed from message!")
            return None

        logging.debug(f"Processing {len(items_list)} items")

        # 2. Chunk items and render per page
        chunks = list(chunk_items(items_list, ROWS_PER_PAGE))
        total_pages = len(chunks)
        ist = pytz.timezone("Asia/Kolkata")
        date_str = datetime.now(ist).strftime("%d-%b-%Y %H:%M:%S")
        final_html = ""
        serial_no = 1

        for page_idx, chunk in enumerate(chunks, 1):
            rows = []
            for item in chunk:
                rows.append({
                    'no': serial_no,
                    'item_name': highlight_devanagari(item.get('item_name', '')),
                    'quantity': item.get('quantity', '')
                })
                serial_no += 1

            html_page = rs_vegetables_template.render(
                date=date_str,
                rows=rows,
                page=page_idx,
                total_pages=total_pages
            )

            final_html += html_page
            if page_idx < total_pages:
                final_html += '<div style="page-break-after: always"></div>'

        # 3. Log HTML before PDF conversion
        logging.debug(f"Generated HTML length: {len(final_html)}")
        logging.debug(f"HTML preview: {final_html[:500]}")

        # 4. Convert HTML to PDF
        res_pdf = requests.post(PDF_API, json={"html": final_html}, timeout=30)

        # CHECK: Verify PDF API response
        if res_pdf.status_code != 200:
            logging.error(f"PDF API error: {res_pdf.status_code} - {res_pdf.text}")
            return None

        logging.debug(f"PDF generated, size: {len(res_pdf.content)} bytes")

        if len(res_pdf.content) < 100:  # PDFs should be > 100 bytes
            logging.error(f"PDF too small, likely empty: {res_pdf.content}")
            return None

        return res_pdf.content

    except Exception as e:
        logging.error(f"Error in process_order: {e}", exc_info=True)
        return None


def _get_order_text():
    if request.is_json:
        return (request.json or {}).get("text", "").strip()
    return request.form.get("text", "").strip()


def _get_shop():
    shop = request.args.get("shop") or request.form.get("shop")
    if request.is_json:
        shop = shop or (request.json or {}).get("shop")
    return shop or "rs_vegetables"


def _check_generate_auth():
    if not GENERATE_API_KEY:
        return True
    provided = (
        request.headers.get("X-API-Key")
        or request.form.get("api_key")
        or (request.json or {}).get("api_key")
    )
    return provided == GENERATE_API_KEY


SHOP_PROCESSORS = {
    "rs_vegetables": process_order_and_generate_pdf_for_rs_vegetables,
    "anil_kiryana": process_order_and_generate_pdf_for_anil_kiryana,
}


def _generate_pdf_bytes(text, shop):
    """Shared pipeline: order text -> PDF bytes (None on failure)."""
    processor = SHOP_PROCESSORS.get(shop)
    if not processor or not text:
        return None
    logging.info(f"Generating PDF for shop={shop}, {len(text)} chars")
    return processor(text)


def _generate_pdf_response(text, shop):
    if shop not in SHOP_PROCESSORS:
        return jsonify({"error": f"Unknown shop: {shop}"}), 400

    if not text:
        return jsonify({"error": "Order text is required"}), 400

    pdf_bytes = _generate_pdf_bytes(text, shop)

    if not pdf_bytes:
        return jsonify({
            "error": "Failed to parse order. Check format.\n\nExample:\nTomato 2kg\nOnion 5kg"
        }), 400

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=receipt.pdf"},
    )


@app.route("/", methods=["GET"])
def generate_form():
    return env.get_template("GenerateReceipt.html").render(
        auth_required=bool(GENERATE_API_KEY)
    )


@app.route("/generate", methods=["POST"])
def generate_receipt():
    if not _check_generate_auth():
        return jsonify({"error": "Invalid or missing access key"}), 401

    return _generate_pdf_response(_get_order_text(), _get_shop())


def _send_telegram_document(bot_token, chat_id, filename, pdf_bytes, caption=""):
    files = {'document': (filename, pdf_bytes)}
    data = {'chat_id': chat_id}
    if caption:
        data['caption'] = caption
    return requests.post(
        f'https://api.telegram.org/bot{bot_token}/sendDocument',
        data=data,
        files=files,
        timeout=60,
    )


def _send_telegram_text(bot_token, chat_id, text):
    return requests.post(
        f'https://api.telegram.org/bot{bot_token}/sendMessage',
        data={'chat_id': chat_id, 'text': text},
        timeout=30,
    )


def _comparison_results(user_message, processor):
    """Run Claude + DeepSeek parses in parallel; return {name: pdf_bytes_or_None}."""
    results = {}

    def run(name, parse_fn):
        try:
            results[name] = processor(user_message, parse_fn=parse_fn)
        except Exception as e:
            logging.error(f"{name} pipeline failed: {e}")
            results[name] = None

    threads = [
        Thread(target=run, args=("claude", call_claude)),
        Thread(target=run, args=("deepseek", call_deepseek)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    update = request.json
    chat_id = update['message']['chat']['id']
    user_message = update['message'].get('text', '')

    def process_and_send():
        # Comparison mode: one PDF per provider so quality can be judged side by side.
        results = _comparison_results(
            user_message, process_order_and_generate_pdf_for_rs_vegetables
        )
        for name in ("claude", "deepseek"):
            pdf_bytes = results.get(name)
            if pdf_bytes:
                _send_telegram_document(
                    BOT_TOKEN, chat_id,
                    f"bill_{name}.pdf", pdf_bytes,
                    caption=f"Bill via {name}",
                )
            else:
                _send_telegram_text(
                    BOT_TOKEN, chat_id,
                    f"WARNING: {name} failed to generate a bill for this order.",
                )

    Thread(target=process_and_send).start()
    return jsonify({'ok': True})

@app.route('/anilkiryanawebhook', methods=['POST'])
def anil_kiryana_telegram_webhook():
    update = request.json
    chat_id = update['message']['chat']['id']
    user_message = update['message'].get('text', '')

    def process_and_send():
        # Comparison mode: one PDF per provider so quality can be judged side by side.
        results = _comparison_results(
            user_message, process_order_and_generate_pdf_for_anil_kiryana
        )
        for name in ("claude", "deepseek"):
            pdf_bytes = results.get(name)
            if pdf_bytes:
                _send_telegram_document(
                    ANIL_KIRYANA_BOT_TOKEN, chat_id,
                    f"bill_{name}.pdf", pdf_bytes,
                    caption=f"Bill via {name}",
                )
            else:
                _send_telegram_text(
                    ANIL_KIRYANA_BOT_TOKEN, chat_id,
                    f"WARNING: {name} failed to generate a bill for this order.",
                )

    Thread(target=process_and_send).start()
    return jsonify({'ok': True})

# @app.route('/rsvegetableswebhook', methods=['POST'])
# def rs_vegetables_telegram_webhook():
#     update = request.json
#     chat_id = update['message']['chat']['id']
#     user_message = update['message'].get('text', '')

#     def process_and_send():
#         pdf_bytes = process_order_and_generate_pdf_for_rs_vegetables(user_message)
#         files = {'document': ('receipt.pdf', pdf_bytes)}
#         requests.post(
#             f'https://api.telegram.org/bot{RS_VEGETABLES_BOT_TOKEN}/sendDocument',
#             data={'chat_id': chat_id},
#             files=files
#         )

#     Thread(target=process_and_send).start()
#     return jsonify({'ok': True})

@app.route('/rsvegetableswebhook', methods=['POST'])
def rs_vegetables_telegram_webhook():
    update = request.json
    chat_id = update['message']['chat']['id']
    user_message = update['message'].get('text', '')

    # Log the incoming message
    logging.info(f"📥 Received from chat {chat_id}")
    logging.info(f"📝 Message: {user_message}")

    def process_and_send():
        try:
            # Send status message
            requests.post(
                f'https://api.telegram.org/bot{RS_VEGETABLES_BOT_TOKEN}/sendMessage',
                json={'chat_id': chat_id, 'text': '⏳ Processing your order...'}
            )

            pdf_bytes = process_order_and_generate_pdf_for_rs_vegetables(user_message)

            if not pdf_bytes:
                logging.error("❌ PDF generation returned None")
                requests.post(
                    f'https://api.telegram.org/bot{RS_VEGETABLES_BOT_TOKEN}/sendMessage',
                    json={
                        'chat_id': chat_id,
                        'text': '❌ Failed to parse order. Please check format.\n\nExample:\nTomato 2kg\nOnion 5kg'
                    }
                )
                return

            logging.info(f"✅ PDF generated: {len(pdf_bytes)} bytes")

            files = {'document': ('receipt.pdf', pdf_bytes)}
            response = requests.post(
                f'https://api.telegram.org/bot{RS_VEGETABLES_BOT_TOKEN}/sendDocument',
                data={'chat_id': chat_id},
                files=files
            )

            if response.status_code == 200:
                logging.info("✅ PDF sent successfully")
            else:
                logging.error(f"❌ Telegram error: {response.text}")

        except Exception as e:
            logging.error(f"❌ Error in process_and_send: {e}", exc_info=True)
            requests.post(
                f'https://api.telegram.org/bot{RS_VEGETABLES_BOT_TOKEN}/sendMessage',
                json={'chat_id': chat_id, 'text': f'❌ Error: {str(e)}'}
            )

    Thread(target=process_and_send).start()
    return jsonify({'ok': True})

# ---------------------------------------------------------------------------
# WhatsApp Cloud API
#
# Forward a customer order to the WhatsApp Business number and the bill PDF
# comes back in the same chat — the Telegram copy-paste step goes away.
#
# Setup (one time, in Meta's developer dashboard):
#   1. Create a Meta app, add the WhatsApp product, add/verify a phone number
#      (this is the "bot" number — it can't be the number on your personal
#      WhatsApp; use a second SIM / virtual number).
#   2. Create a permanent System User access token with
#      whatsapp_business_messaging permission -> WHATSAPP_TOKEN.
#   3. Note the phone number ID shown for that number -> WHATSAPP_PHONE_NUMBER_ID.
#   4. Make up any random string -> WHATSAPP_VERIFY_TOKEN (same value in Meta's
#      webhook config and in the env vars).
#   5. Point Meta's webhook at https://<your-railway-url>/whatsapp and subscribe
#      to the "messages" field.
#
# Env vars (Railway -> Variables):
#   WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN,
#   WHATSAPP_SHOP (optional: rs_vegetables | anil_kiryana, default rs_vegetables)
# ---------------------------------------------------------------------------
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")  # permanent System User token
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_SHOP = os.environ.get("WHATSAPP_SHOP", "rs_vegetables")
WHATSAPP_GRAPH_VERSION = "v23.0"

_wa_graph_base = f"https://graph.facebook.com/{WHATSAPP_GRAPH_VERSION}"
_seen_wa_messages = set()  # dedupe Meta webhook retries


def _wa_post(path, **kwargs):
    url = f"{_wa_graph_base}/{WHATSAPP_PHONE_NUMBER_ID}{path}"
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {WHATSAPP_TOKEN}"
    resp = requests.post(url, headers=headers, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


def whatsapp_send_text(to, body):
    return _wa_post("/messages", json={
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    })


def whatsapp_upload_pdf(pdf_bytes, filename="receipt.pdf"):
    url = f"{_wa_graph_base}/{WHATSAPP_PHONE_NUMBER_ID}/media"
    files = {"file": (filename, pdf_bytes, "application/pdf")}
    data = {"messaging_product": "whatsapp"}
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        data=data,
        files=files,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def whatsapp_send_document(to, media_id, filename="receipt.pdf", caption="🧾 Your bill is ready"):
    return _wa_post("/messages", json={
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {"id": media_id, "filename": filename, "caption": caption},
    })


def _process_whatsapp_order(sender, order_text, msg_type):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logging.error("WhatsApp is not configured (WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID missing)")
        return
    try:
        if msg_type != "text" or not order_text:
            whatsapp_send_text(
                sender,
                "Please forward the order as *text*.\n\nExample:\nTomato 2kg\nOnion 5kg\n\n(I can't read photos or voice notes yet.)",
            )
            return

        whatsapp_send_text(sender, "⏳ Generating your bill...")
        pdf_bytes = _generate_pdf_bytes(order_text, WHATSAPP_SHOP)

        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            logging.error("WhatsApp: PDF generation failed")
            whatsapp_send_text(
                sender,
                "❌ Couldn't read that order. Please check the format.\n\nExample:\nTomato 2kg\nOnion 5kg",
            )
            return

        media_id = whatsapp_upload_pdf(pdf_bytes)
        whatsapp_send_document(sender, media_id, caption="🧾 Your bill is ready")
        logging.info(f"✅ WhatsApp bill sent to {sender}")
    except Exception:
        logging.exception("WhatsApp order processing failed")
        try:
            whatsapp_send_text(sender, "❌ Something went wrong while generating the bill. Please try again.")
        except Exception:
            pass


@app.route("/whatsapp", methods=["GET"])
def whatsapp_verify():
    """Meta webhook verification handshake (called once during setup)."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and WHATSAPP_VERIFY_TOKEN and token == WHATSAPP_VERIFY_TOKEN:
        return Response(challenge or "", status=200, mimetype="text/plain")
    logging.warning("WhatsApp webhook verification failed")
    return jsonify({"error": "verification failed"}), 403


@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    payload = request.get_json(silent=True) or {}

    def handle():
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for message in value.get("messages", []):
                        msg_id = message.get("id")
                        if msg_id in _seen_wa_messages:
                            continue  # Meta retried the webhook; don't bill twice
                        _seen_wa_messages.add(msg_id)
                        if len(_seen_wa_messages) > 2000:
                            _seen_wa_messages.clear()
                        sender = message.get("from")
                        msg_type = message.get("type", "")
                        order_text = ""
                        if msg_type == "text":
                            order_text = ((message.get("text") or {}).get("body") or "").strip()
                        if sender:
                            _process_whatsapp_order(sender, order_text, msg_type)
        except Exception:
            logging.exception("WhatsApp webhook handler failed")

    Thread(target=handle).start()
    return jsonify({"ok": True}), 200


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=os.environ.get("PORT"), debug=True)
