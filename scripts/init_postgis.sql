-- ==============================================================================
-- JOSEPO MEJORADO - INICIALIZACIÓN POSTGRESQL 16 + POSTGIS 3.4 (FASE 7)
-- Ejecutado automáticamente por el contenedor postgis/postgis al inicializar BD
-- ==============================================================================

-- 1. Activar extensiones geoespaciales y de rendimiento
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 2. Función geodésica auxiliar PostGIS para cálculo de distancia en KM (WGS84 SRID 4326)
CREATE OR REPLACE FUNCTION josepo_distance_km(
    lat1 DOUBLE PRECISION,
    lng1 DOUBLE PRECISION,
    lat2 DOUBLE PRECISION,
    lng2 DOUBLE PRECISION
) RETURNS DOUBLE PRECISION AS $$
BEGIN
    RETURN ST_DistanceSphere(
        ST_MakePoint(lng1, lat1),
        ST_MakePoint(lng2, lat2)
    ) / 1000.0;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

