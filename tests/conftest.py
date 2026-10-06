import os

# Hermetic: set (not pop) these, because load_dotenv() never overrides existing variables but
# would refill deleted ones from a developer's .env. No test may reach a real provider.
for _k in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "LANGFUSE_PUBLIC_KEY",
           "LANGFUSE_SECRET_KEY", "DATABASE_URL", "FRUGAL_API_TOKEN"):
    os.environ[_k] = ""
os.environ["FRUGAL_FAKE_EMBED"] = "1"
os.environ["FRUGAL_FAKE_LLM"] = "1"
os.environ["FRUGAL_CACHE"] = "off"
