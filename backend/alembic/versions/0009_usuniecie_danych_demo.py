"""Usuniecie danych demonstracyjnych z tabel produkcyjnych.

Migracje 0007 i 0008 wstawialy dane demo BEZWARUNKOWO, przy kazdym `alembic upgrade head`
- takze na bazie z prawdziwa sprzedaza. Zmyslone wydatki reklamowe i statystyki organiczne
zasilaly KPI (ROAS, CAC, CPO, zaangazowanie organiczne, ranking formatow) i byly
nieodroznialne od danych rzeczywistych. Panel analityczny nie moze pokazywac liczb,
ktorych zrodlem jest kod migracji.

Ta migracja usuwa wylacznie wiersze jednoznacznie oznaczone source='demo'. Dane z API
i importu CSV (source='api'/'csv') pozostaja nietkniete.

CELOWO NIE RUSZAMY core.orders.first_contact_at ani core.products.cost: te kolumny nie
maja znacznika pochodzenia, wiec nie da sie odroznic wartosci wstawionej przez migracje
od wpisanej pozniej przez uzytkownika. Kasowanie ich zniszczyloby prawdziwe dane.
Sposob sprawdzenia i ewentualnego wyczyszczenia opisano w docs/00-decyzje-kanoniczne.md.

Dane demo mozna przywrocic swiadomie:  python -m app.scripts.seed_demo

Revision ID: 0009_usuniecie_danych_demo
Revises: 0008_usprawnienia
"""

from __future__ import annotations

from alembic import op

revision = "0009_usuniecie_danych_demo"
down_revision = "0008_usprawnienia"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Wydatki reklamowe: demo zawyzalo spend, a wiec CAC, CPO i zanizalo ROAS.
    op.execute("DELETE FROM channel_meta.ads_daily WHERE source = 'demo'")
    # Zaangazowanie organiczne i ranking formatow bylyby w calosci zmyslone.
    op.execute("DELETE FROM channel_organic.post_stats_daily WHERE source = 'demo'")
    # Szkice-atrapy z 0007 (wraz z pozycjami; FK ma ON DELETE CASCADE, ale kasujemy jawnie).
    op.execute(
        """
        DELETE FROM core.order_draft_items
         WHERE draft_id IN (
             SELECT id FROM core.orders_draft
              WHERE email_id IS NULL
                AND company_name IN ('Zapytanie mailowe 1', 'Zapytanie mailowe 2')
         )
        """
    )
    op.execute(
        """
        DELETE FROM core.orders_draft
         WHERE email_id IS NULL
           AND company_name IN ('Zapytanie mailowe 1', 'Zapytanie mailowe 2')
        """
    )


def downgrade() -> None:
    # Nie odtwarzamy danych demo automatycznie - sluzy do tego app/scripts/seed_demo.py.
    pass
