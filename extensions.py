#!/usr/bin/env python3
"""extensions.py – gemeinsame Flask-Erweiterungsinstanzen (SQLAlchemy, Login).

Eigenes Modul statt direkt in webapp.py/models.py, damit models.py `db`
importieren kann, ohne einen Zirkelimport mit webapp.py zu erzeugen
(Standard-Flask-Pattern für "App-Factory"-nahe Strukturen).
"""
from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

login_manager = LoginManager()
# Kein serverseitig gerendertes Login-Formular (das Frontend ist eine SPA-
# artige Single-Page-App) - unautorisierte Zugriffe auf @login_required-
# Endpunkte liefern deshalb einfach 401 statt eines Redirects auf eine
# Login-Seite (siehe webapp._unauthorized()).
login_manager.login_view = None

# Hier (statt direkt in webapp.py) angelegt, damit auth.py `@limiter.limit(...)`
# auf seine eigenen Routen anwenden kann, ohne webapp.py zu importieren (Zirkel-
# import: webapp.py importiert bereits `auth.bp`). App-Factory-Pattern: ohne
# `app=` konstruiert, `init_app(app)` passiert in webapp.py (siehe dort für
# `storage_uri`/Redis-Anbindung).
limiter = Limiter(
    key_func=lambda: str(current_user.get_id()) if current_user.is_authenticated else get_remote_address(),
)
