def create_migration_run(
    pg_conn,
    execution_id,
    system_id
):
    """
    Create migration run record.
    """

    cur = pg_conn.cursor()

    cur.execute(
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

    pg_conn.commit()