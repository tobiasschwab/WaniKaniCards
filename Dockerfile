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

# App-Code: das gesamte `shiori`-Package in einem Rutsch (statt einzelner
# Dateinamen) - eliminiert strukturell den früheren Bug, ein neues Modul in
# der COPY-Zeile zu vergessen (siehe tests/test_packaging.py). Nicht-Python-
# Assets (gebündelte Noto-JP-Schriften unter fonts/, WanaKana-JS unter
# vendor/) bleiben bewusst außerhalb des Packages, siehe shiori/webapp.py
# REPO_ROOT-Kommentar.
COPY shiori/ ./shiori/
COPY templates/ ./templates/
COPY fonts/ ./fonts/
COPY vendor/ ./vendor/
COPY web/ ./web/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY docker-entrypoint.sh ./
# CR-Zeichen (Windows/CRLF-Zeilenenden) entfernen, BEVOR das Skript ausführbar
# gemacht wird: checkt jemand das Repo auf Windows aus (git core.autocrlf=true)
# und der Docker-Build-Kontext kommt von diesem Checkout (z. B. über eine
# Netzwerkfreigabe zu einem NAS), landet in der Shebang-Zeile "#!/bin/sh\r" -
# der Kernel sucht dann einen Interpreter namens "/bin/sh\r", findet ihn nicht
# und meldet irreführend "exec ./docker-entrypoint.sh: no such file or
# directory", obwohl die Datei existiert. sed macht das unabhängig von den
# Host-Zeilenenden robust (siehe auch .gitattributes, die das beim Checkout
# von vornherein verhindert).
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

# Datenverzeichnis (Volume): settings.json, output/, jobs/, .cache/ (Phase 1:
# Accounts/Auth liegen in Postgres, siehe DATABASE_URL – Nutzdaten folgen erst
# in Phase 2, siehe README "Multi-User-Architektur")
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
# 2 Worker; großzügiger Timeout, da Exporte API-Aufrufe + Bild-Downloads machen.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "--timeout", "600", "shiori.webapp:app"]
