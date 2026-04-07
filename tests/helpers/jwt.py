"""Generate ES256 test JWTs and seed the auth module's JWKS cache."""

import jwt as pyjwt
from jwt import PyJWK
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from uuid import UUID

_private_key = ec.generate_private_key(ec.SECP256R1())
_public_key = _private_key.public_key()
TEST_KID = "test-kid-001"

_public_jwk = _public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)


def seed_jwks_cache():
    """Pre-seed the auth module's JWKS cache with our test key."""
    import auth
    from jwt.algorithms import ECAlgorithm
    pub_numbers = _public_key.public_numbers()
    jwk_dict = ECAlgorithm.to_jwk(_public_key, as_dict=True)
    jwk_dict["kid"] = TEST_KID
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "ES256"
    auth._jwks_cache[TEST_KID] = PyJWK(jwk_dict)


def make_token(user_id: str | UUID, **extra_claims) -> str:
    payload = {
        "sub": str(user_id),
        "aud": "authenticated",
        "role": "authenticated",
        **extra_claims,
    }
    return pyjwt.encode(
        payload,
        _private_key,
        algorithm="ES256",
        headers={"kid": TEST_KID},
    )


def auth_headers(user_id: str | UUID, **extra_claims) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(user_id, **extra_claims)}"}
