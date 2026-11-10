"""Treść z zewnątrz idzie do modelu w znacznikach danych, nie jako polecenia (prompt injection).

Mail pisze obca osoba, a wyniki narzędzi asystenta niosą nazwy produktów i firm oraz dane
odczytane z maili. Każdy taki tekst trafia do modelu między ``<tag>`` a ``</tag>``, a system
prompt mówi, że treść tych znaczników to dane. Ten sam znacznik w samej treści jest rozbrajany
(``<`` zamienione na ``[``), więc treść nie zamknie bloku danych, żeby dopisać za nim coś, co
wyglądałoby na polecenie spoza danych.

Znaczniki nie są zabezpieczeniem same w sobie: model nadal może posłuchać tekstu z danych.
Dlatego parser maili tylko tworzy szkic do ręcznej weryfikacji, a narzędzia asystenta działają
na roli bazy tylko do odczytu (patrz README, sekcja "Architektura").
"""

from __future__ import annotations

import json
import re
from typing import Any

EMAIL_TAG = "dane_maila"
TOOL_RESULT_TAG = "wynik_narzedzia"


def _tag_pattern(tag: str) -> re.Pattern[str]:
    # <tag>, </tag>, < /tag>, <TAG atrybut="..."> - każdy zapis, który model mógłby wziąć za znacznik
    return re.compile(rf"<\s*/?\s*{re.escape(tag)}(?!\w)", re.IGNORECASE)


def defuse(tag: str, content: str) -> str:
    """Rozbraja w treści każdy zapis znacznika ``tag`` (początek ``<`` zamieniony na ``[``)."""
    return _tag_pattern(tag).sub(lambda m: "[" + m.group(0)[1:], content or "")


def wrap(tag: str, content: str) -> str:
    """Treść w znacznikach danych ``<tag>...</tag>``, z rozbrojonym tym samym znacznikiem w środku."""
    return f"<{tag}>\n{defuse(tag, content)}\n</{tag}>"


def unwrap(tag: str, text: str) -> str | None:
    """Treść spomiędzy znaczników z :func:`wrap`; None, gdy tekst nie jest tak opakowany."""
    head, tail = f"<{tag}>\n", f"\n</{tag}>"
    if isinstance(text, str) and text.startswith(head) and text.endswith(tail):
        return text[len(head):-len(tail)]
    return None


def wrap_tool_result(content: Any) -> str:
    """Wynik narzędzia (JSON albo tekst) w znacznikach ``<wynik_narzedzia>``."""
    raw = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
    return wrap(TOOL_RESULT_TAG, raw)
