import os
import time
import requests
import hmac
import hashlib
import json
import google.generativeai as genai

# ==========================================
# 1. RENDER ENVIRONMENT VARIABLES
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
COINDCX_API_KEY = os.getenv("COINDCX_API_KEY")
COINDCX_SECRET_KEY = os.getenv("COINDCX_SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Paper Trading Mode: 'true' = Simulation, 'false' = Real Money
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# Gemini AI Setup
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("CRITICAL: GEMINI_API_KEY Missing!")

def send_critical_telegram(message):
    """Sends emergency/critical alerts to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[Telegram Emergency Log]: {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"🚨 [BOT ALERT - Paper: {PAPER_TRADING}]\n\n{message}"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Failed to send alert: {e}")

# ==========================================
# 2. COINDCX API HELPERS & SIMULATION
# ==========================================
def send_coindcx_request(endpoint, body):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY:
        return None
    
    url = f"https://api.coindcx.com{endpoint}"
    body['timestamp'] = int(round(time.time() * 1000))
    json_body = json.dumps(body, separators=(',', ':'))
    
    signature = hmac.new(
        bytes(COINDCX_SECRET_KEY, 'utf-8'),
        bytes(json_body, 'utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': COINDCX_API_KEY,
        'X-AUTH-SIGNATURE': signature
    }
    
    try:
        response = requests.post(url, data=json_body, headers=headers, timeout=10)
        return response.json()
    except Exception as e:
        send_critical_telegram(f"CoinDCX API Request Crash: {e}")
        return None

def get_coindcx_balance():
    """Fetches combined account balance in INR equivalent"""
    data = send_coindcx_request("/exchange/v1/users/balances", {})
    if not data or not isinstance(data, list):
        if PAPER_TRADING:
            return 1000.0  # Default simulation balance for testing
        return 0.0
    
    total_inr_bal = 0.0
    for b in data:
        currency = b.get('currency')
        balance = float(b.get('balance', 0))
        
        if currency == 'INR':
            total_inr_bal += balance
        elif currency == 'USDT':
            total_inr_bal += (balance * 87.0)
            
    if total_inr_bal == 0 and PAPER_TRADING:
        return 1000.0
        
    return total_inr_bal

def place_futures_order(pair, side, quantity, leverage):
    """Executes order or simulates it based on PAPER_TRADING flag"""
    if PAPER_TRADING:
        sim_msg = f"🟢 [PAPER TRADING SIMULATION]\nPair: {pair}\nSide: {side.upper()}\nQty: {quantity}\nLeverage: {leverage}x"
        print(sim_msg)
        send_critical_telegram(sim_msg)
        return {"status": "success", "mode": "paper_trading", "pair": pair}
    
    # Real live order execution
    body = {
        "side": side.lower(),
        "pair": pair,
        "order_type": "market",
        "total_quantity": quantity,
        "leverage": leverage
    }
    result = send_coindcx_request("/exchange/v1/derivatives/futures/orders/create", body)
    return result

# ==========================================
# 3. 20% DAILY STOP-LOSS SYSTEM
# ==========================================
DAILY_START_BALANCE = None
DAILY_STOP_LOSS_PERCENT = 20.0
TRADING_HALTED_FOR_TODAY = False

def check_daily_stop_loss():
    global DAILY_START_BALANCE, TRADING_HALTED_FOR_TODAY
    
    current_balance = get_coindcx_balance()
    if current_balance <= 0:
        return False

    if DAILY_START_BALANCE is None:
        DAILY_START_BALANCE = current_balance
        return False

    loss_percent = ((DAILY_START_BALANCE - current_balance) / DAILY_START_BALANCE) * 100
    
    if loss_percent >= DAILY_STOP_LOSS_PERCENT:
        if not TRADING_HALTED_FOR_TODAY:
            alert_msg = (
                f"🚨 20% DAILY STOP-LOSS TRIGGERED!\n"
                f"Start Balance: ₹{DAILY_START_BALANCE:.2f}\n"
                f"Current Balance: ₹{current_balance:.2f}\n"
                f"Total Loss: {loss_percent:.2f}%\n"
                f"Action: Trading completely HALTED for today."
            )
            print(alert_msg)
            send_critical_telegram(alert_msg)
            TRADING_HALTED_FOR_TODAY = True
        return True
    return False

# ==========================================
# 4. FULLY AUTONOMOUS GEMINI AI ENGINE
# ==========================================
def get_gemini_decision(current_inr_balance):
    prompt = f"""
    You are an autonomous AI Crypto Trading Manager on CoinDCX India.
    Current Wallet Balance: ₹{current_inr_balance:.2f}
    
    Full Authority Guidelines:
    1. You have complete freedom to choose ANY futures coin pair (e.g., "B-BTC_USDT", "B-ETH_USDT", "B-SOL_USDT", etc.).
    2. Analyze market structure and determine action ("BUY", "SELL", or "HOLD").
    3. Manage leverage and position size freely based on account balance and risk management.
    
    Reply ONLY in valid JSON:
    {{
        "decision": "BUY" | "SELL" | "HOLD",
        "pair": "B-ETH_USDT",
        "quantity": 0.01,
        "leverage": 5,
        "reason": "Short strategy explanation"
    }}
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(text)
    except Exception as e:
        send_critical_telegram(f"Gemini AI System Failure: {e}")
        return {"decision": "HOLD", "pair": "B-BTC_USDT", "quantity": 0, "leverage": 1, "reason": "AI Connection Error"}

# ==========================================
# 5. MAIN BOT LOOP
# ==========================================
def run_bot():
    print(f"Bot online: Autonomous Gemini AI trading engine active. [Paper Trading Mode: {PAPER_TRADING}]")
    while True:
        try:
            # 1. Evaluate Daily 20% Stop Loss Guard
            if check_daily_stop_loss():
                time.sleep(3600)
                continue

            # 2. Get Current Account Balance
            current_bal = get_coindcx_balance()

            # 3. Get Autonomous Decision from Gemini AI
            ai_signal = get_gemini_decision(current_bal)
            decision = ai_signal.get("decision", "HOLD")
            pair = ai_signal.get("pair", "B-BTC_USDT")
            qty = float(ai_signal.get("quantity", 0))
            leverage = int(ai_signal.get("leverage", 1))
            
            print(f"AI Signal: {decision} | Pair: {pair} | Leverage: {leverage}x | Reason: {ai_signal.get('reason')}")

            # 4. Execute or Simulate Order
            if decision in ["BUY", "SELL"] and qty > 0:
                result = place_futures_order(pair, decision, qty, leverage)
                print(f"Order Output: {result}")

            # Re-evaluate every 5 minutes
            time.sleep(300)
            
        except Exception as e:
            send_critical_telegram(f"Uncaught Bot Crash: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()
