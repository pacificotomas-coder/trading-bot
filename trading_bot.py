#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot de Trading DIARIO - Estrategia EMA 20 + RSI
=================================================
Lógica de COMPRA (en orden):
  1. RSI estuvo por debajo de 30 en los últimos 20 días  → activo sobrevendido
  2. Vela hace 2 días: primer cierre por encima de EMA 20 → "En seguimiento"
  3. Vela de ayer:     segundo cierre por encima de EMA 20 → ✅ SEÑAL DE COMPRA

Lógica de VENTA (en orden):
  1. RSI estuvo por encima de 70 en los últimos 20 días  → activo sobrecomprado
  2. Vela hace 2 días: primer cierre por debajo de EMA 20 → "En seguimiento"
  3. Vela de ayer:     segundo cierre por debajo de EMA 20 → 🔻 SEÑAL DE VENTA
"""

import os
import sys
import io
import json
from datetime import datetime
import yfinance as yf
import requests
import portfolio
import iol_broker

# UTF-8 para consola Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ========================== CONFIGURACIÓN ==========================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_DIR           = os.path.dirname(os.path.abspath(__file__))
LOG_FILE           = os.path.join(BASE_DIR, "alertas.log")
STATE_FILE         = os.path.join(BASE_DIR, "bot_state.json")
RIESGO_MAXIMO      = 10.0   # % máximo de distancia al stop para marcar BAJO RIESGO

TICKERS = {
    "Acciones Argentina": [
        "GGAL.BA", "YPFD.BA", "PAMP.BA", "BMA.BA", "CEPU.BA",
        "LOMA.BA", "BBVA.BA", "SUPV.BA", "ALUA.BA", "COME.BA",
        "TRAN.BA", "BYMA.BA", "METR.BA", "ECOG.BA", "EDN.BA", "TGNO4.BA"
    ],
    "CEDEARs": [
        "NU.BA", "AAPL.BA", "MSFT.BA", "AMZN.BA", "GOOGL.BA",
        "META.BA", "NVDA.BA", "TSLA.BA", "MELI.BA", "KO.BA"
    ],
    "Acciones USA": [
        "SPY", "AAPL", "MSFT", "NVDA", "TSLA", "MELI", "AMZN", "META",
        "GOOGL", "KO", "IBM", "ORCL", "INTC", "NU"
    ],
    "Crypto": [
        "BTC-USD", "ETH-USD", "BNB-USD", "XRP-USD", "SOL-USD",
        "ADA-USD", "DOGE-USD"
    ]
}

EMA_PERIOD   = 20    # días para la media móvil exponencial
RSI_PERIOD   = 14    # días para el RSI
RSI_LOOKBACK = 20    # días hacia atrás para buscar si RSI estuvo bajo 30 o sobre 70
MIN_CANDLES  = 60    # mínimo de velas necesarias para calcular indicadores

# ========================== INDICADORES ==========================

def get_data(ticker):
    """Descarga datos históricos de Yahoo Finance (últimos 4 meses)"""
    try:
        data = yf.download(ticker, period="4mo", progress=False, auto_adjust=True)
        if len(data) < MIN_CANDLES:
            return None
        return data
    except Exception:
        return None

def calculate_ema(close, period):
    return close.ewm(span=period, adjust=False).mean()

def calculate_rsi(close, period):
    delta = close.diff()
    gain  = delta.where(delta > 0, 0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss
    return 100 - (100 / (1 + rs))

# ========================== LÓGICA DE SEÑAL ==========================

def analyze_ticker(ticker, data):
    """
    Analiza un ticker y retorna su estado actual:
      - NORMAL
      - SEGUIMIENTO_COMPRA  → primer cruce sobre EMA con RSI sobrevendido reciente
      - SEÑAL_COMPRA        → segundo cruce sobre EMA (confirmación) ✅
      - SEGUIMIENTO_VENTA   → primer cruce bajo EMA con RSI sobrecomprado reciente
      - SEÑAL_VENTA         → segundo cruce bajo EMA (confirmación) 🔻
    """
    close = data['Close'].squeeze()
    ema   = calculate_ema(close, EMA_PERIOD)
    rsi   = calculate_rsi(close, RSI_PERIOD)

    if len(close) < EMA_PERIOD + RSI_LOOKBACK + 4:
        return None

    try:
        c_dia1 = float(close.iloc[-2])   # posible primer cruce
        e_dia1 = float(ema.iloc[-2])
        c_dia2 = float(close.iloc[-1])   # posible segundo cruce (confirmación)
        e_dia2 = float(ema.iloc[-1])

        rsi_actual   = float(rsi.iloc[-1])
        rsi_reciente = rsi.iloc[-RSI_LOOKBACK:]

        # Buscar si antes del posible cruce el precio estuvo bajo/sobre EMA
        # (miramos las 8 velas previas para capturar el cruce reciente)
        estuvo_bajo_ema  = any(
            float(close.iloc[i]) < float(ema.iloc[i]) for i in range(-10, -2)
        )
        estuvo_sobre_ema = any(
            float(close.iloc[i]) > float(ema.iloc[i]) for i in range(-10, -2)
        )

        # Stop loss estructural usando cierres (más ajustado que usar mínimos de vela)
        # Para COMPRA: mínimo cierre de los últimos 30 días (piso reciente)
        # Para VENTA: máximo cierre de los últimos 30 días (techo reciente)
        stop_compra = float(close.iloc[-30:].min())
        stop_venta  = float(close.iloc[-30:].max())

    except Exception:
        return None

    # ¿Estuvo el RSI en zona extrema recientemente?
    rsi_sobrevendido  = bool((rsi_reciente < 30).any())   # condición para compra
    rsi_sobrecomprado = bool((rsi_reciente > 70).any())   # condición para venta

    # --- Detección de cruces ---
    # SEÑAL COMPRA: venía de abajo → cruzó arriba (día 1) → confirmó arriba (día 2)
    senal_compra       = estuvo_bajo_ema and (c_dia1 > e_dia1) and (c_dia2 > e_dia2) and rsi_sobrevendido
    # SEGUIMIENTO COMPRA: recién hizo el primer cruce (falta confirmación mañana)
    seguimiento_compra = estuvo_bajo_ema and (c_dia1 < e_dia1) and (c_dia2 > e_dia2) and rsi_sobrevendido

    # SEÑAL VENTA: venía de arriba → cruzó abajo (día 1) → confirmó abajo (día 2)
    senal_venta        = estuvo_sobre_ema and (c_dia1 < e_dia1) and (c_dia2 < e_dia2) and rsi_sobrecomprado
    # SEGUIMIENTO VENTA: recién hizo el primer cruce bajista (falta confirmación mañana)
    seguimiento_venta  = estuvo_sobre_ema and (c_dia1 > e_dia1) and (c_dia2 < e_dia2) and rsi_sobrecomprado

    # Determinar status (señal tiene prioridad sobre seguimiento)
    if senal_compra:
        status = "SEÑAL_COMPRA"
    elif senal_venta:
        status = "SEÑAL_VENTA"
    elif seguimiento_compra:
        status = "SEGUIMIENTO_COMPRA"
    elif seguimiento_venta:
        status = "SEGUIMIENTO_VENTA"
    else:
        status = "NORMAL"

    return {
        "status":             status,
        "rsi":                rsi_actual,
        "price":              c_dia2,
        "ema":                e_dia2,
        "rsi_sobrevendido":   rsi_sobrevendido,
        "rsi_sobrecomprado":  rsi_sobrecomprado,
        "stop_compra":        stop_compra,
        "stop_venta":         stop_venta,
    }

# ========================== ESTADO DE POSICIONES ==========================

def load_state():
    """Carga las posiciones abiertas desde el archivo de estado."""
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    """Guarda las posiciones abiertas en el archivo de estado."""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# ========================== NOTIFICACIONES ==========================

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
        if r.status_code == 200:
            print(f"  📲 Telegram enviado OK")
        else:
            print(f"  ⚠  Telegram error {r.status_code}")
    except Exception as e:
        print(f"  ✗ Error Telegram: {e}")

def log_alert(ticker, status, rsi, price, ema):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"{ts} | {status} | {ticker} | Precio {price:.2f} | EMA {ema:.2f} | RSI {rsi:.1f}\n")
    except Exception:
        pass

# ========================== MAIN ==========================

def run_check():
    print(f"\n{'='*65}")
    print(f"  TRADING BOT DIARIO  -  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"  Estrategia: RSI < 30 reciente + 2 cierres sobre EMA 20")
    print(f"{'='*65}")

    # Sincronizar saldo real de IOL antes de operar
    saldo_sincronizado = portfolio.sincronizar_saldo()
    print(f"  💵 Saldo IOL sincronizado: ${saldo_sincronizado:,.2f} ARS disponibles")

    # Cargar posiciones abiertas del estado anterior
    state     = load_state()
    new_state = {}   # se reconstruye en cada corrida

    senales_compra      = []
    senales_venta       = []
    seguimientos_compra = []
    seguimientos_venta  = []
    stops_alcanzados    = []
    telegram_alerts     = []

    for category, tickers_list in TICKERS.items():
        print(f"\n── {category} {'─' * (50 - len(category))}")

        for ticker in tickers_list:
            data = get_data(ticker)
            if data is None:
                print(f"  ⚠  {ticker}: Sin datos suficientes")
                continue

            result = analyze_ticker(ticker, data)
            if result is None:
                print(f"  ⚠  {ticker}: Error al calcular indicadores")
                continue

            status = result["status"]
            rsi    = result["rsi"]
            price  = result["price"]
            ema    = result["ema"]

            # ---- VERIFICAR STOP LOSS para posiciones abiertas ----
            if ticker in state:
                pos = state[ticker]
                stop_guardado  = pos["stop"]
                entrada        = pos["entry"]
                direccion      = pos["direction"]
                fecha_entrada  = pos.get("date", "?")

                stop_tocado = (
                    (direccion == "compra" and price <= stop_guardado) or
                    (direccion == "venta"  and price >= stop_guardado)
                )

                if stop_tocado:
                    perdida_pct = abs((price - entrada) / entrada) * 100
                    print(f"  🚨 {ticker}: STOP LOSS ALCANZADO | Entrada {entrada:.2f} → Precio actual {price:.2f} ({-perdida_pct:.1f}%)")
                    stops_alcanzados.append(ticker)
                    log_alert(ticker, "STOP LOSS", rsi, price, ema)
                    # Recuperar cantidad del portafolio ANTES de cerrar
                    p_actual  = portfolio.load()
                    qty_close = p_actual.get("posiciones", {}).get(ticker, {}).get("cantidad", 0)
                    portfolio.close_position(ticker, price, "stop_loss")
                    msg_iol = iol_broker.place_sell_order(ticker, category, qty_close, price)
                    print(msg_iol)
                    telegram_alerts.append(
                        f"🚨 STOP LOSS: <b>{ticker}</b>\n"
                        f"   Entrada: {entrada:.2f}  ({fecha_entrada})\n"
                        f"   Precio actual: {price:.2f}  ({-perdida_pct:.1f}%)\n"
                        f"   Stop en {stop_guardado:.2f} — posición cerrada\n"
                        f"{msg_iol}"
                    )
                    # No se agrega a new_state → posición cerrada
                else:
                    # Trailing stop: actualizar solo si el nuevo nivel mejora la protección
                    close_series = data['Close'].squeeze()
                    if direccion == "compra":
                        nuevo_stop = float(close_series.iloc[-30:].min())
                        if nuevo_stop > stop_guardado:
                            print(f"     📈 Stop actualizado: {stop_guardado:.2f} → {nuevo_stop:.2f}")
                            pos["stop"] = nuevo_stop
                            portfolio.update_stop(ticker, nuevo_stop)
                    elif direccion == "venta":
                        nuevo_stop = float(close_series.iloc[-30:].max())
                        if nuevo_stop < stop_guardado:
                            print(f"     📉 Stop actualizado: {stop_guardado:.2f} → {nuevo_stop:.2f}")
                            pos["stop"] = nuevo_stop
                            portfolio.update_stop(ticker, nuevo_stop)
                    new_state[ticker] = pos   # sigue abierta

            # Tag del RSI para mostrar en consola
            if rsi < 30:
                rsi_tag = "🔴 SOBREVENDIDO"
            elif rsi > 70:
                rsi_tag = "🟢 SOBRECOMPRADO"
            else:
                rsi_tag = "🟡 normal"

            if status == "SEÑAL_COMPRA":
                stop       = result["stop_compra"]
                riesgo     = ((price - stop) / price) * 100
                bajo_riesgo = riesgo <= RIESGO_MAXIMO
                riesgo_tag  = "  ⭐ BAJO RIESGO" if bajo_riesgo else ""

                print(f"  ✅ {ticker}: SEÑAL DE COMPRA{riesgo_tag}  | Precio {price:.2f} | EMA {ema:.2f} | RSI {rsi:.1f}")
                print(f"     🛑 Stop sugerido: {stop:.2f}  (mínimo cierre 30 días, -{riesgo:.1f}% desde entrada)")
                senales_compra.append(ticker + (" ⭐" if bajo_riesgo else ""))
                log_alert(ticker, "SEÑAL COMPRA", rsi, price, ema)

                # Guardar posición abierta (solo si no hay una ya registrada)
                if ticker not in new_state:
                    new_state[ticker] = {
                        "direction": "compra",
                        "entry":     price,
                        "stop":      stop,
                        "date":      datetime.now().strftime('%Y-%m-%d')
                    }
                if bajo_riesgo:
                    msg_portfolio = portfolio.open_position(ticker, category, price, stop, "diario")
                    if msg_portfolio == "SIN_FONDOS":
                        # Señal válida pero sin capital — avisar para depositar
                        alerta = (
                            f"💡 SEÑAL SIN FONDOS: <b>{ticker}</b>\n"
                            f"   Precio: {price:.2f} | EMA 20: {ema:.2f} | RSI: {rsi:.1f}\n"
                            f"   🛑 Stop sugerido: {stop:.2f}  (-{riesgo:.1f}% desde entrada)\n"
                            f"   ⚠️ Sin capital disponible en IOL para operar.\n"
                            f"   Depositá fondos si querés entrar en esta posición."
                        )
                        telegram_alerts.append(alerta)
                    elif msg_portfolio:
                        alerta = (
                            f"✅ COMPRA ⭐ BAJO RIESGO: <b>{ticker}</b>\n"
                            f"   Precio: {price:.2f} | EMA 20: {ema:.2f} | RSI: {rsi:.1f}\n"
                            f"   🛑 Stop sugerido: {stop:.2f}  (-{riesgo:.1f}% desde entrada)\n"
                            f"   2 cierres sobre EMA 20 ✓ | RSI sobrevendido reciente ✓\n\n"
                            f"{msg_portfolio}"
                        )
                        # Ejecutar en IOL con la cantidad que calculó el portafolio
                        p_nuevo  = portfolio.load()
                        qty_buy  = p_nuevo.get("posiciones", {}).get(ticker, {}).get("cantidad", 0)
                        msg_iol  = iol_broker.place_buy_order(ticker, category, qty_buy, price)
                        print(msg_iol)
                        alerta  += f"\n{msg_iol}"
                        telegram_alerts.append(alerta)

            elif status == "SEÑAL_VENTA":
                stop       = result["stop_venta"]
                riesgo     = ((stop - price) / price) * 100
                bajo_riesgo = riesgo <= RIESGO_MAXIMO
                riesgo_tag  = "  ⭐ BAJO RIESGO" if bajo_riesgo else ""

                print(f"  🔻 {ticker}: SEÑAL DE VENTA{riesgo_tag}   | Precio {price:.2f} | EMA {ema:.2f} | RSI {rsi:.1f}")
                print(f"     🛑 Stop sugerido: {stop:.2f}  (máximo cierre 30 días, +{riesgo:.1f}% desde entrada)")
                senales_venta.append(ticker + (" ⭐" if bajo_riesgo else ""))
                log_alert(ticker, "SEÑAL VENTA", rsi, price, ema)

                # Guardar posición abierta (solo si no hay una ya registrada)
                if ticker not in new_state:
                    new_state[ticker] = {
                        "direction": "venta",
                        "entry":     price,
                        "stop":      stop,
                        "date":      datetime.now().strftime('%Y-%m-%d')
                    }
                if bajo_riesgo:
                    telegram_alerts.append(
                        f"🔻 VENTA ⭐ BAJO RIESGO: <b>{ticker}</b>\n"
                        f"   Precio: {price:.2f} | EMA 20: {ema:.2f} | RSI: {rsi:.1f}\n"
                        f"   🛑 Stop sugerido: {stop:.2f}  (+{riesgo:.1f}% desde entrada)\n"
                        f"   2 cierres bajo EMA 20 ✓ | RSI sobrecomprado reciente ✓"
                    )

            elif status == "SEGUIMIENTO_COMPRA":
                print(f"  ⏳ {ticker}: 1er cruce sobre EMA — esperando confirmación mañana | RSI {rsi:.1f} {rsi_tag}")
                seguimientos_compra.append(ticker)

            elif status == "SEGUIMIENTO_VENTA":
                print(f"  ⏳ {ticker}: 1er cruce bajo EMA  — esperando confirmación mañana | RSI {rsi:.1f} {rsi_tag}")
                seguimientos_venta.append(ticker)

            else:
                diff_pct = ((price - ema) / ema) * 100
                tendencia = "📈" if diff_pct > 0.5 else ("📉" if diff_pct < -0.5 else "➡")
                print(f"  ·  {ticker}: {tendencia} P:{price:.2f} | RSI {rsi:.1f} ({rsi_tag})")

    # Guardar estado actualizado
    save_state(new_state)

    # ---- RESUMEN FINAL ----
    print(f"\n{'='*65}")
    print("  RESUMEN DEL DÍA")
    print(f"{'='*65}")

    if stops_alcanzados:
        print(f"\n  🚨 STOPS ALCANZADOS ({len(stops_alcanzados)}):      {', '.join(stops_alcanzados)}")
    if senales_compra:
        compra_br     = [t for t in senales_compra if "⭐" in t]
        compra_normal = [t for t in senales_compra if "⭐" not in t]
        print(f"\n  ✅ SEÑALES DE COMPRA ({len(senales_compra)}):")
        if compra_br:
            print(f"     ⭐ Bajo riesgo:    {', '.join(compra_br)}")
        if compra_normal:
            print(f"     📊 Riesgo normal:  {', '.join(compra_normal)}")
    if senales_venta:
        venta_br     = [t for t in senales_venta if "⭐" in t]
        venta_normal = [t for t in senales_venta if "⭐" not in t]
        print(f"\n  🔻 SEÑALES DE VENTA  ({len(senales_venta)}):")
        if venta_br:
            print(f"     ⭐ Bajo riesgo:    {', '.join(venta_br)}")
        if venta_normal:
            print(f"     📊 Riesgo normal:  {', '.join(venta_normal)}")
    if seguimientos_compra:
        print(f"  ⏳ EN SEGUIMIENTO COMPRA ({len(seguimientos_compra)}): {', '.join(seguimientos_compra)}")
    if seguimientos_venta:
        print(f"  ⏳ EN SEGUIMIENTO VENTA  ({len(seguimientos_venta)}): {', '.join(seguimientos_venta)}")

    if not any([stops_alcanzados, senales_compra, senales_venta, seguimientos_compra, seguimientos_venta]):
        print("\n  Sin señales activas hoy. Nada que hacer.")

    # ---- REFERENCIA ----
    print(f"\n{'─'*65}")
    print("  REFERENCIA DE SEÑALES")
    print(f"{'─'*65}")
    print("  🚨 STOP LOSS:    Precio tocó el nivel de stop de una posición abierta")
    print("  ✅ COMPRA:       RSI < 30 reciente + 2 cierres sobre EMA 20")
    print("  ⏳ SEGUIMIENTO:  Primer cruce sobre EMA — confirmar mañana")
    print("  🔻 VENTA:        RSI > 70 reciente + 2 cierres bajo EMA 20")
    print(f"  ⭐ BAJO RIESGO:  Stop a menos del {RIESGO_MAXIMO:.0f}% de la entrada")

    # ---- TELEGRAM ----
    if telegram_alerts:
        msg  = f"🤖 <b>TRADING BOT — {datetime.now().strftime('%d/%m/%Y')}</b>\n\n"
        msg += "\n\n".join(telegram_alerts)
        send_telegram(msg)

    print(f"\n{'='*65}\n")


if __name__ == "__main__":
    try:
        run_check()
    except Exception as e:
        import traceback
        print(f"\n❌ ERROR: {e}")
        traceback.print_exc()
    finally:
        input("\nPresioná ENTER para cerrar...")
