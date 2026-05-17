import requests
import time
import json
import os
import threading
from datetime import datetime

TRACKED_WALLET = os.environ.get("TRACKED_WALLET", "0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8897942683:AAGMdMMwhVPdwXOYAgQFUI_sCm_1q5GMJT4")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8087284904")
MY_PORTFOLIO_START = float(os.environ.get("MY_PORTFOLIO", "6000"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))

STATE_FILE = "last_seen.json"
TRADES_FILE = "trades.json"
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

SKIP_KEYWORDS = ["up or down"]


# ── Telegram ──────────────────────────────────────────────────────────────────

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


def get_telegram_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 20, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=25)
        if r.status_code == 200:
            return r.json().get("result", [])
    except Exception:
        pass
    return []


# ── Polymarket API ─────────────────────────────────────────────────────────────

def get_activity(wallet, limit=20):
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


def get_market_info(condition_id):
    try:
        r = requests.get(f"{GAMMA_API}/markets?conditionId={condition_id}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data:
                return data[0]
    except Exception as e:
        print(f"Market API napaka: {e}")
    return None


# ── Trades baza ───────────────────────────────────────────────────────────────

def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE) as f:
            return json.load(f)
    return {"trades": [], "simulated_portfolio": MY_PORTFOLIO_START}


def save_trades(db):
    with open(TRADES_FILE, "w") as f:
        json.dump(db, f, indent=2)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_timestamp": 0, "last_redeem_timestamp": 0}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ── Logika ────────────────────────────────────────────────────────────────────

def should_skip(title):
    title_lower = title.lower()
    return any(kw in title_lower for kw in SKIP_KEYWORDS)


def get_market_prices(condition_id):
    try:
        r = requests.get(f"https://clob.polymarket.com/markets/{condition_id}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            tokens = data.get("tokens", [])
            prices = {}
            for token in tokens:
                outcome = token.get("outcome", "").lower()
                price = float(token.get("price", 0))
                prices[outcome] = price
            return prices
    except Exception as e:
        print(f"CLOB API napaka: {e}")
    return {}


def format_notification(trade, car_portfolio, user_suggestion, pct):
    title = trade.get("title", "Neznan market")
    outcome = trade.get("outcome", "?")
    usdc = float(trade.get("usdcSize", 0))
    price = float(trade.get("price", 0))
    event_slug = trade.get("eventSlug", "")
    condition_id = trade.get("conditionId", "")
    market_url = f"https://polymarket.com/event/{event_slug}" if event_slug else "https://polymarket.com"

    prices = get_market_prices(condition_id)
    yes_price = prices.get("yes", None)
    no_price = prices.get("no", None)
    if yes_price and no_price:
        price_line = f"📈 Cene: <b>YES {yes_price*100:.0f}¢</b> | <b>NO {no_price*100:.0f}¢</b>\n"
    else:
        price_line = ""

    if car_portfolio and pct:
        sizing = (
            f"📐 Car stavi <b>{pct:.1f}%</b> portfelja\n"
            f"💡 Tvoj predlog: <b>${user_suggestion:.0f}</b> ({pct:.1f}% od ${MY_PORTFOLIO_START:.0f})"
        )
    else:
        sizing = f"💡 Tvoj predlog: <b>${user_suggestion:.0f}</b>"

    return (
        f"🚨 <b>@Car je pravkar stavu!</b>\n\n"
        f"📊 {title}\n"
        f"📍 Stran: <b>{outcome}</b> @ {price*100:.0f}¢\n"
        f"{price_line}"
        f"💵 Znesek: <b>${usdc:.0f} USDC</b>\n\n"
        f"{sizing}\n\n"
        f"🔗 <a href='{market_url}'>Odpri market</a>"
    )


def check_resolutions(db, state):
    pending = [t for t in db["trades"] if t["status"] == "pending"]
    if not pending:
        return False

    activity = get_activity(TRACKED_WALLET, limit=50)
    redeems = {
        a["conditionId"]: a
        for a in activity
        if a.get("type") == "REDEEM"
    }

    changed = False
    now = time.time()

    for trade in pending:
        cid = trade["conditionId"]

        # Zmaga: Car je redemal ta market
        if cid in redeems:
            pnl = trade["user_suggestion"] * (1 / trade["price"] - 1)
            db["simulated_portfolio"] += pnl
            trade["status"] = "won"
            trade["user_pnl"] = round(pnl, 2)
            changed = True
            send_telegram(
                f"✅ <b>Zadetek!</b>\n\n"
                f"📊 {trade['title']}\n"
                f"📍 <b>{trade['outcome']}</b> je zmagal\n\n"
                f"💰 Simulirani dobiček: <b>+${pnl:.0f}</b>\n"
                f"📈 Tvoj simulirani portfolio: <b>${db['simulated_portfolio']:.0f}</b>"
            )
            continue

        # Poraz: market je potekel (endDate v preteklosti) in ni redemptiona
        end_date = trade.get("endDate")
        if end_date:
            try:
                end_ts = datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%SZ").timestamp()
            except Exception:
                try:
                    end_ts = datetime.strptime(end_date, "%Y-%m-%d").timestamp()
                except Exception:
                    end_ts = None

            if end_ts and now > end_ts + 86400:  # 24h po izteku
                pnl = -trade["user_suggestion"]
                db["simulated_portfolio"] += pnl
                trade["status"] = "lost"
                trade["user_pnl"] = round(pnl, 2)
                changed = True
                send_telegram(
                    f"❌ <b>Zgrešeno.</b>\n\n"
                    f"📊 {trade['title']}\n"
                    f"📍 <b>{trade['outcome']}</b> ni zmagal\n\n"
                    f"💸 Simulirana izguba: <b>-${abs(pnl):.0f}</b>\n"
                    f"📉 Tvoj simulirani portfolio: <b>${db['simulated_portfolio']:.0f}</b>"
                )

    return changed


def format_stats(db):
    trades = db["trades"]
    resolved = [t for t in trades if t["status"] in ("won", "lost")]
    pending = [t for t in trades if t["status"] == "pending"]
    won = [t for t in resolved if t["status"] == "won"]

    win_rate = (len(won) / len(resolved) * 100) if resolved else 0
    total_pnl = sum(t.get("user_pnl", 0) for t in resolved)
    sim_portfolio = db.get("simulated_portfolio", MY_PORTFOLIO_START)
    portfolio_change = sim_portfolio - MY_PORTFOLIO_START
    portfolio_pct = (portfolio_change / MY_PORTFOLIO_START * 100) if MY_PORTFOLIO_START else 0

    return (
        f"📊 <b>Performance tracker</b>\n\n"
        f"🎯 Car-jeva natančnost: <b>{win_rate:.0f}%</b> ({len(won)}/{len(resolved)} zadetkov)\n"
        f"⏳ Odprte stave: <b>{len(pending)}</b>\n\n"
        f"💼 Tvoj simulirani portfolio:\n"
        f"   Start: <b>${MY_PORTFOLIO_START:.0f}</b>\n"
        f"   Zdaj: <b>${sim_portfolio:.0f}</b>\n"
        f"   Sprememba: <b>{'+'if portfolio_change >= 0 else ''}{portfolio_change:.0f} ({portfolio_pct:+.1f}%)</b>\n\n"
        f"💵 Skupni simulirani P&L: <b>{'+'if total_pnl >= 0 else ''}{total_pnl:.0f} USDC</b>"
    )


# ── Telegram ukazi ────────────────────────────────────────────────────────────

def command_listener(db_ref):
    offset = None
    while True:
        try:
            updates = get_telegram_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip().lower()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                if chat_id != TELEGRAM_CHAT_ID:
                    continue

                if text == "/stats":
                    send_telegram(format_stats(db_ref[0]))
                elif text == "/status":
                    pending = len([t for t in db_ref[0]["trades"] if t["status"] == "pending"])
                    send_telegram(
                        f"✅ Bot teče\n"
                        f"👁 Sledim: @Car\n"
                        f"⏳ Odprte stave v sledenju: {pending}\n"
                        f"💼 Simulirani portfolio: ${db_ref[0].get('simulated_portfolio', MY_PORTFOLIO_START):.0f}"
                    )
                elif text.startswith("/setportfolio"):
                    parts = text.split()
                    if len(parts) == 2:
                        try:
                            new_val = float(parts[1])
                            global MY_PORTFOLIO_START
                            MY_PORTFOLIO_START = new_val
                            send_telegram(f"✅ Portfolio nastavljen na ${new_val:.0f}")
                        except ValueError:
                            send_telegram("❌ Napačen format. Primer: /setportfolio 8000")
        except Exception as e:
            print(f"Command listener napaka: {e}")
        time.sleep(2)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("CarPolyTracker zagnan.")
    db = load_trades()
    db_ref = [db]

    state = load_state()
    last_timestamp = state["last_timestamp"]

    if last_timestamp == 0:
        activity = get_activity(TRACKED_WALLET, limit=1)
        if activity:
            last_timestamp = float(activity[0].get("timestamp", 0))
            state["last_timestamp"] = last_timestamp
            save_state(state)

    send_telegram(
        f"✅ <b>CarPolyTracker aktiven!</b>\n\n"
        f"👁 Sledim: @Car\n"
        f"💼 Tvoj portfolio: ${MY_PORTFOLIO_START:.0f}\n"
        f"🔄 Polling: vsakih {POLL_INTERVAL}s\n\n"
        f"Ukazi: /stats · /status · /setportfolio"
    )

    t = threading.Thread(target=command_listener, args=(db_ref,), daemon=True)
    t.start()

    resolve_counter = 0

    while True:
        try:
            activity = get_activity(TRACKED_WALLET, limit=10)
            new_buys = [
                a for a in activity
                if a.get("type") == "TRADE"
                and a.get("side") == "BUY"
                and float(a.get("timestamp", 0)) > last_timestamp
                and not should_skip(a.get("title", ""))
            ]

            if new_buys:
                car_portfolio = get_car_portfolio(TRACKED_WALLET)
                for trade in reversed(new_buys):
                    usdc = float(trade.get("usdcSize", 0))
                    price = float(trade.get("price", 0.5))
                    pct = (usdc / car_portfolio * 100) if car_portfolio else None
                    user_suggestion = (pct / 100 * MY_PORTFOLIO_START) if pct else 0

                    send_telegram(format_notification(trade, car_portfolio, user_suggestion, pct))

                    market_info = get_market_info(trade.get("conditionId", ""))
                    end_date = market_info.get("endDate") if market_info else None

                    db["trades"].append({
                        "id": f"{trade.get('conditionId','')}_{trade.get('timestamp','')}",
                        "conditionId": trade.get("conditionId", ""),
                        "title": trade.get("title", ""),
                        "outcome": trade.get("outcome", ""),
                        "car_amount": usdc,
                        "car_portfolio": car_portfolio,
                        "car_pct": round(pct, 2) if pct else None,
                        "user_suggestion": round(user_suggestion, 2),
                        "price": price,
                        "timestamp": float(trade.get("timestamp", 0)),
                        "endDate": end_date,
                        "status": "pending",
                        "user_pnl": None
                    })
                    print(f"Nova stava: {trade.get('title', '?')} | ${usdc}")

                last_timestamp = max(float(t.get("timestamp", 0)) for t in new_buys)
                state["last_timestamp"] = last_timestamp
                save_state(state)
                save_trades(db)

            resolve_counter += 1
            if resolve_counter >= (300 // POLL_INTERVAL):
                changed = check_resolutions(db, state)
                if changed:
                    save_trades(db)
                resolve_counter = 0

        except Exception as e:
            print(f"Napaka v glavni zanki: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
