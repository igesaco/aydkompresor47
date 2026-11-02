import sqlite3
from pathlib import Path
from contextlib import contextmanager

# Version 1 tables. Later changes are applied by MIGRATIONS so existing data keeps working.
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
'''


def migrate_v2(db):
    '''Tedarikçi kartları, alış belgeleri ve tedarikçi cari hesabı.'''
    db.execute('''CREATE TABLE suppliers(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, contact TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '', tax_no TEXT DEFAULT '', address TEXT DEFAULT '', iban TEXT DEFAULT '', payment_days INTEGER NOT NULL DEFAULT 30 CHECK(payment_days BETWEEN 0 AND 365), notes TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('''CREATE TABLE purchases(id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL REFERENCES suppliers(id), date TEXT NOT NULL, document_no TEXT DEFAULT '', due_date TEXT NOT NULL, notes TEXT DEFAULT '', subtotal INTEGER NOT NULL, tax INTEGER NOT NULL, total INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('''CREATE TABLE purchase_items(id INTEGER PRIMARY KEY, purchase_id INTEGER NOT NULL REFERENCES purchases(id), stock_id INTEGER REFERENCES stock(id), description TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0), unit_price INTEGER NOT NULL CHECK(unit_price>=0), tax_rate INTEGER NOT NULL CHECK(tax_rate BETWEEN 0 AND 100))''')
    db.execute('''CREATE TABLE supplier_ledger(id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL REFERENCES suppliers(id), date TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('Alış','Ödeme')), amount INTEGER NOT NULL CHECK(amount>0), description TEXT NOT NULL, due_date TEXT, source TEXT UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('ALTER TABLE stock ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id)')
    # Eski serbest metin tedarikçi adlarını kartlara dönüştür; metin sütunu geçmiş için kalır.
    for (name,) in db.execute("SELECT TRIM(supplier) FROM stock WHERE TRIM(COALESCE(supplier,''))!='' GROUP BY TRIM(supplier) ORDER BY MIN(id)").fetchall():
        db.execute('INSERT OR IGNORE INTO suppliers(name) VALUES (?)', (name,))
    db.execute("UPDATE stock SET supplier_id=(SELECT id FROM suppliers WHERE name=TRIM(stock.supplier)) WHERE TRIM(COALESCE(supplier,''))!=''")


MIGRATIONS = {2: migrate_v2}
VERSION = max(MIGRATIONS)


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists() and self.path.stat().st_size > 0
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
        if existed and version < VERSION:
            # Sürüm geçişinden önce eski veritabanının dokunulmamış bir kopyasını sakla.
            folder = self.path.parent/'backups'
            folder.mkdir(exist_ok=True)
            target = folder/f'migration-v{version}-{self.path.name}'
            if not target.exists():
                self.backup(target)
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO settings VALUES ('company', 'AYD Kompresör')")
        with self.connect() as db:
            version = max(1, db.execute('PRAGMA user_version').fetchone()[0])
            if version < VERSION:
                db.execute('BEGIN IMMEDIATE')
                for target in range(version+1, VERSION+1):
                    MIGRATIONS[target](db)
                db.execute(f'PRAGMA user_version={VERSION}')

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
