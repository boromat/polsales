"""Raport PDF „Konkurencja" - trzy grupy (decyzja #22).

Osobny dokument, nie sekcja raportu sprzedażowego: to inny temat i inna kadencja obserwacji.
Współdzieli warstwę wizualną z `report_pdf` (fonty, kolory, nagłówki sekcji, tabele), żeby oba
raporty wyglądały jak jedna rodzina dokumentów.

Reguła, która rządzi układem tego raportu: **każda grupa zaczyna się od tego, czego NIE widać.**
O konkurencji znamy wyłącznie lajki i komentarze; zestawienie tego z własnym zasięgiem dałoby
wnioski wyssane z palca. Dlatego ograniczenie jest pierwszym, a nie ostatnim, co czyta właściciel.
"""

from __future__ import annotations

import io
from datetime import date, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.services.competitors import raport as dane_raportu
from app.services.report_pdf import (
    BG2,
    BODY,
    CONTENT_W,
    DANGER,
    INK,
    LINE,
    MUTED,
    OK,
    ORGANIC,
    PRIMARY,
    SUBTLE,
    TINT,
    NumberedCanvas,
    SectionHeader,
    _data_table,
    _p,
    _register_fonts,
    _styles,
    bar_cell,
    esc,
    humanize,
    int_num,
    period_label,
    ratio_pct,
)

# Kolory formatów - te same odcienie co w raporcie sprzedażowym dla spójności rodziny.
KOLORY_FORMATOW = {
    "reel": PRIMARY,
    "carousel": ORGANIC,
    "photo": OK,
    "video": colors.HexColor("#EA580C"),
    "inny": SUBTLE,
}


def _num_pl(v) -> str:
    """Liczba z przecinkiem dziesiętnym i spacją nierozdzielającą tysięcy."""
    if v is None:
        return "-"
    return f"{float(v):,.1f}".replace(",", " ").replace(".", ",")


def _naglowek_grupy(g: dict, S: dict) -> list:
    """Nagłówek grupy + jednozdaniowe podsumowanie, co w niej widać."""
    if not g["profili"]:
        podsumowanie = "Brak obserwowanych konkurentów w tej grupie."
    elif not g["dosc_danych"]:
        podsumowanie = (
            f"{g['profili']} obserwowanych, ale tylko {g['postow']} "
            f"{'post' if g['postow'] == 1 else 'postów'} w oknie - "
            f"za mało, żeby liczyć wskaźniki (próg: {g['min_postow']})."
        )
    else:
        podsumowanie = (
            f"{g['profili']} obserwowanych · {g['postow']} postów · "
            f"{_num_pl(g['postow_na_tydzien'])} posta/tydzień · "
            f"mediana zaangażowania {_num_pl(g['mediana_zaangazowania'])}"
        )
    return [
        SectionHeader(g["_nr"], g["nazwa"]),
        Paragraph(esc(podsumowanie), S["small"]),
        Spacer(1, 3 * mm),
    ]


def _ramka_widocznosci(g: dict, S: dict):
    """Co widać / czego nie widać - obowiązkowy element każdej grupy (decyzja #22)."""
    # Znacznik: ■ zamiast ✓/✗ - te drugie nie maja glifow w Helvetice ani Arialu
    # i renderowaly sie jako puste kwadraty (sprawdzone na renderze strony).
    lewa = [_p("CO WIDAĆ PUBLICZNIE", 7.5, OK, bold=True), Spacer(1, 1.5 * mm)]
    for w in g["widoczne"]:
        lewa.append(Paragraph(f'<font color="#16A34A">■</font>&nbsp; {esc(w)}', S["small"]))
    prawa = [_p("CZEGO NIE WIDAĆ", 7.5, DANGER, bold=True), Spacer(1, 1.5 * mm)]
    for w in g["niewidoczne"]:
        prawa.append(Paragraph(f'<font color="#DC2626">■</font>&nbsp; {esc(w)}', S["small"]))

    t = Table([[lewa, prawa]], colWidths=[CONTENT_W / 2, CONTENT_W / 2])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), BG2),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LINEAFTER", (0, 0), (0, 0), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _tabela_profili(g: dict, S: dict):
    rows = []
    for p in g["profile"]:
        przyrost = p["przyrost_30d_pct"]
        if przyrost is None:
            kom = _p("-", 9, MUTED, align=2)
        else:
            kolor = OK if przyrost > 0 else (DANGER if przyrost < 0 else MUTED)
            znak = "+" if przyrost > 0 else ""
            kom = _p(f"{znak}{_num_pl(przyrost)}%", 9, kolor, bold=True, align=2)
        rows.append([
            p["name"],
            ("@" + p["ig_username"]) if p["ig_username"] else "-",
            int_num(p["followers"]) if p["followers"] is not None else "-",
            kom,
            int_num(p["postow_zebranych"]),
        ])
    return _data_table(
        ["Konkurent", "Instagram", "Obserwujący", "Zmiana 30 dni", "Zebranych postów"],
        rows, [0, 0, 1, 1, 1],
        col_w=[52 * mm, 34 * mm, 26 * mm, 30 * mm, 28 * mm], S=S,
    )


def _tabela_formatow(g: dict, wlasny: dict, S: dict):
    """Rozkład formatów grupy zestawiony z własnym - to JEST porównywalne (decyzja #22)."""
    wlasne_udzialy = {f["media_type"]: f["udzial"] for f in wlasny["formaty"]}
    rows = []
    for f in g["formaty"]:
        kolor = KOLORY_FORMATOW.get(f["media_type"], SUBTLE)
        moj = wlasne_udzialy.get(f["media_type"])
        rows.append([
            humanize(f["media_type"]),
            int_num(f["postow"]),
            [bar_cell(f["udzial"], 30, 3.2, kolor), Spacer(1, 0.8 * mm),
             _p(ratio_pct(f["udzial"]), 8, INK, bold=True)],
            _p(ratio_pct(moj) if moj is not None else "-", 9, MUTED, align=2),
        ])
    return _data_table(
        ["Format", "Postów", "Udział w grupie", "U Ciebie"],
        rows, [0, 1, 0, 1],
        col_w=[40 * mm, 24 * mm, 56 * mm, 50 * mm], S=S,
    )


def _tabela_top(g: dict, S: dict):
    rows = []
    for p in g["top_posty"]:
        data = ""
        if p["posted_at"]:
            try:
                data = datetime.fromisoformat(p["posted_at"]).strftime("%d.%m.%Y")
            except (ValueError, TypeError):
                data = ""
        opis = (p["caption"] or "").replace("\n", " ").strip()
        if len(opis) > 110:
            opis = opis[:110].rstrip() + "…"
        rows.append([
            p["profil"],
            humanize(p["media_type"]),
            data,
            int_num(p["engagement"]),
            Paragraph(esc(opis) or "-", S["small"]),
        ])
    return _data_table(
        ["Profil", "Format", "Data", "Lajki + kom.", "Początek opisu"],
        rows, [0, 0, 0, 1, 0],
        col_w=[34 * mm, 22 * mm, 22 * mm, 24 * mm, 68 * mm], S=S,
    )


def build_competitors_pdf(db: DBSession, date_from: date, date_to: date) -> bytes:
    _register_fonts()
    S = _styles()
    company = settings.company_name or "Twoja Firma"
    period = period_label(date_from, date_to)
    generated = datetime.now().strftime("%d.%m.%Y")
    dane = dane_raportu(db, date_from, date_to)

    story: list = [
        # Leading MUSI byc wiekszy od stopnia pisma - styl "body" ma 14 pkt i tytul 22 pkt
        # wchodzil na wiersz ponizej.
        _p("Obserwacja konkurencji", 22, INK, bold=True, leading=27),
        Spacer(1, 1.5 * mm),
        Paragraph(
            f'<font size="10" color="#64646E">Okres: {esc(period)}</font>'
            f'&nbsp;&nbsp;·&nbsp;&nbsp;<font size="9" color="#A1A1AA">Wygenerowano {generated}</font>',
            S["small"],
        ),
        Spacer(1, 6 * mm),
    ]

    # Nota metodologiczna PRZED danymi - czytelnik ma znać granice, zanim zobaczy liczby.
    nota = [
        _p("JAK CZYTAĆ TEN RAPORT", 7.5, PRIMARY, bold=True),
        Spacer(1, 1.5 * mm),
        Paragraph(
            "O konkurencji widać wyłącznie dane publiczne: typ posta, datę publikacji, lajki "
            "i komentarze. <b>Zasięgu, wyświetleń ani wydatków reklamowych nie widać</b> - dlatego "
            "w tym raporcie nie ma ROAS-u ani kosztu pozyskania klienta dla konkurentów.",
            S["wk_body"],
        ),
        Spacer(1, 1.5 * mm),
        Paragraph(
            "Zaangażowanie grupy podajemy <b>medianą</b>, nie średnią: jeden viralowy post "
            "przesuwa średnią o rząd wielkości i sugeruje trend, którego nie ma. Porównywalne "
            "z Twoim profilem są rozkład formatów i rytm publikacji - liczone po obu stronach "
            "tą samą metodą.",
            S["wk_body"],
        ),
    ]
    ramka = Table([["", nota]], colWidths=[3 * mm, CONTENT_W - 3 * mm])
    ramka.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), PRIMARY),
        ("BACKGROUND", (1, 0), (1, 0), TINT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (1, 0), (1, 0), 8), ("RIGHTPADDING", (1, 0), (1, 0), 8),
        ("TOPPADDING", (1, 0), (1, 0), 7), ("BOTTOMPADDING", (1, 0), (1, 0), 7),
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
    ]))
    story += [ramka, Spacer(1, 7 * mm)]

    # Numeracja liczona w locie - grupa bez konkurentów nadal dostaje sekcję (z komunikatem),
    # ale gdyby kiedyś któraś znikała, numery i tak zostaną ciągłe.
    licznik = [0]

    def nr() -> str:
        licznik[0] += 1
        return f"{licznik[0]:02d}"

    for i, g in enumerate(dane["grupy"]):
        g["_nr"] = nr()
        blok = _naglowek_grupy(g, S)

        if not g["profili"]:
            blok.append(Paragraph(
                "Dodaj konkurentów do tej grupy w panelu (zakładka „Konkurencja”), "
                "żeby pojawiły się tu dane.", S["small"]))
            story += [KeepTogether(blok), Spacer(1, 7 * mm)]
            continue

        blok += [_ramka_widocznosci(g, S), Spacer(1, 4 * mm), _tabela_profili(g, S)]
        story.append(KeepTogether(blok))

        if g["dosc_danych"]:
            blok_top = [
                _p("Najmocniejsze posty okresu", 9, INK, bold=True),
                Spacer(1, 2.5 * mm),
                _tabela_top(g, S),
            ]
            # Rozjazd mediany i średniej sam w sobie jest informacją. Zostaje w TYM SAMYM
            # bloku co tabela - samo zdanie przeniesione na następną stronę wisiało nad
            # nagłówkiem kolejnej grupy i wyglądało, jakby jej dotyczyło.
            med, sr = g["mediana_zaangazowania"], g["srednia_zaangazowania"]
            if med and sr and sr > med * 1.5:
                blok_top += [
                    Spacer(1, 2.5 * mm),
                    Paragraph(
                        f'<font color="#EA580C">■</font>&nbsp; Średnia zaangażowania '
                        f"({_num_pl(sr)}) jest znacznie wyższa od mediany ({_num_pl(med)}) - "
                        "grupę ciągnie kilka wyjątkowych postów, a nie stały poziom.",
                        S["small"]),
                ]
            story += [
                Spacer(1, 5 * mm),
                KeepTogether([
                    _p("Rozkład formatów - grupa kontra Twój profil", 9, INK, bold=True),
                    Spacer(1, 2.5 * mm),
                    _tabela_formatow(g, dane["wlasny"], S),
                ]),
                Spacer(1, 5 * mm),
                KeepTogether(blok_top),
            ]

        if i < len(dane["grupy"]) - 1:
            story.append(Spacer(1, 8 * mm))

    # --- Własny profil na tle wszystkich grup ---
    w = dane["wlasny"]
    story += [Spacer(1, 8 * mm), SectionHeader(nr(), "Twój profil w tym samym okresie")]
    if not w["postow"]:
        story.append(Paragraph(
            "Brak danych o własnych postach organicznych w tym okresie "
            "(uzupełniane z Instagrama i Facebooka po podłączeniu integracji Meta).", S["small"]))
    else:
        rows = [[
            humanize(f["media_type"]),
            int_num(f["postow"]),
            [bar_cell(f["udzial"], 30, 3.2, KOLORY_FORMATOW.get(f["media_type"], SUBTLE)),
             Spacer(1, 0.8 * mm), _p(ratio_pct(f["udzial"]), 8, INK, bold=True)],
        ] for f in w["formaty"]]
        story += [
            Paragraph(
                f'{int_num(w["postow"])} postów · {_num_pl(w["postow_na_tydzien"])} posta/tydzień'
                + (f' · {int_num(w["views_wlasne"])} wyświetleń'
                   ' <font color="#A1A1AA">(tej metryki nie widać u konkurencji)</font>'
                   if w["views_wlasne"] else ""),
                S["small"]),
            Spacer(1, 3 * mm),
            _data_table(["Format", "Postów", "Udział"], rows, [0, 1, 0],
                        col_w=[40 * mm, 30 * mm, 100 * mm], S=S),
        ]

    def _footer(canvas: Canvas, doc):
        canvas.saveState()
        canvas.setFont(BODY, 7.5)
        canvas.setFillColor(SUBTLE)
        canvas.drawString(20 * mm, 10 * mm, f"{company} · Raport poufny")
        canvas.restoreState()

    def _running(canvas: Canvas, doc):
        canvas.saveState()
        H = A4[1]
        canvas.setFont(BODY, 7.5)
        canvas.setFillColor(SUBTLE)
        canvas.drawString(20 * mm, H - 14 * mm, company)
        canvas.drawRightString(190 * mm, H - 14 * mm, f"Konkurencja · {period}")
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(20 * mm, H - 17 * mm, 190 * mm, H - 17 * mm)
        canvas.restoreState()
        _footer(canvas, doc)

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                          topMargin=20 * mm, bottomMargin=18 * mm, title="Raport: konkurencja")
    frame = Frame(20 * mm, 18 * mm, CONTENT_W, A4[1] - 22 * mm - 18 * mm, id="main")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_running)])
    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()
