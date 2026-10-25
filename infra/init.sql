-- Extensions nécessaires à Jazzar (exécuté une seule fois à la création du volume).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Rôle en lecture seule pour le moteur Text-to-SQL (BI as Code).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'jazzar_ro') THEN
    CREATE ROLE jazzar_ro LOGIN PASSWORD 'jazzar_ro';
  END IF;
END $$;
GRANT CONNECT ON DATABASE jazzar TO jazzar_ro;
GRANT USAGE ON SCHEMA public TO jazzar_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO jazzar_ro;
