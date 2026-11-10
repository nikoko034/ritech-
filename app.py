import os
from datetime import date
import psycopg2, psycopg2.extras
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

@app.after_request
def sin_cache(r):
    r.headers["Cache-Control"] = "no-store"  # el navegador nunca guarda la página vieja
    return r
DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ritech")

def db():
    return psycopg2.connect(DSN, cursor_factory=psycopg2.extras.RealDictCursor)

def init_db():
    with db() as c, c.cursor() as cur:
        cur.execute(open(os.path.join(os.path.dirname(__file__), "schema.sql"), encoding="utf-8").read())

# ---- Reglas de negocio (PB-12 a PB-16) ----
# +2% índice -> +4% inversión (x2). -2% índice -> -2,5% inversión (x1,25).
def rendimiento(var):
    return var * 2.0 if var >= 0 else var * 1.25

def recomendar(var):
    if var >= 2:   t = "Escenario favorable: el índice sube con fuerza y la inversión se amplifica."
    elif var >= 0: t = "Escenario estable o levemente positivo: se sugiere mantener la posición."
    elif var > -2: t = "Caída moderada: se sugiere monitorear antes de decidir."
    else:          t = "Caída fuerte: se sugiere evaluar el riesgo con un profesional financiero."
    return t + " (Recomendación informativa; no sustituye el criterio de un profesional financiero.)"

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/historico")
def historico():
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT fecha::text, valor::float, variacion_pct::float FROM indice_nasdaq ORDER BY fecha")
        return jsonify(cur.fetchall())

@app.post("/api/indice")
def agregar_indice():
    d = request.get_json(force=True)
    try:
        fecha, valor = d["fecha"], float(d["valor"])
        assert valor > 0
    except Exception:
        return jsonify(error="Datos inválidos: fecha y valor > 0"), 400
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT valor::float AS v FROM indice_nasdaq WHERE fecha < %s ORDER BY fecha DESC LIMIT 1", (fecha,))
        prev = cur.fetchone()
        var = round((valor - prev["v"]) / prev["v"] * 100, 4) if prev else None
        cur.execute("""INSERT INTO indice_nasdaq (fecha, valor, variacion_pct) VALUES (%s,%s,%s)
                       ON CONFLICT (fecha) DO UPDATE SET valor=EXCLUDED.valor, variacion_pct=EXCLUDED.variacion_pct""",
                    (fecha, valor, var))
    return jsonify(ok=True, variacion_pct=var)

@app.post("/api/simular")
def simular():
    d = request.get_json(force=True)
    try:
        monto, var = float(d["monto"]), float(d["variacion"])
        assert monto > 0
    except Exception:
        return jsonify(error="Monto debe ser > 0 y variación numérica"), 400
    rend = round(rendimiento(var), 4)
    final = round(monto * (1 + rend / 100), 2)
    rec = recomendar(var)
    with db() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO simulaciones (monto, variacion_pct, rendimiento_pct, valor_final, recomendacion)
                       VALUES (%s,%s,%s,%s,%s)""", (monto, var, rend, final, rec))
    return jsonify(rendimiento_pct=rend, valor_final=final, diferencia=round(final - monto, 2), recomendacion=rec)

@app.get("/api/simulaciones")
def simulaciones():
    with db() as c, c.cursor() as cur:
        cur.execute("""SELECT to_char(creado_en,'YYYY-MM-DD HH24:MI') AS creado_en, COALESCE(ticker,'Índice') AS ticker, monto::float, variacion_pct::float,
                       rendimiento_pct::float, valor_final::float FROM simulaciones ORDER BY id DESC LIMIT 10""")
        return jsonify(cur.fetchall())

def _v(n):
    return f"ROUND(((MAX(CASE WHEN rn=1 THEN cierre END)/NULLIF(MAX(CASE WHEN rn={n} THEN cierre END),0)-1)*100)::numeric,2)::float"

SQL_EMP = f"""WITH r AS (SELECT ticker, fecha, cierre, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fecha DESC) rn FROM precios_empresa)
SELECT e.ticker, e.nombre, e.sector, MAX(CASE WHEN rn=1 THEN cierre END)::float AS cierre,
       MAX(CASE WHEN rn=1 THEN fecha END)::text AS fecha,
       {_v(2)} AS var_dia, {_v(22)} AS var_mes, {_v(253)} AS var_anio
FROM empresas e JOIN r ON r.ticker=e.ticker GROUP BY e.ticker, e.nombre, e.sector ORDER BY e.nombre"""

@app.get("/api/empresas")
def empresas():
    with db() as c, c.cursor() as cur:
        cur.execute(SQL_EMP)
        return jsonify(cur.fetchall())

@app.get("/api/empresa/<t>")
def empresa(t):
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT fecha::text, cierre::float FROM precios_empresa WHERE ticker=%s ORDER BY fecha DESC LIMIT 260", (t.upper(),))
        return jsonify(cur.fetchall()[::-1])

@app.post("/api/regla")
def regla_empresa():
    d = request.get_json(force=True)
    try:
        t, monto = str(d["ticker"]).upper(), float(d["monto"])
        desde, hasta = date.fromisoformat(d["desde"]), date.fromisoformat(d["hasta"])
        assert monto > 0 and desde <= hasta
    except Exception:
        return jsonify(error="Datos inválidos: empresa, monto > 0 y fechas correctas"), 400
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT nombre FROM empresas WHERE ticker=%s", (t,))
        emp = cur.fetchone()
        if not emp:
            return jsonify(error="Empresa no encontrada"), 404
        cur.execute("""SELECT fecha::text AS fecha, cierre::float AS cierre, variacion_pct::float AS var
                       FROM precios_empresa WHERE ticker=%s AND fecha BETWEEN %s AND %s ORDER BY fecha""", (t, desde, hasta))
        rows = cur.fetchall()
        if not rows:
            return jsonify(error="No hay datos de esa empresa en ese periodo"), 404
        cur.execute("SELECT cierre::float AS cierre FROM precios_empresa WHERE ticker=%s AND fecha<%s ORDER BY fecha DESC LIMIT 1", (t, desde))
        b = cur.fetchone()
        ini, fin = (b["cierre"] if b else rows[0]["cierre"]), rows[-1]["cierre"]
        var = round((fin / ini - 1) * 100, 4)
        rend = round(rendimiento(var), 4)
        final = round(monto * (1 + rend / 100), 2)
        txt = ("Con la regla, esta inversión habría generado ganancia en el periodo" if rend >= 0
               else "Con la regla, esta inversión habría generado pérdida en el periodo") + \
              ". Información de apoyo; no sustituye el criterio de un profesional financiero."
        cur.execute("""INSERT INTO simulaciones (monto, variacion_pct, rendimiento_pct, valor_final, recomendacion, ticker)
                       VALUES (%s,%s,%s,%s,%s,%s)""", (monto, var, rend, final, txt, t))
    dias = [{"fecha": r["fecha"], "cierre": r["cierre"], "var": r["var"],
             "regla": None if r["var"] is None else round(rendimiento(r["var"]), 4)} for r in rows]
    ult = {}
    for r in rows:
        ult[r["fecha"][:7]] = r["cierre"]
    meses, prev = [], ini
    for m, cz in ult.items():
        v = round((cz / prev - 1) * 100, 4)
        meses.append({"mes": m, "cierre": cz, "var": v, "regla": round(rendimiento(v), 4)})
        prev = cz
    return jsonify(ticker=t, nombre=emp["nombre"], desde=rows[0]["fecha"], hasta=rows[-1]["fecha"], precio_ini=ini, precio_fin=fin,
                   variacion_pct=var, rendimiento_pct=rend, valor_final=final, ganancia=round(final - monto, 2),
                   sin_regla=round(monto * (1 + var / 100), 2), recomendacion=txt, dias=dias, meses=meses)

# En la nube (gunicorn) no se ejecuta el bloque __main__, así que las tablas se crean aquí.
try:
    init_db()
except Exception as e:
    print("[RiTech v4] No se pudo inicializar la base:", e)

if __name__ == "__main__":
    try:
        with db() as c, c.cursor() as cur:
            cur.execute("""SELECT (SELECT COUNT(*) FROM indice_nasdaq) AS i, (SELECT MIN(fecha)::text FROM indice_nasdaq) AS d,
                           (SELECT COUNT(*) FROM empresas) AS e, (SELECT COUNT(*) FROM precios_empresa) AS p""")
            r = cur.fetchone()
        print(f"[RiTech v4] Carpeta: {os.path.dirname(os.path.abspath(__file__))}")
        print(f"[RiTech v4] Índice: {r['i']} días desde {r['d']} | Empresas: {r['e']} | Precios: {r['p']}")
    except Exception as e:
        print("[RiTech v4] No se pudo leer la base:", e)
    print("[RiTech v4] Abre en el navegador:  http://127.0.0.1:5050")
    app.run(debug=True, port=int(os.getenv("PORT", 5050)))
