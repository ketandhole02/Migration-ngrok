import logging


class AuditService:
    """
    Handles migration auditing.
    """

    def __init__(
        self,
        pg_conn
    ):

        self.pg_conn = pg_conn

    def create_run(
        self,
        execution_id,
        system_id
    ):
        """
        Creates migration run.
        """

        cursor = self.pg_conn.cursor()

        cursor.execute(
            """
            INSERT INTO aide_datastore.dts_aud_migration_interface_execution_log
            (
                execution_id,
                system_id,
                start_time,
                status
            )
            VALUES
            (
                %s,
                %s,
                CURRENT_TIMESTAMP,
                'RUNNING'
            )
            """,
            (
                execution_id,
                system_id
            )
        )

        self.pg_conn.commit()

    def complete_run(
        self,
        execution_id
    ):
        """
        Marks run completed.
        """

        cursor = self.pg_conn.cursor()

        cursor.execute(
            """
            UPDATE aide_datastore.dts_aud_migration_interface_execution_log
            SET
                end_time =
                    CURRENT_TIMESTAMP,
                status='COMPLETED'
            WHERE execution_id=%s
            """,
            (execution_id,)
        )

        self.pg_conn.commit()

    def fail_run(
        self,
        execution_id,
        error_message
    ):
        """
        Marks run failed.
        """

        cursor = self.pg_conn.cursor()

        cursor.execute(
            """
            UPDATE aide_datastore.dts_aud_migration_interface_execution_log
            SET
                end_time =
                    CURRENT_TIMESTAMP,
                status='FAILED',
                error_message=%s
            WHERE execution_id=%s
            """,
            (
                error_message,
                execution_id
            )
        )

        self.pg_conn.commit()

    def log_table(
        self,
        execution_id,
        table_name,
        source_rows,
        target_rows,
        status
    ):
        """
        Logs table result.
        """

        cursor = self.pg_conn.cursor()

        cursor.execute(
            """
            INSERT INTO
            aide_datastore.dts_aud_migration_interface_table_audit
            (
                execution_id,
                table_name,
                source_rows,
                target_rows,
                status
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                execution_id,
                table_name,
                source_rows,
                target_rows,
                status
            )
        )

        self.pg_conn.commit()

    def log_reconciliation(
        self,
        execution_id,
        table_name,
        reconciliation_name,
        source_value,
        target_value,
        passed_flag
    ):
        """
        Logs reconciliation result.
        """

        cursor = self.pg_conn.cursor()

        cursor.execute(
            """
            INSERT INTO
            aide_datastore.dts_aud_migration_interface_reconciliation_result
            (
                execution_id,
                table_name,
                reconciliation_name,
                source_value,
                target_value,
                passed_flag
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                execution_id,
                table_name,
                reconciliation_name,
                source_value,
                target_value,
                passed_flag
            )
        )

        self.pg_conn.commit()