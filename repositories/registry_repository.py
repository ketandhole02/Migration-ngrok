import os
import pyodbc
import psycopg2
from supabase import create_client

from dotenv import load_dotenv

load_dotenv()


def get_supabase_connection():
    """
    Returns a supabase-py client.
    Used by migration_engine.py (REST API path).
    """
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
    conn_string = os.getenv("SUPABASE_PG_CONNECTION")

    if not conn_string:
        raise EnvironmentError(
            "SUPABASE_PG_CONNECTION is not set in .env"
        )

    return psycopg2.connect(conn_string)


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

    if not server:
        raise ValueError("SQL Server host is required")
    if not database:
        raise ValueError("Database name is required")
    if not username:
        raise ValueError("SQL username is required")
    if not password:
        raise ValueError("SQL password is required")

    conn_string = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=yes;"
    )

    return pyodbc.connect(conn_string)