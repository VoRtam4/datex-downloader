# Datex Downloader – Modul pro příjem a distribuci NDIC zpráv

Tento modul slouží jako samostatná komponenta systému pro monitorování otevřených dat v reálném čase. 
Jeho hlavním účelem je příjem zpráv NDIC ve formátu Datex II, jejich zpracování, ukládání a distribuce v rámci systému.

---

## Účel modulu
Datex Downloader poskytuje rozhraní pro příjem zpráv od NDIC, ověřuje jejich správnost, 
ukládá je do souborového úložiště a zpřístupňuje je dalším částem systému prostřednictvím HTTP API a WebSocket připojení. 
Zároveň vede statistiky o přijatých zprávách a přístupech k API.

---

## Použité technologie
- **Python 3.11+** – implementace serveru.
- **FastAPI** – webový framework pro HTTP a WebSocket endpointy.
- **uvicorn** – ASGI server pro běh aplikace.
- **xml.etree.ElementTree** – zpracování a validace XML dat.
- **gzip** a **zipfile** – komprese a dekomprese dat.
- **threading.Lock** – zajištění bezpečného přístupu k uloženým datům z více vláken.

---

## Funkcionalita
- Příjem zpráv NDIC přes endpoint `/datex-in` s podporou **HTTP Basic autentizace**.
- Ověření a uložení zpráv ve formátu XML do adresáře `ndic_messages`.
- Poskytování poslední zprávy nebo všech zpráv ke stažení.
- Zpřístupnění zpráv přes WebSocket v reálném čase připojeným klientům.
- Sledování statistik přijatých zpráv a přístupů k API, generování HTML přehledu statistik.

---

## Struktura projektu
- **main.py** – hlavní aplikace FastAPI se všemi endpointy.
- **storage.py** – třída `DatexStorage` pro ukládání poslední zprávy a správu WebSocket klientů.
- **requirements.txt** – přehled potřebných Python knihoven.

---

## Hlavní endpointy

| Endpoint                 | Metoda  | Popis |
|--------------------------|--------|------|
| `/datex-in`              | POST   | Přijímá NDIC zprávy, ověřuje autentizaci, zpracovává a ukládá zprávy. |
| `/download/all.zip`      | GET    | Vrací všechny uložené zprávy jako ZIP archiv. |
| `/api/latest`            | GET    | Vrací poslední zprávu ve formátu JSON. |
| `/api/latest.xml`        | GET    | Vrací poslední zprávu ve formátu XML. |
| `/statistic`             | GET    | Vrací HTML stránku se statistikami přijatých zpráv. |

---

# Nasazení a spuštění

### Příprava prostředí
Projekt je připraven pro nasazení pomocí **Docker Compose**.  
Stačí mít nainstalovaný **Docker** a **Docker Compose**.

### Spuštění aplikace
```bash
docker-compose up --build -d
```

- `--build` zajistí, že se při spuštění přegeneruje image (vhodné při změnách v kódu).  
- `-d` spustí aplikaci v „detached“ režimu (na pozadí).

Po spuštění bude aplikace dostupná na adrese:
```
http://localhost:8000
```
*(Port lze upravit v souboru `docker-compose.yml`, pokud je potřeba jiný).*

### Zastavení aplikace
```bash
docker-compose down
```

---

## Nasazené prostředí pro testovací účely

V rámci testování pro ověření funkcionality v rámci BP byl systém nasazen na VPS, kde je možné systém testovat na adrese:[http://http://http://80.211.200.65:8000](http://http://http://80.211.200.65:8000/statistic).  

---

## Kontext použití
Tento modul funguje jako samostatná služba systému pro monitorování otevřených dat v reálném čase. 
Předává zprávy NDIC v jednotném formátu do dalších komponent systému a zároveň umožňuje klientům sledovat zprávy prostřednictvím API a WebSocket připojení.
