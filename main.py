import os
import time
import hmac
import hashlib
import json
import requests
import google.generativeai as genai

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

    # Real Live Order Execution on CoinDCX Futures
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
        "Your constraints & rules: "
        "1. Daily Max Loss Limit is strictly 20%. "
        "2. Keep leverage as low as possible by default, but you are authorized to scale up to maximum leverage when market conviction is extremely high. "
        "3. You have full autonomy to decide based on the live market data whether to BUY, SELL, or HOLD, including pair selection, quantity, leverage, and stop-loss logic. "
        "Analyze the live market data and return strictly valid JSON only in this exact schema:\n"
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

if __name__ == "__main__":
    mode_str = "PAPER TRADING (DEMO)" if PAPER_TRADING else "REAL MONEY LIVE TRADING"
    start_msg = f"🚀 Bot Started on Render Cloud Server!\nMode: {mode_str}"
    print(start_msg)
    send_telegram(start_msg)

    while True:
        try:
            # 1. Fetch Live Market Tickers
            tickers = get_market_data()
            
            # 2. Get AI Autonomous Decision
            ai = ask_gemini_ai(tickers)
            print(f"AI Decision: {ai}")

            # 3. Execute Trade based on Gemini Output
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

        # Runs every 5 minutes (300 seconds)
        time.sleep(300)
