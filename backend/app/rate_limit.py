"""
Rate limiting.

Auth endpoints are the ones that matter most: without a limit, /login is an
unmetered password-guessing oracle and /register lets anyone fill the database.
Upload and URL ingestion are limited too because each one costs CPU, disk, and a
Gemini summary call.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

LOGIN_LIMIT = "10/minute"
REGISTER_LIMIT = "5/minute"
UPLOAD_LIMIT = "20/minute"
CHAT_LIMIT = "30/minute"
