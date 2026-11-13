"""Compatibilidad: `python -m app.changes.cli` ejecuta una pasada del worker de cambios.

El punto de entrada vigente es `python -m app.agents.cli` (admite --loop y reconcile).
"""
from app.agents.cli import main

if __name__ == '__main__':
    main([])
