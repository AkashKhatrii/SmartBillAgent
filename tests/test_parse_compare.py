"""Claude vs DeepSeek order-parsing comparison for SmartBillAgent.

Mocked unit tests run with no API keys:
    pytest tests/test_parse_compare.py -v

Live side-by-side comparison (needs real keys, prints a diff report):
    LIVE_COMPARE=1 CLAUDE_API_KEY=... DEEPSEEK_API_KEY=... \
        pytest tests/test_parse_compare.py -v -s -k live
"""
import json
import os
import sys
import types
from unittest import mock

import pytest

# Repo root on path; main.py loads templates relative to cwd.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("CLAUDE_API_KEY", "test")
os.environ.setdefault("DEEPSEEK_API_KEY", "test")

import main  # noqa: E402

SAMPLE_ORDERS = [
    "Tomato 2kg onion 5kg",
    "2 kilo aloo, 1 kilo pyaz",
    "tamatar 3kg\nadrak 500g\nlasun 250g",
    "Paneer 1kg, dahi 2 packet",
    "1 dozen eggs, amul butter 500g",
    "bhindi 1kg\nkarela 500g\ndhaniya 2 gaddi",
]


def _deepseek_http_response(payload_text, status=200):
    resp = types.SimpleNamespace()
    resp.status_code = status
    resp.text = payload_text if status != 200 else ""
    resp.json = lambda: {"choices": [{"message": {"content": payload_text}}]}

    def _raise():
        if status != 200:
            raise RuntimeError(f"HTTP {status}")

    resp.raise_for_status = _raise
    return resp


# ---------------------------------------------------------------- mocked tests

def test_clean_json_text_strips_markdown():
    assert main._clean_json_text('```json\n[{"a": 1}]\n```') == '[{"a": 1}]'
    assert main._clean_json_text('```\n[{"a": 1}]\n```') == '[{"a": 1}]'
    assert main._clean_json_text('  [{"a": 1}]  ') == '[{"a": 1}]'


def test_call_deepseek_parses_items():
    canned = '```json\n[{"item_name": "Tomato (\\u091f\\u092e\\u093e\\u091f\\u0930)", "quantity": "2kg"}]\n```'
    with mock.patch.object(main.requests, "post") as mpost, \
            mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-key"}):
        mpost.return_value = _deepseek_http_response(canned)
        items = main.call_deepseek("Tomato 2kg")

    assert items == [{"item_name": "Tomato (टमाटर)", "quantity": "2kg"}]

    # Verify the request shape: right endpoint, best model, deterministic, same prompt
    (url,), kwargs = mpost.call_args
    assert url == "https://api.deepseek.com/chat/completions"  # canonical: no /v1
    assert kwargs["headers"]["Authorization"] == "Bearer ds-key"
    body = kwargs["json"]
    assert body["model"] == "deepseek-v4-pro"
    assert body["temperature"] == 0
    assert body["messages"][0] == {"role": "system", "content": main.SYSTEM_PROMPT}
    assert body["messages"][1] == {"role": "user", "content": "Tomato 2kg"}


def test_call_deepseek_no_key_returns_empty_without_calling():
    with mock.patch.object(main.requests, "post") as mpost, \
            mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DEEPSEEK_API_KEY", None)
        assert main.call_deepseek("Tomato 2kg") == []
    mpost.assert_not_called()


def test_call_deepseek_http_error_returns_empty():
    with mock.patch.object(main.requests, "post") as mpost, \
            mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-key"}):
        mpost.return_value = _deepseek_http_response("boom", status=500)
        assert main.call_deepseek("Tomato 2kg") == []


def test_call_deepseek_bad_json_returns_empty():
    with mock.patch.object(main.requests, "post") as mpost, \
            mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-key"}):
        mpost.return_value = _deepseek_http_response("not json at all")
        assert main.call_deepseek("Tomato 2kg") == []


def _stub_pdf_pipeline(monkeypatch, claude_items, deepseek_items):
    """Stub both parsers + the PDF API; return captured telegram posts."""
    monkeypatch.setattr(
        main, "call_claude", lambda text: claude_items)
    monkeypatch.setattr(
        main, "call_deepseek", lambda text: deepseek_items)

    fake_pdf = b"%PDF-1.4 " + b"x" * 200  # must pass the processor's >100-byte sanity check

    def fake_post(url, **kwargs):
        resp = types.SimpleNamespace()
        resp.status_code = 200
        resp.text = ""
        resp.content = fake_pdf
        return resp

    monkeypatch.setattr(main.requests, "post", fake_post)
    return fake_pdf


def test_comparison_generates_two_pdfs(monkeypatch):
    items = [{"item_name": "Tomato (टमाटर)", "quantity": "2kg"}]
    fake_pdf = _stub_pdf_pipeline(monkeypatch, items, items)

    results = main._comparison_results(
        "Tomato 2kg", main.process_order_and_generate_pdf_for_rs_vegetables)

    assert set(results) == {"claude", "deepseek"}
    assert results["claude"] == fake_pdf
    assert results["deepseek"] == fake_pdf


def test_comparison_partial_failure_keeps_other_pdf(monkeypatch):
    items = [{"item_name": "Tomato (टमाटर)", "quantity": "2kg"}]
    fake_pdf = _stub_pdf_pipeline(monkeypatch, [], items)  # claude parses nothing

    results = main._comparison_results(
        "Tomato 2kg", main.process_order_and_generate_pdf_for_rs_vegetables)

    assert results["claude"] is None
    assert results["deepseek"] == fake_pdf


def test_processor_default_still_uses_claude():
    """Existing callers (web form, WhatsApp) keep Claude behavior.

    parse_fn's default is bound at def time to the real call_claude, so we
    assert the wiring instead of stubbing it.
    """
    import inspect
    sig = inspect.signature(main.process_order_and_generate_pdf_for_rs_vegetables)
    assert sig.parameters["parse_fn"].default is main.call_claude


def test_processor_explicit_parse_fn(monkeypatch):
    """Explicit parse_fn (the comparison path) is honored."""
    called = {}

    def fake_deepseek(text):
        called["yes"] = True
        return [{"item_name": "Onion", "quantity": "5kg"}]

    def fake_post(url, **kwargs):
        resp = types.SimpleNamespace()
        resp.status_code = 200
        resp.text = ""
        resp.content = b"%PDF-1.4 " + b"x" * 200
        return resp

    monkeypatch.setattr(main.requests, "post", fake_post)

    pdf = main.process_order_and_generate_pdf_for_rs_vegetables(
        "Onion 5kg", parse_fn=fake_deepseek)
    assert called.get("yes") is True
    assert pdf == b"%PDF-1.4 " + b"x" * 200


# ---------------------------------------------------------------- live test

def _live_keys_present():
    return (
        os.getenv("LIVE_COMPARE") == "1"
        and os.getenv("CLAUDE_API_KEY") not in (None, "test")
        and os.getenv("DEEPSEEK_API_KEY") not in (None, "test")
    )


@pytest.mark.skipif(not _live_keys_present(), reason="needs LIVE_COMPARE=1 + real keys")
def test_compare_claude_vs_deepseek_live():
    """Side-by-side: prints a diff report per order. Fails only on total parse failure."""
    print("\n\n=== Claude vs DeepSeek live comparison ===")
    failures = []
    for order in SAMPLE_ORDERS:
        claude_items = main.call_claude(order)
        deepseek_items = main.call_deepseek(order)
        print(f"\nOrder: {order!r}")
        print(f"  claude   ({len(claude_items)} items): "
              f"{[(i.get('item_name'), i.get('quantity')) for i in claude_items]}")
        print(f"  deepseek ({len(deepseek_items)} items): "
              f"{[(i.get('item_name'), i.get('quantity')) for i in deepseek_items]}")

        if not claude_items and not deepseek_items:
            failures.append(order)
            print("  !! BOTH failed to parse")
            continue
        # Flag differences without failing: legit model differences are the point.
        c_set = {(i.get("item_name"), i.get("quantity")) for i in claude_items}
        d_set = {(i.get("item_name"), i.get("quantity")) for i in deepseek_items}
        if c_set != d_set:
            print(f"  ~~ differ: only-claude={c_set - d_set} only-deepseek={d_set - c_set}")
        else:
            print("  == identical")

    assert not failures, f"Both providers failed on: {failures}"
    print("\n=== done ===")


def test_anil_processor_empty_parse_returns_none():
    assert main.process_order_and_generate_pdf_for_anil_kiryana(
        "gibberish", parse_fn=lambda t: []) is None


def test_anil_processor_default_still_uses_claude():
    import inspect
    sig = inspect.signature(main.process_order_and_generate_pdf_for_anil_kiryana)
    assert sig.parameters["parse_fn"].default is main.call_claude


def test_rsvegetables_webhook_sends_two_pdfs(monkeypatch):
    sent_docs, sent_texts = [], []
    monkeypatch.setattr(main, "_comparison_results",
                        lambda msg, proc: {"claude": b"C", "deepseek": b"D"})
    monkeypatch.setattr(main, "_send_telegram_document",
                        lambda tok, chat, fn, data, caption=None: sent_docs.append((fn, data)))
    monkeypatch.setattr(main, "_send_telegram_text",
                        lambda tok, chat, text: sent_texts.append(text))

    class FakeThread:
        def __init__(self, target): self._target = target
        def start(self): self._target()
    monkeypatch.setattr(main, "Thread", FakeThread)

    resp = main.app.test_client().post(
        "/rsvegetableswebhook",
        json={"message": {"chat": {"id": 1}, "text": "Tomato 2kg"}})
    assert resp.status_code == 200
    assert [fn for fn, _ in sent_docs] == ["bill_claude.pdf", "bill_deepseek.pdf"]
    assert sent_texts and "Processing" in sent_texts[0]


def test_deepseek_endpoint_is_canonical():
    # DeepSeek's documented endpoint has no /v1; the /v1 form returned an
    # empty non-JSON body in production (2026-09-27).
    assert main.DEEPSEEK_API_URL == "https://api.deepseek.com/chat/completions"


def test_deepseek_non_json_body_returns_empty(monkeypatch):
    class BadResp:
        status_code = 200
        text = ""
        def raise_for_status(self): pass
        def json(self): raise json.JSONDecodeError("Expecting value", "", 0)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: BadResp())
    assert main.call_deepseek("Tomato 2kg") == []


def _deepseek_resp_with(message):
    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"finish_reason": "stop", "message": message}]}
    return Resp()


def test_deepseek_falls_back_to_reasoning_content(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: _deepseek_resp_with(
        {"content": "", "reasoning_content": '[{"item_name": "Tomato", "quantity": "2kg"}]'}))
    assert main.call_deepseek("x") == [{"item_name": "Tomato", "quantity": "2kg"}]


def test_deepseek_empty_content_and_reasoning_returns_empty(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: _deepseek_resp_with(
        {"content": "", "reasoning_content": ""}))
    assert main.call_deepseek("x") == []
