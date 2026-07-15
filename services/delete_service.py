import logging

def delete_target_data(
    sql_conn,
    table_metadata,
    threshold_value
):
    """
    Deletes target data using metadata-driven strategy.
    """

    target_table      = table_metadata["target_table"]
    delete_strategy   = table_metadata["delete_strategy"]
    delete_column     = table_metadata.get("delete_column")
    delete_operator   = table_metadata.get("delete_operator")
    custom_delete_sql = table_metadata.get("custom_delete_sql")

    cursor = sql_conn.cursor()

    try:

        if delete_strategy == "NONE":

            logging.info(
                f"{target_table} - No delete required"
            )

            return 0

        elif delete_strategy == "FULL_DELETE":

            sql = f"""
            DELETE
            FROM dbo.{target_table}
            """

            cursor.execute(sql)

        elif delete_strategy == "TRUNCATE":

            sql = f"""
            TRUNCATE TABLE dbo.{target_table}
            """

            cursor.execute(sql)

        elif delete_strategy == "THRESHOLD":

            sql = f"""
            DELETE
            FROM dbo.{target_table}
            WHERE {delete_column}
                  {delete_operator}
                  ?
            """

            cursor.execute(
                sql,
                threshold_value
            )

        elif delete_strategy == "CUSTOM":

            cursor.execute(
                custom_delete_sql,
                threshold_value
            )

        else:

            raise Exception(
                f"Unknown delete strategy "
                f"{delete_strategy}"
            )

        deleted_rows = cursor.rowcount

        sql_conn.commit()

        logging.info(
            f"{target_table} - "
            f"Deleted {deleted_rows} rows"
        )

        return deleted_rows

    except Exception:

        sql_conn.rollback()
        raise

    finally:

        cursor.close()