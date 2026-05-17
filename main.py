import requests
import time
import json
import os
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string

TRACKED_WALLET = os.environ.get("TRACKED_WALLET", "0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8897942683:AAGMdMMwhVPdwXOYAgQFUI_sCm_1q5GMJT4")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8087284904")
MY_PORTFOLIO_START = float(os.environ.get("MY_PORTFOLIO", "6000"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
PORT = int(os.environ.get("PORT", "8080"))

STATE_FILE = "last_seen.json"
TRADES_FILE = "trades.json"
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
SKIP_KEYWORDS = ["up or down"]

app = Flask(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CarPolyTracker</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0d0f14; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; }
  .header { padding: 24px 32px; border-bottom: 1px solid #1e2535; display: flex; align-items: center; justify-content: space-between; }
  .header h1 { font-size: 20px; font-weight: 700; color: #fff; }
  .header h1 span { color: #6366f1; }
  .updated { font-size: 12px; color: #4a5568; }
  .container { max-width: 1100px; margin: 0 auto; padding: 32px; }
  .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }
  .stat-card { background: #161b27; border: 1px solid #1e2535; border-radius: 12px; padding: 20px; }
  .stat-label { font-size: 12px; color: #4a5568; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }
  .stat-value { font-size: 28px; font-weight: 700; color: #fff; }
  .stat-sub { font-size: 12px; color: #4a5568; margin-top: 4px; }
  .positive { color: #10b981; }
  .negative { color: #ef4444; }
  .neutral { color: #6366f1; }
  .section { background: #161b27; border: 1px solid #1e2535; border-radius: 12px; padding: 24px; margin-bottom: 24px; }
  .section-title { font-size: 14px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 20px; }
  .chart-wrap { position: relative; height: 220px; }
  table { width: 100%; border-collapse: collapse; }
  th { font-size: 11px; color: #4a5568; text-transform: uppercase; letter-spacing: 0.05em; padding: 8px 12px; text-align: left; border-bottom: 1px solid #1e2535; }
  td { padding: 14px 12px; border-bottom: 1px solid #1a2030; font-size: 14px; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #1a2030; }
  .badge { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
  .badge-won { background: #052e16; color: #10b981; }
  .badge-lost { background: #2d1515; color: #ef4444; }
  .badge-pending { background: #1e1b4b; color: #818cf8; }
  .badge-yes { background: #052e16; color: #10b981; }
  .badge-no { background: #2d1515; color: #ef4444; }
  .market-title { max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .win-bar-wrap { background: #1e2535; border-radius: 8px; height: 8px; width: 100%; margin-top: 8px; }
  .win-bar { background: #6366f1; height: 8px; border-radius: 8px; transition: width 0.5s; }
  @media (max-width: 768px) {
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
    .container { padding: 16px; }
    .market-title { max-width: 180px; }
  }
</style>
</head>
<body>
<div class="header">
  <h1>Car<span>Poly</span>Tracker</h1>
  <div class="updated" id="updated">Nalaganje...</div>
</div>
<div class="container">
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">Win Rate</div>
      <div class="stat-value" id="win-rate">—</div>
      <div class="win-bar-wrap"><div class="win-bar" id="win-bar" style="width:0%"></div></div>
      <div class="stat-sub" id="win-sub">— / — zadetkov</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Skupaj stav</div>
      <div class="stat-value neutral" id="total-trades">—</div>
      <div class="stat-sub" id="pending-sub">— odprtih</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Simulirani portfolio</div>
      <div class="stat-value" id="sim-portfolio">—</div>
      <div class="stat-sub" id="portfolio-sub">start ${{ start }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Skupni P&L</div>
      <div class="stat-value" id="total-pnl">—</div>
      <div class="stat-sub" id="pnl-pct">—</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Simulirani portfolio skozi čas</div>
    <div class="chart-wrap">
      <canvas id="portfolioChart"></canvas>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Sledene stave</div>
    <table>
      <thead>
        <tr>
          <th>Market</th>
          <th>Stran</th>
          <th>Car stavi</th>
          <th>Tvoj predlog</th>
          <th>Car %</th>
          <th>Status</th>
          <th>P&L</th>
        </tr>
      </thead>
      <tbody id="trades-table">
        <tr><td colspan="7" style="color:#4a5568;text-align:center;padding:32px">Nalaganje...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<script>
let chart = null;

function fmt(n) { return n >= 0 ? '+$' + Math.round(n) : '-$' + Math.round(Math.abs(n)); }
function fmtPct(n) { return (n >= 0 ? '+' : '') + n.toFixed(1) + '%'; }

async function load() {
  const res = await fetch('/api/data');
  const d = await res.json();

  document.getElementById('updated').textContent = 'Posodobljeno: ' + new Date().toLocaleTimeString('sl-SI');

  const resolved = d.trades.filter(t => t.status !== 'pending');
  const won = d.trades.filter(t => t.status === 'won');
  const pending = d.trades.filter(t => t.status === 'pending');
  const winRate = resolved.length ? (won.length / resolved.length * 100) : 0;
  const totalPnl = resolved.reduce((s, t) => s + (t.user_pnl || 0), 0);
  const simPortfolio = d.simulated_portfolio;
  const pct = (simPortfolio - d.start) / d.start * 100;

  document.getElementById('win-rate').textContent = resolved.length ? Math.round(winRate) + '%' : '—';
  document.getElementById('win-rate').className = 'stat-value ' + (winRate >= 50 ? 'positive' : 'negative');
  document.getElementById('win-bar').style.width = winRate + '%';
  document.getElementById('win-sub').textContent = won.length + ' / ' + resolved.length + ' zadetkov';
  document.getElementById('total-trades').textContent = d.trades.length;
  document.getElementById('pending-sub').textContent = pending.length + ' odprtih';
  document.getElementById('sim-portfolio').textContent = '$' + Math.round(simPortfolio);
  document.getElementById('sim-portfolio').className = 'stat-value ' + (simPortfolio >= d.start ? 'positive' : 'negative');
  document.getElementById('total-pnl').textContent = fmt(totalPnl);
  document.getElementById('total-pnl').className = 'stat-value ' + (totalPnl >= 0 ? 'positive' : 'negative');
  document.getElementById('pnl-pct').textContent = fmtPct(pct) + ' od starta';

  // Chart
  let running = d.start;
  const labels = ['Start'];
  const values = [d.start];
  const sortedResolved = resolved.sort((a, b) => a.timestamp - b.timestamp);
  sortedResolved.forEach(t => {
    running += (t.user_pnl || 0);
    labels.push(new Date(t.timestamp * 1000).toLocaleDateString('sl-SI'));
    values.push(Math.round(running));
  });

  if (chart) chart.destroy();
  chart = new Chart(document.getElementById('portfolioChart'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99,102,241,0.08)',
        borderWidth: 2,
        pointRadius: 4,
        pointBackgroundColor: '#6366f1',
        fill: true,
        tension: 0.3
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: '#1e2535' }, ticks: { color: '#4a5568', font: { size: 11 } } },
        y: { grid: { color: '#1e2535' }, ticks: { color: '#4a5568', font: { size: 11 }, callback: v => '$' + v } }
      }
    }
  });

  // Table
  const tbody = document.getElementById('trades-table');
  if (!d.trades.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="color:#4a5568;text-align:center;padding:32px">Še ni sledenih stav</td></tr>';
    return;
  }
  const sorted = [...d.trades].sort((a, b) => b.timestamp - a.timestamp);
  tbody.innerHTML = sorted.map(t => {
    const statusBadge = t.status === 'won' ? '<span class="badge badge-won">✓ Zadetek</span>'
      : t.status === 'lost' ? '<span class="badge badge-lost">✗ Zgrešeno</span>'
      : '<span class="badge badge-pending">● Odprto</span>';
    const outcomeBadge = t.outcome && t.outcome.toLowerCase() === 'yes'
      ? `<span class="badge badge-yes">${t.outcome}</span>`
      : `<span class="badge badge-no">${t.outcome || '?'}</span>`;
    const pnlCell = t.user_pnl != null
      ? `<span class="${t.user_pnl >= 0 ? 'positive' : 'negative'}">${fmt(t.user_pnl)}</span>`
      : '<span style="color:#4a5568">—</span>';
    return `<tr>
      <td><div class="market-title" title="${t.title}">${t.title}</div></td>
      <td>${outcomeBadge}</td>
      <td>$${Math.round(t.car_amount || 0)}</td>
      <td>$${Math.round(t.user_suggestion || 0)}</td>
      <td>${t.car_pct != null ? t.car_pct.toFixed(1) + '%' : '—'}</td>
      <td>${statusBadge}</td>
      <td>${pnlCell}</td>
    </tr>`;
  }).join('');
}

load();
setInterval(load, 30000);
</script>
</body>
</html>
""".replace("{{ start }}", str(int(MY_PORTFOLIO_START)))


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/data")
def api_data():
    db = load_trades()
    db["start"] = MY_PORTFOLIO_START
    return jsonify(db)


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
    return {"last_timestamp": 0}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ── Logika ────────────────────────────────────────────────────────────────────

def should_skip(title):
    return any(kw in title.lower() for kw in SKIP_KEYWORDS)


def format_notification(trade, car_portfolio, user_suggestion, pct):
    title = trade.get("title", "Neznan market")
    outcome = trade.get("outcome", "?")
    usdc = float(trade.get("usdcSize", 0))
    price = float(trade.get("price", 0))
    event_slug = trade.get("eventSlug", "")
    condition_id = trade.get("conditionId", "")
    market_url = f"https://polymarket.com/event/{event_slug}" if event_slug else "https://polymarket.com"

    prices = get_market_prices(condition_id)
    yes_price = prices.get("yes")
    no_price = prices.get("no")
    price_line = f"📈 Cene: <b>YES {yes_price*100:.0f}¢</b> | <b>NO {no_price*100:.0f}¢</b>\n" if yes_price and no_price else ""

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
    redeems = {a["conditionId"] for a in activity if a.get("type") == "REDEEM"}

    changed = False
    now = time.time()

    for trade in pending:
        cid = trade["conditionId"]

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
                f"📈 Simulirani portfolio: <b>${db['simulated_portfolio']:.0f}</b>"
            )
            continue

        end_date = trade.get("endDate")
        if end_date:
            try:
                end_ts = datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%SZ").timestamp()
            except Exception:
                try:
                    end_ts = datetime.strptime(end_date, "%Y-%m-%d").timestamp()
                except Exception:
                    end_ts = None

            if end_ts and now > end_ts + 86400:
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
                    f"📉 Simulirani portfolio: <b>${db['simulated_portfolio']:.0f}</b>"
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
        f"💼 Simulirani portfolio:\n"
        f"   Start: <b>${MY_PORTFOLIO_START:.0f}</b>\n"
        f"   Zdaj: <b>${sim_portfolio:.0f}</b>\n"
        f"   Sprememba: <b>{'+'if portfolio_change >= 0 else ''}{portfolio_change:.0f} ({portfolio_pct:+.1f}%)</b>\n\n"
        f"💵 Skupni P&L: <b>{'+'if total_pnl >= 0 else ''}{total_pnl:.0f} USDC</b>"
    )


# ── Telegram ukazi ────────────────────────────────────────────────────────────

def command_listener(db_ref):
    global MY_PORTFOLIO_START
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
                        f"⏳ Odprte stave: {pending}\n"
                        f"💼 Simulirani portfolio: ${db_ref[0].get('simulated_portfolio', MY_PORTFOLIO_START):.0f}"
                    )
                elif text.startswith("/setportfolio"):
                    parts = text.split()
                    if len(parts) == 2:
                        try:
                            new_val = float(parts[1])
                            MY_PORTFOLIO_START = new_val
                            send_telegram(f"✅ Portfolio nastavljen na ${new_val:.0f}")
                        except ValueError:
                            send_telegram("❌ Primer: /setportfolio 8000")
        except Exception as e:
            print(f"Command listener napaka: {e}")
        time.sleep(2)


# ── Main ──────────────────────────────────────────────────────────────────────

def bot_loop(db_ref):
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

    resolve_counter = 0

    while True:
        try:
            db = db_ref[0]
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
            print(f"Napaka v bot zanki: {e}")

        time.sleep(POLL_INTERVAL)


def main():
    print("CarPolyTracker zagnan.")
    db = load_trades()
    db_ref = [db]

    threading.Thread(target=bot_loop, args=(db_ref,), daemon=True).start()
    threading.Thread(target=command_listener, args=(db_ref,), daemon=True).start()

    app.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
