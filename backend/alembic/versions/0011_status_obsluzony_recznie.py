"""Status 'obsluzony_recznie' - domkniecie cyklu zycia nieodczytanego maila.

Mail w stanie 'blad_parsowania' nie mial ZADNEJ sciezki wyjscia: approve_draft/reject_draft
wymagaja istniejacego szkicu, a taki mail szkicu nie ma z definicji. Sekcja ostrzegawcza
w Skrzynce (i plakietka w menu) wisialaby wiec na zawsze - takze po recznym wpisaniu
zamowienia. Po kilku takich zdarzeniach ostrzezenie przestaje cokolwiek znaczyc.

Revision ID: 0011_status_obsluzony_recznie
Revises: 0010_klucz_klienta_cac
"""

from __future__ import annotations

from alembic import op

revision = "0011_status_obsluzony_recznie"
down_revision = "0010_klucz_klienta_cac"
branch_labels = None
depends_on = None

_STARE = ("odebrany", "sklasyfikowany", "sparsowany", "zamowienie_utworzone",
          "odrzucony_automatycznie", "blad_parsowania", "odpowiedz_w_watku", "duplikat")
_NOWE = (*_STARE, "obsluzony_recznie")


def _check(wartosci: tuple[str, ...]) -> str:
    lista = ", ".join(f"'{w}'" for w in wartosci)
    return f"status = ANY (ARRAY[{lista}]::text[])"


def upgrade() -> None:
    op.execute("ALTER TABLE mail.emails DROP CONSTRAINT IF EXISTS ck_emails_status")
    op.execute(f"ALTER TABLE mail.emails ADD CONSTRAINT ck_emails_status CHECK ({_check(_NOWE)})")


def downgrade() -> None:
    # Cofamy oznaczenia, zeby stary CHECK przeszedl.
    op.execute("UPDATE mail.emails SET status = 'blad_parsowania' WHERE status = 'obsluzony_recznie'")
    op.execute("ALTER TABLE mail.emails DROP CONSTRAINT IF EXISTS ck_emails_status")
    op.execute(f"ALTER TABLE mail.emails ADD CONSTRAINT ck_emails_status CHECK ({_check(_STARE)})")
