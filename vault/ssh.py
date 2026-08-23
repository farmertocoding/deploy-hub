"""SSH Ed25519 keypair helpers.

Ed25519 lives here so provision/ never imports cryptography.hazmat
(tests/test_vault.py::test_aead_primitives_used_only_under_vault). Envelope
encryption stays in vault.service; this module only mints PEM.
"""


def generate_ed25519_keypair():
    """Return ``(key_pem: bytes, public_openssh: str)`` for an Ed25519 key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    pub = key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode().strip()
    return pem, pub


def generate_ed25519_raw():
    """Return ``(private_raw: bytes, public_raw: bytes)`` — 32-byte seeds.

    Partner mint uses this so core/ never imports cryptography.hazmat.
    The caller prefixes hubk_*; this helper does not vault the private bytes.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    key = Ed25519PrivateKey.generate()
    private_raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private_raw, public_raw


def public_openssh_from_pem(pem):
    """Return the OpenSSH public line for an OpenSSH PEM private key."""
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        load_ssh_private_key,
    )

    key = load_ssh_private_key(_as_bytes(pem), password=None)
    return key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode().strip()


def _as_bytes(value):
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return str(value).encode()
