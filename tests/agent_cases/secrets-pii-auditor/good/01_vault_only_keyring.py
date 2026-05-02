# GOOD: secrets only via keyring. No plaintext fallback. Logging masks values.
import logging

import keyring

logger = logging.getLogger(__name__)
SERVICE = "FinanzasMMEX"


def get_token(key: str) -> str | None:
    val = keyring.get_password(SERVICE, key)
    if val is None:
        logger.warning("token missing for key=%s", key)
        return None
    logger.debug("token retrieved for key=%s (len=%d)", key, len(val))  # masked
    return val


def set_token(key: str, value: str) -> None:
    keyring.set_password(SERVICE, key, value)
    logger.info("token stored for key=%s", key)
