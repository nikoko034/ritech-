"""Carga datos REALES del NASDAQ-100 (^NDX) en PostgreSQL.

Uso:
  python cargar_datos.py --limpiar                  # descarga desde Yahoo Finance (desde 2020)
  python cargar_datos.py --limpiar --desde 2015-01-01
  python cargar_datos.py --csv historico.csv        # alternativa: CSV bajado de nasdaq.com
Se puede volver a ejecutar cuando quieras para actualizar hasta hoy (no duplica fechas).
"""
import os, argparse
import pandas as pd, psycopg2
from psycopg2.extras import execute_values

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ritech")
ap = argparse.ArgumentParser()
ap.add_argument("--desde", default="2020-01-01")
ap.add_argument("--csv")
ap.add_argument("--limpiar", action="store_true", help="borra los registros actuales (p. ej. la demo)")
a = ap.parse_args()

if a.csv:
    df = pd.read_csv(a.csv)
    df.columns = [c.strip().lower() for c in df.columns]
    f = next(c for c in df.columns if c in ("date", "fecha"))
    v = next(c for c in df.columns if c in ("close", "close/last", "cierre", "ultimo", "último", "price"))
    df = df[[f, v]]; df.columns = ["fecha", "valor"]
    df["valor"] = df["valor"].astype(str).str.replace(r"[$,]", "", regex=True).astype(float)
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
else:
    import yfinance as yf
    h = yf.download("^NDX", start=a.desde, auto_adjust=False, progress=False)
    c = h["Close"]
    if isinstance(c, pd.DataFrame): c = c.iloc[:, 0]
    c = c.dropna()
    if c.empty: raise SystemExit("No llegaron datos. Revisa tu internet o usa --csv.")
    df = pd.DataFrame({"fecha": c.index.date, "valor": c.values})

df = df.sort_values("fecha").drop_duplicates("fecha").reset_index(drop=True)
df["var"] = (df["valor"].pct_change() * 100).round(4)
rows = [(r.fecha, round(float(r.valor), 2), None if pd.isna(r.var) else float(r.var)) for r in df.itertuples()]

with psycopg2.connect(DSN) as con, con.cursor() as cur:
    cur.execute(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql"), encoding="utf-8").read())
    if a.limpiar: cur.execute("DELETE FROM indice_nasdaq")
    execute_values(cur, """INSERT INTO indice_nasdaq (fecha, valor, variacion_pct) VALUES %s
        ON CONFLICT (fecha) DO UPDATE SET valor = EXCLUDED.valor, variacion_pct = EXCLUDED.variacion_pct""", rows)
print(f"Listo: {len(rows)} registros ({rows[0][0]} a {rows[-1][0]}).")
