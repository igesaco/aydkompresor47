import json
import sqlite3
import tempfile
import unittest
import urllib.request
import urllib.error
from datetime import date
from contextlib import closing
from pathlib import Path
from ayd.db import Database,VERSION
from ayd.domain import App,add_months,money
from ayd.server import launch_server


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/'test.sqlite3')
        self.app=App(self.db)
        self.customer=self.app.mutate('customers',{'name':'Test Müşteri'})['id']
        self.compressor=self.add_compressor('TEST-01')
        self.stock=self.app.mutate('stock',dict(sku='F-1',name='Filtre',quantity=5,minimum=2,sell_price='100.25'))['id']
    def tearDown(self):
        self.tmp.cleanup()
    def add_compressor(self,serial):
        return self.app.mutate('compressors',dict(customer_id=self.customer,brand='Lupamat',capacity=50,serial=serial))['id']
    def service(self,**kwargs):
        return self.app.mutate('services',dict(compressor_id=self.compressor,date='2026-01-31',title='Bakım',operations='Filtre değişimi',amount='100.25',maintenance_months=1,status='Tamamlandı',parts=[dict(stock_id=self.stock,quantity=2)],**kwargs))
    def invoice(self,qty=2):
        return self.app.mutate('invoices',dict(customer_id=self.customer,date='2026-01-01',valid_until='2026-02-01',items=[dict(stock_id=self.stock,description='Filtre',quantity=qty,unit_price='100.25',tax_rate=20)]))['id']
    def test_service_posts_stock_and_balance_and_calendar(self):
        self.service()
        s=self.app.snapshot()
        self.assertEqual(s['stock'][0]['quantity'],3)
        self.assertEqual(s['customers'][0]['balance'],10025)
        self.assertEqual(s['services'][0]['next_maintenance'],'2026-02-28')
    def test_service_stock_failure_rolls_back_everything(self):
        with self.assertRaises(ValueError):
            self.app.mutate('services',dict(compressor_id=self.compressor,date='2026-01-31',title='Bakım',operations='Filtre',amount=200,maintenance_months=6,status='Tamamlandı',parts=[dict(stock_id=self.stock,quantity=2),dict(stock_id=self.stock,quantity=8)]))
        s=self.app.snapshot()
        self.assertEqual(s['stock'][0]['quantity'],5)
        self.assertEqual(s['services'],[])
        self.assertEqual(s['ledger'],[])
        self.assertEqual(len(s['movements']),1)
    def test_pending_service_posts_only_on_completion_once(self):
        sid=self.app.mutate('services',dict(compressor_id=self.compressor,date='2026-01-01',title='Bakım',operations='Filtre',amount=200,maintenance_months=6,status='İşlemde',parts=[dict(stock_id=self.stock,quantity=2)]))['id']
        self.assertEqual(self.app.snapshot()['stock'][0]['quantity'],5)
        self.assertEqual(self.app.snapshot()['ledger'],[])
        self.app.mutate('service-complete',{},sid)
        with self.assertRaises(ValueError): self.app.mutate('service-complete',{},sid)
        self.assertEqual(self.app.snapshot()['stock'][0]['quantity'],3)
        self.assertEqual(len(self.app.snapshot()['ledger']),1)
    def test_proforma_conversion_is_atomic_and_idempotent_guarded(self):
        iid=self.invoice()
        s=self.app.snapshot()
        self.assertEqual(s['stock'][0]['quantity'],5)
        self.assertEqual(s['ledger'],[])
        self.assertEqual(s['invoices'][0]['subtotal'],20050)
        self.assertEqual(s['invoices'][0]['tax'],4010)
        self.app.mutate('invoice-convert',{},iid)
        with self.assertRaises(ValueError): self.app.mutate('invoice-convert',{},iid)
        self.assertEqual(self.app.snapshot()['customers'][0]['balance'],24060)
        self.assertEqual(self.app.snapshot()['stock'][0]['quantity'],3)
    def test_proforma_can_be_edited_until_converted(self):
        iid=self.invoice()
        other=self.app.mutate('customers',{'name':'Yeni müşteri'})['id']
        self.app.mutate('invoices',dict(customer_id=other,date='2026-01-05',valid_until='2026-01-20',notes='Revize',items=[dict(description='İşçilik',quantity=1,unit_price='500',tax_rate=20)]),iid)
        s=self.app.snapshot()
        self.assertEqual(len(s['invoices']),1)
        self.assertEqual((s['invoices'][0]['customer_id'],s['invoices'][0]['total'],s['invoices'][0]['notes']),(other,60000,'Revize'))
        self.assertEqual([x['description'] for x in s['invoice_items']],['İşçilik'])
        self.app.mutate('invoice-convert',{},iid)
        with self.assertRaises(ValueError):
            self.app.mutate('invoices',dict(customer_id=other,date='2026-01-05',valid_until='2026-01-20',items=[dict(description='X',quantity=1,unit_price=1)]),iid)
        self.assertEqual(self.app.snapshot()['invoices'][0]['total'],60000)
    def test_failed_sale_keeps_proforma_and_balance(self):
        iid=self.invoice(6)
        with self.assertRaises(ValueError): self.app.mutate('invoice-convert',{},iid)
        s=self.app.snapshot()
        self.assertEqual(s['invoices'][0]['status'],'Proforma')
        self.assertEqual(s['customers'][0]['balance'],0)
        self.assertEqual(s['stock'][0]['quantity'],5)
    def test_recommendations_use_other_same_capacity_completed_records(self):
        self.service()
        other=self.add_compressor('TEST-02')
        result=self.app.recommendations(other)
        self.assertEqual(len(result['matches']),1)
        self.assertEqual(result['matches'][0]['operations'],'Filtre değişimi')
        self.assertEqual(self.app.recommendations(self.compressor)['matches'],[])
    def test_latest_completed_service_suppresses_old_maintenance(self):
        self.service()
        self.app.mutate('services',dict(compressor_id=self.compressor,date=date.today().isoformat(),title='Yeni bakım',operations='Kontrol',amount=0,maintenance_months=12,status='Tamamlandı'))
        self.assertFalse(any(a['type']=='maintenance' for a in self.app.snapshot()['alerts']))
    def test_overdue_accounts_use_payments(self):
        today=date.today().isoformat()
        self.app.mutate('ledger',dict(customer_id=self.customer,date=today,kind='Borç',amount=100,due_date='2020-01-01',description='Borç'))
        self.assertTrue(any(a['type']=='account' for a in self.app.snapshot()['alerts']))
        self.app.mutate('ledger',dict(customer_id=self.customer,date=today,kind='Tahsilat',amount=100,description='Ödeme'))
        self.assertFalse(any(a['type']=='account' for a in self.app.snapshot()['alerts']))
    def test_money_and_integer_validation(self):
        self.assertEqual(money('1.005'),101)
        self.assertEqual(money('1,25'),125)
        for bad in ['-1','NaN','Infinity','abc']:
            with self.assertRaises(ValueError): money(bad)
        with self.assertRaises(ValueError): self.app.mutate('stock-movement',dict(stock_id=self.stock,delta='1.5',description='Test'))
    def test_backup_includes_wal_and_restores(self):
        self.service()
        backup=Path(self.tmp.name)/'backup.sqlite3'
        self.db.backup(backup)
        restored=App(Database(backup)).snapshot()
        self.assertEqual(restored['customers'][0]['balance'],10025)
        self.assertEqual(restored['stock'][0]['quantity'],3)
        # sqlite3.Connection.__exit__ commits/rolls back but does not close.
        # Windows cannot remove the temporary backup while this handle is open.
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')
    def test_edits_do_not_change_stock_quantities(self):
        self.app.mutate('stock',dict(sku='F-1',name='Yeni filtre',quantity=999,minimum=1,buy_price=1,sell_price=2),self.stock)
        self.assertEqual(self.app.snapshot()['stock'][0]['quantity'],5)
    def test_service_history_owner_cannot_be_silently_reassigned(self):
        self.service()
        other=self.app.mutate('customers',{'name':'Diğer müşteri'})['id']
        with self.assertRaises(ValueError):
            self.app.mutate('compressors',dict(customer_id=other,brand='Lupamat',capacity=50,serial='TEST-01'),self.compressor)
        self.assertEqual(self.app.snapshot()['services'][0]['customer_id'],self.customer)
    def test_pending_service_rejects_nonexistent_part(self):
        with self.assertRaises(ValueError):
            self.app.mutate('services',dict(compressor_id=self.compressor,date='2026-01-01',title='Bakım',operations='Kontrol',status='Bekliyor',parts=[dict(stock_id=99999,quantity=1)]))
        self.assertEqual(self.app.snapshot()['services'],[])
    def test_month_end_and_leap_year(self):
        self.assertEqual(add_months('2024-01-31',1),'2024-02-29')
        self.assertEqual(add_months('2026-12-31',2),'2027-02-28')
    def supplier(self,**kwargs):
        return self.app.mutate('suppliers',dict(name='Anadolu Teknik',phone='0232 444 10 20',payment_days=30,**kwargs))['id']
    def test_purchase_adds_stock_updates_cost_and_supplier_debt(self):
        sid=self.supplier()
        self.app.mutate('purchases',dict(supplier_id=sid,date='2026-01-10',document_no='F-77',items=[dict(stock_id=self.stock,description='Filtre',quantity=4,unit_price='50',tax_rate=20),dict(description='Nakliye',quantity=1,unit_price='10',tax_rate=20)]))
        s=self.app.snapshot()
        self.assertEqual(s['stock'][0]['quantity'],9)
        self.assertEqual(s['stock'][0]['buy_price'],5000)
        self.assertEqual(s['purchases'][0]['total'],25200)
        self.assertEqual(s['purchases'][0]['due_date'],'2026-02-09')
        self.assertEqual(s['suppliers'][0]['balance'],25200)
        self.assertEqual(s['supplier_ledger'][0]['source'],'purchase:1')
        self.app.mutate('supplier-ledger',dict(supplier_id=sid,date='2026-01-20',kind='Ödeme',amount='252',description='Havale'))
        self.assertEqual(self.app.snapshot()['suppliers'][0]['balance'],0)
    def test_failed_purchase_rolls_back(self):
        sid=self.supplier()
        with self.assertRaises(sqlite3.IntegrityError):
            self.app.mutate('purchases',dict(supplier_id=sid,date='2026-01-10',items=[dict(stock_id=self.stock,description='Filtre',quantity=2,unit_price=1),dict(stock_id=99999,description='Yok',quantity=1,unit_price=1)]))
        s=self.app.snapshot()
        self.assertEqual(s['stock'][0]['quantity'],5)
        self.assertEqual(s['purchases'],[])
        self.assertEqual(s['supplier_ledger'],[])
    def test_supplier_overdue_and_upcoming_alerts(self):
        sid=self.supplier()
        self.app.mutate('supplier-ledger',dict(supplier_id=sid,date='2020-01-01',kind='Alış',amount=100,due_date='2020-02-01',description='Açılış'))
        self.assertEqual('Vadesi geçen ödemeniz: 100,00 TL',[a for a in self.app.snapshot()['alerts'] if a['type']=='payable'][0]['detail'])
        self.app.mutate('supplier-ledger',dict(supplier_id=sid,date=date.today().isoformat(),kind='Ödeme',amount=100,description='Ödeme'))
        self.assertFalse(any(a['type']=='payable' for a in self.app.snapshot()['alerts']))
        self.app.mutate('supplier-ledger',dict(supplier_id=sid,date=date.today().isoformat(),kind='Alış',amount=50,due_date=date.today().isoformat(),description='Yeni'))
        self.assertIn('Yaklaşan',[a for a in self.app.snapshot()['alerts'] if a['type']=='payable'][0]['detail'])
    def test_stock_links_supplier_and_alert_shows_contact(self):
        sid=self.supplier()
        self.app.mutate('stock',dict(sku='F-1',name='Filtre',minimum=9,supplier_id=sid),self.stock)
        s=self.app.snapshot()
        self.assertEqual(s['stock'][0]['supplier_name'],'Anadolu Teknik')
        self.assertIn('0232 444 10 20',[a for a in s['alerts'] if a['type']=='stock'][0]['detail'])
    def test_duplicate_supplier_name_rejected(self):
        self.supplier()
        with self.assertRaises(sqlite3.IntegrityError):
            self.app.mutate('suppliers',dict(name='anadolu teknik'))
    def test_delete_only_unlinked_cards(self):
        sid=self.supplier()
        self.app.mutate('stock',dict(sku='F-1',name='Filtre',supplier_id=sid),self.stock)
        with self.assertRaises(ValueError): self.app.mutate('delete',{'table':'suppliers'},sid)
        with self.assertRaises(ValueError): self.app.mutate('delete',{'table':'customers'},self.customer)
        with self.assertRaises(ValueError): self.app.mutate('delete',{'table':'stock'},self.stock)
        empty=self.app.mutate('customers',{'name':'Boş müşteri'})['id']
        self.app.mutate('delete',{'table':'customers'},empty)
        self.assertEqual(len(self.app.snapshot()['customers']),1)
    def test_email_validation(self):
        with self.assertRaises(ValueError):
            self.app.mutate('customers',dict(name='E-posta',email='gecersiz'))
    def test_company_settings(self):
        self.app.mutate('settings',dict(company='AYD',company_phone='0232 000 00 00',company_iban='TR00'))
        settings=self.app.snapshot()['settings']
        self.assertEqual(settings['company_phone'],'0232 000 00 00')
        self.assertEqual(settings['company_iban'],'TR00')
        with self.assertRaises(ValueError): self.app.mutate('settings',dict(company=''))


V1_SCHEMA='''CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '', email TEXT DEFAULT '', tax_no TEXT DEFAULT '', address TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE stock(id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL, category TEXT DEFAULT 'Parça', quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity>=0), minimum INTEGER NOT NULL DEFAULT 2 CHECK(minimum>=0), buy_price INTEGER NOT NULL DEFAULT 0 CHECK(buy_price>=0), sell_price INTEGER NOT NULL DEFAULT 0 CHECK(sell_price>=0), supplier TEXT DEFAULT '');
INSERT INTO stock(sku,name,quantity,supplier) VALUES ('A','Filtre',3,'Anadolu Teknik'),('B','Yağ',4,' anadolu teknik '),('C','Valf',1,'');
PRAGMA user_version=1;'''


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'ayd.sqlite3'
    def tearDown(self):
        self.tmp.cleanup()
    def test_v1_database_gets_suppliers_and_keeps_backup(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(V1_SCHEMA)
        app=App(Database(self.path))
        s=app.snapshot()
        self.assertEqual([t['name'] for t in s['suppliers']],['Anadolu Teknik'])
        self.assertEqual(sorted(x['supplier_name'] for x in s['stock']),['','Anadolu Teknik','Anadolu Teknik'])
        self.assertTrue((Path(self.tmp.name)/'backups'/'migration-v1-ayd.sqlite3').exists())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],VERSION)
    def test_old_default_company_name_is_corrected_but_custom_name_kept(self):
        for old,expected in [('AYD Kompresör','Aydemir Kompresör'),('Başka Firma','Başka Firma')]:
            path=Path(self.tmp.name)/f'{len(old)}.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.executescript(V1_SCHEMA+"CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);")
                db.execute('INSERT INTO settings VALUES (?,?)',('company',old))
                db.commit()
            self.assertEqual(App(Database(path)).snapshot()['settings']['company'],expected)
        self.assertEqual(App(Database(Path(self.tmp.name)/'yeni.sqlite3')).snapshot()['settings']['company'],'Aydemir Kompresör')
    def test_reopening_keeps_version_and_data(self):
        app=App(Database(self.path))
        app.mutate('suppliers',dict(name='Tek tedarikçi'))
        Database(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],VERSION)
        self.assertEqual(len(App(Database(self.path)).snapshot()['suppliers']),1)
        self.assertFalse((Path(self.tmp.name)/'backups').exists())


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/'http.sqlite3')
        self.server,self.url=launch_server(self.db)
        self.base=self.url.split('/?')[0]
        with urllib.request.urlopen(self.url) as r:
            self.cookie=r.headers['Set-Cookie'].split(';')[0]
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()
    def request(self,path,body=None,origin=None):
        headers={'Cookie':self.cookie,'X-AYD-Request':'1','Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        req=urllib.request.Request(self.base+path,headers=headers,data=json.dumps(body).encode() if body is not None else None)
        return urllib.request.urlopen(req)
    def test_session_and_cross_origin_protection(self):
        with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(self.base+'/api/snapshot')
        self.assertEqual(err.exception.code,401)
        with self.assertRaises(urllib.error.HTTPError) as err:self.request('/api/customers',{'name':'Test'},'https://example.com')
        self.assertEqual(err.exception.code,403)
        with self.request('/api/customers',{'name':'Test'},self.base) as r:self.assertEqual(r.status,200)
        with self.request('/api/snapshot') as r:self.assertEqual(json.load(r)['customers'][0]['name'],'Test')
    def test_backup_is_valid_sqlite(self):
        with self.request('/api/backup') as r:self.assertTrue(r.read().startswith(b'SQLite format 3'))
    def test_invalid_json_gets_validation_response(self):
        with self.assertRaises(urllib.error.HTTPError) as err:self.request('/api/customers',[],self.base)
        self.assertEqual(err.exception.code,400)


if __name__=='__main__':unittest.main()
