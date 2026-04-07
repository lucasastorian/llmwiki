import os
import sys

os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5434/supavault_test"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_JWT_SECRET"] = "test-jwt-secret-that-is-at-least-32-characters-long-for-hs256"
os.environ["AWS_ACCESS_KEY_ID"] = ""
os.environ["AWS_SECRET_ACCESS_KEY"] = ""
os.environ["S3_BUCKET"] = ""
os.environ["LOGFIRE_TOKEN"] = ""
os.environ["SENTRY_DSN"] = ""
os.environ["APP_URL"] = "http://localhost:3000"
os.environ["GLOBAL_MAX_USERS"] = "1000"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
