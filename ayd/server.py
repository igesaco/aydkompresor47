import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .db import Database
from .domain import App, integer


def data_directory():
    if os.environ.get('AYD_DATA_DIR'):
        return Path(os.environ['AYD_DATA_DIR'])
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'AYD Kompresor'
    if sys.platform == 'darwin':
        return Path.home()/'Library'/'Application Support'/'AYD Kompresor'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local'/'share'))/'ayd-kompresor'


def create_server(database, port=0):
    app=App(database)
    token=secrets.token_urlsafe(32)
    root=(Path(sys._MEIPASS) if hasattr(sys,'_MEIPASS') else Path(__file__).resolve().parent.parent)/'web'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def respond(self,status,body,content_type='application/json; charset=utf-8',extra=None):
            if isinstance(body,(dict,list)):
                body=json.dumps(body,ensure_ascii=False).encode()
            elif isinstance(body,str):
                body=body.encode()
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            for k,v in (extra or {}).items():
                self.send_header(k,v)
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            try:
                c=SimpleCookie(self.headers.get('Cookie',''))
                return 'ayd_session' in c and secrets.compare_digest(c['ayd_session'].value,token)
            except Exception:
                return False

        def valid_host(self):
            return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403,{'error':'Geçersiz yerel adres.'})
            parsed=urlsplit(self.path)
            if parsed.path=='/':
                supplied=parse_qs(parsed.query).get('session',[''])[0]
                if not self.authorized() and not secrets.compare_digest(supplied,token):
                    return self.respond(403,{'error':'Uygulamayı masaüstü başlatıcısıyla açın.'})
                return self.respond(200,(root/'index.html').read_bytes(),'text/html; charset=utf-8',{'Set-Cookie':f'ayd_session={token}; HttpOnly; SameSite=Strict; Path=/'})
            if not self.authorized():
                return self.respond(401,{'error':'Oturum bulunamadı. Uygulamayı yeniden açın.'})
            try:
                if parsed.path=='/api/snapshot':
                    return self.respond(200,app.snapshot())
                if parsed.path.startswith('/api/recommendations/'):
                    return self.respond(200,app.recommendations(int(parsed.path.rsplit('/',1)[1])))
                if parsed.path=='/api/backup':
                    with tempfile.TemporaryDirectory() as folder:
                        file=Path(folder)/'backup.sqlite3'
                        database.backup(file)
                        return self.respond(200,file.read_bytes(),'application/octet-stream',{'Content-Disposition':'attachment; filename="ayd-yedek.sqlite3"'})
                assets={'/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}
                if parsed.path in assets:
                    return self.respond(200,(root/parsed.path[1:]).read_bytes(),assets[parsed.path])
                return self.respond(404,{'error':'Sayfa bulunamadı.'})
            except (ValueError,KeyError):
                return self.respond(400,{'error':'Geçersiz istek.'})

        def do_POST(self):
            origin=f'http://127.0.0.1:{self.server.server_port}'
            if not self.valid_host() or not self.authorized() or self.headers.get('Origin')!=origin or self.headers.get('X-AYD-Request')!='1':
                return self.respond(403,{'error':'İstek doğrulanamadı.'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                return self.respond(415,{'error':'JSON gerekli.'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<1 or length>1000000:
                    return self.respond(413,{'error':'İstek boyutu geçersiz.'})
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict):
                    raise ValueError('Geçersiz veri.')
                parts=urlsplit(self.path).path.strip('/').split('/')
                if len(parts) not in (2,3) or parts[0]!='api':
                    return self.respond(404,{'error':'İşlem bulunamadı.'})
                result=app.mutate(parts[1],payload,integer(parts[2],1) if len(parts)==3 else None)
                self.respond(200,result)
            except sqlite3.IntegrityError as exc:
                message='Bu stok kodu veya seri numarası zaten kayıtlı.' if 'UNIQUE' in str(exc) else 'Bağlı kayıt bulunamadı veya veri kuralına uymuyor.'
                self.respond(400,{'error':message})
            except (ValueError,TypeError,KeyError,OverflowError) as exc:
                self.respond(400,{'error':str(exc) or 'Geçersiz veri.'})
            except sqlite3.Error:
                self.respond(503,{'error':'Veritabanı işlemi tamamlanamadı. Tekrar deneyin.'})

    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server, f'http://127.0.0.1:{server.server_port}/?session={token}'


def launch_server(database,port=0):
    server,url=create_server(database,port)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    return server,url
