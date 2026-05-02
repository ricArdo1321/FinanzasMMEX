# BAD: hard-coded OAuth token, hard-coded MP key, secret read from env bypassing vault,
# logger prints full token.
import logging
import os

logger = logging.getLogger(__name__)

# VIOLATION: hard-coded Google OAuth refresh token-shaped value
GMAIL_TOKEN = "ya29.a0AfH6SMBexampleFAKEtokenPATTERN1234567890"

# VIOLATION: hard-coded Mercado Pago app token
MP_ACCESS_TOKEN = (
    "APP_USR-1234567890123456-052026-abcdef1234567890abcdef1234567890-987654321"
)

# VIOLATION: bypassing vault.py
PASSWORD = os.environ.get("BE_PASSWORD", "default-password-123")


def authenticate() -> None:
    logger.info("using gmail token: %s", GMAIL_TOKEN)  # VIOLATION: full secret in log
