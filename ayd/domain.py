import calendar
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def money(value):
    try:
        v = Decimal(str(value).replace(',', '.'))
        if not v.is_finite() or v < 0 or v > 1000000000:
            raise ValueError('Tutar 0 ile 1 milyar TL arasında olmalı.')
        return int((v * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError):
        raise ValueError('Geçerli bir tutar girin.')


def integer(v, minimum=0, maximum=100000000):
    try:
        n = int(str(v))
    except (ValueError, TypeError):
        raise ValueError('Tam sayı girin.')
    if not minimum <= n <= maximum:
        raise ValueError(f'Sayı {minimum} ile {maximum} arasında olmalı.')
    return n


def day(v):
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise ValueError('Geçerli bir tarih girin.')


def text(v, required=False):
    s = str(v or '').strip()
    if len(s) > 10000 or (required and not s):
        raise ValueError('Zorunlu alanları doldurun; metin en fazla 10000 karakter olabilir.')
    return s


def email(v):
    s = text(v)
    if s and (len(s) > 254 or '@' not in s.strip('@') or ' ' in s):
        raise ValueError('Geçerli bir e-posta adresi girin.')
    return s


def tl(kurus):
    '''Kuruşu Türkçe para biçimine çevirir: 1234567 -> 12.345,67 TL'''
    return f'{kurus/100:,.2f}'.replace(',', ' ').replace('.', ',').replace(' ', '.') + ' TL'


def due(value):
    # Devreden bakiyeler geçmiş vadeyle girilebildiği için işlem tarihine göre kısıtlanmaz.
    return day(value) if value else None


def open_dues(entries, debit, today, soon):
    '''Ödemeleri en eski vadeli borçlara dağıtır; (geciken, yaklaşan, ilk yaklaşan vade) döner.'''
    credits = sum(e['amount'] for e in entries if e['kind'] != debit)
    overdue = upcoming = 0
    first = None
    for e in sorted((e for e in entries if e['kind'] == debit), key=lambda e: (e['due_date'] or e['date'], e['id'])):
        paid = min(credits, e['amount'])
        credits -= paid
        left = e['amount'] - paid
        if left and e['due_date'] and e['due_date'] < today:
            overdue += left
        elif left and e['due_date'] and e['due_date'] <= soon:
            upcoming += left
            first = first or e['due_date']
    return overdue, upcoming, first


# Silme yalnızca bağlı kaydı olmayan kartlarda yapılır; geçmiş hareketler korunur.
DELETABLE = {
    'customers': [('compressors', 'customer_id'), ('ledger', 'customer_id'), ('invoices', 'customer_id'), ('events', 'customer_id')],
    'compressors': [('services', 'compressor_id')],
    'suppliers': [('stock', 'supplier_id'), ('purchases', 'supplier_id'), ('supplier_ledger', 'supplier_id')],
    'events': [],
}
COMPANY_FIELDS = ['company', 'company_phone', 'company_email', 'company_address', 'company_tax_no', 'company_iban']


def add_months(value, months):
    d = date.fromisoformat(value)
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


class App:
    def __init__(self, database):
        self.database = database

    def snapshot(self):
        with self.database.connect() as db:
            result = {
                'customers': rows(db, '''SELECT c.*, COALESCE((SELECT SUM(CASE WHEN kind='Borç' THEN amount ELSE -amount END) FROM ledger WHERE customer_id=c.id),0) balance FROM customers c ORDER BY c.name'''),
                'compressors': rows(db, 'SELECT k.*,c.name customer_name FROM compressors k JOIN customers c ON c.id=k.customer_id ORDER BY k.id DESC'),
                'stock': rows(db, '''SELECT s.*,COALESCE(t.name,'') supplier_name,COALESCE(t.phone,'') supplier_phone FROM stock s LEFT JOIN suppliers t ON t.id=s.supplier_id ORDER BY s.name'''),
                'suppliers': rows(db, '''SELECT t.*, COALESCE((SELECT SUM(CASE WHEN kind='Alış' THEN amount ELSE -amount END) FROM supplier_ledger WHERE supplier_id=t.id),0) balance FROM suppliers t ORDER BY t.name'''),
                'purchases': rows(db, 'SELECT p.*,t.name supplier_name FROM purchases p JOIN suppliers t ON t.id=p.supplier_id ORDER BY p.date DESC,p.id DESC'),
                'purchase_items': rows(db, 'SELECT * FROM purchase_items'),
                'supplier_ledger': rows(db, 'SELECT l.*,t.name supplier_name FROM supplier_ledger l JOIN suppliers t ON t.id=l.supplier_id ORDER BY l.date DESC,l.id DESC'),
                'services': rows(db, '''SELECT s.*,k.brand,k.model,k.capacity,k.serial,k.customer_id,c.name customer_name FROM services s JOIN compressors k ON k.id=s.compressor_id JOIN customers c ON c.id=k.customer_id ORDER BY s.date DESC,s.id DESC'''),
                'ledger': rows(db, 'SELECT l.*,c.name customer_name FROM ledger l JOIN customers c ON c.id=l.customer_id ORDER BY l.date DESC,l.id DESC'),
                'events': rows(db, 'SELECT e.*,c.name customer_name FROM events e LEFT JOIN customers c ON c.id=e.customer_id ORDER BY e.date,e.time'),
                'invoices': rows(db, 'SELECT i.*,c.name customer_name FROM invoices i JOIN customers c ON c.id=i.customer_id ORDER BY i.id DESC'),
                'invoice_items': rows(db, 'SELECT * FROM invoice_items'),
                'movements': rows(db, 'SELECT m.*,s.name stock_name FROM stock_movements m JOIN stock s ON s.id=m.stock_id ORDER BY m.id DESC LIMIT 200'),
                'settings': dict(db.execute('SELECT key,value FROM settings').fetchall()),
                'today': date.today().isoformat(),
            }
        alerts = []
        today = date.today().isoformat()
        limit = (date.today() + timedelta(days=30)).isoformat()
        for s in result['stock']:
            if s['quantity'] <= s['minimum']:
                supplier = ' '.join(x for x in [s['supplier_name'],s['supplier_phone']] if x) or 'Tedarikçi belirtilmedi'
                alerts.append({'type':'stock','title':s['name'], 'detail':f"{s['quantity']} adet kaldı · Alt sınır {s['minimum']} · {supplier}",'date':today,'target':'stock'})
        for c in result['compressors']:
            if c['warranty_end'] and c['warranty_end'] <= limit:
                alerts.append({'type':'warranty','title':c['customer_name'], 'detail':f"{c['brand']} {c['capacity']} lt · {c['serial']} · Garanti uzatması için görüşün",'date':c['warranty_end'],'target':'compressors'})
            completed = [s for s in result['services'] if s['compressor_id']==c['id'] and s['status']=='Tamamlandı']
            if completed:
                latest = max(completed, key=lambda s:(s['date'],s['id']))
                if latest['next_maintenance'] <= limit:
                    alerts.append({'type':'maintenance','title':c['customer_name'],'detail':f"{c['brand']} {c['capacity']} lt · {c['serial']} · {latest['maintenance_months']} aylık bakım için görüşün",'date':latest['next_maintenance'],'target':'services'})
        # Tahsilatları en eski borçlara dağıtarak kalan vadesi geçmiş tutarı hesapla.
        for c in result['customers']:
            overdue = open_dues([l for l in result['ledger'] if l['customer_id']==c['id']],'Borç',today,today)[0]
            if overdue:
                alerts.append({'type':'account','title':c['name'],'detail':f'Vadesi geçen tutar: {tl(overdue)}','date':today,'target':'ledger'})
        # Tedarikçiye olan borçlar: geciken ve 7 gün içinde vadesi gelen ödemeler.
        week = (date.today() + timedelta(days=7)).isoformat()
        for t in result['suppliers']:
            overdue, upcoming, first = open_dues([l for l in result['supplier_ledger'] if l['supplier_id']==t['id']],'Alış',today,week)
            if overdue:
                alerts.append({'type':'payable','title':t['name'],'detail':f'Vadesi geçen ödemeniz: {tl(overdue)}','date':today,'target':f"supplier/{t['id']}"})
            elif upcoming:
                alerts.append({'type':'payable','title':t['name'],'detail':f'Yaklaşan ödeme: {tl(upcoming)}','date':first,'target':f"supplier/{t['id']}"})
        result['alerts'] = sorted(alerts,key=lambda a:a['date'])
        return result

    def mutate(self, resource, p, record_id=None):
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if resource == 'customers':
                fields = {k:text(p.get(k),k=='name') for k in ['name','phone','tax_no','address','notes']}
                fields['email'] = email(p.get('email'))
            elif resource == 'suppliers':
                fields = {k:text(p.get(k),k=='name') for k in ['name','contact','phone','tax_no','address','iban','notes']}
                fields['email'] = email(p.get('email'))
                fields['payment_days'] = integer(p.get('payment_days',30),0,365)
            elif resource == 'compressors':
                fields = dict(customer_id=integer(p.get('customer_id'),1),brand=text(p.get('brand'),True),model=text(p.get('model')),serial=text(p.get('serial'),True),capacity=integer(p.get('capacity'),1,100000),warranty_end=day(p['warranty_end']) if p.get('warranty_end') else None,notes=text(p.get('notes')))
                if record_id:
                    existing=db.execute('SELECT customer_id FROM compressors WHERE id=?',(record_id,)).fetchone()
                    if existing and existing['customer_id']!=fields['customer_id'] and db.execute('SELECT 1 FROM services WHERE compressor_id=? LIMIT 1',(record_id,)).fetchone():
                        raise ValueError('Servis geçmişi olan kompresörün müşterisi değiştirilemez; geçmiş hesap bağlantısı korunur.')
            elif resource == 'stock':
                fields = dict(sku=text(p.get('sku'),True),name=text(p.get('name'),True),category=text(p.get('category')) or 'Parça',minimum=integer(p.get('minimum',2)),buy_price=money(p.get('buy_price',0)),sell_price=money(p.get('sell_price',0)),supplier_id=integer(p['supplier_id'],1) if p.get('supplier_id') else None)
                if not record_id:
                    fields['quantity'] = integer(p.get('quantity',0))
            elif resource == 'stock-movement':
                sid = integer(p.get('stock_id'),1)
                delta = integer(p.get('delta'),-1000000,1000000)
                if not delta:
                    raise ValueError('Hareket miktarı sıfır olamaz.')
                self.move_stock(db,sid,delta,text(p.get('description'),True))
                return {'ok':True}
            elif resource == 'services':
                if record_id:
                    raise ValueError('Kesinleşen servis kaydı değiştirilemez.')
                status = p.get('status','Tamamlandı')
                if status not in ['Bekliyor','İşlemde','Tamamlandı']:
                    raise ValueError('Geçersiz servis durumu.')
                dt = day(p.get('date'))
                months = integer(p.get('maintenance_months',6),1,120)
                amount = money(p.get('amount',0))
                cid = integer(p.get('compressor_id'),1)
                comp = db.execute('SELECT * FROM compressors WHERE id=?',(cid,)).fetchone()
                if not comp:
                    raise ValueError('Kompresör bulunamadı.')
                parts = p.get('parts',[])
                if not isinstance(parts,list) or len(parts)>100:
                    raise ValueError('Geçersiz parça listesi.')
                normalized=[]
                for part in parts:
                    sid, qty = integer(part.get('stock_id'),1),integer(part.get('quantity'),1)
                    if not db.execute('SELECT 1 FROM stock WHERE id=?',(sid,)).fetchone():
                        raise ValueError('Planlanan parça için stok kartı bulunamadı.')
                    if status == 'Tamamlandı':
                        self.move_stock(db,sid,-qty,'Servis: '+text(p.get('title'),True))
                    normalized.append({'stock_id':sid,'quantity':qty})
                fields = dict(compressor_id=cid,date=dt,title=text(p.get('title'),True),operations=text(p.get('operations'),True),amount=amount,maintenance_months=months,next_maintenance=add_months(dt,months),status=status,parts=json.dumps(normalized))
                rid = self.save(db,'services',fields)
                if status=='Tamamlandı' and amount:
                    self.save(db,'ledger',dict(customer_id=comp['customer_id'],date=dt,kind='Borç',amount=amount,description=fields['title'],due_date=due(p.get('due_date')) or dt,source=f'service:{rid}'))
                return {'id':rid}
            elif resource == 'service-complete':
                service = db.execute('SELECT s.*,k.customer_id FROM services s JOIN compressors k ON k.id=s.compressor_id WHERE s.id=?',(record_id,)).fetchone()
                if not service:
                    raise ValueError('Servis bulunamadı.')
                if service['status']=='Tamamlandı':
                    raise ValueError('Servis zaten tamamlandı.')
                for part in json.loads(service['parts']):
                    self.move_stock(db,part['stock_id'],-part['quantity'],'Servis: '+service['title'])
                db.execute("UPDATE services SET status='Tamamlandı' WHERE id=?",(record_id,))
                if service['amount']:
                    self.save(db,'ledger',dict(customer_id=service['customer_id'],date=service['date'],kind='Borç',amount=service['amount'],description=service['title'],due_date=day(p.get('due_date') or date.today().isoformat()),source=f'service:{record_id}'))
                return {'ok':True}
            elif resource == 'ledger':
                if record_id:
                    raise ValueError('Cari hareket değiştirilemez; düzeltici hareket ekleyin.')
                kind = p.get('kind')
                if kind not in ['Borç','Tahsilat']:
                    raise ValueError('Geçersiz hareket türü.')
                amount=money(p.get('amount',0))
                if not amount:
                    raise ValueError('Tutar sıfırdan büyük olmalı.')
                dt=day(p.get('date'))
                fields=dict(customer_id=integer(p.get('customer_id'),1),date=dt,kind=kind,amount=amount,description=text(p.get('description'),True),due_date=due(p.get('due_date')))
            elif resource == 'supplier-ledger':
                if record_id:
                    raise ValueError('Tedarikçi hareketi değiştirilemez; düzeltici hareket ekleyin.')
                kind = p.get('kind')
                if kind not in ['Alış','Ödeme']:
                    raise ValueError('Geçersiz hareket türü.')
                amount=money(p.get('amount',0))
                if not amount:
                    raise ValueError('Tutar sıfırdan büyük olmalı.')
                dt=day(p.get('date'))
                rid=self.save(db,'supplier_ledger',dict(supplier_id=integer(p.get('supplier_id'),1),date=dt,kind=kind,amount=amount,description=text(p.get('description'),True),due_date=due(p.get('due_date')) if kind=='Alış' else None))
                return {'id':rid}
            elif resource == 'purchases':
                if record_id:
                    raise ValueError('Alış belgesi değiştirilemez; düzeltme için stok ve tedarikçi hareketi girin.')
                supplier=db.execute('SELECT * FROM suppliers WHERE id=?',(integer(p.get('supplier_id'),1),)).fetchone()
                if not supplier:
                    raise ValueError('Tedarikçi bulunamadı.')
                items=p.get('items',[])
                if not isinstance(items,list) or not 1<=len(items)<=100:
                    raise ValueError('En az bir, en fazla 100 alış kalemi ekleyin.')
                dt=day(p.get('date'))
                due_date=due(p.get('due_date')) or (date.fromisoformat(dt)+timedelta(days=supplier['payment_days'])).isoformat()
                clean=[]
                subtotal=tax=0
                for i in items:
                    q=integer(i.get('quantity'),1,100000)
                    price=money(i.get('unit_price'))
                    rate=integer(i.get('tax_rate',20),0,100)
                    subtotal+=q*price
                    tax+=int((Decimal(q*price)*rate/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                    clean.append(dict(stock_id=integer(i['stock_id'],1) if i.get('stock_id') else None,description=text(i.get('description'),True),quantity=q,unit_price=price,tax_rate=rate))
                rid=self.save(db,'purchases',dict(supplier_id=supplier['id'],date=dt,document_no=text(p.get('document_no')),due_date=due_date,notes=text(p.get('notes')),subtotal=subtotal,tax=tax,total=subtotal+tax))
                label=f'AL-{rid:04d}'
                for i in clean:
                    self.save(db,'purchase_items',dict(purchase_id=rid,**i))
                    if i['stock_id']:
                        # Alış stoğu artırır; birim alış fiyatı son alış maliyetiyle güncellenir.
                        self.move_stock(db,i['stock_id'],i['quantity'],f"Alış {label} · {supplier['name']}")
                        db.execute('UPDATE stock SET buy_price=? WHERE id=?',(i['unit_price'],i['stock_id']))
                if subtotal+tax:
                    self.save(db,'supplier_ledger',dict(supplier_id=supplier['id'],date=dt,kind='Alış',amount=subtotal+tax,description=f"{label} alış"+(f" · {text(p.get('document_no'))}" if p.get('document_no') else ''),due_date=due_date,source=f'purchase:{rid}'))
                return {'id':rid}
            elif resource == 'delete':
                table=p.get('table')
                if table not in DELETABLE or not record_id:
                    raise ValueError('Bu kayıt silinemez.')
                for child,column in DELETABLE[table]:
                    if db.execute(f'SELECT 1 FROM {child} WHERE {column}=? LIMIT 1',(record_id,)).fetchone():
                        raise ValueError('Bu karta bağlı kayıtlar var; geçmişi korumak için silinemez.')
                if db.execute(f'DELETE FROM {table} WHERE id=?',(record_id,)).rowcount!=1:
                    raise ValueError('Kayıt bulunamadı.')
                return {'ok':True}
            elif resource == 'events':
                tm=text(p.get('time') or '09:00')
                from datetime import time
                try: time.fromisoformat(tm)
                except ValueError: raise ValueError('Geçerli bir saat girin.')
                fields=dict(customer_id=integer(p['customer_id'],1) if p.get('customer_id') else None,date=day(p.get('date')),time=tm,title=text(p.get('title'),True),notes=text(p.get('notes')),done=integer(p.get('done',0),0,1))
            elif resource == 'invoices':
                if record_id:
                    raise ValueError('Teklif değiştirilemez; yeni teklif oluşturun.')
                items=p.get('items',[])
                if not isinstance(items,list) or not 1<=len(items)<=100:
                    raise ValueError('En az bir, en fazla 100 teklif kalemi ekleyin.')
                clean=[]
                subtotal=tax=0
                for i in items:
                    q=integer(i.get('quantity'),1,100000)
                    price=money(i.get('unit_price'))
                    rate=integer(i.get('tax_rate',20),0,100)
                    subtotal+=q*price
                    tax+=int((Decimal(q*price)*rate/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                    clean.append(dict(stock_id=integer(i['stock_id'],1) if i.get('stock_id') else None,description=text(i.get('description'),True),quantity=q,unit_price=price,tax_rate=rate))
                dt,valid=day(p.get('date')),day(p.get('valid_until'))
                if valid<dt:
                    raise ValueError('Geçerlilik tarihi teklif tarihinden önce olamaz.')
                rid=self.save(db,'invoices',dict(customer_id=integer(p.get('customer_id'),1),date=dt,valid_until=valid,notes=text(p.get('notes')),subtotal=subtotal,tax=tax,total=subtotal+tax))
                for i in clean:
                    self.save(db,'invoice_items',dict(invoice_id=rid,**i))
                return {'id':rid}
            elif resource == 'invoice-convert':
                invoice=db.execute('SELECT * FROM invoices WHERE id=?',(record_id,)).fetchone()
                if not invoice or invoice['status']!='Proforma':
                    raise ValueError('Yalnızca proforma durumundaki teklif satışa dönüştürülebilir.')
                for item in db.execute('SELECT * FROM invoice_items WHERE invoice_id=?',(record_id,)).fetchall():
                    if item['stock_id']:
                        self.move_stock(db,item['stock_id'],-item['quantity'],f'Satış PF-{record_id:04d}')
                if invoice['total']:
                    self.save(db,'ledger',dict(customer_id=invoice['customer_id'],date=date.today().isoformat(),kind='Borç',amount=invoice['total'],description=f'PF-{record_id:04d} satış',due_date=day(p.get('due_date') or date.today().isoformat()),source=f'invoice:{record_id}'))
                db.execute("UPDATE invoices SET status='Satış' WHERE id=?",(record_id,))
                return {'ok':True}
            elif resource == 'settings':
                values={k:text(p.get(k),k=='company') for k in COMPANY_FIELDS}
                values['company_email']=email(values['company_email'])
                for k,v in values.items():
                    db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(k,v))
                return {'ok':True}
            else:
                raise ValueError('Bilinmeyen işlem.')
            rid=self.save(db,resource,fields,record_id)
            if resource=='stock' and not record_id and fields.get('quantity'):
                self.save(db,'stock_movements',dict(stock_id=rid,date=date.today().isoformat(),delta=fields['quantity'],description='Açılış stoku'))
            return {'id':rid}

    def save(self,db,table,fields,rid=None):
        if rid:
            cur=db.execute(f"UPDATE {table} SET "+','.join(f'{k}=?' for k in fields)+' WHERE id=?',(*fields.values(),rid))
            if cur.rowcount!=1:
                raise ValueError('Kayıt bulunamadı.')
            return rid
        cur=db.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",tuple(fields.values()))
        return cur.lastrowid

    def move_stock(self,db,sid,delta,description):
        cur=db.execute('UPDATE stock SET quantity=quantity+? WHERE id=? AND quantity+?>=0',(delta,sid,delta))
        if cur.rowcount!=1:
            raise ValueError('Stok yetersiz veya parça bulunamadı. İşlem kaydedilmedi.')
        self.save(db,'stock_movements',dict(stock_id=sid,date=date.today().isoformat(),delta=delta,description=description))

    def recommendations(self,compressor_id):
        with self.database.connect() as db:
            c=db.execute('SELECT * FROM compressors WHERE id=?',(compressor_id,)).fetchone()
            if not c:
                raise ValueError('Kompresör bulunamadı.')
            matches=rows(db,'''SELECT s.id,s.title,s.operations,s.date,k.brand,k.model,k.serial,k.capacity FROM services s JOIN compressors k ON k.id=s.compressor_id WHERE s.status='Tamamlandı' AND k.capacity=? AND k.id!=? ORDER BY (k.brand=?) DESC,s.date DESC LIMIT 8''',(c['capacity'],c['id'],c['brand']))
        return {'matches':matches,'basis':f"Aynı {c['capacity']} lt kapasitedeki diğer kompresörlerin tamamlanan servisleri; aynı marka önceliklidir.",'note':'Geçmiş kayıtlarına dayalı öneridir. Üretici bakım kılavuzu ve teknisyen kontrolüyle doğrulayın.'}
