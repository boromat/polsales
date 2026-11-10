"""Local stand-in for an Anthropic-compatible model: no API key, no network, deterministic.

Used for the demo GIF and for trying the assistant end to end without paying for tokens:

    python tools/mock_llm.py --port 8765
    # backend/.env:  AI_BASE_URL=http://127.0.0.1:8765   (and no OPENROUTER/ANTHROPIC key)

It implements just enough of ``POST /v1/messages`` (streaming and non-streaming) for the
panel's chat loop: a question that contains a NIP (masked or not) triggers the
``get_company_profile`` tool, and the tool result is summarised in Polish. Every request is
logged to stdout, so you can see exactly what a real model would have received - with
masking on, that is tokens such as ``<FIRMA_1>`` and ``<NIP_1>`` instead of client data.
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN_RE = re.compile(r"<[A-Z][A-Z_]*_\d+>")
NIP_RE = re.compile(r"<NIP_\d+>|\b\d{3}-?\d{3}-?\d{2}-?\d{2}\b")
TOOL_OPEN, TOOL_CLOSE = "<wynik_narzedzia>\n", "\n</wynik_narzedzia>"


def _text_of(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _tool_payload(raw):
    """The panel sends every tool result between <wynik_narzedzia> tags (data, not instructions)."""
    if isinstance(raw, str) and raw.startswith(TOOL_OPEN) and raw.endswith(TOOL_CLOSE):
        return raw[len(TOOL_OPEN):-len(TOOL_CLOSE)]
    return raw


def _question(text: str) -> str:
    return text.split("</kontekst_widoku>")[-1].split("</kontekst_czasowy>")[-1].strip()


def _pln(value) -> str:
    try:
        return f"{float(value):,.0f}".replace(",", " ") + " zł"
    except (TypeError, ValueError):
        return "-"


def _num(value) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "-"


def _answer_from_tool(result: dict) -> str:
    if not result.get("found", True) or "company_name" not in result:
        return "Nie znalazłem firmy o tym NIP w danych panelu."
    return (
        f"**{result['company_name']}** (NIP {result.get('nip')}) to klient B2B z "
        f"{_num(result.get('orders_count'))} zamówieniami o łącznej wartości "
        f"**{_pln(result.get('ltv_net'))} netto**.\n\n"
        f"| Wskaźnik | Wartość |\n|---|---|\n"
        f"| Średnia wartość zamówienia | {_pln(result.get('avg_order_value_net'))} |\n"
        f"| Średni odstęp między zamówieniami | {_num(result.get('frequency_days'))} dni |\n"
        f"| Ostatnie zamówienie | {result.get('last_order') or '-'} |\n\n"
        "Klient kupuje regularnie - warto zaproponować mu ofertę na kolejny sezon."
    )


def decide(body: dict) -> list[dict]:
    """Content blocks of the reply for one request (text and/or tool_use)."""
    messages = body.get("messages") or []
    last = messages[-1] if messages else {"role": "user", "content": ""}
    content = last.get("content")
    if isinstance(content, list) and content and content[0].get("type") == "tool_result":
        raw = _tool_payload(content[0].get("content"))
        try:
            result = json.loads(raw) if isinstance(raw, str) else {}
        except ValueError:
            result = {}
        return [{"type": "text", "text": _answer_from_tool(result)}]

    question = _question(_text_of(last))
    tools = {t.get("name") for t in body.get("tools") or []}
    nip = NIP_RE.search(question)
    if nip and "get_company_profile" in tools:
        return [{"type": "tool_use", "id": "toolu_mock_1", "name": "get_company_profile",
                 "input": {"nip": nip.group(0), "company_id": None, "include_order_history": False}}]
    if body.get("output_config") or "JSON" in str(body.get("system", "")):
        return [{"type": "text", "text": "{}"}]
    return [{"type": "text", "text": "To lokalna atrapa modelu. Zapytaj o firmę po NIP, np. "
                                     "„Jak idzie współpraca z firmą o NIP 123-456-32-18?”"}]


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep stdout for the request dump below
        return

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        last = (body.get("messages") or [{}])[-1]
        print("<<< model input (last message):", json.dumps(last, ensure_ascii=False)[:600], flush=True)
        blocks = decide(body)
        stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
        usage = {"input_tokens": 120, "output_tokens": 60}

        if not body.get("stream"):
            payload = {"id": "msg_mock", "type": "message", "role": "assistant", "model": "mock",
                       "content": blocks, "stop_reason": stop, "stop_sequence": None, "usage": usage}
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        w = self.wfile.write
        w(_sse("message_start", {"type": "message_start", "message": {
            "id": "msg_mock", "type": "message", "role": "assistant", "model": "mock", "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 120, "output_tokens": 1}}}))
        for i, block in enumerate(blocks):
            if block["type"] == "text":
                w(_sse("content_block_start", {"type": "content_block_start", "index": i,
                                               "content_block": {"type": "text", "text": ""}}))
                text = block["text"]
                for start in range(0, len(text), 9):  # small chunks: tokens get split across them
                    w(_sse("content_block_delta", {"type": "content_block_delta", "index": i,
                                                   "delta": {"type": "text_delta", "text": text[start:start + 9]}}))
            else:
                w(_sse("content_block_start", {"type": "content_block_start", "index": i, "content_block": {
                    "type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}}))
                w(_sse("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {
                    "type": "input_json_delta", "partial_json": json.dumps(block["input"], ensure_ascii=False)}}))
            w(_sse("content_block_stop", {"type": "content_block_stop", "index": i}))
        w(_sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                 "usage": {"output_tokens": 60}}))
        w(_sse("message_stop", {"type": "message_stop"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(f"Mock model on http://{args.host}:{args.port} - set AI_BASE_URL to this address.", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
