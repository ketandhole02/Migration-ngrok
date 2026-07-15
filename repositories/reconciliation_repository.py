def get_reconciliation_queries(
    pg_conn,
    target_table
):
    """
    Get reconciliation queries.
    """

    cur = pg_conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM aide_datastore.dts_ref_migration_interface_reconciliation_query
        WHERE active_flag = true
          AND target_table = %s
        ORDER BY reconciliation_id
        """,
        (target_table,)
    )

    columns = [
        col[0]
        for col
        in cur.description
    ]

    return [
        dict(zip(columns, row))
        for row
        in cur.fetchall()
    ]