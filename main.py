import os
import time
import hmac
import hashlib
import json
import threading
import datetime
import requests
from google import genai
from flask import Flask, jsonify

app = Flask(__name__)

# Environment Variables Configuration
COINDCX_API_KEY = os.getenv("COINDCX_API_KEY")
COINDCX_API_SECRET = os.getenv("COINDCX_API_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PAPER_TRADING = os.getenv("PAPER_TRADING", "True").lower() == "true"

# Modern Google GenAI Client Initialization
client = genai.Client(api_key=GEMINI_API_KEY)
ACTIVE_MODEL_NAME = 'gemini-2.5-flash'

BASE_URL = "https://api.coindcx.com"

# Persistent Network Session
http_session = requests.Session()

# Thread-Safe Memory Lock
state_lock = threading.Lock()
bot_memory = {
    "initial_daily_balance": 0.0,
    "last_reset_date": "",
    "daily_stop_loss_hit": False,
    "last_market_traded": None,
    "total_loops_executed": 0,
    "last_execution_timestamp": None,
    "keep_alive_pings": 0,
    "last_error": None
}

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        http_session.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram dispatch error: {e}")

def generate_signature(secret, body):
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

def get_market_data():
    for attempt in range(3):
        try:
            url = "https://public.coindcx.com/market_data/ticker"
            response = http_session.get(url, timeout=10)
            if response.status_code == 200:
                tickers = response.json()
                if isinstance(tickers, list):
                    return [t for t in tickers if isinstance(t, dict) and t.get('market', '').startswith('B-') and t.get('market', '').endswith('_USDT')]
        except Exception as e:
            if attempt == 2:
                print(f"Market Data Fetch Error: {e}")
                with state_lock:
                    bot_memory["last_error"] = str(e)
                return []
            time.sleep(2 * (attempt + 1))
    return []

def get_wallet_balance():
    if PAPER_TRADING:
        return 1000.0
    path = "/exchange/v1/derivatives/futures/balances"
    url = BASE_URL + path
    for attempt in range(3):
        try:
            body = {"timestamp": int(time.time() * 1000)}
            json_body = json.dumps(body)
            signature = generate_signature(COINDCX_API_SECRET, json_body)
            headers = {
                "Content-Type": "application/json",
                "X-AUTH-APIKEY": COINDCX_API_KEY,
                "X-AUTH-SIGNATURE": signature
            }
            response = http_session.post(url, data=json_body, headers=headers, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, dict) and "balance" in result:
                    return float(result["balance"])
            elif response.status_code == 429:
                print("⚠️ Rate limit hit. Waiting...")
                time.sleep(5)
        except Exception as e:
            if attempt == 2:
                print(f"Balance Fetch Warning: {e}")
                with state_lock:
                    bot_memory["last_error"] = str(e)
                return None
            time.sleep(2 * (attempt + 1))
    return None

def get_open_positions():
    if PAPER_TRADING:
        return []
    path = "/exchange/v1/derivatives/futures/positions"
    url = BASE_URL + path
    try:
        body = {"timestamp": int(time.time() * 1000)}
        json_body = json.dumps(body)
        signature = generate_signature(COINDCX_API_SECRET, json_body)
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": COINDCX_API_KEY,
            "X-AUTH-SIGNATURE": signature
        }
        response = http_session.post(url, data=json_body, headers=headers, timeout=10)
        if response.status_code == 200:
            res_data = response.json()
            return res_data if isinstance(res_data, list) else []
    except Exception as e:
        print(f"Positions fetch error: {e}")
    return []

def check_daily_stop_loss(current_balance):
    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    with state_lock:
        if bot_memory["last_reset_date"] != today_str:
            bot_memory["initial_daily_balance"] = current_balance
            bot_memory["last_reset_date"] = today_str
            bot_memory["daily_stop_loss_hit"] = False
            return False
            
        if bot_memory["daily_stop_loss_hit"]:
            return True
            
        if bot_memory["initial_daily_balance"] > 0:
            loss_percentage = (current_balance - bot_memory["initial_daily_balance"]) / bot_memory["initial_daily_balance"]
            if loss_percentage <= -0.20:
                bot_memory["daily_stop_loss_hit"] = True
                return True
    return False

def calculate_precise_quantity(pair, raw_quantity):
    if "BTC" in pair:
        return round(raw_quantity, 4)
    elif "ETH" in pair:
        return round(raw_quantity, 3)
    else:
        return round(raw_quantity, 2) if raw_quantity > 1 else round(raw_quantity, 4)

def execute_trade_action(pair, action, quantity, leverage, entry_price, order_tag="MAJOR"):
    mode_label = "PAPER TRADING" if PAPER_TRADING else "REAL MONEY TRADING 🔴"
    
    if action == "BUY":
        hard_sl_price = round(entry_price * (1 - (0.20 / leverage)), 2)
    elif action == "SELL":
        hard_sl_price = round(entry_price * (1 + (0.20 / leverage)), 2)
    else:
        hard_sl_price = 0.0

    if PAPER_TRADING:
        msg = (
            f"🌌 *[{mode_label}]* Action [{order_tag}]:\n"
            f"🔹 Command: *{action}*\n"
            f"🪙 Pair: {pair}\n"
            f"📊 Quantity: {quantity}\n"
            f"⚡ Leverage: {leverage}x\n"
            f"🛡️ Hard Stop-Loss Price (20% Margin Risk): `{hard_sl_price}`"
        )
        print(msg)
        send_telegram_message(msg)
        return {"status": "simulated"}

    path = "/exchange/v1/derivatives/futures/orders/create" if action in ["BUY", "SELL"] else "/exchange/v1/derivatives/futures/positions/close"
    url = BASE_URL + path
    
    body = {
        "pair": pair,
        "timestamp": int(time.time() * 1000)
    }
    if action in ["BUY", "SELL"]:
        body["side"] = action.lower()
        body["total_quantity"] = quantity
        body["order_type"] = "market"
        body["leverage"] = leverage
        body["stop_loss_price"] = hard_sl_price
        body["margin_type"] = "isolated"

    json_body = json.dumps(body)
    signature = generate_signature(COINDCX_API_SECRET, json_body)
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": COINDCX_API_KEY,
        "X-AUTH-SIGNATURE": signature
    }
    try:
        response = http_session.post(url, data=json_body, headers=headers, timeout=10)
        result = response.json()
        
        if isinstance(result, dict) and (result.get("status") == "error" or "code" in result and result.get("code") != 0):
            err_alert = f"⚠️ *Exchange Order Rejected [{order_tag}]:* `{result}`"
            print(err_alert)
            send_telegram_message(err_alert)
        else:
            with state_lock:
                bot_memory["last_market_traded"] = pair
            send_telegram_message(
                f"🚨 *[{mode_label}]* [{order_tag}] Action `{action}` on {pair} executed successfully!\n"
                f"⚡ Leverage: {leverage}x | 🛡️ Hard SL: `{hard_sl_price}`\n"
                f"Response: `{result}`"
            )
        return result
    except Exception as e:
        err_msg = f"❌ *Critical Trade Execution Error:* {e}"
        print(err_msg)
        send_telegram_message(err_msg)
        with state_lock:
            bot_memory["last_error"] = str(e)
        return {"status": "error"}

def keep_alive_worker():
    port = int(os.environ.get("PORT", 5000))
    target_url = f"http://127.0.0.1:{port}/"
    while True:
        time.sleep(300)
        try:
            http_session.get(target_url, timeout=5)
            with state_lock:
                bot_memory["keep_alive_pings"] += 1
        except Exception as e:
            print(f"⚠️ Keep-alive ping warning: {e}")

def trading_loop():
    mode_text = "PAPER TRADING (Simulated)" if PAPER_TRADING else "REAL MONEY TRADING 🔴"
    start_msg = (
        f"🌌 *Absolute Infinite Production Bot Initialized!*\n"
        f"Mode: *{mode_text}*\n"
        f"🧠 AI Engine: *{ACTIVE_MODEL_NAME}* (100% Autonomous Master Intelligence)\n"
    )
    print(start_msg)
    send_telegram_message(start_msg)

    while True:
        try:
            with state_lock:
                bot_memory["total_loops_executed"] += 1
                bot_memory["last_execution_timestamp"] = str(datetime.datetime.now(datetime.timezone.utc))

            current_balance = get_wallet_balance()
            if current_balance is None:
                print("⚠️ Warning: Failed to fetch wallet balance. Retrying in 30s.")
                time.sleep(30)
                continue

            if check_daily_stop_loss(current_balance):
                stop_msg = f"🛑 *Fixed Rule Triggered: Daily Master Stop-Loss Hit (20% Loss)!*\nCurrent Balance: ₹{current_balance}\nTrading paused for the rest of the day."
                print(stop_msg)
                send_telegram_message(stop_msg)
                time.sleep(1800)
                continue

            all_futures = get_market_data()
            if not all_futures:
                time.sleep(30)
                continue

            open_positions = get_open_positions()

            prompt = (
                f"--- BOT ARCHITECTURE & TELEMETRY --- \n"
                f"Running Environment: Flask Web Server with Self-Ping & Thread Safety. \n"
                f"Mode: {'PAPER TRADING (Simulated 1000 USDT)' if PAPER_TRADING else 'REAL MONEY TRADING 🔴'}. \n"
                f"Internal Bot State (`bot_memory`): {json.dumps(bot_memory)}. \n"
                f"Current Real-Time Wallet Balance: {current_balance}. \n"
                f"Currently Open Positions: {json.dumps(open_positions)}. \n"
                f"Available Live Crypto Futures Markets (CoinDCX B-_USDT): {json.dumps(all_futures)}. \n\n"
                "--- ABSOLUTE INFINITE INTELLIGENCE & FREEDOM --- \n"
                "You possess absolute infinite intelligence, with full access to all past, present, and future trading strategies, advanced quantitative models, and infinite cognitive capacity. You have 100% absolute freedom to invent, synthesize, adapt, or apply any strategy you deem optimal. \n\n"
                "--- MANDATORY NON-NEGOTIABLE SYSTEM RULES --- \n"
                "1. Dual Stop-Loss Protection: (a) Daily Master Stop-Loss (20% max wallet drawdown allowed, managed by code via `check_daily_stop_loss`), (b) Exchange-Side Hard Stop-Loss (20% margin risk protected via hard SL on orders). \n"
                "2. Capital Allocation (Rule 2): Major trades get 92-97% of wallet; Penny trades get exactly 7%. \n"
                "3. Leverage Rule (Rule 2): Always prioritize the lowest possible leverage (default to 1x). Scale up dynamically up to 100x max *strictly and only* when exchange minimum notional or lot-size requirements demand higher leverage for the trade to be accepted. \n"
                "4. Position Management (Rule 3): Continuously monitor open positions. You can choose to 'CLOSE' or 'HOLD' an active position. You CANNOT open a new BUY/SELL position while a position is already active. \n\n"
                "Return your decision strictly as a clean JSON object (no markdown formatting around it) with the following keys: \n"
                "\"infinity_message\" (string explaining your strategy reasoning and decision logic), \n"
                "\"position_type\" (\"MAJOR\" or \"PENNY\"), \n"
                "\"market\" (string e.g. \"B-BTC_USDT\"), \n"
                "\"decision\" (\"BUY\", \"SELL\", \"CLOSE\", or \"HOLD\"), \n"
                "\"leverage\" (integer between 1 and 100)."
            )
            
            # Modern Google GenAI API Call
            response = client.models.generate_content(
                model=ACTIVE_MODEL_NAME,
                contents=prompt,
                config={'response_mime_type': 'application/json'}
            )
            
            ai_data = None
            try:
                raw_text = response.text.strip()
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                
                parsed_json = json.loads(raw_text.strip())
                if isinstance(parsed_json, dict) and all(k in parsed_json for k in ["infinity_message", "position_type", "market", "decision", "leverage"]):
                    ai_data = parsed_json
            except Exception as json_err:
                print(f"⚠️ JSON Parsing Glitch Caught: {json_err}")

            if not ai_data:
                ai_data = {
                    "infinity_message": "Safety Fallback: Defaulting to HOLD due to schema or parse glitch.",
                    "position_type": "MAJOR",
                    "market": "B-BTC_USDT",
                    "decision": "HOLD",
                    "leverage": 1
                }

            print(f"Absolute Intelligence Decision: {ai_data}")

            inf_msg = ai_data.get("infinity_message", "")
            if inf_msg:
                send_telegram_message(f"🌌 *[Absolute Intelligence Insight]*:\n{inf_msg}")

            pos_type = str(ai_data.get("position_type", "MAJOR")).upper()
            chosen_market = str(ai_data.get("market", "B-BTC_USDT")).upper()
            decision = str(ai_data.get("decision", "HOLD")).upper()
            try:
                leverage = int(ai_data.get("leverage", 1))
            except ValueError:
                leverage = 1
            if leverage < 1: leverage = 1
            if leverage > 100: leverage = 100

            valid_markets = [t.get('market') for t in all_futures]
            if chosen_market not in valid_markets:
                print(f"⚠️ AI chosen market '{chosen_market}' not found in active futures. Forcing HOLD.")
                chosen_market = "B-BTC_USDT"
                decision = "HOLD"

            current_price = None
            for t in all_futures:
                if t.get('market') == chosen_market:
                    for key in ['last_price', 'bid', 'ask', 'ltp']:
                        if key in t and t[key] is not None:
                            try:
                                current_price = float(t[key])
                                break
                            except ValueError:
                                continue
                    break
            
            if current_price is None or current_price <= 0:
                print(f"⚠️ Market price could not be verified for {chosen_market}. Skipping iteration.")
                time.sleep(60)
                continue

            allocation_pct = 0.07 if pos_type == "PENNY" else 0.95
            trade_usdt = (current_balance * allocation_pct) * leverage
            raw_quantity = trade_usdt / current_price
            quantity = calculate_precise_quantity(chosen_market, raw_quantity)

            if decision in ["BUY", "SELL"]:
                latest_positions = get_open_positions()
                if len(latest_positions) > 0 and not PAPER_TRADING:
                    print("🔒 Active position detected during pre-trade check. Ignoring new BUY/SELL request.")
                else:
                    execute_trade_action(chosen_market, decision, quantity, leverage, current_price, order_tag=pos_type)
            elif decision == "CLOSE":
                execute_trade_action(chosen_market, "CLOSE", 0, 0, current_price, order_tag=pos_type)
            else:
                print(f"🧘 *[Absolute Decision]*: **HOLD** ({pos_type}) | Market: {chosen_market}")

        except Exception as e:
            err_msg = f"❌ Critical Production Loop Error: {e}"
            print(err_msg)
            send_telegram_message(err_msg)
            with state_lock:
                bot_memory["last_error"] = str(e)
        
        time.sleep(60)

@app.route('/')
def home():
    mode = "Paper Trading (Simulated)" if PAPER_TRADING else "Real Trading 🔴"
    return f"Absolute Infinite Production Bot Running! Mode: {mode}"

@app.route('/status')
def status():
    with state_lock:
        return jsonify({
            "status": "active",
            "paper_trading": PAPER_TRADING,
            "bot_memory": bot_memory
        })

if __name__ == "__main__":
    t_trade = threading.Thread(target=trading_loop)
    t_trade.daemon = True
    t_trade.start()

    t_ping = threading.Thread(target=keep_alive_worker)
    t_ping.daemon = True
    t_ping.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
