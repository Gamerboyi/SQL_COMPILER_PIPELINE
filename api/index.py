"""
Vercel Serverless Function entry point.
Wraps the Flask app so Vercel can route /api/* requests to it.
"""

import sys
import os

# Add the backend directory to Python's module search path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app import app
