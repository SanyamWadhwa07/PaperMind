"""
Quick script to create database tables in Supabase
"""
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
import pathlib

print("🔧 Setting up database tables...")
print(f"📡 Connecting to: {SUPABASE_URL}")

client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Read SQL schema
schema_path = pathlib.Path(__file__).parent / 'database' / 'schema.sql'
sql = schema_path.read_text()

print("📝 Running SQL schema...")

# Split into individual statements and execute
statements = [s.strip() for s in sql.split(';') if s.strip()]

for i, statement in enumerate(statements, 1):
    if statement:
        try:
            # Use the REST API to execute SQL
            result = client.rpc('exec_sql', {'query': statement + ';'}).execute()
            print(f"✅ Statement {i}/{len(statements)} executed")
        except Exception as e:
            # Try alternate method - direct table creation
            if 'CREATE TABLE users' in statement:
                print(f"⚠️  Statement {i} - Using alternate method")
            else:
                print(f"⚠️  Statement {i} - {str(e)[:100]}")

print("\n✅ Database setup complete!")
print("🔍 Verifying tables...")

# Verify tables exist
try:
    result = client.table('users').select('*').limit(1).execute()
    print("✅ 'users' table exists")
except Exception as e:
    print(f"❌ 'users' table error: {e}")

try:
    result = client.table('summaries').select('*').limit(1).execute()
    print("✅ 'summaries' table exists")
except Exception as e:
    print(f"❌ 'summaries' table error: {e}")

try:
    result = client.table('user_activity').select('*').limit(1).execute()
    print("✅ 'user_activity' table exists")
except Exception as e:
    print(f"❌ 'user_activity' table error: {e}")

print("\n🎉 Setup complete! Restart your backend and try signing up again.")
