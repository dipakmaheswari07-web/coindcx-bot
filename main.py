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

# Paper Trading Switch: true = Demo, false = Real Money Live Trading
PAPER_TRADING = os.getenv('PAPER_TRADING', 'true').lower() == 'true'

BASE_URL = "https://api.coindcx.com"

# Gemini AI Configuration (Using Free Flash Model)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name='gemini-2.0-flash',
    generation_config={"response_mime_type": "application/json"}
)

@app.route('/')
def home():
    return "CoinDCX Trading Bot Web Service is Running Live!"

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

def execute_coindcx_trade(pair, side, quantity, leverage):
    if PAPER_TRADING:
        alert = f"🟢 [PAPER TRADING] Order Sim: {side.upper()} {pair} | Qty: {quantity} | Leverage: {leverage}x"
        print(alert)
        send_telegram(alert)
        return {"status": "paper_success"}

    url = f"{BASE_URL}/exchange/v1/derivatives/futures/orders/create"
    body = {
        "timestamp": int(time.time() * 1000),
        "pair": pair,
        "side": side,
        "order_type": "market",
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
        err = f"❌ Real Order Execution Failed: {e}"
        print(err)
        send_telegram(err)
        return None

def ask_gemini_ai(market_tickers):
    system_instruction = (
        "You are an autonomous CoinDCX Crypto Futures trading bot. "
        "Your core rules: "
        "1. Daily stop loss is strictly 20%. "
        "2. Keep leverage as low as possible by default, but you are free to use maximum or as much leverage as needed when required. "
        "Analyze the live market data and have full autonomy to decide whether to BUY, SELL, or HOLD, along with the coin pair, quantity, and leverage. "
        "Return strictly valid JSON only in this exact schema:\n"
        "{\n"
        '  "action": "BUY" | "SELL" | "HOLD",\n'
        '  "pair": "string (e.g., B-BTC_USDT)",\n'
        '  "quantity": number,\n'
        '  "leverage": number,\n'
        '  "reason": "short explanation"\n'
        "}"
    )
    
    prompt = f"System Rules:\n{system_instruction}\n\nLive Market Tickers:\n{json.dumps(market_tickers[:15])}"
    
    try:
        response = model.generate_content(prompt)
        decision = json.loads(response.text)
        return decision
    except Exception as e:
        print(f"Gemini Decision Error: {e}")
        return {"action": "HOLD", "reason": "AI Error"}

def trading_bot_loop():
    start_msg = f"🚀 Bot Started as Web Service on Render!\nMode: {'PAPER TRADING' if PAPER_TRADING else 'REAL MONEY'}"
    print(start_msg)
    send_telegram(start_msg)

    while True:
        try:
            tickers = get_market_data()
            ai = ask_gemini_ai(tickers)
            print(f"AI Decision: {ai}")

            action = ai.get("action", "HOLD").upper()
            if action in ["BUY", "SELL"]:
                execute_coindcx_trade(
                    pair=ai.get("pair"),
                    side=action.lower(),
                    quantity=ai.get("quantity", 0.001),
                    leverage=ai.get("leverage", 1)
                )
            else:
                print(f"Holding/No Action: {ai.get('reason')}")

        except Exception as e:
            err = f"Loop Error: {e}"
            print(err)
            send_telegram(err)

        time.sleep(300)

if __name__ == "__main__":
    # Start trading loop in a background thread so the web server can respond to port checks
    t = threading.Thread(target=trading_bot_loop, daemon=True)
    t.start()

    # Run Flask web server on Render's assigned port
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
