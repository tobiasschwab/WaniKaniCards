#!/usr/bin/env python3
"""extensions.py – gemeinsame Flask-Erweiterungsinstanzen (SQLAlchemy, Login).

Eigenes Modul statt direkt in webapp.py/models.py, damit models.py `db`
importieren kann, ohne einen Zirkelimport mit webapp.py zu erzeugen
(Standard-Flask-Pattern für "App-Factory"-nahe Strukturen).
"""
from __future__ import annotations

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

login_manager = LoginManager()
# Kein serverseitig gerendertes Login-Formular (das Frontend ist eine SPA-
# artige Single-Page-App) - unautorisierte Zugriffe auf @login_required-
# Endpunkte liefern deshalb einfach 401 statt eines Redirects auf eine
# Login-Seite (siehe webapp._unauthorized()).
login_manager.login_view = None
