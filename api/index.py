import sys, os
# Make project root importable when Vercel runs from api/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app  # noqa: F401 — Vercel picks up the ASGI app
