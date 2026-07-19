# Shiori – Web-Frontend + Generator
FROM python:3.12-slim

# WeasyPrint braucht die nativen Bibliotheken Pango/Cairo/GDK-PixBuf.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        fonts-dejavu-core \
        fontconfig \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WKCARDS_DATA=/data \
    WKCARDS_CACHE_DIR=/data/.cache \
    PORT=8000

WORKDIR /app

# Abhängigkeiten zuerst (bessere Layer-Caches)
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

# App-Code (inkl. gebündelter Noto-JP-Schriften unter fonts/ und WanaKana-JS unter vendor/)
COPY kanji_cards.py anki_export.py webapp.py dictionary.py sample_data.json ./
COPY templates/ ./templates/
COPY fonts/ ./fonts/
COPY vendor/ ./vendor/
COPY web/ ./web/

# Datenverzeichnis (Volume): settings.json, output/, jobs/, .cache/
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# 2 Worker; großzügiger Timeout, da Exporte API-Aufrufe + Bild-Downloads machen.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "--timeout", "600", "webapp:app"]
