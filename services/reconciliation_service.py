import logging
import pandas as pd

from repositories.reconciliation_repository import (
    get_reconciliation_queries
)


def run_reconciliation(
    pg_conn,
    sql_conn,
    target_table,
    system_id,
    threshold_value,
    execution_id,
    audit_service
):
    """
    Runs all active reconciliation rules for a given target_table.
    Each rule compares a source value (Supabase) vs target value (SQL Server).
    Results are logged to audit — mismatches do NOT stop migration.
    """

    queries = get_reconciliation_queries(pg_conn, target_table)

    if not queries:
        logging.info(
            f"{target_table} - No reconciliation rules configured"
        )
        return

    for query_row in queries:

        reconciliation_name = query_row["reconciliation_name"]
        source_query        = query_row["source_query"]
        target_query        = query_row["target_query"]

        try:
            # psycopg2 uses %(name)s style for named params.
            # Reconciliation queries in the DB must use
            # %(system_id)s and %(threshold_value)s as placeholders.
            source_df = pd.read_sql(
                source_query,
                pg_conn,
                params={
                    "system_id":       system_id,
                    "threshold_value": threshold_value
                }
            )

            target_df = pd.read_sql(
                target_query,
                sql_conn
            )

            if source_df.empty:
                raise RuntimeError(
                    f"Source reconciliation query returned no rows "
                    f"for {reconciliation_name}"
                )

            if target_df.empty:
                raise RuntimeError(
                    f"Target reconciliation query returned no rows "
                    f"for {reconciliation_name}"
                )

            source_value = source_df.iloc[0, 0]
            target_value = target_df.iloc[0, 0]
            passed_flag  = (source_value == target_value)

            audit_service.log_reconciliation(
                execution_id,
                target_table,
                reconciliation_name,
                str(source_value),
                str(target_value),
                passed_flag
            )

            status = "PASSED" if passed_flag else "FAILED"
            logging.info(
                f"{target_table} - {reconciliation_name} [{status}] "
                f"Source={source_value}, Target={target_value}"
            )

        except Exception as ex:
            # Log the error and continue — one bad rule
            # should not block the rest
            logging.error(
                f"{target_table} - Reconciliation '{reconciliation_name}' "
                f"error: {ex}"
            )