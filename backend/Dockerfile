FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Czcionka DejaVu pod raport PDF. `report_pdf._register_fonts()` szuka kolejno Ariala
# (Windows) i DejaVu (Linux), a gdy nie znajdzie żadnej - schodzi do wbudowanej Helvetiki,
# która NIE MA polskich znaków. Raport wtedy powstaje i wygląda poprawnie w logach
# (jest %PDF, jest rozmiar), tylko w treści brakuje ą, ć, ę, ł, ń, ó, ś, ź, ż. Obraz `slim`
# nie zawiera żadnych czcionek, więc bez tej warstwy produkcja dostaje raport z dziurami
# w słowach. `--no-install-recommends` trzyma koszt na ~2 MB.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Najpierw zależności (lepsze cache warstw)
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e .

# Kod aplikacji
COPY . .

# Katalog na dane (załączniki maili) i użytkownik bez uprawnień roota.
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown -R app:app /data /app
USER app

EXPOSE 8000

# Domyślne polecenie (docker-compose nadpisuje dla worker)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
