#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Toto Trading Bot — Proceso principal
=====================================
Escucha comandos de Telegram y ejecuta el análisis automáticamente.

Comandos disponibles:
  /start   → Muestra ayuda
  /diario  → Corre el análisis diario ahora
  /semanal → Corre el análisis semanal ahora
  /estado  → Muestra las posiciones abiertas

Automático:
  - Lunes a viernes a las 18:30 (hora Argentina) → análisis diario
  - Domingos a las 20:00 (hora Argentina)        → análisis semanal
"""

import os
import json
import logging
import datetime
import pytz
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import yfinance as yf
import trading_bot
import trading_bot_semanal
import portfolio

# ========================== CONFIGURACIÓN ==========================

TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TZ_ARG  = pytz.timezone("America/Argentina/Buenos_Aires")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ========================== TECLADO PERSISTENTE ==========================

MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("📊 Estado"),  KeyboardButton("💼 Cartera")],
     [KeyboardButton("📈 Diario"), KeyboardButton("📅 Semanal")]],
    resize_keyboard=True,
    is_persistent=True
)

# ========================== COMANDOS ==========================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "🤖 <b>Toto Trading Bot activo</b>\n\n"
        "Usá los botones de abajo para controlar el bot.\n\n"
        "💼 <b>Portafolio:</b>\n"
        "/depositar 100000 → carga fondos en ARS\n"
        "/cartera → ver posiciones y P&L\n\n"
        "⏰ <b>Automático:</b>\n"
        "Lun–Vie 18:30 → análisis diario\n"
        "Domingo 20:00 → análisis semanal\n\n"
        "<i>El bot opera automáticamente al detectar señales con bajo riesgo.</i>\n"
        "<i>Hora Argentina (ART)</i>"
    )
    await update.message.reply_text(texto, parse_mode="HTML", reply_markup=MENU)


async def cmd_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los botones del teclado persistente."""
    texto = update.message.text
    if "Estado" in texto:
        await cmd_estado(update, context)
    elif "Cartera" in texto:
        await cmd_cartera(update, context)
    elif "Diario" in texto:
        await cmd_diario(update, context)
    elif "Semanal" in texto:
        await cmd_semanal(update, context)


async def cmd_diario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Corriendo análisis diario, esperá un momento...")
    try:
        trading_bot.run_check()
    except Exception as e:
        await update.message.reply_text(f"❌ Error en análisis diario: {e}")


async def cmd_semanal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Corriendo análisis semanal, esperá un momento...")
    try:
        trading_bot_semanal.run_check()
    except Exception as e:
        await update.message.reply_text(f"❌ Error en análisis semanal: {e}")


async def cmd_cartera(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el portafolio con P&L en tiempo real."""
    await update.message.reply_text("⏳ Consultando saldo IOL y precios actuales...")
    try:
        # Sincronizar saldo real de IOL antes de mostrar
        portfolio.sincronizar_saldo()

        p          = portfolio.load()
        posiciones = p.get("posiciones", {})

        # Obtener precio actual de cada posición abierta
        precios = {}
        for ticker in posiciones:
            try:
                data = yf.download(ticker, period="2d", progress=False, auto_adjust=True)
                if len(data) > 0:
                    precios[ticker] = float(data['Close'].squeeze().iloc[-1])
            except Exception:
                pass

        msg = portfolio.get_cartera_msg(precios)
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Error consultando cartera: {e}")


async def cmd_depositar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el saldo real de la cuenta IOL. Los depósitos se hacen directamente en IOL."""
    msg = portfolio.depositar(0)  # solo consulta, no modifica nada
    await update.message.reply_text(msg)


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra las posiciones abiertas de ambos bots."""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    def leer_estado(path, label):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            if not state:
                return f"<b>{label}:</b> Sin posiciones abiertas.\n"
            lineas = [f"<b>{label}:</b>"]
            for ticker, pos in state.items():
                direccion = "📈 COMPRA" if pos["direction"] == "compra" else "📉 VENTA"
                lineas.append(
                    f"  {direccion} <b>{ticker}</b>\n"
                    f"  Entrada: {pos['entry']:.2f}  |  Stop: {pos['stop']:.2f}  |  Desde: {pos.get('date','?')}"
                )
            return "\n".join(lineas) + "\n"
        except Exception:
            return f"<b>{label}:</b> Sin datos.\n"

    msg  = "📊 <b>POSICIONES ABIERTAS</b>\n\n"
    msg += leer_estado(os.path.join(BASE_DIR, "bot_state.json"),        "Diario")
    msg += "\n"
    msg += leer_estado(os.path.join(BASE_DIR, "bot_state_semanal.json"), "Semanal")

    await update.message.reply_text(msg, parse_mode="HTML")


# ========================== JOBS AUTOMÁTICOS ==========================

async def job_diario(context: ContextTypes.DEFAULT_TYPE):
    logging.info("Ejecutando análisis diario automático...")
    try:
        trading_bot.run_check()
    except Exception as e:
        logging.error(f"Error en job diario: {e}")


async def job_semanal(context: ContextTypes.DEFAULT_TYPE):
    logging.info("Ejecutando análisis semanal automático...")
    try:
        trading_bot_semanal.run_check()
    except Exception as e:
        logging.error(f"Error en job semanal: {e}")


# ========================== MAIN ==========================

def main():
    if not TOKEN:
        raise ValueError("Falta la variable de entorno TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("diario",    cmd_diario))
    app.add_handler(CommandHandler("semanal",   cmd_semanal))
    app.add_handler(CommandHandler("estado",    cmd_estado))
    app.add_handler(CommandHandler("cartera",   cmd_cartera))
    app.add_handler(CommandHandler("depositar", cmd_depositar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_texto))

    # Jobs automáticos
    jq = app.job_queue

    # Lun–Vie a las 18:30 ART → análisis diario
    jq.run_daily(
        job_diario,
        time=datetime.time(hour=18, minute=30, tzinfo=TZ_ARG),
        days=(0, 1, 2, 3, 4)   # 0=lunes … 4=viernes
    )

    # Domingo a las 20:00 ART → análisis semanal
    jq.run_daily(
        job_semanal,
        time=datetime.time(hour=20, minute=0, tzinfo=TZ_ARG),
        days=(6,)   # 6=domingo
    )

    logging.info("Bot iniciado. Escuchando comandos...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
