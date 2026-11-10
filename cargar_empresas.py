"""Carga TODO el histórico día a día: empresas del NASDAQ-100 + índice (^NDX).
Uso: python cargar_empresas.py                     (desde 2025-01-01; borra y recarga todo)
     python cargar_empresas.py --desde 2024-01-01
     python cargar_empresas.py --sin-limpiar        (actualiza sin borrar)
     python cargar_empresas.py --tickers AAPL,MSFT  (si Wikipedia falla)"""
import os, io, sys, time, argparse
import pandas as pd, psycopg2, requests, yfinance as yf
from psycopg2.extras import execute_values

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ritech")
ap = argparse.ArgumentParser()
ap.add_argument("--desde", default="2025-01-01"); ap.add_argument("--tickers")
ap.add_argument("--sin-limpiar", action="store_true"); ap.add_argument("--limpiar", action="store_true")  # --limpiar se ignora
a = ap.parse_args()

SEC = dict(T="Information Technology", C="Communication Services", D="Consumer Discretionary", S="Consumer Staples",
           H="Health Care", I="Industrials", U="Utilities", F="Financials", E="Energy", M="Materials", R="Real Estate")
# Lista de respaldo (aprox.; la composición del índice cambia de vez en cuando)
RESPALDO = """AAPL|Apple|T;MSFT|Microsoft|T;NVDA|Nvidia|T;AMZN|Amazon|D;GOOGL|Alphabet (A)|C;GOOG|Alphabet (C)|C;META|Meta Platforms|C;
AVGO|Broadcom|T;TSLA|Tesla|D;COST|Costco|S;NFLX|Netflix|C;TMUS|T-Mobile US|C;CSCO|Cisco|T;PEP|PepsiCo|S;LIN|Linde|M;ADBE|Adobe|T;
AMD|AMD|T;QCOM|Qualcomm|T;INTU|Intuit|T;TXN|Texas Instruments|T;AMGN|Amgen|H;ISRG|Intuitive Surgical|H;BKNG|Booking Holdings|D;
HON|Honeywell|I;AMAT|Applied Materials|T;CMCSA|Comcast|C;VRTX|Vertex Pharmaceuticals|H;PANW|Palo Alto Networks|T;ADP|ADP|I;
GILD|Gilead Sciences|H;ADI|Analog Devices|T;SBUX|Starbucks|D;MU|Micron|T;LRCX|Lam Research|T;MELI|MercadoLibre|D;INTC|Intel|T;
KLAC|KLA|T;APP|AppLovin|T;CRWD|CrowdStrike|T;REGN|Regeneron|H;MDLZ|Mondelez|S;CDNS|Cadence|T;SNPS|Synopsys|T;PYPL|PayPal|F;
MAR|Marriott|D;ORLY|O'Reilly Automotive|D;CTAS|Cintas|I;ASML|ASML|T;CEG|Constellation Energy|U;MRVL|Marvell|T;ABNB|Airbnb|D;
FTNT|Fortinet|T;ADSK|Autodesk|T;DASH|DoorDash|D;WDAY|Workday|T;ROP|Roper Technologies|T;CHTR|Charter Communications|C;
PCAR|Paccar|I;NXPI|NXP Semiconductors|T;AEP|American Electric Power|U;CPRT|Copart|I;FAST|Fastenal|I;MNST|Monster Beverage|S;
PAYX|Paychex|I;ROST|Ross Stores|D;KDP|Keurig Dr Pepper|S;ODFL|Old Dominion Freight Line|I;BKR|Baker Hughes|E;EXC|Exelon|U;
CCEP|Coca-Cola Europacific|S;FANG|Diamondback Energy|E;XEL|Xcel Energy|U;VRSK|Verisk|I;EA|Electronic Arts|C;CTSH|Cognizant|T;
KHC|Kraft Heinz|S;LULU|Lululemon|D;TTWO|Take-Two Interactive|C;GEHC|GE HealthCare|H;DDOG|Datadog|T;IDXX|Idexx Laboratories|H;
CSGP|CoStar Group|R;ON|ON Semiconductor|T;TEAM|Atlassian|T;ZS|Zscaler|T;CDW|CDW|T;BIIB|Biogen|H;TTD|The Trade Desk|C;
MDB|MongoDB|T;GFS|GlobalFoundries|T;DXCM|DexCom|H;WBD|Warner Bros. Discovery|C;ARM|Arm Holdings|T;PDD|PDD Holdings|D;
MCHP|Microchip Technology|T;CSX|CSX|I;AZN|AstraZeneca|H;SHOP|Shopify|T;PLTR|Palantir|T;AXON|Axon Enterprise|I;
TRI|Thomson Reuters|I;FER|Ferrovial|I;ALNY|Alnylam|H;INSM|Insmed|H;MSTR|Strategy|T"""

def desde_wikipedia():
    try:
        html = requests.get("https://en.wikipedia.org/wiki/Nasdaq-100", headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
        for x in pd.read_html(io.StringIO(html)):
            x.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in x.columns]
            col = {c.lower(): c for c in x.columns}
            tk = next((col[c] for c in col if "ticker" in c or "symbol" in c), None)
            nm = next((col[c] for c in col if "company" in c or "name" in c), None)
            if tk and nm and len(x) >= 80:
                sc = next((col[c] for c in col if "sector" in c), None)
                return [(str(r[tk]).strip().replace(".", "-"), str(r[nm]), str(r[sc]) if sc else "N/D") for r in x.to_dict("records")]
    except Exception as e:
        print("Wikipedia no respondió como se esperaba:", e)
    return None

if a.tickers:
    emp = [(t.strip().upper(), t.strip().upper(), "N/D") for t in a.tickers.split(",")]
else:
    emp = desde_wikipedia()
    if not emp:
        print("Usando la lista de respaldo incluida en el script.")
        emp = [(p[0], p[1], SEC[p[2]]) for p in (x.strip().split("|") for x in RESPALDO.replace("\n", "").split(";"))]
print(f"{len(emp)} empresas. Descargando precios desde {a.desde} (1 a 3 minutos)...")

def serie(tk):
    h = yf.Ticker(tk).history(start=a.desde, auto_adjust=False)["Close"].dropna()
    h.index = pd.to_datetime(h.index).tz_localize(None)
    return h

def bajar(tickers):
    out = {}
    for i in range(0, len(tickers), 20):
        lote = tickers[i:i + 20]
        for intento in range(3):
            try:
                px = yf.download(lote, start=a.desde, auto_adjust=False, progress=False, threads=False)["Close"]
                if isinstance(px, pd.Series): px = px.to_frame(lote[0])
                for tk in px.columns:
                    s = px[tk].dropna()
                    if not s.empty: out[tk] = s
                break
            except Exception as e:
                print(f"  reintentando lote {i // 20 + 1}: {e}"); time.sleep(3)
        print(f"  {min(i + 20, len(tickers))}/{len(tickers)} procesadas")
    for tk in tickers:  # las que faltaron se piden una por una
        if tk not in out:
            try:
                s = serie(tk)
                if not s.empty: out[tk] = s
            except Exception:
                pass
    return out

def filas(s, dec):
    s = s.sort_index(); ch = (s.pct_change() * 100).round(4)
    return [(d.date(), round(float(v), dec), None if pd.isna(c) else float(c)) for d, v, c in zip(s.index, s.values, ch.values)]

precios = bajar([e[0] for e in emp])
print("Descargando el índice NASDAQ-100 (^NDX)...")
ndx = bajar(["^NDX"]).get("^NDX")
if not precios: sys.exit("No se pudo descargar ninguna empresa. Revisa tu internet y vuelve a intentar.")

try:
    con = psycopg2.connect(DSN)
except Exception as e:
    sys.exit(f"No se pudo conectar a PostgreSQL: {e}\nRevisa que esté encendido y que la contraseña sea correcta (variable DATABASE_URL).")
with con, con.cursor() as cur:
    cur.execute(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql"), encoding="utf-8").read())
    if not a.sin_limpiar:
        cur.execute("DELETE FROM empresas"); cur.execute("DELETE FROM indice_nasdaq")
    if ndx is not None:
        execute_values(cur, """INSERT INTO indice_nasdaq (fecha,valor,variacion_pct) VALUES %s ON CONFLICT (fecha)
            DO UPDATE SET valor=EXCLUDED.valor, variacion_pct=EXCLUDED.variacion_pct""", filas(ndx, 2))
    execute_values(cur, """INSERT INTO empresas (ticker,nombre,sector) VALUES %s
        ON CONFLICT (ticker) DO UPDATE SET nombre=EXCLUDED.nombre, sector=EXCLUDED.sector""", [e for e in emp if e[0] in precios])
    rows = [(tk,) + r for tk, s in precios.items() for r in filas(s, 4)]
    execute_values(cur, """INSERT INTO precios_empresa (ticker,fecha,cierre,variacion_pct) VALUES %s
        ON CONFLICT (ticker,fecha) DO UPDATE SET cierre=EXCLUDED.cierre, variacion_pct=EXCLUDED.variacion_pct""", rows, page_size=5000)
    cur.execute("SELECT to_char(date_trunc('month',fecha),'YYYY-MM'), COUNT(*) FROM indice_nasdaq GROUP BY 1 ORDER BY 1")
    print("\nDías por mes (índice):", "  ".join(f"{m}: {n}" for m, n in cur.fetchall()))
    cur.execute("SELECT COUNT(DISTINCT ticker), MIN(fecha), MAX(fecha), COUNT(*) FROM precios_empresa")
    n, mi, ma, t = cur.fetchone()
    print(f"Empresas con precios: {n} | Registros: {t} | Del {mi} al {ma}")
print("Sin datos en Yahoo:", ", ".join(e[0] for e in emp if e[0] not in precios) or "ninguna")
print("Listo ✔")
