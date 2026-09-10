"""Authenticated private reading gateway; offline site bytes remain unchanged."""
from urllib.parse import parse_qs
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .app import make_app
from .config import ROOT

LOGIN = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>开发工作台 · 登录</title>
<style>body{font:16px system-ui;background:#f3f6fc;color:#18263d;margin:0}main{max-width:360px;margin:12vh auto;padding:28px;background:white;border-radius:14px}label,input,button{display:block;box-sizing:border-box;width:100%;margin:14px 0}input,button{padding:12px;font:inherit}button{background:#3458ef;color:white;border:0;border-radius:6px}</style>
<main><h1>开发工作台</h1><p>私有网络阅读入口。请使用本机登记的账号登录。</p>
<form method="post" action="/session"><label>账号<input name="identifier" required autocomplete="username"></label>
<label>口令<input name="credential" type="password" required autocomplete="current-password"></label>
<button>登录并查看</button></form><p>会话30分钟到期。离线文件仍可独立打开。</p></main></html>'''


def make_private_app(services=None):
    app=make_app(services)
    auth=app.state.services.authentication

    @app.middleware('http')
    async def private_boundary(request,call_next):
        path=request.url.path
        if path.startswith('/private/'):
            try:auth.authenticate(request.cookies.get('devplm_session',''))
            except Exception:return JSONResponse({'message':'登录已过期，请重新登录。'},status_code=401)
            if request.method not in {'GET','HEAD','OPTIONS'}:
                if request.headers.get('origin')!=str(request.base_url).rstrip('/'):
                    return JSONResponse({'message':'请求来源不一致。'},status_code=403)
            if path.startswith('/private/api/'):
                headers=[(k,v) for k,v in request.scope['headers'] if k.lower()!=b'authorization']
                headers.append((b'authorization',('Bearer '+request.cookies['devplm_session']).encode()))
                request.scope['headers']=headers
        if path not in {'/login','/session'} and not path.startswith('/v1/'):
            try:auth.authenticate(request.cookies.get('devplm_session',''))
            except Exception:
                return RedirectResponse('/login?next=workbench' if path=='/workbench' else '/login',status_code=303)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        # Keep Origin on same-origin form navigations; no-referrer makes Chromium
        # send Origin: null on POST, which our CSRF boundary correctly rejects.
        # Cross-origin destinations still receive no referrer.
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        return response

    @app.get('/login',include_in_schema=False)
    def login(request:Request):
        html=LOGIN
        if request.query_params.get('next')=='workbench':html=html.replace('<label>账号','<input type="hidden" name="next" value="workbench"><label>账号')
        return HTMLResponse(html)

    @app.post('/session',include_in_schema=False)
    async def session(request:Request):
        # Same-origin form only; no redirects to arbitrary user-supplied URLs.
        origin=request.headers.get('origin')
        if origin and origin.split('://',1)[-1]!=request.headers.get('host'):
            return JSONResponse({'message':'登录来源不一致。'},status_code=403)
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>8192:return JSONResponse({'message':'输入过长。'},status_code=413)
        form=parse_qs(body.decode('utf-8',errors='replace'))
        try:token=auth.issue_token(form.get('identifier',[''])[0],form.get('credential',[''])[0])
        except Exception:return HTMLResponse(LOGIN.replace('<h1>','<p role="alert">登录失败，请检查账号与口令或本机服务状态。</p><h1>'),status_code=401)
        response=RedirectResponse('/workbench' if form.get('next')==['workbench'] else '/site/index.html',status_code=303)
        response.set_cookie('devplm_session',token['access_token'],max_age=1800,httponly=True,secure=True,samesite='strict',path='/')
        return response

    @app.get('/',include_in_schema=False)
    def home():return RedirectResponse('/site/index.html',status_code=303)

    @app.post('/logout',include_in_schema=False)
    def logout():
        response=RedirectResponse('/login',status_code=303);response.delete_cookie('devplm_session');return response

    from .online import install_online
    install_online(app,auth,app.state.services)
    app.mount('/private/api',make_app(app.state.services,authentication=auth),name='browser-api')
    app.mount('/site',StaticFiles(directory=ROOT/'site',html=True),name='private-site')
    return app


app=make_private_app()
