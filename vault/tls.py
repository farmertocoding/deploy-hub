"""TLS keypair / CSR / local-leaf helpers.

X.509 lives here so deploys/ and providers/ never import cryptography.hazmat
(tests/test_vault.py::test_aead_primitives_used_only_under_vault). Envelope
encryption stays in vault.service; this module only mints PEM.
"""
from datetime import datetime, timedelta, timezone


def generate_ec_keypair_and_csr(hostnames):
    """Return ``(key_pem: bytes, csr_pem: str)`` for an EC P-256 key."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    private_key = ec.generate_private_key(ec.SECP256R1())
    key_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cn = hostnames[0] if hostnames else "localhost"
    builder = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
    )
    if hostnames:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(h) for h in hostnames]),
            critical=False,
        )
    csr = builder.sign(private_key, hashes.SHA256())
    return key_pem, csr.public_bytes(serialization.Encoding.PEM).decode()


def public_keys_match(key_pem, cert_pem):
    """True when the certificate's public key is the private key's public key."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        load_pem_private_key,
    )

    key = load_pem_private_key(_as_bytes(key_pem), password=None)
    cert = x509.load_pem_x509_certificate(_as_bytes(cert_pem))
    key_pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    cert_pub = cert.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return key_pub == cert_pub


def mint_local_leaf(csr, hostnames, *, validity_days):
    """Sign a CSR's public key as a locally-minted leaf (T1/T2, never Cloudflare)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    pem = csr.encode() if isinstance(csr, str) else csr
    request = x509.load_pem_x509_csr(pem)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=int(validity_days))
    cn = hostnames[0] if hostnames else "localhost"
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(request.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(expires_at)
    )
    if hostnames:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(h) for h in hostnames]),
            critical=False,
        )
    cert = builder.sign(ca_key, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM).decode(), expires_at


def _as_bytes(value):
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return str(value).encode()
