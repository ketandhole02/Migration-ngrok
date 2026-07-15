import os
try:
    import pyodbc
except ImportError:  # SQLConnect mode does not need an ODBC driver in AIDE.
    pyodbc = None
try:
    import psycopg2
except ImportError:  # The REST-based migration engine does not use psycopg2.
    psycopg2 = None
try:
    from supabase import create_client
except ImportError:
    create_client = None
from remote_sql import RemoteSqlConnection

from dotenv import load_dotenv

load_dotenv()


def get_supabase_connection():
    """
    Returns a supabase-py client.
    Used by migration_engine.py (REST API path).
    """
    if create_client is None:
        raise RuntimeError("supabase is required to run a migration. Install requirements.txt.")

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url:
        raise EnvironmentError(
            "SUPABASE_URL is not set in .env"
        )

    if not key:
        raise EnvironmentError(
            "SUPABASE_SERVICE_ROLE_KEY is not set in .env"
        )

    return create_client(url, key)


def get_postgres_connection():
    """
    Returns a raw psycopg2 connection to Supabase PostgreSQL.
    Used by services layer (audit_service, load_service, etc.)
    which use cursor() / pd.read_sql() directly.
    """
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required for the services-layer migration path.")

    conn_string = os.getenv("SUPABASE_PG_CONNECTION")

    if not conn_string:
        raise EnvironmentError(
            "SUPABASE_PG_CONNECTION is not set in .env"
        )

    return psycopg2.connect(conn_string)


def get_sql_driver():
    """
    Return newest installed SQL Server ODBC driver.
    """
    if pyodbc is None:
        raise RuntimeError("pyodbc is required only for a direct SQL Server connection.")
    drivers = pyodbc.drivers()

    if "ODBC Driver 18 for SQL Server" in drivers:
        return "ODBC Driver 18 for SQL Server"

    if "ODBC Driver 17 for SQL Server" in drivers:
        return "ODBC Driver 17 for SQL Server"

    raise RuntimeError(
        f"No SQL Server ODBC driver found. Installed drivers: {drivers}"
    )

def get_sql_server_connection(
    server,
    port,
    database,
    username,
    password
):
    """
    Returns a pyodbc connection to SQL Server.
    """

    bridge_url = os.getenv("LOCAL_API_URL")
    bridge_token = os.getenv("LOCAL_API_TOKEN")
    if bridge_url or bridge_token:
        if not bridge_url or not bridge_token:
            raise EnvironmentError("LOCAL_API_URL and LOCAL_API_TOKEN must both be configured for SQLConnect.")
        return RemoteSqlConnection(bridge_url, bridge_token)

    if not server:
        raise ValueError("SQL Server host is required")
    if not database:
        raise ValueError("Database name is required")
    if not username:
        raise ValueError("SQL username is required")
    if not password:
        raise ValueError("SQL password is required")

    conn_string = (
        f"DRIVER={{{get_sql_driver()}}};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=yes;"
    )

    return pyodbc.connect(conn_string)
