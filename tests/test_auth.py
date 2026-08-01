from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from opspilot.auth import AuthenticationError, JWKSAuthenticator


class JWKSAuthenticatorTests(unittest.TestCase):
    private_key: ClassVar[bytes]
    public_key: ClassVar[bytes]

    @classmethod
    def setUpClass(cls) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private_key = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        cls.public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def setUp(self) -> None:
        self.authenticator = JWKSAuthenticator(
            jwks_url="https://identity.example.test/.well-known/jwks.json",
            issuer="https://identity.example.test/",
            audience="opspilot-api",
        )

    def _token(self, **overrides: object) -> str:
        now = datetime.now(UTC)
        claims: dict[str, object] = {
            "iss": "https://identity.example.test/",
            "aud": "opspilot-api",
            "sub": "operator@example.com",
            "name": "Operator",
            "tenant_id": "tenant-alpha",
            "actor_type": "human",
            "roles": ["investigator", "remediation_proposer"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        claims.update(overrides)
        return jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )

    def test_verified_claims_create_a_tenant_scoped_principal(self) -> None:
        with patch.object(
            self.authenticator._client,
            "get_signing_key_from_jwt",
            return_value=SimpleNamespace(key=self.public_key),
        ):
            principal = self.authenticator.authenticate(self._token())

        self.assertEqual("operator@example.com", principal.subject)
        self.assertEqual("tenant-alpha", principal.tenant_id)
        self.assertTrue(principal.has_any_role(frozenset({"investigator"})))
        self.assertEqual("human", principal.actor().actor_type)

    def test_wrong_audience_and_expired_tokens_are_rejected_without_details(self) -> None:
        expired = datetime.now(UTC) - timedelta(minutes=1)
        tokens = [
            self._token(aud="another-api"),
            self._token(exp=expired),
        ]
        for token in tokens:
            with (
                self.subTest(token=token[:12]),
                patch.object(
                    self.authenticator._client,
                    "get_signing_key_from_jwt",
                    return_value=SimpleNamespace(key=self.public_key),
                ),
                self.assertRaisesRegex(AuthenticationError, "invalid_token"),
            ):
                self.authenticator.authenticate(token)


if __name__ == "__main__":
    unittest.main()
