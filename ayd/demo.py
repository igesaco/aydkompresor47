from datetime import date,timedelta
from .domain import App,add_months


def populate(database):
    app=App(database)
    if app.snapshot()['customers']:
        return
    today=date.today()
    iso=today.isoformat()
    customers=[('Mavişehir Otomotiv','0532 100 20 30','Sanayi Mah. 204. Sokak No:12'),('Atlas Metal Sanayi','0533 200 30 40','Organize Sanayi Bölgesi, 5. Cadde'),('Yılmaz Oto Servis','0544 300 40 50','Yeni Sanayi Sitesi C Blok'),('Demir Mobilya','0555 400 50 60','Marangozlar Sitesi No:47')]
    for name,phone,address in customers:
        app.mutate('customers',dict(name=name,phone=phone,address=address))
    for i,(name,qty,minimum,price) in enumerate([('Hava filtresi · 50 lt',3,5,450),('Kompresör yağı · 1 lt',12,5,680),('Basınç şalteri · 8 bar',2,3,1250),('Emniyet valfi · 1/4”',18,4,320),('Kayış · A-42',7,3,280)]):
        app.mutate('stock',dict(sku=f'AYD-{101+i}',name=name,quantity=qty,minimum=minimum,buy_price=str(price*.65),sell_price=price,supplier='Anadolu Teknik',category='Sarf malzeme' if i<2 else 'Yedek parça'))
    for cid,brand,model,serial,cap,war in [(1,'Lupamat','LKT 50','LPM-2024-081',50,12),(2,'Dalgakıran','DKC 200','DLG-2023-142',200,90),(3,'Lupamat','LKT 50','LPM-2025-096',50,180),(4,'Fini','MK 100','FIN-2024-032',100,-5)]:
        app.mutate('compressors',dict(customer_id=cid,brand=brand,model=model,serial=serial,capacity=cap,warranty_end=(today+timedelta(days=war)).isoformat()))
    old=add_months(iso,-6)
    app.mutate('services',dict(compressor_id=1,date=old,title='Periyodik bakım',operations='Hava filtresi değiştirildi. Kompresör yağı yenilendi. Tank tahliyesi ve 8 bar basınç testi yapıldı.',amount=1850,maintenance_months=6,status='Tamamlandı',parts=[]))
    app.mutate('services',dict(compressor_id=2,date=iso,title='Basınç kaybı kontrolü',operations='Kaçak testi ve basınç şalteri kontrolü planlandı.',amount=2400,maintenance_months=6,status='İşlemde',parts=[{'stock_id':3,'quantity':1}]))
    app.mutate('services',dict(compressor_id=4,date=(today-timedelta(days=5)).isoformat(),title='Yağ ve filtre bakımı',operations='Yağ yenilendi, filtre temizlendi ve sızdırmazlık kontrol edildi.',amount=3200,maintenance_months=6,status='Tamamlandı',parts=[]))
    app.mutate('ledger',dict(customer_id=1,date=iso,kind='Tahsilat',amount=850,description='Kısmi servis ödemesi'))
    app.mutate('ledger',dict(customer_id=2,date=iso,kind='Borç',amount=12400,description='Önceki dönem satış bakiyesi',due_date=(today-timedelta(days=7)).isoformat()))
    for i,(title,cid,offset,tm) in enumerate([('Periyodik bakım görüşmesi',1,0,'10:30'),('Atölyede basınç testi',2,0,'14:00'),('Kompresör teslimi',4,1,'11:00'),('50 lt bakım randevusu',3,3,'09:30')]):
        app.mutate('events',dict(title=title,customer_id=cid,date=(today+timedelta(days=offset)).isoformat(),time=tm))
    app.mutate('invoices',dict(customer_id=3,date=iso,valid_until=(today+timedelta(days=15)).isoformat(),notes='Teslimat: 3 iş günü. Ödeme: havale / EFT.',items=[dict(stock_id=1,description='Hava filtresi · 50 lt',quantity=2,unit_price=450,tax_rate=20),dict(description='Periyodik bakım işçiliği',quantity=1,unit_price=950,tax_rate=20)]))
