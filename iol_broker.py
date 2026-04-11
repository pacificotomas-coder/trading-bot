#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IOL (InvertirOnline) Broker — Cliente API
==========================================
Gestiona autenticación y ejecución de órdenes en BYMA vía la API de IOL.

Variables de entorno requeridas:
  IOL_USER  →  usuario de InvertirOnline (email o DNI)
  IOL_PASS  →  contraseña de InvertirOnline

Notas:
  - Cripto NO es soportado por IOL → esas posiciones quedan como virtuales.
  - Las órdenes se colocan como límite con un pequeño buffer para asegurar el fill.
  - Si el mercado está cerrado, IOL las procesa al próximo inicio de rueda.
"""

import os
import json
import requests
from datetime import datetime

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, "iol_token.json")

IOL_BASE = "https://api.invertironline.com"
IOL_USER = os.getenv("IOL_USER", "")
IOL_PASS = os.getenv("IOL_PASS", "")

# ── Mapping tickers Yahoo Finance → (símbolo IOL, mercado) ──────────────────────
# Mercado: "bCBA" = BYMA Buenos Aires
TICKER_MAP = {
    # Acciones Argentina
    "GGAL.BA":  ("GGAL",  "bCBA"),
    "YPFD.BA":  ("YPFD",  "bCBA"),
    "PAMP.BA":  ("PAMP",  "bCBA"),
    "BMA.BA":   ("BMA",   "bCBA"),
    "CEPU.BA":  ("CEPU",  "bCBA"),
    "LOMA.BA":  ("LOMA",  "bCBA"),
    "BBVA.BA":  ("BBAR",  "bCBA"),   # BBVA Argentina cotiza como BBAR en BYMA
    "SUPV.BA":  ("SUPV",  "bCBA"),
    "ALUA.BA":  ("ALUA",  "bCBA"),
    "COME.BA":  ("COME",  "bCBA"),
    "TRAN.BA":  ("TRAN",  "bCBA"),
    "BYMA.BA":  ("BYMA",  "bCBA"),
    "METR.BA":  ("METR",  "bCBA"),
    "ECOG.BA":  ("ECOG",  "bCBA"),
    "EDN.BA":   ("EDN",   "bCBA"),
    "TGNO4.BA": ("TGNO4", "bCBA"),
    # CEDEARs
    "NU.BA":    ("NU",    "bCBA"),
    "AAPL.BA":  ("AAPL",  "bCBA"),
    "MSFT.BA":  ("MSFT",  "bCBA"),
    "AMZN.BA":  ("AMZN",  "bCBA"),
    "GOOGL.BA": ("GOOGL", "bCBA"),
    "META.BA":  ("META",  "bCBA"),
    "NVDA.BA":  ("NVDA",  "bCBA"),
    "TSLA.BA":  ("TSLA",  "bCBA"),
    "MELI.BA":  ("MELI",  "bCBA"),
    "KO.BA":    ("KO",    "bCBA"),
}

# Tickers que NO tienen ejecución real (sólo seguimiento virtual)
VIRTUAL_ONLY = {"Crypto", "Acciones USA"}


# ── Autenticación ───────────────────────────────────────────────────────────────

def _load_token():
    try:
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_token(data):
    try:
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _login():
    """Login completo con usuario y contraseña."""
    if not IOL_USER or not IOL_PASS:
        raise ValueError(
            "Faltan credenciales IOL.\n"
            "Configurar las variables de entorno IOL_USER e IOL_PASS."
        )
    r = requests.post(
        f"{IOL_BASE}/token",
        data={
            "username":   IOL_USER,
            "password":   IOL_PASS,
            "grant_type": "password",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    data["saved_at"] = datetime.now().isoformat()
    _save_token(data)
    return data["access_token"]


def _refresh(refresh_token: str):
    """Renueva el access_token sin necesidad de usuario/contraseña."""
    r = requests.post(
        f"{IOL_BASE}/token",
        data={
            "refresh_token": refresh_token,
            "grant_type":    "refresh_token",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if r.status_code != 200:
        return None
    data = r.json()
    data["saved_at"] = datetime.now().isoformat()
    _save_token(data)
    return data["access_token"]


def _get_token():
    """Devuelve un token válido, renovando o logueando si es necesario."""
    cached = _load_token()
    if cached.get("refresh_token"):
        token = _refresh(cached["refresh_token"])
        if token:
            return token
    return _login()


def _headers():
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type":  "application/json",
    }


# ── Órdenes ─────────────────────────────────────────────────────────────────────

def place_buy_order(ticker_yf: str, category: str, cantidad: float, precio_ref: float) -> str:
    """
    Coloca orden de COMPRA en IOL.

    ticker_yf   : ticker Yahoo Finance (ej: "GGAL.BA")
    category    : categoría del bot (ej: "Acciones Argentina", "CEDEARs", "Crypto")
    cantidad    : unidades calculadas por el portafolio
    precio_ref  : precio de referencia (cierre de ayer desde yfinance)

    Retorna string con el resultado para loggear / enviar por Telegram.
    """
    if category in VIRTUAL_ONLY:
        return f"  ℹ {ticker_yf}: operación virtual (no ejecutada en IOL)"

    if ticker_yf not in TICKER_MAP:
        return f"  ⚠ IOL: {ticker_yf} no mapeado — registrá manualmente en IOL."

    simbolo, mercado = TICKER_MAP[ticker_yf]
    cantidad_int     = int(cantidad)

    if cantidad_int < 1:
        return f"  ⚠ IOL: cantidad calculada < 1 para {ticker_yf} — capital insuficiente."

    # Límite ligeramente por encima del precio de referencia para asegurar fill
    precio_limite = round(precio_ref * 1.005, 2)

    body = {
        "mercado":  mercado,
        "simbolo":  simbolo,
        "cantidad": cantidad_int,
        "precio":   precio_limite,
        "plazo":    "t2",
        "validez":  "hoy",
    }

    try:
        r = requests.post(
            f"{IOL_BASE}/api/v2/operar/Comprar",
            json=body,
            headers=_headers(),
            timeout=15,
        )
        if r.status_code in (200, 201):
            return (
                f"  ✅ IOL COMPRA ejecutada: {simbolo} x{cantidad_int} "
                f"@ ${precio_limite:,.2f} ARS (t2)"
            )
        else:
            return f"  ⚠ IOL error {r.status_code} en COMPRA {simbolo}: {r.text[:150]}"
    except Exception as e:
        return f"  ✗ IOL excepción en COMPRA {simbolo}: {e}"


def place_sell_order(ticker_yf: str, category: str, cantidad: float, precio_ref: float) -> str:
    """
    Coloca orden de VENTA en IOL (cierre de posición por stop loss).
    """
    if category in VIRTUAL_ONLY:
        return f"  ℹ {ticker_yf}: cierre virtual (no ejecutado en IOL)"

    if ticker_yf not in TICKER_MAP:
        return f"  ⚠ IOL: {ticker_yf} no mapeado — cerrá manualmente en IOL."

    simbolo, mercado = TICKER_MAP[ticker_yf]
    cantidad_int     = int(cantidad)

    if cantidad_int < 1:
        return f"  ⚠ IOL: cantidad < 1 para cierre de {ticker_yf}."

    # Límite ligeramente por debajo del precio de referencia para asegurar fill
    precio_limite = round(precio_ref * 0.995, 2)

    body = {
        "mercado":  mercado,
        "simbolo":  simbolo,
        "cantidad": cantidad_int,
        "precio":   precio_limite,
        "plazo":    "t2",
        "validez":  "hoy",
    }

    try:
        r = requests.post(
            f"{IOL_BASE}/api/v2/operar/Vender",
            json=body,
            headers=_headers(),
            timeout=15,
        )
        if r.status_code in (200, 201):
            return (
                f"  ✅ IOL VENTA ejecutada: {simbolo} x{cantidad_int} "
                f"@ ${precio_limite:,.2f} ARS (t2)"
            )
        else:
            return f"  ⚠ IOL error {r.status_code} en VENTA {simbolo}: {r.text[:150]}"
    except Exception as e:
        return f"  ✗ IOL excepción en VENTA {simbolo}: {e}"


# ── Consultas de cuenta ──────────────────────────────────────────────────────────

def get_posiciones_iol() -> set:
    """
    Devuelve el conjunto de símbolos IOL que el usuario tiene en cartera (ej: {"GGAL", "AAPL"}).
    Retorna None si la API no está disponible (fuera de horario).
    """
    try:
        r = requests.get(
            f"{IOL_BASE}/api/v2/portafolio/Argentina",
            headers=_headers(),
            timeout=15,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        # La API puede retornar mensaje de mantenimiento
        if "message" in data:
            return None
        activos = data.get("activos", [])
        return {a.get("simbolo", "").upper() for a in activos if a.get("cantidad", 0) > 0}
    except Exception:
        return None


def get_saldo_ars() -> float:
    """Devuelve el saldo disponible en la cuenta IOL como float en ARS. Retorna 0.0 si falla."""
    try:
        r = requests.get(
            f"{IOL_BASE}/api/v2/cuenta/estado",
            headers=_headers(),
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        saldo = data.get("cuentas", [{}])[0].get("montoDisponible", 0.0)
        return float(saldo) if isinstance(saldo, (int, float)) else 0.0
    except Exception:
        return 0.0


def get_saldo_disponible() -> str:
    """Consulta el saldo disponible en la cuenta IOL (ARS) como string para Telegram."""
    saldo = get_saldo_ars()
    if saldo > 0:
        return f"💵 Saldo IOL disponible: ${saldo:,.2f} ARS"
    return "⚠ No se pudo consultar saldo IOL"
