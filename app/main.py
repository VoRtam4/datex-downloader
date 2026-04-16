"""
@File: main.py
@Author: Dominik Vondruška
@Project: Bakalářská práce — Systém pro monitorování otevřených dat v reálném čase
@Description: API server pro příjem, ukládání a distribuci NDIC zpráv ve formátu Datex II.
"""
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, status, Depends, Response, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, FileResponse
import xml.etree.ElementTree as ET
import base64
import secrets
import gzip
import datetime
import json
import os
import threading
import time
import urllib.request
import zipfile
import pytz
from collections import deque
from pathlib import Path

app = FastAPI()
security = HTTPBasic()

TZ = pytz.timezone("Europe/Prague")

latest_raw = None
clients = set()

# Uživatelské jméno a heslo pro přijímání dat z NDIC.
USERNAME = os.getenv("DATEX_USERNAME", "")
PASSWORD = os.getenv("DATEX_PASSWORD", "")

# Konfigurace aktivního stahování NDIC snapshotu.
PULL_ENABLED = os.getenv("DATEX_PULL_ENABLED", "false").lower() == "true"
PULL_URL = os.getenv("DATEX_PULL_URL", "")
PULL_USERNAME = os.getenv("DATEX_PULL_USERNAME", "")
PULL_PASSWORD = os.getenv("DATEX_PULL_PASSWORD", "")
PULL_INTERVAL_SECONDS = int(os.getenv("DATEX_PULL_INTERVAL_SECONDS", "300"))
_poller_started = False

# Statistické fronty (FIFO) pro ukládání historie.
BASE_DIR = Path(__file__).resolve().parent.parent
received_stats = deque(maxlen=1000)
api_access_log = deque(maxlen=1000)
messages_log = deque(maxlen=50)

STATISTICS_FILE = BASE_DIR / "statistics.json"
XML_STORAGE_DIR = BASE_DIR / "ndic_messages"

# uchování statistik po dobu 30 dní.
STAT_RETENTION_DAYS = 30

os.makedirs(XML_STORAGE_DIR, exist_ok=True)

# Pomocné funkce pro práci se statistikami a stavem aplikace.
def save_statistics():
    """
    Uloží aktuální statistiky (received_stats, api_access_log, messages_log) do JSON souboru.
    Záznamy starší než STAT_RETENTION_DAYS dní jsou odstraněny.
    """
    now =  datetime.datetime.now(TZ)
    cutoff = now - datetime.timedelta(days=STAT_RETENTION_DAYS)
    while received_stats and received_stats[0][0] < cutoff:
        received_stats.popleft()
    while api_access_log and api_access_log[0][0] < cutoff:
        api_access_log.popleft()

    with open(STATISTICS_FILE, "w") as f:
        json.dump({
            "received_stats": [(ts.isoformat(), size) for ts, size in received_stats],
            "api_access_log": [(ts.isoformat(), ep) for ts, ep in api_access_log],
            "messages_log": [(ts.isoformat(), size, msg) for ts, size, msg in messages_log]
        }, f)

def load_statistics():
    """
    Při startu aplikace načte uložené statistiky z JSON souboru STATISTICS_FILE.
    Záznamy starší než STAT_RETENTION_DAYS dní nejsou načteny.
    """
    if os.path.exists(STATISTICS_FILE):
        try:
            with open(STATISTICS_FILE, "r") as f:
                data = json.load(f)
                now =  datetime.datetime.now(TZ)
                cutoff = now - datetime.timedelta(days=STAT_RETENTION_DAYS)
                received_stats.extend((datetime.datetime.fromisoformat(ts), size) for ts, size in data.get("received_stats", []) if datetime.datetime.fromisoformat(ts) >= cutoff)
                api_access_log.extend((datetime.datetime.fromisoformat(ts), ep) for ts, ep in data.get("api_access_log", []) if datetime.datetime.fromisoformat(ts) >= cutoff)
                messages_log.extend((datetime.datetime.fromisoformat(ts), size, msg) for ts, size, msg in data.get("messages_log", []))
        except Exception as e:
            print("Failed to load statistics:", e)

async def store_xml_message(raw_data: bytes):
    """
    Validuje, uloží a zveřejní jednu XML zprávu nezávisle na zdroji
    (HTTP push přes /datex-in nebo interní periodický pull).
    """
    global latest_raw
    latest_raw = raw_data.decode("utf-8")
    try:
        ET.fromstring(latest_raw)
    except ET.ParseError:
        raise HTTPException(status_code=400, detail="Invalid XML")

    timestamp = datetime.datetime.now(TZ)
    filename_only = f"{timestamp.isoformat().replace(':', '-')}.xml"
    filename = os.path.join(XML_STORAGE_DIR, filename_only)

    received_stats.append((timestamp, len(raw_data)))
    messages_log.append((timestamp, len(raw_data), filename_only))
    save_statistics()

    with open(filename, "w", encoding="utf-8") as f:
        f.write(latest_raw)

    files = sorted(os.listdir(XML_STORAGE_DIR))
    while len(files) > 50:
        os.remove(os.path.join(XML_STORAGE_DIR, files.pop(0)))

    disconnected_clients = set()
    for client in clients:
        try:
            await client.send_text(latest_raw)
        except RuntimeError:
            disconnected_clients.add(client)
    clients.difference_update(disconnected_clients)

def fetch_pull_xml() -> bytes:
    """
    Stáhne NDIC snapshot z oficiálního PULL endpointu.
    Podporuje volitelnou HTTP Basic autentizaci a gzip odpověď.
    """
    request = urllib.request.Request(
        PULL_URL,
        headers={
            "Accept": "application/xml, text/xml;q=0.9, */*;q=0.1",
            "Accept-Encoding": "gzip",
            "User-Agent": "riot-datex-downloader/1.0",
        },
    )

    if PULL_USERNAME or PULL_PASSWORD:
        credentials = f"{PULL_USERNAME}:{PULL_PASSWORD}".encode("utf-8")
        token = base64.b64encode(credentials).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")

    with urllib.request.urlopen(request, timeout=60) as response:
        raw_data = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw_data = gzip.decompress(raw_data)
        return raw_data

def pull_loop():
    """
    Periodicky stahuje poslední NDIC XML snapshot a ukládá ho stejnou cestou
    jako push data přijatá na /datex-in.
    """
    import asyncio

    while True:
        try:
            if not PULL_URL:
                print("DATEX pull is enabled but DATEX_PULL_URL is empty.")
            else:
                raw_data = fetch_pull_xml()
                asyncio.run(store_xml_message(raw_data))
        except Exception as e:
            print(f"DATEX pull failed: {e}")
        time.sleep(max(PULL_INTERVAL_SECONDS, 1))

@app.on_event("startup")
def startup_event():
    global _poller_started
    load_statistics()
    if PULL_ENABLED and not _poller_started:
        thread = threading.Thread(target=pull_loop, daemon=True)
        thread.start()
        _poller_started = True

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """
    Ověření přihlašovacích údajů pomocí HTTP Basic autentizace.
    Pokud jsou údaje neplatné, vrátí HTTP 401 Unauthorized.
    """
    if USERNAME == "" and PASSWORD == "":
        return ""

    correct_username = secrets.compare_digest(credentials.username, USERNAME)
    correct_password = secrets.compare_digest(credentials.password, PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@app.post("/datex-in")
async def datex_in(request: Request, username: str = Depends(verify_credentials)):
    """
    Přijímá příchozí NDIC zprávy (Datex II) přes POST endpoint.
    - Ověří přihlášení přes Basic Auth.
    - Rozbalí zprávu pokud je gzip komprimovaná.
    - Ověří, zda zpráva obsahuje validní XML.
    - Uloží zprávu do logu, statistik a na disk.
    - Pošle zprávu všem připojeným WebSocket klientům.
    """
    global latest_raw
    raw_data = await request.body()
    if request.headers.get("Content-Encoding") == "gzip":
        try:
            raw_data = gzip.decompress(raw_data)
        except Exception:
            raise HTTPException(status_code=400, detail="Failed to decompress gzip data")
    await store_xml_message(raw_data)
    return {"status": "ok"}

# Vrací nejnovější uloženou NDIC XML zprávu jako soubor ke stažení. Pokud není k dispozici žádná zpráva, vrátí 404.
@app.get("/download/latest.xml")
async def download_latest():
    if not messages_log:
        raise HTTPException(status_code=404, detail="No messages available")
    ts, _, filename = messages_log[-1]
    path = os.path.join(XML_STORAGE_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Latest XML file not found")
    return FileResponse(path, media_type="application/xml", filename="latest.xml")

# Vytvoří ZIP archiv se všemi uloženými NDIC zprávami a vrátí ho ke stažení.
@app.get("/download/all.zip")
async def download_all():
    zip_path = "/tmp/ndic_all_messages.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for file in os.listdir(XML_STORAGE_DIR):
            zf.write(os.path.join(XML_STORAGE_DIR, file), arcname=file)
    return FileResponse(zip_path, media_type="application/zip", filename="all_messages.zip")

# Vrací nejnovější uloženou zprávu ve formátu JSON (obsah pole latest_raw). Loguje přístup do statistik.
@app.get("/api/latest")
async def get_latest():
    api_access_log.append(( datetime.datetime.now(TZ), "/api/latest"))
    save_statistics()
    return {"latest_raw": latest_raw}

# Vrací nejnovější uloženou zprávu ve formátu XML. Pokud není žádná zpráva dostupná, vrátí 404.
@app.get("/api/latest.xml")
async def get_latest_xml():
    api_access_log.append(( datetime.datetime.now(TZ), "/api/latest.xml"))
    save_statistics()
    if latest_raw is None:
        raise HTTPException(status_code=404, detail="No data available")
    return Response(content=latest_raw, media_type="application/xml")

@app.get("/statistic")
async def get_statistic():
    """
    Generuje HTML stránku s přehledem statistik:
    - velikost zpráv a jejich čas,
    - intervaly mezi zprávami,
    - seznam posledních API přístupů.
    Součástí stránky je graf vytvořený pomocí knihovny Chart.js.
    """
    def format_cz_time(dt: datetime.datetime):
        return dt.strftime(f"%-d. %-m. %Y %H:%M:%S")

    received_intervals = [
        ((received_stats[i][0] - received_stats[i - 1][0]).total_seconds(), received_stats[i][0])
        for i in range(1, len(received_stats))
    ]
    iso_times = [t.isoformat() for t, _ in received_stats]
    sizes = [round(s / 1048576, 3) for _, s in received_stats]

    html = f"""
    <html><head><title>Statistiky</title>
    <link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>
    <script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
    <style>
        body {{ background-color: #f8f9fa; padding: 30px; }}
        .container {{ max-width: 900px; margin: auto; }}
        .chart-container {{ position: relative; height: 400px; }}
        canvas {{ background-color: #fff; border: 1px solid #ccc; border-radius: 8px; max-width: 100%; }}
    </style>
    </head>
    <body><div class="container">
    <h1 class="mb-4">Statistiky příchozích zpráv</h1>
    <div class="row mb-3">
        <div class="col-md-5">
            <label class="form-label">Od:</label><input class="form-control" type='datetime-local' id='from'>
        </div>
        <div class="col-md-5">
            <label class="form-label">Do:</label><input class="form-control" type='datetime-local' id='to'>
        </div>
        <div class="col-md-2 d-flex align-items-end">
            <button class="btn btn-primary w-100" onclick='updateChart()'>Zobrazit</button>
        </div>
    </div>
    <div class="mb-3 d-flex gap-3">
        <a class="btn btn-success" href="/download/latest.xml">Stáhnout poslední XML</a>
        <a class="btn btn-secondary" href="/download/all.zip">Stáhnout všechny zprávy (ZIP)</a>
    </div>
    <div class="chart-container">
    <canvas id="chart1"></canvas>
    </div>
    <script>
        const fullLabels = {json.dumps(iso_times)};
        const fullData = {json.dumps(sizes)};

        function formatCzTime(d) {{
            const day = d.getDate();
            const month = d.getMonth() + 1;
            const year = d.getFullYear();
            const hours = String(d.getHours()).padStart(2, '0');
            const minutes = String(d.getMinutes()).padStart(2, '0');
            const seconds = String(d.getSeconds()).padStart(2, '0');
            return `${{day}}. ${{month}}. ${{year}} ${{hours}}:${{minutes}}:${{seconds}}`;
        }}

        const ctx = document.getElementById('chart1').getContext('2d');
        const initialLabels = fullLabels.map(t => formatCzTime(new Date(t)));
        const chart = new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: initialLabels,
                datasets: [{{
                    label: 'Velikost zprávy (MB)',
                    data: fullData,
                    backgroundColor: 'rgba(75, 192, 192, 0.6)'
                }}]
            }},
            options: {{ responsive: true, maintainAspectRatio: false }}
        }});

        function updateChart() {{
            const from = new Date(document.getElementById('from').value);
            const to = new Date(document.getElementById('to').value);
            const filtered = fullLabels.map((t, i) => {{
                return {{ time: new Date(t), size: fullData[i] }};
            }}).filter(e =>
                (!isNaN(from) ? e.time >= from : true) &&
                (!isNaN(to) ? e.time <= to : true)
            );

            chart.data.labels = filtered.map(e => formatCzTime(e.time));
            chart.data.datasets[0].data = filtered.map(e => e.size);
            chart.update();
        }}
    </script>
    <h2 class="mt-5">Intervaly mezi zprávami (s)</h2><ul class="list-group mb-4">
    {''.join(f"<li class='list-group-item'>{interval:.2f} s – {format_cz_time(ts)}</li>" for interval, ts in received_intervals)}
    </ul>
    <h2>API přístupy</h2><ul class="list-group">
    {''.join(f"<li class='list-group-item'>{format_cz_time(t)} – {ep}</li>" for t, ep in list(api_access_log)[-20:])}
    </ul>
    </div></body></html>
    """
    return HTMLResponse(content=html)
