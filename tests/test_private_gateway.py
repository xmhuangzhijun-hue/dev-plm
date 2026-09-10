"""Gateway transport checks; real DB/business acceptance stays test_backend.py."""
import secrets
from datetime import datetime,timedelta,timezone
import jwt
from fastapi.testclient import TestClient
from backend.private_site import make_private_app
from backend.protocol import Identity


def test_private_site_login_cookie_and_api_boundary(monkeypatch):
    class IdentityFixture:
        def resolve_identity(self,tenant,principal):return Identity(tenant,principal,'viewer')
        def issue_token(self,identifier,credential):return self.authentication.issue_token(identifier,credential)
        def list_projects(self,identity):return []
    app=make_private_app(IdentityFixture());auth=app.state.services.authentication
    signing=secrets.token_urlsafe(48);password=secrets.token_urlsafe(48)
    auth.bindings=lambda:[{'identifier':'viewer','tenant_id':'fictional','principal_id':'viewer','credential_ref':'fixture'}]
    auth.read_secret=lambda reference:password
    monkeypatch.setattr(auth,'signing_key',lambda:signing)
    with TestClient(app,base_url='https://testserver',follow_redirects=False) as client:
        assert client.get('/login').headers['referrer-policy']=='same-origin'
        assert client.get('/site/assets/project-data.js').status_code==303
        assert client.get('/v1/projects').status_code==401
        assert client.post('/session',data={'identifier':'viewer','credential':'invalid'}).status_code==401
        assert client.post('/session',headers={'Origin':'https://other.invalid'},data={}).status_code==403
        assert client.post('/session',headers={'Origin':'null'},data={}).status_code==403
        response=client.post('/session',headers={'Origin':'https://testserver'},data={'identifier':'viewer','credential':password})
        assert response.status_code==303
        cookie=response.headers['set-cookie'].lower()
        assert all(flag in cookie for flag in ['httponly','secure','samesite=strict'])
        assert client.get('/site/index.html').status_code==200
        assert client.get('/workbench').status_code==200
        assert client.get('/private/workspace').status_code==200
        assert client.get('/private/api/v1/projects').status_code==200
        assert client.post('/private/api/v1/auth/token',json={'identifier':'viewer','credential':password}).status_code==403
        assert client.post('/private/api/v1/auth/token',headers={'Origin':'https://other.invalid'},json={'identifier':'viewer','credential':password}).status_code==403
        assert client.post('/private/api/v1/auth/token',headers={'Origin':'https://testserver'},json={'identifier':'viewer','credential':password}).status_code==200
        assert client.get('/v1/projects').status_code==401  # Cookie never replaces API bearer auth.
        token=client.post('/v1/auth/token',json={'identifier':'viewer','credential':password}).json()['access_token']
        assert client.get('/v1/projects',headers={'Authorization':'Bearer '+token}).status_code==200
        now=datetime.now(timezone.utc)
        expired=jwt.encode({'sub':'viewer','tenant':'fictional','iat':now-timedelta(hours=2),'exp':now-timedelta(hours=1),'iss':'dev-plm-local','aud':'dev-plm-api','jti':'expired'},signing,algorithm='HS256')
        client.cookies.set('devplm_session',expired)
        assert client.get('/site/index.html').status_code==303
        assert client.get('/v1/projects',headers={'Authorization':'Bearer '+expired}).status_code==401


def test_private_real_flag_allowed_only_outside_repository(tmp_path):
    import shutil,yaml,build,pytest
    root=tmp_path/'external';project=root/'private-channel-fixture'
    shutil.copytree(build.ROOT/'projects/qingdan',project)
    metadata=project/'project.yaml';data=yaml.safe_load(metadata.read_text(encoding='utf-8'))
    data.update(id=project.name,example=False,description='Fictional fixture for external real-project flag validation')
    metadata.write_text(yaml.safe_dump(data,allow_unicode=True),encoding='utf-8')
    parsed,_=build.load_project(project,build.ROOT,data_root=root)
    assert parsed['example'] is False
    with pytest.raises(build.BuildError):build.load_project(project,tmp_path,data_root=root)
