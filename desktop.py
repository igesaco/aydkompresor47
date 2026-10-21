"""AYD desktop launcher. Core business and storage code has no external dependencies."""
import argparse
import sys
import webbrowser
from ayd.db import Database
from ayd.server import data_directory,launch_server


def main():
    parser=argparse.ArgumentParser(description='AYD Kompresör · Atölye yönetimi')
    parser.add_argument('--browser',action='store_true',help='Masaüstü penceresi yerine tarayıcı kullan')
    parser.add_argument('--headless',action='store_true',help='Tarayıcı açmadan yerel sunucuyu başlat')
    parser.add_argument('--demo',action='store_true',help='Ayrı bir örnek veri alanı kullan')
    parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args()
    folder=data_directory()
    if args.demo:
        folder=folder/'demo'
    db=Database(folder/'ayd.sqlite3')
    if args.demo:
        from ayd.demo import populate
        populate(db)
    # Keep rotating startup backups separate from working database; snapshot via SQLite API.
    from datetime import date
    backups=folder/'backups'
    backups.mkdir(exist_ok=True)
    backup=backups/f'ayd-{date.today().isoformat()}.sqlite3'
    if not backup.exists():
        db.backup(backup)
    for old in sorted(backups.glob('ayd-*.sqlite3'))[:-14]:
        old.unlink()
    server,url=launch_server(db,args.port)
    if args.headless:
        print(url,flush=True)
        print(f'Veri dizini: {folder}',flush=True)
    elif not args.browser:
        try:
            import webview
            webview.settings['ALLOW_DOWNLOADS'] = True
            webview.create_window('AYD Kompresör | Atölye yönetimi',url,width=1440,height=960,min_size=(1050,720))
            webview.start()
            server.shutdown()
            return
        except ImportError:
            print('Masaüstü pencere paketi yok; uygulama varsayılan tarayıcıda açılıyor.')
            webbrowser.open(url)
    else:
        webbrowser.open(url)
    try:
        import threading
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__=='__main__':
    main()
