import uuid
import time
import logging
import traceback

from config import MAX_RETRIES

from repositories.registry_repository import (
    get_registry,
    get_system_threshold
)

from services.delete_service import (
    delete_target_data
)

from services.load_service import (
    load_table
)

from services.reconciliation_service import (
    run_reconciliation
)

from services.audit_service import (
    AuditService
)

from db import (
    get_postgres_connection,   # psycopg2 — correct for services layer
    get_sql_server_connection
)

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    )
)


def run_migration(
    system_id,
    server,
    port,
    database,
    username,
    password
):
    """
    Services-layer migration entry point.
    Uses psycopg2 directly (not supabase-py).
    Includes full audit logging and per-table retry.
    """

    execution_id = str(uuid.uuid4())

    pg_conn  = None
    sql_conn = None

    try:
        logging.info(
            f"Starting migration RunId={execution_id}"
        )

        # psycopg2 connection — compatible with cursor() and pd.read_sql
        try:
            pg_conn = get_postgres_connection()
        except Exception as ex:
            raise RuntimeError(
                f"Cannot connect to Supabase PostgreSQL. "
                f"Check SUPABASE_PG_CONNECTION in .env. Detail: {ex}"
            ) from ex

        try:
            sql_conn = get_sql_server_connection(
                server   = server,
                port     = port,
                database = database,
                username = username,
                password = password
            )
        except Exception as ex:
            raise RuntimeError(
                f"Cannot connect to SQL Server at {server}:{port}. "
                f"Detail: {ex}"
            ) from ex

        audit_service = AuditService(pg_conn)

        audit_service.create_run(
            execution_id = execution_id,
            system_id    = system_id
        )

        threshold_value = get_system_threshold(pg_conn, system_id)

        registry = get_registry(pg_conn)

        logging.info(f"Found {len(registry)} tables to process")

        for table_metadata in registry:

            process_table_with_retry(
                pg_conn         = pg_conn,
                sql_conn        = sql_conn,
                audit_service   = audit_service,
                table_metadata  = table_metadata,
                threshold_value = threshold_value,
                system_id       = system_id,
                execution_id    = execution_id
            )

        audit_service.complete_run(execution_id)

        logging.info(
            f"Migration completed RunId={execution_id}"
        )

        return (
            f"Migration completed successfully. "
            f"Run Id: {execution_id}"
        )

    except Exception as ex:

        logging.error(
            f"Migration failed RunId={execution_id}\n"
            f"{traceback.format_exc()}"
        )

        if pg_conn:
            try:
                audit_service.fail_run(execution_id, str(ex))
            except Exception:
                pass

        raise

    finally:
        if sql_conn:
            sql_conn.close()
        if pg_conn:
            pg_conn.close()


def process_table_with_retry(
    pg_conn,
    sql_conn,
    audit_service,
    table_metadata,
    threshold_value,
    system_id,
    execution_id
):
    """
    Wraps process_table with retry logic (MAX_RETRIES attempts, 5s backoff).
    """

    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            process_table(
                pg_conn         = pg_conn,
                sql_conn        = sql_conn,
                audit_service   = audit_service,
                table_metadata  = table_metadata,
                threshold_value = threshold_value,
                system_id       = system_id,
                execution_id    = execution_id
            )
            return

        except Exception as ex:
            last_exception = ex
            logging.error(
                f"Attempt {attempt}/{MAX_RETRIES} failed for "
                f"{table_metadata['target_table']}: {ex}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(5)

    raise last_exception


def process_table(
    pg_conn,
    sql_conn,
    audit_service,
    table_metadata,
    threshold_value,
    system_id,
    execution_id
):
    """
    Full lifecycle for one table:
      1. Delete target rows
      2. Count source rows
      3. Load source -> target
      4. Count target rows
      5. Validate counts
      6. Run reconciliation
    """

    source_table = table_metadata["source_table"]
    target_table = table_metadata["target_table"]

    logging.info(f"Processing {source_table} -> {target_table}")

    deleted_rows = delete_target_data(
        sql_conn        = sql_conn,
        table_metadata  = table_metadata,
        threshold_value = threshold_value
    )
    logging.info(f"{target_table}: {deleted_rows} rows deleted")

    source_rows = get_source_row_count(pg_conn, source_table, system_id)

    loaded_rows = load_table(
        pg_conn        = pg_conn,
        sql_conn       = sql_conn,
        table_metadata = table_metadata,
        system_id      = system_id
    )

    target_rows = get_target_row_count(sql_conn, target_table)

    validation_status = validate_load(source_rows, loaded_rows)

    audit_service.log_table(
        execution_id = execution_id,
        table_name   = target_table,
        source_rows  = source_rows,
        target_rows  = target_rows,
        status       = validation_status
    )

    run_reconciliation(
        pg_conn         = pg_conn,
        sql_conn        = sql_conn,
        target_table    = target_table,
        system_id       = system_id,
        threshold_value = threshold_value,
        execution_id    = execution_id,
        audit_service   = audit_service
    )

    logging.info(f"{target_table} completed")


def get_source_row_count(pg_conn, source_table, system_id):
    """Count rows in Supabase source table for this system_id."""

    cursor = pg_conn.cursor()
    cursor.execute(
        f"""
        SELECT COUNT(*)
        FROM aide_datamart.{source_table}
        WHERE system_id = %s
        """,
        (system_id,)
    )
    return cursor.fetchone()[0]


def get_target_row_count(sql_conn, target_table):
    """Count rows in SQL Server target table."""

    cursor = sql_conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM dbo.{target_table}")
    return cursor.fetchone()[0]


def validate_load(source_rows, loaded_rows):
    """Returns SUCCESS or a WARNING string — never raises."""

    if source_rows == loaded_rows:
        return "SUCCESS"

    return (
        f"WARNING "
        f"(Source={source_rows}, Loaded={loaded_rows})"
    )