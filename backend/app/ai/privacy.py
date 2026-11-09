"""Optional PII masking for every LLM call, powered by polanon (``pip install polanon``).

Before any text leaves the server, personal data (names, e-mails, phone numbers, NIP/PESEL,
IBANs, addresses, company names...) is replaced with tokens such as ``<OSOBA_1>`` or
``<FIRMA_1>``. The model only ever sees the tokens. The mapping token -> real value lives in
memory for the duration of ONE request (one chat turn, one e-mail, one weekly summary) and is
used to:

* restore real values in the arguments of tool calls before a tool touches the database
  (the model may call ``company_profile(nip="<NIP_1>")``),
* restore real values in the answer shown to the user, also while it is being streamed,
* restore real values in structured output (fields of an order parsed from an e-mail).

Rules (the same as in PolCRM and PolCV):

* with masking switched off the AI features work exactly as before,
* when masking is switched ON but polanon is missing or fails, NOTHING is sent to the model
  (:class:`MaskingUnavailable` is raised) - better an error than personal data in clear text,
* client company names and NIPs known from the database are masked always, through polanon's
  ``DenylistGuard``, also when a name looks like a well-known brand.

This module imports nothing from FastAPI or the database, so it can be unit tested in isolation.
The database-aware part (settings, known terms) lives in :mod:`app.services.privacy_settings`.
"""

from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

#: Shape of a polanon token: ``<OSOBA_1>``, ``<EMAIL_12>``, ``<KOD_POCZTOWY_3>``...
TOKEN_RE = re.compile(r"<[A-Z][A-Z_]*_\d+>")
#: A trailing fragment of a streamed chunk that may still grow into a token ("<", "<OSO", "<OSOBA_1").
_PARTIAL_RE = re.compile(r"<[A-Z_]*\d*$")
_MAX_PARTIAL = 32

#: Appended to every system prompt when masking is on, so the model treats tokens as real values.
TOKENS_NOTE = (
    "\n\nDANE OSOBOWE SA ZAMASKOWANE: imiona i nazwiska, e-maile, telefony, NIP, adresy, numery kont "
    "i nazwy firm klientow sa zastapione tokenami w nawiasach ostrych, np. <OSOBA_1>, <EMAIL_1>, "
    "<FIRMA_1>, <NIP_1>. Traktuj token jak prawdziwa wartosc. Gdy przekazujesz ja do narzedzia albo "
    "cytujesz w odpowiedzi lub w polu JSON, przepisz token dokladnie tak, jak jest zapisany - bez "
    "odmiany, bez zmiany liter i bez spacji w srodku. Nie tworz nowych tokenow."
)

AnonymizeFn = Callable[[str, dict[str, str]], tuple[str, dict[str, str]]]


class MaskingUnavailable(RuntimeError):
    """Masking is switched on but cannot run. The caller must not contact the model."""


def polanon_status() -> dict[str, Any]:
    """What the settings page shows: is polanon installed, which version, is spaCy NER available."""
    info: dict[str, Any] = {"installed": False, "version": None, "ner": False}
    if importlib.util.find_spec("polanon") is None:
        return info
    try:
        import polanon  # noqa: PLC0415 - optional at import time on purpose

        info["installed"] = True
        info["version"] = getattr(polanon, "__version__", None)
    except Exception:  # noqa: BLE001 - a broken install is reported as missing, not a crash
        return info
    info["ner"] = (
        importlib.util.find_spec("spacy") is not None
        and importlib.util.find_spec("pl_core_news_md") is not None
    )
    return info


# One base anonymizer per ``with_ner`` flag for the whole process: building the guards (and loading
# the spaCy model) is the expensive part, and polanon's Anonymizer keeps no per-call state.
_ANONYMIZERS: dict[bool, Any] = {}


def _get_anonymizer(with_ner: bool):
    """The shared polanon Anonymizer (rules, optionally spaCy NER). Raises MaskingUnavailable."""
    if with_ner not in _ANONYMIZERS:
        try:
            from polanon import WELL_KNOWN_NAMES, Allowlist, Anonymizer, default_guards  # noqa: PLC0415
        except ImportError as exc:
            raise MaskingUnavailable("pakiet polanon nie jest zainstalowany (pip install polanon)") from exc
        try:
            guards = default_guards(with_ner=with_ner)
            _ANONYMIZERS[with_ner] = Anonymizer(guards, allowlist=Allowlist(WELL_KNOWN_NAMES))
        except Exception as exc:  # noqa: BLE001 - spaCy/model missing (ModuleNotFoundError, OSError) or broken install
            raise MaskingUnavailable(f"polanon nie może wystartować: {exc}") from exc
    return _ANONYMIZERS[with_ner]


def ensure_available(with_ner: bool = False) -> None:
    """Raise :class:`MaskingUnavailable` when polanon (or spaCy, for NER) cannot run."""
    _get_anonymizer(with_ner)


class StreamRestorer:
    """Restores tokens in a streamed answer without breaking a token split across chunks.

    A provider streams arbitrary fragments, so ``<FIRMA_1>`` can arrive as ``<FIR`` + ``MA_1>``.
    Any trailing fragment that could still become a token is held back until the next chunk.
    """

    def __init__(self, restore: Callable[[str], str]) -> None:
        """``restore`` replaces complete tokens in a piece of text (usually :meth:`Masker.restore`)."""
        self._restore = restore
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        """Consume one chunk and return the text that is safe to show now."""
        self._buffer += chunk
        partial = _PARTIAL_RE.search(self._buffer)
        if partial is None or partial.end() - partial.start() > _MAX_PARTIAL:
            ready, self._buffer = self._buffer, ""
        else:
            ready, self._buffer = self._buffer[: partial.start()], self._buffer[partial.start():]
        return self._restore(ready)

    def flush(self) -> str:
        """Return whatever is still buffered at the end of the stream."""
        ready, self._buffer = self._buffer, ""
        return self._restore(ready)


@dataclass
class Masker:
    """Masks one request. Tokens stay consistent across every text masked with the same instance.

    ``anonymize`` is injectable for tests: ``(text, mapping) -> (masked_text, full_mapping)``.
    """

    anonymize: AnonymizeFn
    mapping: dict[str, str] = field(default_factory=dict)

    # -- outgoing: real values -> tokens -----------------------------------------------------

    def mask(self, text: str) -> str:
        """Mask one text. Any failure of the anonymizer becomes :class:`MaskingUnavailable`.

        Token-shaped text already in the input (a stale token stored in history, something the
        user typed) is defused to ``[FIRMA_2]`` first: numbering starts again in every request,
        so an old ``<FIRMA_2>`` must never be restored to whoever got that token this time.
        """
        if not text or not isinstance(text, str):
            return text
        text = TOKEN_RE.sub(lambda m: "[" + m.group(0)[1:-1] + "]", text)
        try:
            masked, self.mapping = self.anonymize(text, self.mapping)
        except MaskingUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - any polanon failure must stop the request
            raise MaskingUnavailable(f"blad polanon: {exc}") from exc
        return masked

    def mask_data(self, value: Any) -> Any:
        """Mask every string inside a JSON-like value (tool results). Keys and numbers stay as they are."""
        if isinstance(value, str):
            return self.mask(value)
        if isinstance(value, dict):
            return {k: self.mask_data(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.mask_data(v) for v in value]
        return value

    # -- incoming: tokens -> real values -----------------------------------------------------

    def restore(self, text: str) -> str:
        """Replace known tokens with real values. Unknown tokens are left as they are."""
        if not text or not isinstance(text, str) or not self.mapping:
            return text
        return TOKEN_RE.sub(lambda m: self.mapping.get(m.group(0), m.group(0)), text)

    def restore_data(self, value: Any) -> Any:
        """Restore tokens inside a JSON-like value (tool call arguments, structured output)."""
        if isinstance(value, str):
            return self.restore(value)
        if isinstance(value, dict):
            return {k: self.restore_data(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.restore_data(v) for v in value]
        return value

    def stream_restorer(self) -> StreamRestorer:
        """A restorer for one streamed model response (create a new one per response)."""
        return StreamRestorer(self.restore)

    def unknown_tokens(self, text: str) -> list[str]:
        """Tokens in a model answer that are not in the mapping (the model invented or mangled them)."""
        return [t for t in TOKEN_RE.findall(text or "") if t not in self.mapping]

    def labels(self) -> dict[str, int]:
        """How many values of each kind were masked, e.g. ``{"FIRMA": 2, "NIP": 1}`` (no values)."""
        return dict(Counter(t[1:].rsplit("_", 1)[0] for t in self.mapping))

    # -- Anthropic Messages API content blocks ------------------------------------------------

    def mask_blocks(self, content: Any) -> Any:
        """Mask the content of one chat message (a string or a list of Anthropic content blocks).

        Only the parts that carry user data are touched: ``text``, the ``input`` of ``tool_use``
        and the ``content`` of ``tool_result``. Block types, ids and tool names stay intact.
        Any other block type (e.g. ``thinking``, stored while masking was off) is dropped:
        it cannot be masked without breaking its signature, and it is not needed for history.
        """
        if isinstance(content, str):
            return self.mask(content)
        if not isinstance(content, list):
            return content
        out = []
        for block in content:
            if not isinstance(block, dict):
                out.append(block)
                continue
            kind = block.get("type")
            if kind == "text":
                block = {**block, "text": self.mask(block.get("text", ""))}
            elif kind == "tool_use":
                block = {**block, "input": self.mask_data(block.get("input") or {})}
            elif kind == "tool_result":
                block = {**block, "content": self._mask_tool_content(block.get("content"))}
            else:
                continue  # fail closed: an unknown block type never goes out unmasked
            out.append(block)
        return out

    def restore_blocks(self, content: Any) -> Any:
        """Inverse of :meth:`mask_blocks` for blocks produced by the model (text and tool_use)."""
        if isinstance(content, str):
            return self.restore(content)
        if not isinstance(content, list):
            return content
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                block = {**block, "text": self.restore(block.get("text", ""))}
            elif isinstance(block, dict) and block.get("type") == "tool_use":
                block = {**block, "input": self.restore_data(block.get("input") or {})}
            out.append(block)
        return out

    def _mask_tool_content(self, content: Any) -> Any:
        """Tool results are stored as JSON strings - mask the values, keep the JSON valid."""
        if isinstance(content, str):
            try:
                data = json.loads(content)
            except ValueError:
                return self.mask(content)
            return json.dumps(self.mask_data(data), ensure_ascii=False)
        return self.mask_blocks(content) if isinstance(content, list) else content


def _client_words(terms: Iterable[str]) -> set[str]:
    return {w.lower() for t in terms for w in t.split()}


def polanon_masker(with_ner: bool = False, terms: Iterable[str] = ()) -> Masker:
    """A :class:`Masker` backed by polanon. Raises :class:`MaskingUnavailable` when it cannot run.

    ``terms`` are values the panel already knows are sensitive: client company names and NIPs
    from the database. polanon's rules find names with a legal form ("sp. z o.o.") or a first
    name, but not "Klub Sportowy Orlik" alone in a tool result field; known terms are masked
    always, through polanon's ``DenylistGuard`` (token ``<FIRMA_n>``).
    """
    anonymizer = _get_anonymizer(with_ner)
    cleaned = [t for t in dict.fromkeys((t or "").strip() for t in terms) if len(t) >= 3]
    if cleaned:
        try:
            anonymizer = _with_known_terms(anonymizer, cleaned)
        except Exception as exc:  # noqa: BLE001 - fail closed, never fall back to the rules alone
            raise MaskingUnavailable(f"polanon nie przyjął listy znanych wartości: {exc}") from exc

    def _anonymize(text: str, mapping: dict[str, str]) -> tuple[str, dict[str, str]]:
        result = anonymizer.anonymize_sync(text, mapping)
        return result.anonymized, dict(result.mapping)

    return Masker(anonymize=_anonymize)


def _with_known_terms(anonymizer, cleaned: list[str]):
    """The shared anonymizer plus a DenylistGuard for this request's known client values."""
    from polanon import WELL_KNOWN_NAMES, Allowlist, Anonymizer, DenylistGuard  # noqa: PLC0415

    # polanon leaves allowlisted public names (big brands, cities) unmasked, also when a
    # DenylistGuard found them. A client of the shop is never "just public", so its words are
    # taken out of the allowlist for this request.
    words = _client_words(cleaned)
    allowlist = Allowlist([n for n in WELL_KNOWN_NAMES if not ({w.lower() for w in n.split()} & words)])
    # The same guard instances (the spaCy model stays loaded) plus this request's known terms.
    return Anonymizer([*anonymizer.guards, DenylistGuard(cleaned)], allowlist=allowlist)
