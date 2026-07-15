import logging
import traceback
import pandas as pd

from config import DTE_SCH_REPO_DTM, DTE_SCH_REPO_DTS, BATCH_SIZE
from db import get_sql_server_connection, get_supabase_connection

# Log to both file and console so errors are visible everywhere
_handlers = [
    logging.FileHandler("migration.log"),
    logging.StreamHandler()
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=_handlers
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supabase helpers (use supabase-py REST client)
# ---------------------------------------------------------------------------

def get_system_threshold(supabase, system_id):
    """
    Fetch the threshold value for this system_id from Supabase.
    Column name: key_threshold_value (confirmed from migration.log).
    """
    logger.info(f"Fetching threshold for system_id={system_id}")

    try:
        result = (
            supabase.schema(DTE_SCH_REPO_DTS)
            .table("dts_ref_migration_interface_system_config")
            .select("key_threshold_value")
            .eq("system_id", system_id)
            .single()
            .execute()
        )
    except Exception as ex:
        raise RuntimeError(
            f"Failed to fetch system threshold for system_id={system_id}. "
            f"Check that the system_id exists in "
            f"aide_datastore.dts_ref_migration_interface_system_config. "
            f"Detail: {ex}"
        ) from ex

    if not result.data:
        raise RuntimeError(
            f"No threshold config found for system_id={system_id}. "
            f"Row may be missing in dts_ref_migration_interface_system_config."
        )

    value = result.data.get("key_threshold_value")
    logger.info(f"Threshold value: {value}")
    return value


def get_table_registry(supabase):
    """
    Fetch all active tables from the migration registry, ordered by migration_order.
    """
    logger.info("Fetching table registry from Supabase")

    try:
        result = (
            supabase.schema(DTE_SCH_REPO_DTS)
            .table("dts_ref_migration_interface_table_registry")
            .select("*")
            .eq("active_flag", True)
            .order("migration_order")
            .execute()
        )
    except Exception as ex:
        raise RuntimeError(
            f"Failed to fetch table registry from "
            f"aide_datastore.dts_ref_migration_interface_table_registry. "
            f"Detail: {ex}"
        ) from ex

    if not result.data:
        raise RuntimeError(
            "Table registry returned no active rows. "
            "Ensure active_flag=true rows exist in "
            "dts_ref_migration_interface_table_registry."
        )

    logger.info(f"Found {len(result.data)} tables in registry")
    return result.data


def fetch_source_data(supabase, source_table, system_id):
    """
    Fetch all rows for this system_id from the given source table
    in the aide_datamart schema via supabase-py REST client.
    """
    logger.info(f"Fetching source data: aide_datamart.{source_table}")

    try:
        result = (
            supabase.schema(DTE_SCH_REPO_DTM)
            .table(source_table)
            .select("*")
            .eq("system_id", system_id)
            .execute()
        )
    except Exception as ex:
        raise RuntimeError(
            f"Failed to fetch data from aide_datamart.{source_table} "
            f"for system_id={system_id}. "
            f"Check the table name in the registry and that the schema "
            f"permissions allow SELECT. Detail: {ex}"
        ) from ex

    df = pd.DataFrame(result.data)
    logger.info(f"Fetched {len(df)} rows from {source_table}")
    return df


# ---------------------------------------------------------------------------
# SQL Server helpers (use pyodbc)
# ---------------------------------------------------------------------------

def delete_target_data(
    sql_conn,
    target_table,
    delete_strategy,
    delete_column=None,
    delete_operator=None,
    threshold_value=None,
    custom_delete_sql=None
):
    """
    Delete target SQL Server data using the metadata-driven strategy.
    Strategies: NONE | FULL_DELETE | TRUNCATE | THRESHOLD | CUSTOM
    """
    logger.info(
        f"{target_table} - Delete strategy: {delete_strategy}"
    )

    cursor = sql_conn.cursor()

    try:
        if delete_strategy == "NONE":
            logger.info(f"{target_table} - No delete required")
            return 0

        elif delete_strategy == "FULL_DELETE":
            cursor.execute(f"DELETE FROM dbo.{target_table}")

        elif delete_strategy == "TRUNCATE":
            cursor.execute(f"TRUNCATE TABLE dbo.{target_table}")

        elif delete_strategy == "THRESHOLD":
            if not delete_column or not delete_operator:
                raise ValueError(
                    f"{target_table}: THRESHOLD strategy requires "
                    f"delete_column and delete_operator to be set in registry."
                )
            sql = (
                f"DELETE FROM dbo.{target_table} "
                f"WHERE {delete_column} {delete_operator} ?"
            )
            cursor.execute(sql, threshold_value)

        elif delete_strategy == "CUSTOM":
            if not custom_delete_sql:
                raise ValueError(
                    f"{target_table}: CUSTOM strategy requires "
                    f"custom_delete_sql to be set in registry."
                )
            # Custom SQL is self-contained — no params passed
            cursor.execute(custom_delete_sql)

        else:
            raise ValueError(
                f"{target_table}: Unknown delete strategy '{delete_strategy}'. "
                f"Valid values: NONE, FULL_DELETE, TRUNCATE, THRESHOLD, CUSTOM"
            )

        deleted_rows = cursor.rowcount
        sql_conn.commit()
        logger.info(f"{target_table} - Deleted {deleted_rows} rows")
        return deleted_rows

    except Exception:
        sql_conn.rollback()
        raise

    finally:
        cursor.close()


def get_target_columns(sql_conn, target_table):
    """Return list of column names that exist in the SQL Server target table."""
    df = pd.read_sql(
        f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME   = '{target_table}'
        """,
        sql_conn
    )

    if df.empty:
        raise RuntimeError(
            f"Target table dbo.{target_table} not found in SQL Server, "
            f"or it has no columns. Check the table name in the registry."
        )

    return df["COLUMN_NAME"].tolist()


def get_identity_column(sql_conn, target_table):
    """Return the identity column name for the target table, or None."""
    df = pd.read_sql(
        f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME   = '{target_table}'
          AND COLUMNPROPERTY(
                OBJECT_ID(TABLE_SCHEMA + '.' + TABLE_NAME),
                COLUMN_NAME,
                'IsIdentity'
              ) = 1
        """,
        sql_conn
    )

    if df.empty:
        return None

    return df.iloc[0]["COLUMN_NAME"]


def sanitize_row(row):
    """
    Convert a list of values from a DataFrame row into types that
    pyodbc can safely insert into SQL Server.

    Problems this solves:
    - pandas/numpy types (np.int64, np.float64, np.bool_) cause
      MemoryError with fast_executemany and type errors without it.
    - pd.NaT / float('nan') must become None (SQL NULL).
    - numpy.nan must become None.
    """
    import math
    import numpy as np

    safe = []
    for v in row:
        # Treat all NA-like values as None (SQL NULL)
        if v is None:
            safe.append(None)
        elif isinstance(v, float) and math.isnan(v):
            safe.append(None)
        elif isinstance(v, pd.Timestamp):
            safe.append(None if pd.isnull(v) else v.to_pydatetime())
        elif type(v).__module__ == "numpy":
            # Convert any numpy scalar to its Python native equivalent
            native = v.item()
            safe.append(None if isinstance(native, float) and math.isnan(native) else native)
        else:
            safe.append(v)
    return safe


def load_to_sql(sql_conn, target_table, dataframe):
    """
    Insert a DataFrame into the SQL Server target table in batches.
    - Strips system_id column (internal only).
    - Handles IDENTITY_INSERT automatically.
    - Sanitizes all values to native Python types before insert
      (avoids MemoryError caused by numpy types + fast_executemany).
    """
    target_cols  = get_target_columns(sql_conn, target_table)
    identity_col = get_identity_column(sql_conn, target_table)

    # Only keep columns that exist in target, drop system_id
    source_cols = [
        c for c in dataframe.columns
        if c in target_cols and c != "system_id"
    ]

    if not source_cols:
        raise RuntimeError(
            f"{target_table}: No matching columns found between source "
            f"and target. Source columns: {list(dataframe.columns)}. "
            f"Target columns: {target_cols}."
        )

    dataframe = dataframe[source_cols]

    identity_insert = (
        identity_col is not None and identity_col in source_cols
    )

    placeholders = ",".join(["?"] * len(source_cols))
    columns_str  = ",".join(source_cols)
    insert_sql   = (
        f"INSERT INTO dbo.{target_table} ({columns_str}) "
        f"VALUES ({placeholders})"
    )

    total_rows = len(dataframe)
    cursor = sql_conn.cursor()

    # NOTE: fast_executemany is intentionally OFF.
    # It causes MemoryError when rows contain NULL values or numpy scalar
    # types, which is common when data comes from a Supabase REST response
    # converted to a DataFrame. Standard executemany handles these safely.
    cursor.fast_executemany = False

    try:
        if identity_insert:
            cursor.execute(
                f"SET IDENTITY_INSERT dbo.{target_table} ON"
            )

        for start in range(0, total_rows, BATCH_SIZE):
            batch = dataframe.iloc[start: start + BATCH_SIZE]

            # Sanitize every row: convert numpy types and NaN/NaT to None
            rows = [sanitize_row(row) for row in batch.values.tolist()]

            cursor.executemany(insert_sql, rows)
            sql_conn.commit()

            end = min(start + BATCH_SIZE, total_rows)
            logger.info(
                f"{target_table} - Inserted rows "
                f"{start + 1}-{end} of {total_rows}"
            )

    finally:
        if identity_insert:
            cursor.execute(
                f"SET IDENTITY_INSERT dbo.{target_table} OFF"
            )
            sql_conn.commit()

        cursor.close()

    return total_rows


def validate_counts(source_df, sql_conn, target_table):
    """
    Compare source row count vs target row count after load.
    Logs a warning if they differ — does NOT raise, so migration continues.
    """
    source_count = len(source_df)

    target_count = pd.read_sql(
        f"SELECT COUNT(*) AS cnt FROM dbo.{target_table}",
        sql_conn
    ).iloc[0]["cnt"]

    if source_count == target_count:
        logger.info(
            f"{target_table} - Count validation PASSED "
            f"(rows={source_count})"
        )
    else:
        logger.warning(
            f"{target_table} - Count validation WARNING: "
            f"Source={source_count}, Target={target_count}. "
            f"Some rows may not have loaded correctly."
        )


# ---------------------------------------------------------------------------
# Per-table orchestration
# ---------------------------------------------------------------------------

def migrate_table(supabase, sql_conn, row, system_id):
    """
    Full cycle for one table:
      1. Delete target data
      2. Fetch source data from Supabase
      3. Load into SQL Server
      4. Validate counts
    """
    source_table  = row["source_table"]
    target_table  = row["target_table"]
    delete_strategy = row.get("delete_strategy", "NONE")

    logger.info(
        f"--- Starting table: {source_table} -> {target_table} ---"
    )

    # Step 1 — Delete
    delete_target_data(
        sql_conn        = sql_conn,
        target_table    = target_table,
        delete_strategy = delete_strategy,
        delete_column   = row.get("delete_column"),
        delete_operator = row.get("delete_operator"),
        threshold_value = row.get("_threshold_value"),  # injected below
        custom_delete_sql = row.get("custom_delete_sql")
    )

    # Step 2 — Fetch source
    df = fetch_source_data(supabase, source_table, system_id)

    if df.empty:
        logger.info(
            f"{source_table} has no rows for system_id={system_id}. "
            f"Skipping load."
        )
        return

    # Step 3 — Load
    load_to_sql(sql_conn, target_table, df)

    # Step 4 — Validate
    validate_counts(df, sql_conn, target_table)

    logger.info(f"--- Completed table: {target_table} ---")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_tables(supabase, sql_conn, system_id):
    """
    Orchestrate migration of all active tables in registry order.
    Each table failure is caught and logged; migration continues to next table.
    At the end, raises if any table failed.
    """
    threshold_value = get_system_threshold(supabase, system_id)
    registry        = get_table_registry(supabase)

    failed_tables = []

    for row in registry:
        # Inject threshold into row so migrate_table can access it
        row["_threshold_value"] = threshold_value
        target_table = row.get("target_table", "unknown")

        try:
            migrate_table(supabase, sql_conn, row, system_id)

        except Exception as ex:
            error_detail = traceback.format_exc()
            logger.error(
                f"FAILED table {target_table}: {ex}\n{error_detail}"
            )
            failed_tables.append((target_table, str(ex)))

    if failed_tables:
        summary = "\n".join(
            f"  • {t}: {e}" for t, e in failed_tables
        )
        raise RuntimeError(
            f"{len(failed_tables)} table(s) failed during migration:\n"
            f"{summary}\n"
            f"See migration.log for full details."
        )


def run_migration(
    system_id,
    server_name,
    port,
    database_name,
    username,
    password
):
    """
    Main migration entry point called by app.py.
    Returns a success message string, or raises with a clear error message.
    """
    logger.info(
        f"========== Migration started | system_id={system_id} =========="
    )

    sql_conn = None

    try:
        # Connect to SQL Server
        logger.info(
            f"Connecting to SQL Server: {server_name}:{port}/{database_name}"
        )
        try:
            sql_conn = get_sql_server_connection(
                server   = server_name,
                port     = port,
                database = database_name,
                username = username,
                password = password
            )
        except Exception as ex:
            raise RuntimeError(
                f"Cannot connect to SQL Server at {server_name}:{port}. "
                f"Check host, port, credentials, and that ODBC Driver 17 "
                f"is installed. Detail: {ex}"
            ) from ex

        # Connect to Supabase
        logger.info("Connecting to Supabase")
        try:
            supabase = get_supabase_connection()
        except Exception as ex:
            raise RuntimeError(
                f"Cannot connect to Supabase. "
                f"Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env. "
                f"Detail: {ex}"
            ) from ex

        # Run migration
        process_tables(supabase, sql_conn, system_id)

        logger.info(
            f"========== Migration completed | system_id={system_id} =========="
        )

        return (
            f"Migration completed successfully for system_id={system_id}."
        )

    except Exception as ex:
        logger.error(
            f"========== Migration FAILED ==========\n"
            f"{traceback.format_exc()}"
        )
        raise

    finally:
        if sql_conn:
            sql_conn.close()
            logger.info("SQL Server connection closed")