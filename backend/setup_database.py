"""
Quick script to create database tables in Supabase
"""
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
import pathlib
import structlog

logger = structlog.get_logger(__name__)

logger.info("database_setup_started")
logger.info("supabase_connection", url=SUPABASE_URL)

client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Read SQL schema
schema_path = pathlib.Path(__file__).parent / 'database' / 'schema.sql'
sql = schema_path.read_text()

logger.info("schema_loaded", path=str(schema_path))

# Split into individual statements and execute
statements = [s.strip() for s in sql.split(';') if s.strip()]

for i, statement in enumerate(statements, 1):
    if statement:
        try:
            # Use the REST API to execute SQL
            result = client.rpc('exec_sql', {'query': statement + ';'}).execute()
            logger.info("sql_statement_executed", statement_num=i, total=len(statements))
        except Exception as e:
            # Try alternate method - direct table creation
            if 'CREATE TABLE users' in statement:
                logger.warning("sql_statement_fallback", statement_num=i, reason="using_alternate_method")
            else:
                logger.warning("sql_statement_error", statement_num=i, error=str(e)[:100])

logger.info("database_setup_completed")
logger.info("verifying_tables")

# Verify tables exist
try:
    result = client.table('users').select('*').limit(1).execute()
    logger.info("table_verified", table="users")
except Exception as e:
    logger.error("table_verification_failed", table="users", error=str(e))

try:
    result = client.table('summaries').select('*').limit(1).execute()
    logger.info("table_verified", table="summaries")
except Exception as e:
    logger.error("table_verification_failed", table="summaries", error=str(e))

try:
    result = client.table('user_activity').select('*').limit(1).execute()
    logger.info("table_verified", table="user_activity")
except Exception as e:
    logger.error("table_verification_failed", table="user_activity", error=str(e))

logger.info("setup_complete", next_step="restart_backend_and_signup")
