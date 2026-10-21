import sqlite3
from pathlib import Path
from contextlib import contextmanager

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '', email TEXT DEFAULT '', tax_no TEXT DEFAULT '', address TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS compressors(id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), brand TEXT NOT NULL, model TEXT DEFAULT '', serial TEXT NOT NULL UNIQUE, capacity INTEGER NOT NULL CHECK(capacity>0), warranty_end TEXT, notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS stock(id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL, category TEXT DEFAULT 'Parça', quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity>=0), minimum INTEGER NOT NULL DEFAULT 2 CHECK(minimum>=0), buy_price INTEGER NOT NULL DEFAULT 0 CHECK(buy_price>=0), sell_price INTEGER NOT NULL DEFAULT 0 CHECK(sell_price>=0), supplier TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS services(id INTEGER PRIMARY KEY, compressor_id INTEGER NOT NULL REFERENCES compressors(id), date TEXT NOT NULL, title TEXT NOT NULL, operations TEXT NOT NULL, amount INTEGER NOT NULL DEFAULT 0 CHECK(amount>=0), maintenance_months INTEGER NOT NULL DEFAULT 6 CHECK(maintenance_months BETWEEN 1 AND 120), next_maintenance TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('Bekliyor','İşlemde','Tamamlandı')), parts TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), date TEXT NOT NULL, valid_until TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Proforma', notes TEXT DEFAULT '', subtotal INTEGER NOT NULL, tax INTEGER NOT NULL, total INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS invoice_items(id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id), stock_id INTEGER REFERENCES stock(id), description TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0), unit_price INTEGER NOT NULL CHECK(unit_price>=0), tax_rate INTEGER NOT NULL CHECK(tax_rate BETWEEN 0 AND 100));
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), date TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('Borç','Tahsilat')), amount INTEGER NOT NULL CHECK(amount>0), description TEXT NOT NULL, due_date TEXT, source TEXT UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY, stock_id INTEGER NOT NULL REFERENCES stock(id), date TEXT NOT NULL, delta INTEGER NOT NULL, description TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), date TEXT NOT NULL, time TEXT DEFAULT '09:00', title TEXT NOT NULL, notes TEXT DEFAULT '', done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0,1)));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
PRAGMA user_version=1;
'''

class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO settings VALUES ('company', 'AYD Kompresör')")
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    def backup(self, target):
        with self.connect() as db:
            dst = sqlite3.connect(target)
            try:
                db.backup(dst)
            finally:
                dst.close()
