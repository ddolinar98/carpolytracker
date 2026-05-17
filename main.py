import requests
import time
import json
import os

TRACKED_WALLET = os.environ.get("TRACKED_WALLET", "0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8897942683:AAGMdMMwhVPdwXOYAgQFUI_sCm_1q5GMJT4")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8087284904")
MY_PORTFOLIO = float(os.environ.get("MY_PORTFOLIO", "6000"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
STATE_FILE = "last_seen.json"

DATA_API = "https://data-api.polymarket.com"


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
    except Exception as e:
        print(f"Telegram napaka: {e}")


def get_activity(wallet, limit=10):
    try:
        r = requests.get(f"{DATA_API}/activity?user={wallet}&limit={limit}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"Activity API napaka: {e}")
    return []


def get_car_portfolio(wallet):
    try:
        r = requests.get(f"{DATA_API}/positions?user={wallet}&sizeThreshold=0&limit=500", timeout=10)
        if r.status_code == 200:
            positions = r.json()
            return sum(float(p.get("currentValue", 0)) for p in positions)
    except Exception as e:
        print(f"Portfolio API napaka: {e}")
    return None


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_timestamp": 0}


def save_state(timestamp):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_timestamp": timestamp}, f)


def format_message(trade, car_portfolio):
    title = trade.get("title", "Neznan market")
    outcome = trade.get("outcome", "?")
    usdc = float(trade.get("usdcSize", 0))
    price = float(trade.get("price", 0))
    event_slug = trade.get("eventSlug", "")
    market_url = f"https://polymarket.com/event/{event_slug}" if event_slug else "https://polymarket.com"

    if car_portfolio and car_portfolio > 0 and usdc > 0:
        pct = (usdc / car_portfolio) * 100
        my_suggestion = (pct / 100) * MY_PORTFOLIO
        sizing = (
            f"📐 <b>Car stavi {pct:.1f}% portfelja</b>\n"
            f"💡 Tvoj predlog: <b>${my_suggestion:.0f}</b> ({pct:.1f}% od ${MY_PORTFOLIO:.0f})"
        )
    else:
        sizing = f"💵 Znesek: <b>${usdc:.0f} USDC</b>"

    return (
        f"🚨 <b>@Car je pravkar stavu!</b>\n\n"
        f"📊 {title}\n"
        f"📍 Stran: <b>{outcome}</b> @ ${price:.3f}\n"
        f"💵 Znesek: <b>${usdc:.0f} USDC</b>\n\n"
        f"{sizing}\n\n"
        f"🔗 <a href='{market_url}'>Odpri market</a>"
    )


def main():
    print("CarPolyTracker zagnan.")
    send_telegram(
        "✅ <b>CarPolyTracker aktiven!</b>\n\n"
        f"👁 Sledim: @Car\n"
        f"💼 Tvoj portfolio: ${MY_PORTFOLIO:.0f}\n"
        f"🔄 Interval: vsakih {POLL_INTERVAL}s\n\n"
        "Dobiš notification takoj ko @Car stavi."
    )

    state = load_state()
    last_timestamp = state["last_timestamp"]

    # Na prvem zagonu nastavi last_timestamp na zadnji trade (da ne pošlje starih)
    if last_timestamp == 0:
        trades = get_activity(TRACKED_WALLET, limit=1)
        if trades:
            last_timestamp = trades[0].get("timestamp", 0)
            save_state(last_timestamp)
            print(f"Inicializirano — sledim od: {last_timestamp}")

    while True:
        try:
            trades = get_activity(TRACKED_WALLET, limit=10)
            new_buys = [
                t for t in trades
                if t.get("type") == "TRADE"
                and t.get("side") == "BUY"
                and float(t.get("timestamp", 0)) > last_timestamp
            ]

            new_buys = [t for t in new_buys if "up or down" not in t.get("title", "").lower()]

            if new_buys:
                car_portfolio = get_car_portfolio(TRACKED_WALLET)
                for trade in reversed(new_buys):
                    msg = format_message(trade, car_portfolio)
                    send_telegram(msg)
                    print(f"Notification: {trade.get('title', '?')} | ${trade.get('usdcSize', 0)}")

                last_timestamp = max(float(t.get("timestamp", 0)) for t in new_buys)
                save_state(last_timestamp)

        except Exception as e:
            print(f"Napaka v glavni zanki: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
