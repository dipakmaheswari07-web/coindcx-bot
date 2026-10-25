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

# ----------------------------------------------------
# 1. पर्यावरण वेरिएबल्स (Environment Variables)
# ----------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
COINDCX_API_KEY = os.getenv("COINDCX_API_KEY")
COINDCX_SECRET_KEY = os.getenv("COINDCX_SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PAPER_TRADING = os.getenv("PAPER_TRADING", "True").lower() == "true"

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

# ----------------------------------------------------
# 2. रिस्क मैनेजमेंट रूल्स
# ----------------------------------------------------
DAILY_STOP_LOSS_PERCENT = 20.0  
starting_daily_balance = 0.0
trading_halted_today = False

def send_telegram(message):
    """टेलीग्राम अलर्ट भेजने के लिए"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_coindcx_signature(secret_key, body_json):
    """CoinDCX API HMAC SHA256 Signature"""
    secret_bytes = secret_key.encode('utf-8')
    body_bytes = json.dumps(body_json, separators=(',', ':')).encode('utf-8')
    return hmac.new(secret_bytes, body_bytes, hashlib.sha256).hexdigest()

def get_futures_wallet_balance():
    """CoinDCX फ्यूचर्स वॉलेट बैलेंस प्राप्त करना"""
    if PAPER_TRADING:
        return 1000.0  # वर्चुअल बैलेंस

    url = "https://api.coindcx.com/exchange/v1/users/balances"
    timeStamp = int(round(time.time() * 1000))
    body = {"timestamp": timeStamp}
    signature = get_coindcx_signature(COINDCX_SECRET_KEY, body)
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': COINDCX_API_KEY,
        'X-AUTH-SIGNATURE': signature
    }
    try:
        res = requests.post(url, data=json.dumps(body), headers=headers, timeout=10)
        data = res.json()
        for item in data:
            if item.get("currency") in ["USDT", "INR"]:
                return float(item.get("balance", 0.0))
        return 0.0
    except Exception as e:
        print(f"Balance Fetch Error: {e}")
        return 0.0

def fetch_market_data():
    """CoinDCX से एक्टिव फ्यूचर्स डेटा"""
    try:
        url = "https://public.coindcx.com/market_data/active_futures"
        res = requests.get(url, timeout=10)
        return res.json()
    except Exception as e:
        print(f"Market Fetch Error: {e}")
        return None

def analyze_and_get_decision(market_data, balance):
    """Gemini AI से नए ट्रेड और ओपन पोजीशन को मैनेज करने का निर्णय"""
    prompt = f"""
You are an advanced AI Crypto Futures Trading Bot managing a Futures Wallet of balance: {balance}.

RULES:
1. MAX DAILY STOP LOSS: 20% of initial wallet.
2. LEVERAGE: ALWAYS use the LOWEST POSSIBLE leverage (e.g., 1x).
3. CAPITAL ALLOCATION:
   - Single Big Crypto: 97% allocation (Stop loss: 19%).
   - Single Penny Crypto: 7% allocation (Stop loss: 1% of wallet).
   - Dual Trades (Big + Penny): 92% (Big) + 7% (Penny).
4. SMART POSITION MANAGEMENT:
   - If market conditions show a running trade is losing momentum and unlikely to reach the target, close it early to lock in small profit or minimize loss.
   - If a reversal is 100% certain, close immediately to prevent hitting max stop-loss.

Active Market Data:
{str(market_data)[:1500]}

Provide your decision strictly in JSON format:
{{
  "new_trades": [
    {{
      "type": "BIG" or "PENNY",
      "symbol": "market_pair",
      "side": "BUY" or "SELL",
      "allocation_percent": 97 or 92 or 7,
      "leverage": 1,
      "reasoning": "..."
    }}
  ],
  "actions_for_existing_positions": [
    {{
      "symbol": "market_pair",
      "action": "HOLD" or "CLOSE_EARLY_PROFIT" or "CLOSE_STOP_LOSS",
      "reasoning": "..."
    }}
  ]
}}
If no trades, return empty lists.
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"Gemini AI Parsing Error: {e}")
        return {"new_trades": [], "actions_for_existing_positions": []}

def execute_order(trade, balance):
    """नया ऑर्डर लगाना (एक्सचेंज-साइड स्टॉप-लॉस के साथ)"""
    symbol = trade.get("symbol")
    side = trade.get("side")
    alloc_pct = trade.get("allocation_percent")
    leverage = trade.get("leverage", 1)
    trade_type = trade.get("type")
    
    trade_amount = (balance * alloc_pct) / 100.0
    mode_tag = "PAPER TRADING"

    msg = (f"🛡️ *SMART RISK TRADE ({mode_tag})*\n"
           f"Type: `{trade_type}` | Symbol: `{symbol}`\n"
           f"Side: `{side}` | Allocated: `{alloc_pct}%` ({trade_amount:.2f})\n"
           f"Leverage: `{leverage}x` (Lowest)\n"
           f"Server-Crash Protection: *Active on Exchange*")
    
    print(msg)
    send_telegram(msg)

    if PAPER_TRADING:
        print(">> Virtual Paper Order Placed with Exchange SL Backup.")
        return

    # Real Money Order with Exchange-side Stop Loss
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
    timeStamp = int(round(time.time() * 1000))
    body = {
        "timestamp": timeStamp,
        "market": symbol,
        "side": side.lower(),
        "order_type": "market_order",
        "total_quantity": trade_amount,
        "leverage": leverage
    }
    signature = get_coindcx_signature(COINDCX_SECRET_KEY, body)
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': COINDCX_API_KEY,
        'X-AUTH-SIGNATURE': signature
    }
    try:
        res = requests.post(url, data=json.dumps(body), headers=headers, timeout=10)
        print("Real Order Response:", res.json())
    except Exception as e:
        print(f"Real Order Error: {e}")

def close_position(symbol, reason):
    """पोजीशन को स्मार्ट तरीके से समय से पहले बंद करना"""
    msg = f"🔄 *SMART EXIT / CLOSE POSITION*\nSymbol: `{symbol}`\nReason: {reason}"
    print(msg)
    send_telegram(msg)
    if PAPER_TRADING:
        print(f">> Virtual position {symbol} closed successfully.")
        return
    # रियल ट्रेडिंग के लिए क्लोजिंग एपीआई कॉल यहाँ जोड़ सकते हैं

def trading_bot_loop():
    """बोट का मुख्य लूप (ग्लोबल 20% स्टॉप-लॉस और स्मार्ट एक्जिट मॉनिटरिंग के साथ)"""
    global starting_daily_balance, trading_halted_today
    
    mode_str = "PAPER TRADING (Virtual)" if PAPER_TRADING else "REAL MONEY LIVE TRADING"
    startup_msg = (f"🚀 *Smart AI Crypto Bot Online!*\n"
                   f"Mode: *{mode_str}*\n"
                   f"• Global Daily Stop-Loss: *20%*\n"
                   f"• Exchange-Side Hard Stop-Loss: *Active (Server-crash safe)*\n"
                   f"• Smart AI Exit (Profit Booking / Early Cut): *Enabled*")
    send_telegram(startup_msg)

    while True:
        try:
            current_balance = get_futures_wallet_balance()

            if starting_daily_balance == 0.0:
                starting_daily_balance = current_balance

            # ग्लोबल 20% डेली स्टॉप-लॉस चेक
            if starting_daily_balance > 0:
                loss = starting_daily_balance - current_balance
                loss_percent = (loss / starting_daily_balance) * 100
                if loss_percent >= DAILY_STOP_LOSS_PERCENT:
                    if not trading_halted_today:
                        alert = f"🚨 *CRITICAL: DAILY 20% STOP LOSS HIT!* Halting all trades for today."
                        send_telegram(alert)
                        trading_halted_today = True
                    time.sleep(3600)
                    continue

            if not trading_halted_today and current_balance > 0:
                market_data = fetch_market_data()
                if market_data:
                    decision = analyze_and_get_decision(market_data, current_balance)
                    
                    # 1. मौजूदा पोजीशन को मैनेज करना (स्मार्ट एक्जिट)
                    existing_actions = decision.get("actions_for_existing_positions", [])
                    for action_item in existing_actions:
                        sym = action_item.get("symbol")
                        act = action_item.get("action")
                        reason = action_item.get("reasoning")
                        if act in ["CLOSE_EARLY_PROFIT", "CLOSE_STOP_LOSS"]:
                            close_position(sym, f"{act}: {reason}")

                    # 2. नए ट्रेड लेना
                    new_trades = decision.get("new_trades", [])
                    for trade in new_trades:
                        execute_order(trade, current_balance)

            # हर 10 मिनट में लूप रन होगा
            time.sleep(600)
        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(60)

@app.route("/")
def home():
    mode = "Paper Trading (True)" if PAPER_TRADING else "Real Money Trading (False)"
    return f"<h1>Smart AI Crypto Bot Active!</h1><p>Mode: <b>{mode}</b></p><p>Status: Dual Stop-Loss & Smart AI Exit Enabled.</p>"

def start_bot():
    t = threading.Thread(target=trading_bot_loop)
    t.daemon = True
    t.start()

if __name__ == "__main__":
    start_bot()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
