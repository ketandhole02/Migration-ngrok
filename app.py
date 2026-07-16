import streamlit as st
import os
import traceback
import os
import streamlit as st
from migration_engine import run_migration

st.set_page_config(
    page_title="Data Entrega Migration Portal",
    layout="wide"
)

st.title("Data Entrega Migration Portal")

with st.form("migration_form"):

    customer_name = st.text_input("Customer Name")
    system_id     = st.text_input("System ID")

    using_bridge = bool(os.getenv("LOCAL_API_URL"))
    if using_bridge:
        st.info("Using the configured SQLConnect bridge through ngrok. SQL Server credentials stay on the local machine.")
        server_name = port = database_name = username = password = ""
    else:
        st.subheader("SQL Server Connection")
        server_name = st.text_input("SQL Server Host")
        port = st.text_input("Port", value="1433")
        database_name = st.text_input("Database Name")
        username = st.text_input("SQL Username")
        password = st.text_input("SQL Password", type="password")

    submitted = st.form_submit_button("Start Migration")

if submitted:

    # --- Input validation ---
    errors = []
    if not system_id.strip():
        errors.append("System ID is required.")
    if not using_bridge and not server_name.strip():
        errors.append("SQL Server Host is required.")
    if not using_bridge and not database_name.strip():
        errors.append("Database Name is required.")
    if not using_bridge and not username.strip():
        errors.append("SQL Username is required.")
    if not using_bridge and not password.strip():
        errors.append("SQL Password is required.")

    if errors:
        for e in errors:
            st.error(e)

    else:
        with st.spinner("Migration running... please wait."):
            try:
                result = run_migration(
                    system_id     = system_id.strip(),
                    server_name   = server_name.strip(),
                    port          = port.strip(),
                    database_name = database_name.strip(),
                    username      = username.strip(),
                    password      = password
                )
                st.success(result)
                st.info("Full details have been written to migration.log")

            except Exception as ex:
                # Show the human-readable message prominently
                st.error(f"Migration failed: {ex}")

                # Show the full traceback in an expander for debugging
                with st.expander("Show full error details"):
                    st.code(traceback.format_exc(), language="python")

                st.warning(
                    "Check migration.log for the complete run history."
                )
