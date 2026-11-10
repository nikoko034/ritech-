-- Base de datos RiTech SAS (PostgreSQL)
CREATE TABLE IF NOT EXISTS indice_nasdaq (
  id            SERIAL PRIMARY KEY,
  fecha         DATE UNIQUE NOT NULL,          -- un registro por día
  valor         NUMERIC(12,2) NOT NULL CHECK (valor > 0),
  variacion_pct NUMERIC(8,4)                   -- % frente al día anterior
);
CREATE TABLE IF NOT EXISTS simulaciones (
  id              SERIAL PRIMARY KEY,
  creado_en       TIMESTAMP NOT NULL DEFAULT now(),
  monto           NUMERIC(16,2) NOT NULL CHECK (monto > 0),
  variacion_pct   NUMERIC(8,4) NOT NULL,       -- variación del NASDAQ-100 simulada
  rendimiento_pct NUMERIC(8,4) NOT NULL,       -- efecto sobre la inversión
  valor_final     NUMERIC(16,2) NOT NULL,
  recomendacion   TEXT NOT NULL
);
-- Los datos reales se cargan con: python cargar_datos.py --limpiar

-- Empresas que componen el NASDAQ-100 y su historial de precios
CREATE TABLE IF NOT EXISTS empresas (
  ticker VARCHAR(12) PRIMARY KEY,
  nombre VARCHAR(150) NOT NULL,
  sector VARCHAR(80)
);
CREATE TABLE IF NOT EXISTS precios_empresa (
  ticker VARCHAR(12) NOT NULL REFERENCES empresas(ticker) ON DELETE CASCADE,
  fecha DATE NOT NULL,
  cierre NUMERIC(14,4) NOT NULL,
  variacion_pct NUMERIC(8,4),
  PRIMARY KEY (ticker, fecha)
);

-- Simulaciones por empresa
ALTER TABLE simulaciones ADD COLUMN IF NOT EXISTS ticker VARCHAR(12);

-- Resumen mes a mes de cada empresa (se calcula solo a partir de los precios diarios)
CREATE OR REPLACE VIEW resumen_mensual AS
WITH m AS (
  SELECT ticker, date_trunc('month', fecha)::date AS mes,
         (array_agg(cierre ORDER BY fecha DESC))[1] AS cierre_mes,
         MIN(cierre) AS minimo, MAX(cierre) AS maximo, COUNT(*) AS dias
  FROM precios_empresa GROUP BY ticker, date_trunc('month', fecha))
SELECT ticker, mes, cierre_mes, minimo, maximo, dias,
       ROUND(((cierre_mes / NULLIF(LAG(cierre_mes) OVER (PARTITION BY ticker ORDER BY mes), 0) - 1) * 100)::numeric, 2) AS variacion_pct
FROM m;
