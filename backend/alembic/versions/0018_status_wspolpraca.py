"""Status 'wspolpraca' - zgloszenie wspolpracy ze strony (klub sportowy / hurtownik).

Strona dostala zakladke „Wspolpraca". Zgloszenia ida na te sama skrzynke i z tego samego
nadawcy co zamowienia, ale zamowieniami nie sa: panel ma je pokazac w Skrzynce i nie robic
z nich szkicu. Bez wlasnego statusu taki mail trafial w tor zamowien (parser AI, falszywy
szkic albo ciche odrzucenie).

Revision ID: 0018_status_wspolpraca
Revises: 0017_email_uzytkownika
"""

from __future__ import annotations

from alembic import op

revision = "0018_status_wspolpraca"
down_revision = "0017_email_uzytkownika"
branch_labels = None
depends_on = None

_STARE = ("odebrany", "sklasyfikowany", "sparsowany", "zamowienie_utworzone",
          "odrzucony_automatycznie", "blad_parsowania", "odpowiedz_w_watku", "duplikat",
          "obsluzony_recznie")
_NOWE = (*_STARE, "wspolpraca")


def _check(wartosci: tuple[str, ...]) -> str:
    lista = ", ".join(f"'{w}'" for w in wartosci)
    return f"status = ANY (ARRAY[{lista}]::text[])"


def upgrade() -> None:
    op.execute("ALTER TABLE mail.emails DROP CONSTRAINT IF EXISTS ck_emails_status")
    op.execute(f"ALTER TABLE mail.emails ADD CONSTRAINT ck_emails_status CHECK ({_check(_NOWE)})")


def downgrade() -> None:
    # Zgloszenia wracaja do stanu „zamkniete recznie", zeby stary CHECK przeszedl.
    op.execute("UPDATE mail.emails SET status = 'obsluzony_recznie' WHERE status = 'wspolpraca'")
    op.execute("ALTER TABLE mail.emails DROP CONSTRAINT IF EXISTS ck_emails_status")
    op.execute(f"ALTER TABLE mail.emails ADD CONSTRAINT ck_emails_status CHECK ({_check(_STARE)})")
