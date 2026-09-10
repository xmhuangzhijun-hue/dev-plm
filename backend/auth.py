"""Short-lived JWTs; tenant/role is rechecked against file-projected principals."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from uuid import uuid4

import jwt
from .config import account_bindings, secret, settings
from .protocol import Identity, ServiceError


class Authentication:
    def __init__(self, resolve_identity, bindings=account_bindings, read_secret=secret):
        self.resolve_identity = resolve_identity
        self.bindings, self.read_secret = bindings, read_secret

    def signing_key(self):
        value = self.read_secret(settings().get('DEVPLM_JWT_SECRET'))
        if len(value) < 32:
            raise ServiceError(503, 'SERVICE_UNAVAILABLE', '令牌签名配置不可用。')
        return value

    def issue_token(self, identifier, credential):
        matches = [a for a in self.bindings() if a.get('identifier') == identifier]
        # Compare fixed-size values. Never interpolate identifier/credential in errors.
        expected = self.read_secret(matches[0]['credential_ref']) if len(matches) == 1 else ''
        valid = hmac.compare_digest(hashlib.sha256(credential.encode()).digest(), hashlib.sha256(expected.encode()).digest())
        if len(matches) != 1 or not valid:
            raise ServiceError(401, 'INVALID_CREDENTIALS', '登录凭据无效。')
        actor = self.resolve_identity(matches[0]['tenant_id'], matches[0]['principal_id'])
        now = datetime.now(timezone.utc)
        token = jwt.encode({'sub': actor.principal_id, 'tenant': actor.tenant_id,
            'iat': now, 'exp': now + timedelta(minutes=30), 'iss': 'dev-plm-local',
            'aud': 'dev-plm-api', 'jti': uuid4().hex}, self.signing_key(), algorithm='HS256')
        return {'access_token': token, 'token_type': 'Bearer', 'expires_in': 1800}

    def authenticate(self, token):
        try:
            claims = jwt.decode(token, self.signing_key(), algorithms=['HS256'],
                audience='dev-plm-api', issuer='dev-plm-local',
                options={'require': ['sub', 'tenant', 'iat', 'exp', 'iss', 'aud', 'jti']})
            return self.resolve_identity(claims['tenant'], claims['sub'])
        except (jwt.PyJWTError, KeyError, TypeError):
            raise ServiceError(401, 'AUTH_REQUIRED', '访问令牌无效或已过期。') from None
