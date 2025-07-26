from flask import Flask, request, jsonify, render_template_string
from jinja2 import Environment, FileSystemLoader, select_autoescape
from threading import Thread
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
import os
import anthropic
import pytz


load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN") # Replace with your token
ANIL_KIRYANA_BOT_TOKEN = os.environ.get("ANIL_KIRYANA_BOT_TOKEN")
RS_VEGETABLES_BOT_TOKEN = os.environ.get("RS_VEGETABLES_BOT_TOKEN")
PDF_API = os.environ.get("PDF_API")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")

anthropic_client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))


ROWS_PER_PAGE = 18

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

def call_claude(user_message):
    try:
        message = anthropic_client.messages.create(
            model="claude-opus-4-20250514",
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
        return json.loads(content)
    except Exception as e:
        print("Claude error:", e)
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


def process_order_and_generate_pdf_for_rs_vegetables(user_message):
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

        html_page = rs_vegetables_template.render(
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

@app.route('/rsvegetableswebhook', methods=['POST'])
def rs_vegetables_telegram_webhook():
    update = request.json
    chat_id = update['message']['chat']['id']
    user_message = update['message'].get('text', '')

    def process_and_send():
        pdf_bytes = process_order_and_generate_pdf_for_rs_vegetables(user_message)
        files = {'document': ('receipt.pdf', pdf_bytes)}
        requests.post(
            f'https://api.telegram.org/bot{RS_VEGETABLES_BOT_TOKEN}/sendDocument',
            data={'chat_id': chat_id},
            files=files
        )

    Thread(target=process_and_send).start()
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=os.environ.get("PORT"), debug=True)