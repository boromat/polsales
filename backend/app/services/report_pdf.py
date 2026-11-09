"""Generowanie eleganckiego raportu PDF (Etap 8) - reportlab (pure-Python, Windows+Linux).

Kierunek wizualny: "editorial / raport konsultingowy" - biel + jeden akcent indygo, hairline'owe
siatki KPI, tabele bez pionów z lekkim tintem nagłówka, data-bary i lejek z komórek Table, wykres
kanałów w kolorach kanałów, callout tygodniowy z paskiem-akcentem. Wszystkie liczby po polsku
(przecinek dziesiętny, spacja tysięcy), kody uczłowieczone, brak surowych identyfikatorów i dat ISO.
"""

from __future__ import annotations

import io
import os
import re
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.services.marketing import (
    ad_format_ranking,
    channel_summary,
    funnel,
    organic_engagement,
)
from app.services.metrics import dashboard_kpi
from app.services.weekly_summary import list_summaries

# --- Czcionki: Arial (Windows) → DejaVu (Linux/VPS) → Helvetica (fallback bez polskich znaków) ---
BODY, BOLD = "Helvetica", "Helvetica-Bold"


def _register_fonts() -> None:
    global BODY, BOLD
    for reg, bold in [
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]:
        if os.path.exists(reg) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("ReportBody", reg))
                pdfmetrics.registerFont(TTFont("ReportBody-Bold", bold))
                pdfmetrics.registerFontFamily("ReportBody", normal="ReportBody", bold="ReportBody-Bold")
                BODY, BOLD = "ReportBody", "ReportBody-Bold"
                return
            except Exception:  # noqa: BLE001, S110 - brak tej czcionki: próbujemy następnej
                pass


_register_fonts()

# --- Paleta (spójna z panelem) ---
INK = colors.HexColor("#18181B")
MUTED = colors.HexColor("#64646E")
SUBTLE = colors.HexColor("#A1A1AA")
LINE = colors.HexColor("#E4E4E7")
BG2 = colors.HexColor("#FAFAFB")
PRIMARY = colors.HexColor("#4F46E5")
TINT = colors.HexColor("#EEF2FF")
WHITE = colors.white
# Kanały
META = colors.HexColor("#2563EB")
GOOGLE = colors.HexColor("#EA580C")
ORGANIC = colors.HexColor("#9333EA")
DIRECT = colors.HexColor("#0D9488")
OFFLINE = colors.HexColor("#64748B")
# Semantyka
OK = colors.HexColor("#16A34A")
WARN = colors.HexColor("#D97706")
DANGER = colors.HexColor("#DC2626")
B2C_TINT = colors.HexColor("#A5B4FC")
FUNNEL_SHADES = [PRIMARY, colors.HexColor("#6366F1"), colors.HexColor("#818CF8"), colors.HexColor("#A5B4FC")]

CHANNEL_COLORS = {
    "meta_ads": META, "google_ads": GOOGLE, "fb_ig_organic": ORGANIC,
    "seo_direct": DIRECT, "direct": DIRECT, "organic": ORGANIC,
    "offline": OFFLINE, "brak": OFFLINE, "polecenie": DIRECT,
}

NBSP = " "
PL_MONTHS = ["", "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
             "lipca", "sierpnia", "września", "października", "listopada", "grudnia"]
PL_MONTHS_NOM = ["", "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
                 "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"]

HUMANIZE = {
    # kanały / platformy
    "meta_ads": "Meta Ads", "google_ads": "Google Ads", "fb_ig_organic": "Facebook / Instagram",
    "search": "Wyszukiwarka", "organic": "Organiczne", "direct": "Bezpośrednie",
    "seo_direct": "SEO / bezpośrednie", "offline": "Offline", "brak": "Bez atrybucji",
    "polecenie": "Polecenie",
    # formaty
    "reel": "Rolka", "reels": "Rolka", "carousel": "Karuzela", "image": "Zdjęcie",
    "photo": "Zdjęcie", "video": "Wideo", "story": "Relacja", "link": "Link",
    # typ
    "paid": "Płatny", "organic_post": "Organiczny",
}


def esc(v) -> str:
    """Escapuje tekst uzytkownika przed wstawieniem do Paragraph.

    reportlab parsuje zawartosc Paragraph jak XML. Nazwa produktu z maila typu
    "Rura <20mm" albo "Kawa <mocna" wywracala CALE generowanie raportu
    (ValueError: unclosed tags) - /api/reports/pdf zwracal 500 az do recznej
    poprawy tej jednej pozycji. Escapujemy &, < i >.
    """
    return escape("" if v is None else str(v))


def humanize(code) -> str:
    if code is None:
        return "-"
    key = str(code).strip().lower()
    if key in HUMANIZE:
        return HUMANIZE[key]
    return str(code).replace("_", " ").strip().title()


# Podzbiór bezpieczny do podmiany w wolnym tekście (tylko jednoznaczne kody - bez „brak", „polecenie"
# itp., które są zwykłymi polskimi słowami i mogłyby zepsuć narrację).
TEXT_HUMANIZE = {
    "google_ads": "Google Ads", "meta_ads": "Meta Ads",
    "fb_ig_organic": "Facebook / Instagram", "seo_direct": "SEO / bezpośrednie",
    "reels": "Rolka", "reel": "Rolka", "carousel": "Karuzela",
}
_TEXT_HUMANIZE_RE = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(k) for k in sorted(TEXT_HUMANIZE, key=len, reverse=True)) + r")(?!\w)",
    re.IGNORECASE,
)


def humanize_text(s: str) -> str:
    return _TEXT_HUMANIZE_RE.sub(lambda m: TEXT_HUMANIZE.get(m.group(0).lower(), m.group(0)), s)


# --- Formattery (jedno miejsce prawdy; przecinek dziesiętny + NBSP tysięcy) ---
def _grp(s: str) -> str:
    return s.replace(",", NBSP).replace(".", ",")


def money_num(v) -> str:
    return "-" if v is None else _grp(f"{float(v):,.2f}")


def int_num(v) -> str:
    return "-" if v is None else f"{int(round(float(v))):,}".replace(",", NBSP)


def roas_num(v) -> str:
    return "-" if v is None else f"{float(v):.2f}".replace(".", ",")


def pct_num(v) -> str:
    """Wartość już w procentach (np. margin_pct=40.0)."""
    return "-" if v is None else f"{float(v):.1f}".replace(".", ",")


def ratio_pct(v) -> str:
    """Współczynnik 0-1 → procent (np. CTR 0.024 → 2,4%)."""
    return "-" if v is None else f"{float(v) * 100:.1f}".replace(".", ",") + "%"


def days_num(v) -> str:
    return "-" if v is None else f"{float(v):.1f}".replace(".", ",")


def qty_num(v) -> str:
    if v is None:
        return "-"
    f = float(v)
    return _grp(f"{f:,.0f}") if f == int(f) else _grp(f"{f:,.2f}")


def channel_color(code) -> colors.Color:
    return CHANNEL_COLORS.get(str(code).strip().lower(), OFFLINE)


def channel_label(c) -> str:
    """Czytelna nazwa kanału - preferuj zwięzłe mapowanie po kodzie, inaczej name_pl."""
    code = str(c.get("channel_code") or "").strip().lower()
    if code in HUMANIZE:
        return HUMANIZE[code]
    return humanize(c.get("name_pl") or c.get("channel_code"))


def period_label(df: date, dt: date) -> str:
    """Ładny opis okresu - pełny miesiąc gdy pasuje, inaczej zakres dd.mm.rrrr."""
    is_full_month = (
        df.day == 1 and df.month == dt.month and df.year == dt.year
        and (dt + timedelta(days=1)).month != dt.month
    )
    if is_full_month:
        return f"{PL_MONTHS_NOM[df.month]} {df.year}"
    return f"{df.strftime('%d.%m.%Y')} - {dt.strftime('%d.%m.%Y')}"


def polonize_decimals(s: str) -> str:
    """Zamienia kropkę dziesiętną między cyframi na przecinek (dla narracji AI/baseline).

    Daty w formacie polskim (13.07.2026) są chronione - kropka jest tam poprawna,
    a zamiana zrobiłaby z nich „13,07,2026". Odpowiednik `polonizeDecimals`
    z frontend/src/lib/format.ts; oba muszą dawać ten sam wynik, bo panel i PDF
    pokazują tę samą narrację tygodniową.
    """
    # Alternatywa w regexie: najpierw próba dopasowania DATY (zwracamy bez zmian),
    # dopiero potem cyfra-kropka-cyfra.
    return re.sub(
        r"\d{1,2}\.\d{1,2}\.\d{4}|(\d)\.(\d)",
        lambda m: m.group(0) if m.group(1) is None else f"{m.group(1)},{m.group(2)}",
        s,
    )


def fmt_week(iso_start: str, iso_end: str) -> str:
    try:
        s = datetime.strptime(iso_start, "%Y-%m-%d").date()
        e = datetime.strptime(iso_end, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return f"{iso_start}-{iso_end}"
    if s.year == e.year:
        return f"{s.strftime('%d.%m')} - {e.strftime('%d.%m.%Y')}"
    return f"{s.strftime('%d.%m.%Y')} - {e.strftime('%d.%m.%Y')}"


# =========================================================================
#  Elementy wizualne
# =========================================================================
CONTENT_W = 170 * mm


def _styles() -> dict:
    return {
        "label": ParagraphStyle("label", fontName=BODY, fontSize=7.5, textColor=MUTED, leading=9.5),
        "body": ParagraphStyle("body", fontName=BODY, fontSize=9.5, textColor=INK, leading=14),
        "cell": ParagraphStyle("cell", fontName=BODY, fontSize=9, textColor=INK, leading=11.5),
        "cellhead": ParagraphStyle("cellhead", fontName=BOLD, fontSize=8, textColor=MUTED, leading=10),
        "small": ParagraphStyle("small", fontName=BODY, fontSize=8, textColor=MUTED, leading=10.5),
        "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=13, textColor=INK, leading=15),
        "wk_head": ParagraphStyle("wk_head", fontName=BOLD, fontSize=11, textColor=INK, leading=14),
        "wk_body": ParagraphStyle("wk_body", fontName=BODY, fontSize=9.5, textColor=INK, leading=14),
    }


def _p(txt, size, color=INK, bold=False, align=0, leading=None):
    """Skrót na Paragraph z inline stylem (align: 0=lewo, 1=środek, 2=prawo)."""
    return Paragraph(txt, ParagraphStyle(
        "p", fontName=BOLD if bold else BODY, fontSize=size, textColor=color,
        leading=leading or size + 2.5, alignment=align))


def bar_cell(frac: float, width_mm: float, height_mm: float, color, track=TINT):
    """Poziomy data-bar zbudowany z 2-komórkowej tabeli (kolor + tor)."""
    frac = max(0.0, min(1.0, frac or 0.0))
    if frac <= 0:
        t = Table([[""]], colWidths=[width_mm * mm], rowHeights=[height_mm * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), track),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return t
    fw = max(0.012, frac) * width_mm
    rest = max(0.0, width_mm - fw)
    cols = [fw * mm] + ([rest * mm] if rest > 0.05 else [])
    row = [""] * len(cols)
    t = Table([row], colWidths=cols, rowHeights=[height_mm * mm])
    st = [
        ("BACKGROUND", (0, 0), (0, 0), color),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if len(cols) > 1:
        st.append(("BACKGROUND", (1, 0), (1, 0), track))
    t.setStyle(TableStyle(st))
    return t


class SectionHeader(Flowable):
    """Nagłówek sekcji: pionowy tick indygo + numer 0X + tytuł.

    Odstęp pod nagłówkiem jest CZĘŚCIĄ tego elementu (nie osobnym Spacerem), a
    `keepWithNext` przykleja nagłówek do treści sekcji. Bez tego reportlab potrafił
    zostawić sam tytuł na dole strony, a tabelę czy wykres przenieść na następną -
    czytelnik widział pusty nagłówek bez zawartości.
    """

    keepWithNext = 1

    PASEK = 7 * mm      # wysokość samego nagłówka
    ODSTEP = 3 * mm     # światło pod nagłówkiem

    def __init__(self, number: str, title: str):
        super().__init__()
        self.number = number
        self.title = title
        self.height = self.PASEK + self.ODSTEP
        self.width = CONTENT_W

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        d = self.ODSTEP  # rysujemy nad zarezerwowanym światłem
        c.setFillColor(PRIMARY)
        c.roundRect(0, d + 0.5 * mm, 1.4 * mm, self.PASEK - 1 * mm, 0.6 * mm, stroke=0, fill=1)
        c.setFont(BOLD, 11)
        c.setFillColor(PRIMARY)
        c.drawString(5 * mm, d + 1.8 * mm, self.number)
        c.setFont(BOLD, 13)
        c.setFillColor(INK)
        c.drawString(5 * mm + c.stringWidth(self.number, BOLD, 11) + 3 * mm, d + 1.6 * mm, self.title)


class HBarChart(Flowable):
    """Poziomy wykres słupkowy (hand-drawn) - etykieta po lewej, zaokrąglony słupek, wartość na końcu."""

    def __init__(self, items, value_key, label_key, color_fn, fmt_fn, unit="", dot_fn=None,
                 label_w=42, bar_w=95, row_h=8):
        super().__init__()
        self.items = items
        self.value_key = value_key
        self.label_key = label_key
        self.color_fn = color_fn
        self.fmt_fn = fmt_fn
        self.unit = unit
        self.dot_fn = dot_fn
        self.label_w = label_w
        self.bar_w = bar_w
        self.row_h = row_h
        self.width = CONTENT_W
        self.height = (len(items) * row_h + 3) * mm

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        maxv = max((float(it[self.value_key] or 0) for it in self.items), default=0) or 1
        bar_x = self.label_w * mm
        top = self.height - 2 * mm
        for i, it in enumerate(self.items):
            y = top - (i + 1) * self.row_h * mm + 1.5 * mm
            v = float(it[self.value_key] or 0)
            frac = max(0.0, v / maxv)
            # etykieta
            c.setFont(BODY, 8.5)
            c.setFillColor(INK)
            lab = str(it[self.label_key])
            c.drawRightString(bar_x - 3 * mm, y + 0.6 * mm, _truncate(c, lab, BODY, 8.5, (self.label_w - 4) * mm))
            # tor
            c.setFillColor(TINT)
            c.roundRect(bar_x, y, self.bar_w * mm, 4.6 * mm, 1.2 * mm, stroke=0, fill=1)
            # słupek
            w = max(0.6, frac * self.bar_w)
            c.setFillColor(self.color_fn(it))
            c.roundRect(bar_x, y, w * mm, 4.6 * mm, 1.2 * mm, stroke=0, fill=1)
            # wartość
            c.setFont(BOLD, 8)
            c.setFillColor(INK)
            vx = bar_x + w * mm + 2 * mm
            txt = self.fmt_fn(v) + (self.unit if self.unit else "")
            if self.dot_fn:
                dot = self.dot_fn(it)
                if dot is not None:
                    c.setFillColor(dot)
                    c.circle(vx + 1.4 * mm, y + 2.3 * mm, 1.1 * mm, stroke=0, fill=1)
                    vx += 4 * mm
                c.setFillColor(INK)
            c.drawString(vx, y + 0.6 * mm, txt)


def _truncate(c, s, font, size, max_w):
    if c.stringWidth(s, font, size) <= max_w:
        return s
    while s and c.stringWidth(s + "…", font, size) > max_w:
        s = s[:-1]
    return s + "…"


# =========================================================================
#  Główna funkcja
# =========================================================================
def build_report_pdf(db: DBSession, date_from: date, date_to: date) -> bytes:
    S = _styles()
    company = settings.company_name or "Twoja Firma"
    period = period_label(date_from, date_to)
    generated = datetime.now().strftime("%d.%m.%Y")

    kpi = dashboard_kpi(db, date_from, date_to)
    channels = channel_summary(db, date_from, date_to)
    fn = funnel(db, date_from, date_to, "all")
    formats = ad_format_ranking(db, date_from, date_to)[:8]
    organic = organic_engagement(db, date_from, date_to)
    weekly = list_summaries(db, 1)
    products = db.execute(
        text(
            """SELECT product_name, round(sum(line_net),2) rev, sum(quantity) qty
               FROM analytics.v_product_sales
               WHERE status IN ('potwierdzone','zrealizowane') AND order_date BETWEEN :df AND :dt
               GROUP BY product_name ORDER BY rev DESC LIMIT 6"""
        ),
        {"df": date_from, "dt": date_to},
    ).mappings().all()
    seg = db.execute(
        text(
            """SELECT CASE WHEN company_id IS NOT NULL THEN 'B2B' ELSE 'B2C' END seg,
                      count(*) orders, round(sum(total_net),2) revenue
               FROM analytics.v_orders_all
               WHERE status IN ('potwierdzone','zrealizowane') AND order_date BETWEEN :df AND :dt
               GROUP BY 1 ORDER BY 1"""
        ),
        {"df": date_from, "dt": date_to},
    ).mappings().all()

    story: list = [NextPageTemplate("later")]

    # ---- helper: komórka KPI ----
    def kpi_cell(label, num, suffix="", hero=False, sub=None, bar_frac=None):
        size = 22 if hero else 17
        parts = [Paragraph(label.upper(), S["label"])]
        val = f'<font name="{BOLD}" size="{size}" color="#18181B">{num}</font>'
        if suffix:
            val += f' <font name="{BODY}" size="{max(8, size - 9)}" color="#64646E">{suffix}</font>'
        parts.append(Paragraph(val, ParagraphStyle("v", fontName=BOLD, fontSize=size, leading=size + 3, spaceBefore=2)))
        if sub:
            parts.append(Paragraph(
                sub, ParagraphStyle("s", fontName=BODY, fontSize=8.5, textColor=MUTED, leading=11, spaceBefore=1)))
        if bar_frac is not None:
            parts.append(Spacer(1, 1.5 * mm))
            parts.append(bar_cell(bar_frac, 48, 2, PRIMARY))
        return parts

    # ================= 01 · KPI =================
    margin_pct = kpi.get("margin_pct")
    gm = kpi.get("gross_margin_net")
    lead = kpi.get("avg_lead_time_days")
    margin_sub = f"{money_num(gm)} zł" if gm is not None else "brak kosztów produktów"
    hero = [
        kpi_cell("Przychód netto", money_num(kpi["revenue_net"]), "zł", hero=True),
        kpi_cell("Marża brutto",
                 pct_num(margin_pct) if margin_pct is not None else "-",
                 "%" if margin_pct is not None else "",
                 hero=True, sub=margin_sub,
                 bar_frac=(float(margin_pct) / 100 if margin_pct is not None else None)),
        kpi_cell("ROAS", roas_num(kpi["roas"]), "×" if kpi["roas"] is not None else "", hero=True),
    ]
    r2 = [
        kpi_cell("Liczba zamówień", int_num(kpi["orders_count"])),
        kpi_cell("Śr. wartość zam.", money_num(kpi["avg_order_value_net"]), "zł"),
        kpi_cell("Wydatki reklamowe", money_num(kpi.get("ad_spend")), "zł"),
    ]
    r3 = [
        kpi_cell("CAC", money_num(kpi["cac"]), "zł"),
        kpi_cell("LTV śr. (B2B)", money_num(kpi["avg_ltv_net"]), "zł"),
        kpi_cell("Czas kontakt→sprzedaż", days_num(lead), "dni" if lead is not None else ""),
    ]
    kpi_grid = Table([hero, r2, r3], colWidths=[CONTENT_W / 3] * 3)
    kpi_grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
    ]))
    # Numery sekcji liczone w locie. Wpisane na sztywno gubily ciaglosc: sekcje sa
    # warunkowe, wiec przy braku danych organicznych raport skakal z "06" na "08"
    # i czytelnik szukal brakujacej sekcji siodmej.
    _licznik = [0]

    def nr() -> str:
        _licznik[0] += 1
        return f"{_licznik[0]:02d}"

    story += [SectionHeader(nr(), "Kluczowe wskaźniki"), kpi_grid]

    # ================= 02 · Segmentacja =================
    if seg:
        seg_map = {s["seg"]: s for s in seg}
        b2b = seg_map.get("B2B")
        b2c = seg_map.get("B2C")
        tot_rev = sum(float(s["revenue"] or 0) for s in seg) or 1
        cells, widths, bg = [], [], []
        for key, col in (("B2B", PRIMARY), ("B2C", B2C_TINT)):
            s = seg_map.get(key)
            if not s:
                continue
            rev = float(s["revenue"] or 0)
            share = rev / tot_rev
            widths.append(max(0.06, share) * CONTENT_W)
            inside = f"{key} {share * 100:.0f}%" if share >= 0.12 else ""
            cells.append(Paragraph(f'<font color="white" size="8"><b>{inside}</b></font>', S["cell"]))
            bg.append(col)
        if cells:
            bar = Table([cells], colWidths=widths, rowHeights=[9 * mm])
            bst = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                   ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                   ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]
            for i, col in enumerate(bg):
                bst.append(("BACKGROUND", (i, 0), (i, 0), col))
            bar.setStyle(TableStyle(bst))

            def _seg_line(key, s):
                if not s:
                    return "-"
                return (f'{int_num(s["orders"])} zam.  ·  {money_num(s["revenue"])} zł netto')
            b2b_txt = f'<font color="#4F46E5"><b>■</b></font> <b>B2B (firmy)</b> - {_seg_line("B2B", b2b)}'
            b2c_txt = f'<font color="#A5B4FC"><b>■</b></font> <b>B2C (osoby)</b> - {_seg_line("B2C", b2c)}'
            legend = Table(
                [[Paragraph(b2b_txt, S["small"]), Paragraph(b2c_txt, S["small"])]],
                colWidths=[CONTENT_W / 2, CONTENT_W / 2],
            )
            legend.setStyle(TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story += [Spacer(1, 7 * mm),
                      KeepTogether([SectionHeader(nr(), "Segmentacja B2B / B2C"), bar, legend])]

    # ================= 03 · Lejek =================
    stages = [("Wyświetlenia", fn["impressions"]), ("Kliknięcia", fn["clicks"]),
              ("Sesje", fn["sessions"]), ("Zamówienia", fn["orders"])]
    maxv = max((v for _, v in stages), default=0) or 1
    frows = []
    for i, (name, v) in enumerate(stages):
        frows.append([
            Paragraph(name, S["cell"]),
            bar_cell(v / maxv, 106, 7, FUNNEL_SHADES[i]),
            _p(int_num(v), 9.5, INK, bold=True, align=2),
        ])
    funnel_bars = Table(frows, colWidths=[30 * mm, 110 * mm, 30 * mm])
    funnel_bars.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    def _metric_strip(pairs):
        row = []
        for k, v in pairs:
            row.append([
                _p(k.upper(), 6.8, MUTED, align=1, leading=8.5),
                _p(v, 9, INK, bold=True, align=1, leading=12),
            ])
        n = len(pairs)
        t = Table([row], colWidths=[CONTENT_W / n] * n)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("LINEABOVE", (0, 0), (-1, 0), 0.5, LINE),
            ("LINEAFTER", (0, 0), (-2, -1), 0.4, LINE),
        ]))
        return t

    metrics = _metric_strip([
        ("CTR", ratio_pct(fn["ctr"])),
        ("Sesja→zam.", ratio_pct(fn["cr_session_order"])),
        ("CPC", (money_num(fn["cpc"]) + " zł") if fn["cpc"] else "-"),
        ("CPO", (money_num(fn["cpo"]) + " zł") if fn["cpo"] else "-"),
        ("ROAS płatne", (roas_num(fn["roas"]) + "×") if fn["roas"] is not None else "-"),
        ("Wydatki", money_num(fn["spend"]) + " zł"),
    ])
    story += [Spacer(1, 7 * mm),
              KeepTogether([SectionHeader(nr(), "Lejek konwersji"),
                            funnel_bars, Spacer(1, 2 * mm), metrics])]

    # ================= 04 · Kanały =================
    if channels:
        chart_items = [{"label": channel_label(c), "rev": c["revenue_net"],
                        "code": c["channel_code"], "roas": c["roas"]} for c in channels if c["revenue_net"]]
        naglowek = SectionHeader(nr(), "Kanały pozyskania")
        blocks = [naglowek]
        if chart_items:
            def _roas_dot(it):
                r = it.get("roas")
                if r is None:
                    return None
                return OK if r >= 3 else (DANGER if r < 1 else OFFLINE)
            # Nagłówek + podpis + wykres + legenda jako JEDEN blok (jak sekcje 02 i 03).
            # Sam `keepWithNext` przyklejał nagłówek tylko do podpisu, a wykres i tak
            # przechodził na następną stronę - zostawał pusty tytuł na dole strony.
            blocks = [
                KeepTogether([
                    naglowek,
                    Paragraph("Przychód netto wg kanału", S["small"]),
                    Spacer(1, 1.5 * mm),
                    HBarChart(chart_items, "rev", "label",
                              color_fn=lambda it: channel_color(it["code"]),
                              fmt_fn=lambda v: money_num(v) + " zł",
                              dot_fn=_roas_dot),
                    Spacer(1, 1 * mm),
                    Paragraph('Kropka przy wartości = próg ROAS: '
                              '<font color="#16A34A">●</font> ≥3 · '
                              '<font color="#64748B">●</font> 1-3 · '
                              '<font color="#DC2626">●</font> &lt;1', S["small"]),
                ]),
                Spacer(1, 3 * mm),
            ]
        # tabela
        head = ["Kanał", "Wydatki", "Sesje", "Zam.", "Przychód netto", "ROAS"]
        rows = []
        for c in channels:
            dot = "#" + channel_color(c["channel_code"]).hexval()[2:]
            rows.append([
                Paragraph(f'<font color="{dot}">●</font>&nbsp; {esc(channel_label(c))}', S["cell"]),
                money_num(c["spend"]) + " zł", int_num(c["sessions"]), int_num(c["orders"]),
                money_num(c["revenue_net"]) + " zł", (roas_num(c["roas"]) + "×" if c["roas"] is not None else "-"),
            ])
        blocks.append(_data_table(head, rows, [0, 1, 1, 1, 1, 1],
                                  col_w=[48 * mm, 24 * mm, 22 * mm, 18 * mm, 30 * mm, 28 * mm], S=S))
        story += [Spacer(1, 7 * mm)] + blocks

    # ================= 05 · Formaty =================
    if formats:
        maxeng = max((f["engagement"] for f in formats), default=0) or 1
        head = ["Platforma", "Format", "Typ", "CTR", "Zaangażowanie"]
        rows = []
        for f in formats:
            eng = f["engagement"]
            eng_cell = [bar_cell(eng / maxeng, 22, 3.2, ORGANIC), Spacer(1, 0.6 * mm),
                        _p(int_num(eng), 8, INK, bold=True)] if eng else Paragraph("-", S["cell"])
            # Źródłem prawdy jest kolumna `kind` z analytics.v_ad_format_stats ('platny'/'organiczny')
            # - tak samo klasyfikuje panel. Lista platform to tylko fallback, gdy kind jest puste.
            plat = str(f["platform"]).lower()
            kind = str(f.get("kind", "")).strip().lower()
            is_paid = kind == "platny" if kind else plat in ("meta_ads", "google_ads")
            rows.append([
                humanize(f["platform"]), humanize(f["format"]),
                "Płatny" if is_paid else "Organiczny",
                ratio_pct(f["ctr"]) if f["ctr"] else "-",
                eng_cell,
            ])
        story += [Spacer(1, 7 * mm), SectionHeader(nr(), "Ranking formatów reklamowych"),
                  _data_table(head, rows, [0, 0, 0, 1, 0],
                              col_w=[38 * mm, 30 * mm, 26 * mm, 28 * mm, 48 * mm], S=S)]

    # ================= 06 · Produkty =================
    if products:
        maxrev = max((float(p["rev"] or 0) for p in products), default=0) or 1
        prows = []
        for p in products:
            rev = float(p["rev"] or 0)
            prows.append([
                Paragraph(esc(p["product_name"]), S["cell"]),
                bar_cell(rev / maxrev, 56, 6, PRIMARY),
                _p(f'<b>{money_num(rev)} zł</b> <font color="#64646E" size="8">· {qty_num(p["qty"])} szt.</font>',
                   9, INK, align=2),
            ])
        ptable = Table(prows, colWidths=[64 * mm, 58 * mm, 48 * mm])
        ptable.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ]))
        story += [Spacer(1, 7 * mm), SectionHeader(nr(), "Najlepsze produkty"), ptable]

    # ================= 07 · Organiczne (opcjonalnie) =================
    ot = organic.get("by_type") if organic else None
    if ot:
        maxeng = max((t["engagement"] for t in ot), default=0) or 1
        head = ["Typ posta", "Posty", "Wyświetlenia", "Zaangażowanie", "Wsk. zaang."]
        rows = []
        for t in ot:
            rows.append([
                humanize(t["post_type"]), int_num(t["posts"]), int_num(t["views"]),
                [bar_cell(t["engagement"] / maxeng, 24, 3.2, ORGANIC), Spacer(1, 0.6 * mm),
                 _p(int_num(t["engagement"]), 8, INK, bold=True)],
                ratio_pct(t["engagement_rate"]),
            ])
        story += [Spacer(1, 7 * mm), SectionHeader(nr(), "Zaangażowanie organiczne"),
                  _data_table(head, rows, [0, 1, 1, 0, 1],
                              col_w=[38 * mm, 22 * mm, 32 * mm, 44 * mm, 34 * mm], S=S)]

    # ================= 08 · Zestawienie tygodniowe =================
    if weekly:
        w = weekly[0]
        headline = str(w["headline"])
        # usuń zbędny prefiks ISO "Tydzień YYYY-MM-DD-YYYY-MM-DD:" (zakres pokazujemy w etykiecie)
        if headline.lower().startswith("tydzień") and ":" in headline:
            headline = headline.split(":", 1)[1].strip()
            headline = headline[:1].upper() + headline[1:]
        headline = polonize_decimals(humanize_text(headline))
        wk_range = fmt_week(w["week_start"], w["week_end"])
        inner = [
            Paragraph(f'<font name="{BOLD}" size="7.5" color="#4F46E5">PODSUMOWANIE TYGODNIA</font>'
                      f'&nbsp;&nbsp;<font size="8" color="#64646E">{wk_range}</font>', S["small"]),
            Spacer(1, 1.5 * mm),
            Paragraph(esc(headline), S["wk_head"]),
            Spacer(1, 2 * mm),
        ]
        for ln in str(w["body"]).split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            bullet = f'<font color="#4F46E5">■</font>&nbsp; {esc(polonize_decimals(humanize_text(ln)))}'
            inner.append(Paragraph(bullet, S["wk_body"]))
        callout = Table([["", inner]], colWidths=[3 * mm, CONTENT_W - 3 * mm])
        callout.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), PRIMARY),
            ("BACKGROUND", (1, 0), (1, 0), BG2),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (1, 0), (1, 0), 7), ("RIGHTPADDING", (1, 0), (1, 0), 7),
            ("TOPPADDING", (1, 0), (1, 0), 6), ("BOTTOMPADDING", (1, 0), (1, 0), 6),
            ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0),
            ("ROUNDEDCORNERS", [3, 3, 3, 3]),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ]))
        story += [Spacer(1, 7 * mm), SectionHeader(nr(), "Zestawienie tygodniowe"), callout]

    # ---- chrome ----
    def _footer(canvas: Canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(20 * mm, 14 * mm, 190 * mm, 14 * mm)
        canvas.setFont(BODY, 7.5)
        canvas.setFillColor(SUBTLE)
        canvas.drawString(20 * mm, 10 * mm, f"{company} · Raport poufny")
        # Numer strony ('Strona X / Y') dorysowuje NumberedCanvas w fazie save() - total znany.
        canvas.restoreState()

    def _cover(canvas: Canvas, doc):
        canvas.saveState()
        H = A4[1]
        # górna linia akcentu
        canvas.setStrokeColor(PRIMARY)
        canvas.setLineWidth(1.2)
        canvas.line(20 * mm, H - 12 * mm, 190 * mm, H - 12 * mm)
        # logo-mark
        canvas.setFillColor(PRIMARY)
        canvas.roundRect(20 * mm, H - 26 * mm, 9 * mm, 9 * mm, 1.5 * mm, stroke=0, fill=1)
        canvas.setFillColor(WHITE)
        canvas.setFont(BOLD, 13)
        initial = next((ch for ch in company if ch.isalnum()), "F").upper()
        canvas.drawCentredString(24.5 * mm, H - 23.4 * mm, initial)
        # nazwa firmy + podpis
        canvas.setFillColor(INK)
        canvas.setFont(BOLD, 9.5)
        canvas.drawString(32 * mm, H - 20 * mm, company)
        canvas.setFillColor(MUTED)
        canvas.setFont(BODY, 8)
        canvas.drawString(32 * mm, H - 24 * mm, "Raport analityczno-sprzedażowy")
        # tytuł
        canvas.setFillColor(INK)
        canvas.setFont(BOLD, 24)
        canvas.drawString(20 * mm, H - 46 * mm, "Raport sprzedaży i marketingu")
        # podtytuł
        canvas.setFillColor(MUTED)
        canvas.setFont(BODY, 10.5)
        canvas.drawString(20 * mm, H - 53 * mm, f"Okres: {period}")
        canvas.setFillColor(SUBTLE)
        canvas.setFont(BODY, 9)
        canvas.drawRightString(190 * mm, H - 53 * mm, f"Wygenerowano {generated}")
        # linia zamykająca
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(20 * mm, H - 58 * mm, 190 * mm, H - 58 * mm)
        canvas.restoreState()
        _footer(canvas, doc)

    def _running(canvas: Canvas, doc):
        canvas.saveState()
        H = A4[1]
        canvas.setFont(BODY, 7.5)
        canvas.setFillColor(SUBTLE)
        canvas.drawString(20 * mm, H - 14 * mm, company)
        canvas.drawRightString(190 * mm, H - 14 * mm, f"Raport sprzedaży · {period}")
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(20 * mm, H - 17 * mm, 190 * mm, H - 17 * mm)
        canvas.restoreState()
        _footer(canvas, doc)

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                          topMargin=20 * mm, bottomMargin=18 * mm, title="Raport sprzedaży i marketingu")
    cover_frame = Frame(20 * mm, 18 * mm, CONTENT_W, A4[1] - 62 * mm - 18 * mm, id="cover")
    later_frame = Frame(20 * mm, 18 * mm, CONTENT_W, A4[1] - 22 * mm - 18 * mm, id="later")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=_cover),
        PageTemplate(id="later", frames=[later_frame], onPage=_running),
    ])
    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def _data_table(headers, rows, aligns, col_w, S):
    """Wspólny styl tabeli: lekki tint nagłówka, tylko poziome hairline, bez pionów."""
    head = [Paragraph(esc(h).upper(), S["cellhead"]) for h in headers]
    body = []
    for r in rows:
        cells = []
        for c in r:
            if isinstance(c, (list, tuple)) or hasattr(c, "wrap"):
                cells.append(c)
            else:
                # Tekst z bazy (nazwy kanalow, formatow, typow postow) - escapowany,
                # bo Paragraph parsuje zawartosc jak XML.
                cells.append(Paragraph(esc(c), S["cell"]))
        body.append(cells)
    t = Table([head] + body, colWidths=col_w, repeatRows=1, hAlign="LEFT")
    st = [
        ("BACKGROUND", (0, 0), (-1, 0), TINT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if len(body) >= 6:
        st.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BG2]))
    for i, a in enumerate(aligns):
        st.append(("ALIGN", (i, 0), (i, -1), "RIGHT" if a == 1 else "LEFT"))
    t.setStyle(TableStyle(st))
    return t


class NumberedCanvas(Canvas):
    """Dwufazowy zapis, by dorysować w stopce 'Strona X / Y' (total znany dopiero na końcu)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for i, state in enumerate(self._saved, start=1):
            self.__dict__.update(state)
            self.setFont(BODY, 7.5)
            self.setFillColor(SUBTLE)
            self.drawRightString(190 * mm, 10 * mm, f"Strona {i} / {total}")
            super().showPage()
        super().save()
