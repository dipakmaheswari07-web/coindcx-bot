import os
import time
import hmac
import hashlib
import json
import threading
import requests
import google.generativeai as genai
from flask import Flask

app = Flask(__name__)

# Environment Variables Setup
API_KEY = os.getenv('COINDCX_API_KEY')
API_SECRET = os.getenv('COINDCX_API_SECRET')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

PAPER_TRADING = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
BASE_URL = "https://api.coindcx.com"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name='gemini-2.0-flash',
    generation_config={"response_mime_type": "application/json"}
)

@app.route('/')
def home():
    return "CoinDCX Trading Bot with Advanced PnL & Candle-Start Retry Safety is Running Live!"

def send_telegram(msg):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
        except Exception as e:
            print(f"Telegram Error: {e}")

def get_signature(body):
    secret_bytes = bytes(API_SECRET, encoding='utf-8')
    body_string = json.dumps(body, separators=(',', ':'))
    return hmac.new(secret_bytes, body_string.encode('utf-8'), hashlib.sha256).hexdigest()

def get_market_data():
    try:
        url = f"{BASE_URL}/exchange/ticker"
        res = requests.get(url, timeout=10)
        return res.json()
    except Exception as e:
        print(f"Market Data Fetch Error: {e}")
        return []

def get_active_positions():
    if PAPER_TRADING:
        return []
    
    url = f"{BASE_URL}/exchange/v1/derivatives/futures/positions"
    body = {"timestamp": int(time.time() * 1000)}
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': API_KEY,
        'X-AUTH-SIGNATURE': get_signature(body)
    }
    try:
        res = requests.post(url, data=json.dumps(body, separators=(',', ':')), headers=headers, timeout=10)
        return res.json()
    except Exception as e:
        print(f"Fetch Positions Error: {e}")
        return []

def execute_coindcx_trade(pair, side, quantity, leverage, order_type="market"):
    if PAPER_TRADING:
        alert = f"🟢 [PAPER TRADING] Action: {side.upper()} | Pair: {pair} | Qty: {quantity} | Lev: {leverage}x"
        print(alert)
        send_telegram(alert)
        return {"status": "paper_success"}

    url = f"{BASE_URL}/exchange/v1/derivatives/futures/orders/create"
    body = {
        "timestamp": int(time.time() * 1000),
        "pair": pair,
        "side": side,
        "order_type": order_type,
        "total_quantity": float(quantity),
        "leverage": int(leverage)
    }
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': API_KEY,
        'X-AUTH-SIGNATURE': get_signature(body)
    }
    try:
        res = requests.post(url, data=json.dumps(body, separators=(',', ':')), headers=headers, timeout=10)
        res_data = res.json()
        send_telegram(f"🚨 [REAL TRADE EXECUTED]: {res_data}")
        return res_data
    except Exception as e:
        err = f"❌ Order Execution Failed: {e}"
        print(err)
        send_telegram(err)
        return None

def ask_gemini_ai(market_tickers, active_positions):
    system_instruction = (
        "You are an autonomous CoinDCX Crypto Futures trading bot. "
        "Your core rules: "
        "1. Daily stop loss is strictly 20%. "
        "2. Keep leverage as low as possible by default, but use maximum when required. "
        "3. If there is an active/open position and market conditions turn against it, output 'CLOSE' to exit early. "
        "4. If no position is open, decide 'BUY', 'SELL', or 'HOLD'. "
        "Return strictly valid JSON only in this exact schema:\n"
        "{\n"
        '  "action": "BUY" | "SELL" | "CLOSE" | "HOLD",\n'
        '  "pair": "string (e.g., B-BTC_USDT)",\n'
        '  "quantity": number,\n'
        '  "leverage": number,\n'
        '  "reason": "short explanation"\n'
        "}"
    )
    
    prompt = f"System Rules:\n{system_instruction}\n\nCurrently Active Positions:\n{json.dumps(active_positions)}\n\nLive Market Tickers:\n{json.dumps(market_tickers[:15])}"
    
    try:
        response = model.generate_content(prompt)
        decision = json.loads(response.text)
        return decision
    except Exception as e:
        print(f"Gemini Decision Error: {e}")
        return {"action": "HOLD", "reason": "AI Error"}

def trading_bot_loop():
    start_msg = f"🚀 Bot Started with Advanced PnL & Start Retry Safety on Render!\nMode: {'PAPER TRADING' if PAPER_TRADING else 'REAL MONEY'}"
    print(start_msg)
    send_telegram(start_msg)

    consecutive_start_failures = 0

    while True:
        try:
            # 1. 5-min candle sync and 5-sec buffer
            now = time.time()
            interval = 300
            remainder = now % interval
            sleep_to_5s = interval - remainder + 5
            if sleep_to_5s > interval:
                sleep_to_5s -= interval
            time.sleep(sleep_to_5s)

            # 2. First 14 seconds check at candle start
            tickers = []
            for attempt in range(1, 11):
                tickers = get_market_data()
                if tickers and len(tickers) > 0:
                    break
                time.sleep(1)

            initial_14s_success = bool(tickers and len(tickers) > 0)

            # 3. If first 14s failed, extend retry up to 1 minute (60s total)
            if not initial_14s_success:
                consecutive_start_failures += 1
                warn_msg = f"⚠️ Warning: Data not received in first 14s. Consecutive start failures: {consecutive_start_failures}. Extending retry for up to 1 minute..."
                print(warn_msg)
                send_telegram(warn_msg)

                for extended_attempt in range(1, 47):
                    tickers = get_market_data()
                    if tickers and len(tickers) > 0:
                        print(f"Data received during extended retry at attempt {extended_attempt}")
                        break
                    time.sleep(1)

            # 4. If no data received even after 1 full minute
            if not tickers:
                error_alert = "🚨 [CRITICAL EXTREME ALERT] No market data received for 1 full minute from candle start!"
                print(error_alert)
                send_telegram(error_alert)

                positions = get_active_positions()
                if positions and len(positions) > 0:
                    close_msg = "🚨 [SAFETY AUTO-CLOSE] Data unavailable for 1 full minute. Closing open position!"
                    print(close_msg)
                    send_telegram(close_msg)
                    ai = {"action": "CLOSE", "reason": "No data received for 1 minute safety close"}
                else:
                    ai = {"action": "HOLD", "reason": "No data received, no open position"}
            else:
                if initial_14s_success:
                    consecutive_start_failures = 0  # कैंडल की शुरुआत में 14 सेकंड में डेटा मिलने पर काउंटर रीसेट

                positions = get_active_positions()
                
                # Check Profit or Loss state from active positions
                in_loss = False
                if positions and len(positions) > 0:
                    for pos in positions:
                        pnl = float(pos.get('pnl', pos.get('unrealized_pnl', 0.0)))
                        if pnl < 0:
                            in_loss = True
                            break

                # Apply consecutive candle-start failure rules with PnL condition
                if not initial_14s_success and positions and len(positions) > 0:
                    if in_loss and consecutive_start_failures >= 3:
                        close_msg = f"🚨 [EXTREME ALERT & AUTO-CLOSE] 3rd consecutive candle start failure while position is in LOSS! Closing position."
                        print(close_msg)
                        send_telegram(close_msg)
                        ai = {"action": "CLOSE", "reason": "3rd candle start failure in loss"}
                    elif not in_loss and consecutive_start_failures >= 4:
                        close_msg = f"🚨 [EXTREME ALERT & AUTO-CLOSE] 4th consecutive candle start failure while position is in PROFIT! Closing position."
                        print(close_msg)
                        send_telegram(close_msg)
                        ai = {"action": "CLOSE", "reason": "4th candle start failure in profit"}
                    else:
                        ai = ask_gemini_ai(tickers, positions)
                else:
                    ai = ask_gemini_ai(tickers, positions)
            
            print(f"AI Decision: {ai}")

            # 5. Execute Action
            action = ai.get("action", "HOLD").upper()
            pair = ai.get("pair")
            quantity = ai.get("quantity", 0.001)
            leverage = ai.get("leverage", 1)

            if action == "BUY":
                execute_coindcx_trade(pair, "buy", quantity, leverage)
            elif action == "SELL":
                execute_coindcx_trade(pair, "sell", quantity, leverage)
            elif action == "CLOSE":
                send_telegram(f"🚨 [CLOSING POSITION] Reason: {ai.get('reason')}")
            else:
                print(f"Holding: {ai.get('reason')}")

        except Exception as e:
            err = f"Loop Error: {e}"
            print(err)
            send_telegram(err)
            time.sleep(10)

if __name__ == "__main__":
    t = threading.Thread(target=trading_bot_loop, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
