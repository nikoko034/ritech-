# RiTech SAS – Análisis NASDAQ-100 (Flask + PostgreSQL)

## Puesta en marcha
1. Instala PostgreSQL y crea la BD:  `createdb -U postgres ritech`
2. `pip install -r requirements.txt`
3. (Si tu usuario/clave difieren) `export DATABASE_URL=postgresql://USUARIO:CLAVE@localhost:5432/ritech`
4. `python app.py`  → abre http://127.0.0.1:5000  (al arrancar crea las tablas y carga datos demo)

## Cómo funciona la base de datos
- `indice_nasdaq`: un registro por día (fecha única, valor de cierre, variación % vs día anterior, calculada automáticamente).
- `simulaciones`: guarda cada cálculo (monto, variación, rendimiento, valor final, recomendación).
- Python se conecta con `psycopg2`; Flask expone una API (`/api/...`) y la página la consume con `fetch`.
- `schema.sql` es idempotente (`IF NOT EXISTS`): se puede ejecutar varias veces sin duplicar nada.

## Regla de negocio
Índice ≥ 0 → rendimiento = variación × 2 (2 % → 4 %). Índice < 0 → rendimiento = variación × 1,25 (−2 % → −2,5 %).
