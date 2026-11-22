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

The masking itself is polanon's :class:`~polanon.MaskedTurn`, one per request: it masks the
history, the question and every tool result with one mapping, re-masks an earlier message when a
value is first recognised in a later one, restores a streamed answer, and masks the values the
panel knows from its database (``known``) wherever they appear, also when a name looks like a
well-known brand, without its legal form, and a NIP however its digits are grouped. PolSales
stores the history with real values, so the turn is started with ``plain_input=True``: no token
in the input belongs to this request, and token-shaped text is defused to ``[FIRMA_2]`` (see
:meth:`Masker.mask`). :class:`Masker` adds what is PolSales' own:

* :class:`MaskingUnavailable`, which callers catch without importing polanon,
* tool arguments and parsed fields restored as the mapping holds them, a case the model added
  dropped (``restore_data(as_held=True)``): they go to code and the database, which hold the
  original spelling, while an answer a person reads comes back declined ("Janowi Testowskiemu"),
* :meth:`Masker.restore_blocks` for the content blocks the model returns, and
  :meth:`Masker.labels` for the chat badge.

Rules (the same as in PolCRM and PolCV):

* with masking switched off the AI features work exactly as before,
* when masking is switched ON but polanon is missing or fails, NOTHING is sent to the model
  (:class:`MaskingUnavailable` is raised) - better an error than personal data in clear text,
* client company names and NIPs known from the database are masked always.

This module imports nothing from FastAPI or the database, and it imports polanon only when a
masker is built, so it can be unit tested in isolation. The database-aware part (settings, known
terms) lives in :mod:`app.services.privacy_settings`.
"""

from __future__ import annotations

import importlib.util
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polanon import Anonymizer, StreamRestorer

#: Shape of a polanon token: ``<OSOBA_1>``, ``<EMAIL_12>``, ``<KOD_POCZTOWY_3>``..., and a person's
#: token with the grammatical case polanon 0.4 adds after a colon, ``<OSOBA_1:celownik>`` (as its
#: ``CASED_TOKEN_PATTERN``). No capturing group, so ``findall`` returns whole tokens.
TOKEN_RE = re.compile(r"<[A-Z][A-Z_]*_\d+(?::[^\W\d_]+)?>")

#: Appended to every system prompt when masking is on, so the model treats tokens as real values.
TOKENS_NOTE = (
    "\n\nDANE OSOBOWE SA ZAMASKOWANE: imiona i nazwiska, e-maile, telefony, NIP, adresy, numery kont "
    "i nazwy firm klientow sa zastapione tokenami w nawiasach ostrych, np. <OSOBA_1>, <EMAIL_1>, "
    "<FIRMA_1>, <NIP_1>. Traktuj token jak prawdziwa wartosc. Gdy przekazujesz ja do narzedzia albo "
    "cytujesz w odpowiedzi lub w polu JSON, przepisz token dokladnie tak, jak jest zapisany - bez "
    "odmiany, bez zmiany liter i bez spacji w srodku. Nie tworz nowych tokenow."
)


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
        importlib.util.find_spec("spacy") is not None and importlib.util.find_spec("pl_core_news_md") is not None
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


@contextmanager
def _fail_closed(what: str) -> Iterator[None]:
    """Turn any failure of polanon into :class:`MaskingUnavailable`, so the request stops."""
    try:
        yield
    except MaskingUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - any polanon failure must stop the request
        raise MaskingUnavailable(f"{what}: {exc}") from exc


class Masker:
    """Masks one request on a polanon :class:`~polanon.MaskedTurn`.

    Tokens stay consistent across every text masked with the same instance. ``anonymizer`` is
    polanon's Anonymizer, or for tests anything with ``judge = None`` and
    ``anonymize_sync(text, mapping)``; ``known`` are values masked wherever they appear.
    """

    def __init__(self, anonymizer: Anonymizer, known: Iterable[str] = ()) -> None:
        """Start the request's turn. Raises :class:`MaskingUnavailable` when polanon cannot."""
        try:
            from polanon import MaskedTurn  # noqa: PLC0415 - optional at import time on purpose
        except ImportError as exc:
            raise MaskingUnavailable("pakiet polanon nie jest zainstalowany (pip install polanon)") from exc
        with _fail_closed("polanon nie przyjął listy znanych wartości"):
            # "drop": a block no mask reaches (a thinking block stored while masking was off) is
            # left out of the history; its signature forbids masking it, and the model needs none.
            # plain_input: the history is stored with real values, the model's answers restored.
            self._turn = MaskedTurn(anonymizer, known=list(known), unknown_blocks="drop", plain_input=True)

    @property
    def mapping(self) -> dict[str, str]:
        """A copy of the request's token -> real value mapping."""
        return self._turn.mapping

    # -- outgoing: real values -> tokens -----------------------------------------------------

    def mask(self, text: str) -> str:
        """Mask one text. Any failure of polanon becomes :class:`MaskingUnavailable`.

        Token-shaped text already in the input (a token the model invented, stored as it wrote
        it, something the user typed) is defused to ``[FIRMA_2]`` first, by polanon's
        ``plain_input``; so is every string :meth:`mask_data` and :meth:`mask_messages` mask.
        Numbering starts again in every request and the history is stored with real values, so
        an old ``<FIRMA_2>`` is never a token of this request: read as one, it would stand for
        the value that got ``<FIRMA_2>`` earlier in the request, and the answer would restore it
        to that value.
        """
        if not text or not isinstance(text, str):
            return text
        with _fail_closed("blad polanon"):
            return self._turn.mask(text)

    def mask_data(self, value: Any) -> Any:
        """Mask every string inside a JSON-like value (tool results, aggregates).

        Keys, numbers, booleans and None stay as they are. Anything else, such as a date or a
        Decimal, is masked as its text, the form ``json.dumps(default=str)`` sends it in.
        """
        with _fail_closed("blad polanon"):
            return self._turn.mask_data(value, default=str)

    def mask_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Mask a chat history in the Anthropic Messages API shape (one mapping for all of it).

        The ``text`` of every block, the ``input`` of ``tool_use`` and the ``content`` of
        ``tool_result`` are masked; a tool result stored as JSON stays valid JSON. Roles, block
        types, ids and tool names stay intact. Any other block type (e.g. ``thinking``, stored
        while masking was off) is left out: it cannot be masked without breaking its signature.
        A value first recognised in a later message is masked in the earlier ones too.
        """
        with _fail_closed("blad polanon"):
            return self._turn.mask_messages(messages)

    # -- incoming: tokens -> real values -----------------------------------------------------

    def restore(self, text: str) -> str:
        """Replace known tokens in text a person reads with real values; unknown ones stay.

        A token with a case gives the name declined, ``<OSOBA_1:celownik>`` "Janowi Testowskiemu";
        a name polanon cannot decline for sure comes back as written.
        """
        if not text or not isinstance(text, str):
            return text
        return self._turn.restore(text)

    def restore_data(self, value: Any) -> Any:
        """Restore tokens inside a JSON-like value (tool call arguments, structured output).

        The values go to code and the database, which hold the original spelling, so a token with
        a case gives the value as the mapping holds it, not declined.
        """
        return self._turn.restore_data(value, as_held=True)

    def stream_restorer(self) -> StreamRestorer:
        """A restorer for one streamed model response (create a new one per response).

        It holds back a token split across chunks (``<FIR`` + ``MA_1>``) until it is whole.
        """
        return self._turn.stream_restorer()

    def unknown_tokens(self, text: str) -> list[str]:
        """Tokens in a model answer that are not in the mapping (the model invented or mangled them).

        Each is given as the mapping would hold it, ``<OSOBA_9>`` for ``<OSOBA_9:celownik>``.
        """
        return self._turn.unknown_tokens(text or "")

    def labels(self) -> dict[str, int]:
        """How many values of each kind were masked, e.g. ``{"FIRMA": 2, "NIP": 1}`` (no values)."""
        return dict(Counter(t[1:].rsplit("_", 1)[0] for t, v in self._turn.mapping.items() if v != t))

    def restore_blocks(self, content: Any) -> Any:
        """Restore the content the model returned (a string or ``text`` and ``tool_use`` blocks)."""
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


def polanon_masker(with_ner: bool = False, terms: Iterable[str] = ()) -> Masker:
    """A :class:`Masker` backed by polanon. Raises :class:`MaskingUnavailable` when it cannot run.

    ``terms`` are values the panel already knows are sensitive: client company names and NIPs
    from the database. polanon's rules find names with a legal form ("sp. z o.o.") or a first
    name, but not "Klub Sportowy Orlik" alone in a tool result field; known terms are masked
    always, through the turn's ``known`` (polanon's ``DenylistGuard``, token ``<FIRMA_n>``).
    """
    anonymizer = _get_anonymizer(with_ner)
    known = [t for t in dict.fromkeys((t or "").strip() for t in terms) if len(t) >= 3]
    return Masker(anonymizer, known)
