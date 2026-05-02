import json
from typing import Any, Dict

import keyring


class Vault:
    SERVICE_NAME = "FinanzasMMEX"

    def set_secret(self, key: str, value: Any) -> None:
        """Almacena un secreto en el Windows Credential Manager."""
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        keyring.set_password(self.SERVICE_NAME, key, str(value))

    def get_secret(self, key: str) -> str | None:
        """Recupera un secreto del Windows Credential Manager."""
        return keyring.get_password(self.SERVICE_NAME, key)

    def get_json_secret(self, key: str) -> Dict[str, Any] | None:
        """Recupera un secreto JSON del Windows Credential Manager."""
        val = self.get_secret(key)
        if val:
            try:
                data = json.loads(val)
                if isinstance(data, dict):
                    return data
                return None
            except json.JSONDecodeError:
                return None
        return None

    def delete_secret(self, key: str) -> None:
        """Elimina un secreto."""
        try:
            keyring.delete_password(self.SERVICE_NAME, key)
        except keyring.errors.PasswordDeleteError:
            pass
