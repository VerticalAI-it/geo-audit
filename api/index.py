import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app as app  # `app` must be at module level for Vercel ASGI detection
