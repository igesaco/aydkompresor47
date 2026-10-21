import json
import sqlite3
import tempfile
import unittest
import urllib.request
import urllib.error
from datetime import date
from contextlib import closing
from pathlib import Path
from ayd.db import Database
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
