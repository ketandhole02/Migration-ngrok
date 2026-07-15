import math
import logging
import numpy as np
import pandas as pd

from config import (
    BATCH_SIZE,
    SUPABASE_SCHEMA
)


def sanitize_row(row):
    """
    Convert a DataFrame row's values to native Python types safe for pyodbc.
    Handles: numpy scalars, NaN, NaT, None.
    """
    safe = []
    for v in row:
        if v is None:
            safe.append(None)
        elif isinstance(v, float) and math.isnan(v):
            safe.append(None)
        elif isinstance(v, pd.Timestamp):
            safe.append(None if pd.isnull(v) else v.to_pydatetime())
        elif type(v).__module__ == "numpy":
            native = v.item()
            safe.append(
                None if isinstance(native, float) and math.isnan(native)
                else native
            )
        else:
            safe.append(v)
    return safe


def load_table(
    pg_conn,
    sql_conn,
    table_metadata,
    system_id
):
    """
    Reads source table from Supabase (via psycopg2) and loads into SQL Server.
    """

    source_table = table_metadata["source_table"]
    target_table = table_metadata["target_table"]

    logging.info(f"Loading {source_table} -> {target_table}")

    source_df = pd.read_sql(
        f"""
        SELECT *
        FROM {SUPABASE_SCHEMA}.{source_table}
        WHERE system_id = %s
        """,
        pg_conn,
        params=[system_id]
    )

    if source_df.empty:
        logging.info(f"{source_table} has no rows for system_id={system_id}")
        return 0

    rows_loaded = insert_dataframe(
        sql_conn,
        target_table,
        source_df
    )

    return rows_loaded


def insert_dataframe(
    sql_conn,
    target_table,
    dataframe
):
    """
    Inserts a DataFrame into the SQL Server target table in batches.
    Handles IDENTITY_INSERT automatically.
    """

    # Resolve target columns and identity column before opening cursor
    target_columns  = get_target_columns(sql_conn, target_table)
    identity_column = get_identity_column(sql_conn, target_table)

    source_columns = [
        col for col in dataframe.columns
        if col in target_columns and col != "system_id"
    ]

    if not source_columns:
        raise RuntimeError(
            f"{target_table}: No matching columns between source and target. "
            f"Source cols: {list(dataframe.columns)}, "
            f"Target cols: {target_columns}"
        )

    dataframe = dataframe[source_columns]

    # Determine identity_insert BEFORE entering try/finally
    # so the finally block can always reference it safely
    identity_insert = (
        identity_column is not None
        and identity_column in source_columns
    )

    placeholders = ",".join(["?"] * len(source_columns))
    insert_sql = (
        f"INSERT INTO dbo.{target_table} "
        f"({','.join(source_columns)}) "
        f"VALUES ({placeholders})"
    )

    total_rows = len(dataframe)
    cursor = sql_conn.cursor()

    try:
        if identity_insert:
            cursor.execute(
                f"SET IDENTITY_INSERT dbo.{target_table} ON"
            )

        # fast_executemany intentionally OFF — causes MemoryError with
        # NULL values and numpy scalar types from pandas DataFrames.
        cursor.fast_executemany = False

        for start in range(0, total_rows, BATCH_SIZE):
            end      = start + BATCH_SIZE
            batch_df = dataframe.iloc[start:end]

            rows = [sanitize_row(row) for row in batch_df.values.tolist()]

            cursor.executemany(insert_sql, rows)
            sql_conn.commit()

            logging.info(
                f"{target_table} - Loaded rows "
                f"{start + 1}-{min(end, total_rows)} of {total_rows}"
            )

        return total_rows

    finally:
        # identity_insert is always defined here (set before try)
        if identity_insert:
            cursor.execute(
                f"SET IDENTITY_INSERT dbo.{target_table} OFF"
            )
            sql_conn.commit()

        cursor.close()


def get_target_columns(sql_conn, target_table):
    """Return column names of the SQL Server target table."""

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
            f"Target table dbo.{target_table} not found in SQL Server "
            f"or has no columns. Verify the table name in the registry."
        )

    return df["COLUMN_NAME"].tolist()


def get_identity_column(sql_conn, target_table):
    """Return the IDENTITY column name, or None if none exists."""

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