"""Dopasowanie nazw produktów do katalogu - warstwa aliasów + fuzzy (pipeline §d)."""

from __future__ import annotations

import unicodedata

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db.models.core import Product
from app.db.models.drafts import ProductAlias

# Progi dopasowania (pipeline §d).
AUTO_THRESHOLD = 92
SUGGEST_THRESHOLD = 70


def normalize_name(name: str) -> str:
    """Lowercase, usunięcie polskich znaków diakrytycznych i interpunkcji - do porównań i aliasów."""
    # 'ł' nie rozkłada się przez NFKD (osobna litera) - mapujemy jawnie.
    pre = name.lower().replace("ł", "l").replace("Ł", "l")
    nfkd = unicodedata.normalize("NFKD", pre)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join("".join(ch if ch.isalnum() else " " for ch in ascii_only).split())


def match_product(db: DBSession, raw_name: str) -> dict:
    """Zwraca {matched_product_id, match_score, match_status, suggestions?}."""
    if not raw_name:
        return {"matched_product_id": None, "match_score": None, "match_status": "brak"}

    norm = normalize_name(raw_name)

    # 1. Warstwa aliasów - dokładne trafienie po znormalizowanej nazwie aliasu = pewne.
    alias = db.scalar(select(ProductAlias).where(ProductAlias.raw_name_normalized == norm))
    if alias is not None:
        return {"matched_product_id": alias.product_id, "match_score": 100.0, "match_status": "auto"}

    # 2. Fuzzy: pula kandydatów = nazwy aktywnych produktów + uczące się aliasy.
    products = db.scalars(select(Product).where(Product.is_active.is_(True))).all()
    by_id = {p.id: p for p in products}

    # Kandydaci (znormalizowany_tekst, product_id): nazwa produktu + wszystkie jego aliasy.
    candidates: list[tuple[str, int]] = [(normalize_name(p.name), p.id) for p in products]
    if by_id:
        aliases = db.scalars(
            select(ProductAlias).where(ProductAlias.product_id.in_(by_id.keys()))
        ).all()
        candidates += [
            (a.raw_name_normalized, a.product_id) for a in aliases if a.raw_name_normalized
        ]

    # Najlepszy wynik per produkt (produkt ma nazwę i może mieć wiele aliasów).
    best_by_product: dict[int, float] = {}
    for text_norm, pid in candidates:
        if pid not in by_id:
            continue
        score = max(fuzz.token_set_ratio(norm, text_norm), fuzz.partial_ratio(norm, text_norm))
        if score > best_by_product.get(pid, -1.0):
            best_by_product[pid] = score

    scored = sorted(
        ((sc, by_id[pid]) for pid, sc in best_by_product.items()),
        key=lambda x: x[0],
        reverse=True,
    )

    if not scored:
        return {"matched_product_id": None, "match_score": None, "match_status": "brak"}

    best_score, best = scored[0]
    if best_score >= AUTO_THRESHOLD:
        return {"matched_product_id": best.id, "match_score": float(best_score), "match_status": "auto"}
    if best_score >= SUGGEST_THRESHOLD:
        return {
            "matched_product_id": best.id,
            "match_score": float(best_score),
            "match_status": "zasugerowane",
            "suggestions": [{"id": p.id, "name": p.name, "score": float(s)} for s, p in scored[:5]],
        }
    return {"matched_product_id": None, "match_score": float(best_score), "match_status": "brak"}


def learn_alias(db: DBSession, raw_name: str, product_id: int) -> None:
    """Zapamiętuje ręczną korektę jako alias - przyspiesza kolejne dopasowania."""
    norm = normalize_name(raw_name)
    if not norm:
        return
    existing = db.scalar(select(ProductAlias).where(ProductAlias.raw_name_normalized == norm))
    if existing is None:
        db.add(ProductAlias(raw_name_normalized=norm, product_id=product_id))
    else:
        existing.product_id = product_id
