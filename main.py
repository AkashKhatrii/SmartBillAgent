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

        # FIX: Strip markdown code blocks if present
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]  # Remove ```json
        if content.startswith("```"):
            content = content[3:]   # Remove ```
        if content.endswith("```"):
            content = content[:-3]  # Remove trailing ```
        content = content.strip()

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

def process_order_and_generate_pdf_for_anil_kiryana(user_message):
    # 1. Send to OpenAI and parse
    items_list = call_claude(user_message)
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

def process_order_and_generate_pdf_for_rs_vegetables(user_message):
    try:
        # 1. Send to Claude and parse
        items_list = call_claude(user_message)

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


def _generate_pdf_response(text, shop):
    processors = {
        "rs_vegetables": process_order_and_generate_pdf_for_rs_vegetables,
        "anil_kiryana": process_order_and_generate_pdf_for_anil_kiryana,
    }
    processor = processors.get(shop)
    if not processor:
        return jsonify({"error": f"Unknown shop: {shop}"}), 400

    if not text:
        return jsonify({"error": "Order text is required"}), 400

    logging.info(f"Generating PDF for shop={shop}, {len(text)} chars")
    pdf_bytes = processor(text)

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


@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    update = request.json
    chat_id = update['message']['chat']['id']
    user_message = update['message'].get('text', '')

    def process_and_send():
        pdf_bytes = process_order_and_generate_pdf_for_rs_vegetables(user_message)
        files = {'document': ('receipt.pdf', pdf_bytes)}
        requests.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendDocument',
            data={'chat_id': chat_id},
            files=files
        )

    Thread(target=process_and_send).start()
    return jsonify({'ok': True})

@app.route('/anilkiryanawebhook', methods=['POST'])
def anil_kiryana_telegram_webhook():
    update = request.json
    chat_id = update['message']['chat']['id']
    user_message = update['message'].get('text', '')

    def process_and_send():
        pdf_bytes = process_order_and_generate_pdf_for_anil_kiryana(user_message)
        files = {'document': ('receipt.pdf', pdf_bytes)}
        requests.post(
            f'https://api.telegram.org/bot{ANIL_KIRYANA_BOT_TOKEN}/sendDocument',
            data={'chat_id': chat_id},
            files=files
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

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=os.environ.get("PORT"), debug=True)
