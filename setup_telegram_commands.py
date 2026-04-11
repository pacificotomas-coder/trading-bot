#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registra los comandos del bot en Telegram vía API.
Ejecutar una sola vez (o cada vez que se agreguen comandos nuevos).

Uso:
    python setup_telegram_commands.py
"""

import os
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

COMMANDS = [
    {"command": "start",     "description": "Mostrar ayuda y estado del bot"},
    {"command": "diario",    "description": "Correr análisis diario ahora"},
    {"command": "semanal",   "description": "Correr análisis semanal ahora"},
    {"command": "estado",    "description": "Ver posiciones abiertas (bot_state)"},
    {"command": "cartera",   "description": "Ver portafolio completo con P&L"},
    {"command": "depositar", "description": "Cargar fondos — uso: /depositar 100000"},
]


def main():
    if not TOKEN:
        print("ERROR: Variable de entorno TELEGRAM_BOT_TOKEN no configurada.")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/setMyCommands"
    r   = requests.post(url, json={"commands": COMMANDS}, timeout=10)

    if r.status_code == 200 and r.json().get("ok"):
        print("Comandos registrados exitosamente en Telegram:")
        for cmd in COMMANDS:
            print(f"  /{cmd['command']:<12} — {cmd['description']}")
    else:
        print(f"Error al registrar comandos: {r.status_code}")
        print(r.text)


if __name__ == "__main__":
    main()
