"""
Global application configuration.
"""

BATCH_SIZE = 5000

MAX_RETRIES = 3

LOG_LEVEL = "INFO"

SQL_SCHEMA = "dbo"

SUPABASE_SCHEMA = "aide_datamart"

#-- DATA ENTREGA DATABASE VARIABLES
DTE_SCH_REPO_DTM = "aide_datamart"
DTE_SCH_REPO_DTS = "aide_datastore"
DTE_SCH_REPO_STG = "aide_staging"

#-- CLIENT DATABASE VARIABLES
CLT_SCH_WSSS_MTA  = "dbo"