"""
Criptografia simetrica autenticada para o Cofre de Senhas.
Usa AES-256-GCM via cryptography.

A chave (COFRE_KEY) NAO deve estar no banco. Configure a variavel COFRE_KEY no ambiente do Coolify.
Gerar uma nova chave: python -c "import secrets; print(secrets.token_urlsafe(32))"
"""
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_key() -> bytes:
    """Carrega a chave de 32 bytes do env COFRE_KEY (base64-url ou raw 64-char hex)."""
    key = os.getenv("COFRE_KEY")
    if not key:
        raise RuntimeError(
            "COFRE_KEY nao configurada. Gere com: "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\" "
            "e configure a variavel COFRE_KEY no ambiente do Coolify."
        )
    # Aceita base64-url (44 chars) ou hex (64 chars) ou raw bytes
    try:
        if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
            return bytes.fromhex(key)
        # padding base64
        pad = "=" * (-len(key) % 4)
        return base64.urlsafe_b64decode(key + pad)[:32].ljust(32, b"\0")
    except Exception:
        return key.encode("utf-8")[:32].ljust(32, b"\0")


def encrypt(plaintext: str) -> str:
    """Criptografa string. Retorna base64-url(nonce + ciphertext+tag)."""
    if plaintext is None:
        return None
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    aesgcm = AESGCM(_get_key())
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    blob = nonce + ct
    return "v1:" + base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")


def decrypt(token: str) -> str:
    """Descriptografa. Retorna texto vazio se invalido (nao quebra a app)."""
    if not token:
        return ""
    # Compatibilidade: se nao tem prefixo v1:, eh dado legado em plaintext
    if not token.startswith("v1:"):
        return token
    try:
        raw = token[3:]
        pad = "=" * (-len(raw) % 4)
        blob = base64.urlsafe_b64decode(raw + pad)
        nonce, ct = blob[:12], blob[12:]
        aesgcm = AESGCM(_get_key())
        return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
    except Exception:
        return ""


def mask(plaintext: str) -> str:
    """Mascara senha para exibicao default (apenas tamanho)."""
    if not plaintext:
        return ""
    n = len(plaintext)
    if n <= 4:
        return "*" * n
    return plaintext[0] + "*" * (n - 2) + plaintext[-1]
