from cryptography.fernet import Fernet
from app.core.config import settings


class KeyEncryption:
    """
    Wraps Fernet symmetric encryption for storing API keys in the database.
    Keys are encrypted at rest and only decrypted in-memory when making
    a proxied API call. They are never returned to the frontend.
    """

    def __init__(self):
        self._fernet = Fernet(settings.ENCRYPTION_KEY.encode())

    def encrypt(self, plaintext: str) -> str:
        """Encrypt an API key string → returns base64 ciphertext string."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt stored ciphertext → returns original API key string."""
        return self._fernet.decrypt(ciphertext.encode()).decode()

    def mask(self, plaintext: str) -> str:
        """Return a safe display version: AIza...xK9f"""
        if len(plaintext) <= 8:
            return "••••••••"
        return plaintext[:4] + "••••••••" + plaintext[-4:]


key_encryption = KeyEncryption()
