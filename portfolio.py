#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gestión de portafolio — Bull Market
=====================================
Rastrea capital disponible, posiciones abiertas y P&L en tiempo real.

Reglas:
  - Cada señal de COMPRA con BAJO RIESGO invierte el 30% del capital disponible.
  - No hay límite de posiciones simultáneas: opera mientras haya liquidez.
  - Las posiciones se cierran automáticamente cuando se toca el stop loss.
  - El capital recuperado (con ganancia o pérdida) vuelve al disponible.
"""

import os
import json
from datetime import datetime

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "portfolio_state.json")

# ── Configuración ──────────────────────────────────────────────────────────────

# Porcentaje del capital disponible a invertir por cada señal
PORCENTAJE_POR_OPERACION = 1.0   # 100% — invertir todo cuando hay señal

# Tipo de cambio ARS/USD para posiciones en cripto (actualizar según MEP del día)
DOLAR_ARS = 1200.0

# Categorías que se gestionan en este portafolio (las que opera Bull Market)
CATEGORIAS_BULL = {"Acciones Argentina", "CEDEARs", "Crypto"}


# ── Estado ──────────────────────────────────────────────────────────────────────

def _empty():
    return {
        "fondos_total_depositado": 0.0,
        "fondos_disponibles":      0.0,
        "posiciones":              {},
        "historial":               []
    }


def load():
    try:
        with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return _empty()


def save(p):
    try:
        with open(PORTFOLIO_FILE, 'w', encoding='utf-8') as f:
            json.dump(p, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"  ✗ Error guardando portafolio: {e}")


# ── Operaciones ─────────────────────────────────────────────────────────────────

def sincronizar_saldo() -> float:
    """
    Lee el saldo real de la cuenta IOL y actualiza fondos_disponibles.
    Descuenta las posiciones virtuales (Crypto) que no están en IOL.
    Si la API de IOL no está disponible (fuera de horario), conserva el último saldo conocido.
    Retorna el saldo disponible en ARS.
    """
    import iol_broker
    saldo_iol = iol_broker.get_saldo_ars()
    p = load()

    if saldo_iol > 0:
        # API disponible: actualizar con datos reales
        crypto_invertido = sum(
            pos["monto_invertido"]
            for pos in p["posiciones"].values()
            if pos.get("category") == "Crypto"
        )
        disponible_real = max(0.0, saldo_iol - crypto_invertido)
        p["fondos_disponibles"] = disponible_real
        p["fondos_total_depositado"] = saldo_iol
        p["saldo_iol_actualizado"] = datetime.now().strftime('%Y-%m-%d %H:%M')
        save(p)
        return disponible_real
    else:
        # API no disponible (fuera de horario): conservar último saldo conocido
        return p.get("fondos_disponibles", 0.0)


def depositar(monto_ars: float) -> str:
    """
    Ya no es necesario. Los fondos se depositan directamente en IOL
    y el bot los lee automáticamente al operar.
    Este comando solo muestra el saldo real actual.
    """
    import iol_broker
    saldo = iol_broker.get_saldo_ars()
    if saldo > 0:
        return (
            f"💡 Los fondos se gestionan directamente desde tu cuenta IOL.\n"
            f"   No necesitás usar este comando — el bot lee tu saldo real automáticamente.\n\n"
            f"💵 Saldo actual en IOL: ${saldo:,.2f} ARS"
        )
    return (
        "💡 Los fondos se gestionan directamente desde tu cuenta IOL.\n"
        "   Depositá dinero en tu cuenta IOL y el bot lo usará automáticamente."
    )


def open_position(ticker: str, category: str, price: float, stop: float, bot: str):
    """
    Abre una posición si hay fondos disponibles y no hay posición ya abierta.
    Retorna un mensaje de confirmación o None si no opera.
    """
    if category not in CATEGORIAS_BULL:
        return None

    p = load()

    if ticker in p["posiciones"]:
        return None  # ya hay posición abierta, no duplicar

    if p["fondos_disponibles"] <= 0:
        return "SIN_FONDOS"  # señal válida pero sin capital disponible

    monto_a_invertir = p["fondos_disponibles"] * PORCENTAJE_POR_OPERACION
    is_crypto        = (category == "Crypto")

    if is_crypto:
        monto_usd = monto_a_invertir / DOLAR_ARS
        cantidad  = monto_usd / price   # fraccionaria
        currency  = "USD"
    else:
        cantidad = int(monto_a_invertir / price)
        if cantidad < 1:
            # Precio demasiado alto para el monto disponible → no opera
            return None
        monto_a_invertir = cantidad * price  # ajustar al múltiplo real (sin fracción)
        monto_usd        = None
        currency         = "ARS"

    p["posiciones"][ticker] = {
        "direction":       "compra",
        "entry":           price,
        "cantidad":        cantidad,
        "monto_invertido": monto_a_invertir,
        "monto_usd":       monto_usd,
        "stop":            stop,
        "date":            datetime.now().strftime('%Y-%m-%d'),
        "bot":             bot,
        "currency":        currency,
        "category":        category,
    }
    p["fondos_disponibles"] -= monto_a_invertir
    save(p)

    if is_crypto:
        return (
            f"💼 POSICIÓN ABIERTA: {ticker}\n"
            f"   Invertido: ${monto_a_invertir:,.0f} ARS (~${monto_usd:.2f} USD)\n"
            f"   Cantidad: {cantidad:.6f} | Precio: ${price:.2f} USD\n"
            f"   Stop: ${stop:.2f} | Disponible: ${p['fondos_disponibles']:,.0f} ARS"
        )
    else:
        return (
            f"💼 POSICIÓN ABIERTA: {ticker}\n"
            f"   Invertido: ${monto_a_invertir:,.0f} ARS\n"
            f"   Cantidad: {int(cantidad)} unidades | Precio: ${price:,.2f} ARS\n"
            f"   Stop: ${stop:,.2f} | Disponible: ${p['fondos_disponibles']:,.0f} ARS"
        )


def close_position(ticker: str, price_exit: float, motivo: str = "stop"):
    """
    Cierra una posición y devuelve el capital (con ganancia o pérdida) al disponible.
    Retorna un mensaje de confirmación o None si no había posición.
    """
    p = load()
    if ticker not in p["posiciones"]:
        return None

    pos      = p["posiciones"].pop(ticker)
    entrada  = pos["entry"]
    cantidad = pos["cantidad"]
    currency = pos.get("currency", "ARS")
    monto_in = pos["monto_invertido"]

    if currency == "USD":
        resultado_usd = (price_exit - entrada) * cantidad
        resultado_ars = resultado_usd * DOLAR_ARS
        monto_salida  = monto_in + resultado_ars
    else:
        monto_salida = cantidad * price_exit

    pnl_pct = ((price_exit - entrada) / entrada) * 100

    p["fondos_disponibles"] += monto_salida
    p["historial"].append({
        "ticker":    ticker,
        "entry":     entrada,
        "exit":      price_exit,
        "pnl_pct":   round(pnl_pct, 2),
        "monto_in":  round(monto_in, 2),
        "monto_out": round(monto_salida, 2),
        "date_in":   pos["date"],
        "date_out":  datetime.now().strftime('%Y-%m-%d'),
        "motivo":    motivo,
    })
    save(p)

    emoji = "✅" if pnl_pct >= 0 else "🔴"
    return (
        f"{emoji} POSICIÓN CERRADA: {ticker}\n"
        f"   Entrada: {entrada:,.2f} → Salida: {price_exit:,.2f}  ({pnl_pct:+.1f}%)\n"
        f"   Disponible ahora: ${p['fondos_disponibles']:,.0f} ARS"
    )


def update_stop(ticker: str, nuevo_stop: float):
    """Actualiza el nivel de stop (trailing stop) de una posición abierta."""
    p = load()
    if ticker in p["posiciones"]:
        p["posiciones"][ticker]["stop"] = nuevo_stop
        save(p)


# ── Resumen para Telegram ────────────────────────────────────────────────────────

def get_cartera_msg(precios: dict) -> str:
    """
    Genera el mensaje de resumen del portafolio con P&L en tiempo real.

    precios: diccionario {ticker: precio_actual (float)}
    """
    p          = load()
    posiciones = p["posiciones"]
    disponible = p["fondos_disponibles"]

    actualizado = p.get("saldo_iol_actualizado", "—")

    if not posiciones and disponible == 0:
        return (
            "💼 <b>PORTAFOLIO</b>\n\n"
            "Sin posiciones abiertas y sin saldo sincronizado.\n\n"
            "El saldo se sincroniza automáticamente durante el horario de mercado (lun-vie 10:00-17:00).\n"
            f"Última sincronización: {actualizado}"
        )

    lines = [f"💼 <b>PORTAFOLIO IOL</b>  <i>(sync: {actualizado})</i>\n"]

    total_invertido = 0.0
    total_pnl_ars   = 0.0

    for ticker, pos in posiciones.items():
        entrada   = pos["entry"]
        cantidad  = pos["cantidad"]
        currency  = pos.get("currency", "ARS")
        monto_in  = pos["monto_invertido"]
        p_actual  = precios.get(ticker)

        if p_actual is not None:
            pnl_pct = ((p_actual - entrada) / entrada) * 100
            if currency == "USD":
                pnl_ars = (p_actual - entrada) * cantidad * DOLAR_ARS
            else:
                pnl_ars = (p_actual - entrada) * cantidad
            precio_str = f"{p_actual:,.2f}"
        else:
            pnl_pct    = 0.0
            pnl_ars    = 0.0
            precio_str = "N/D"

        total_invertido += monto_in
        total_pnl_ars   += pnl_ars

        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
        lines.append(
            f"📈 <b>{ticker}</b>  {pnl_emoji} <b>{pnl_pct:+.1f}%</b>\n"
            f"  Entrada: {entrada:,.2f} | Actual: {precio_str}\n"
            f"  Stop: {pos['stop']:,.2f} | Desde: {pos['date']}\n"
            f"  Invertido: ${monto_in:,.0f} ARS"
        )

    total_valor   = total_invertido + total_pnl_ars
    total_capital = disponible + total_valor

    lines.append(f"\n{'─'*28}")
    lines.append(f"💵 Disponible IOL:  ${disponible:,.0f} ARS")

    if total_invertido > 0:
        lines.append(f"📊 Invertido:       ${total_invertido:,.0f} ARS")
        pnl_total_pct = (total_pnl_ars / total_invertido) * 100
        lines.append(f"📈 P&L total:       ${total_pnl_ars:+,.0f} ARS  ({pnl_total_pct:+.1f}%)")
        lines.append(f"💰 Capital total:   ${total_capital:,.0f} ARS")

    return "\n".join(lines)
