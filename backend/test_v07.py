"""v0.7: Geographic, customer-to-truck pinning and migration smoke tests."""
import os
import sqlite3
import tempfile
import unittest
from fastapi.testclient import TestClient
from main import app
from locations import ZONES,DEPOT,to_latlng


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.old=os.environ.get('TRANSOPT_DB')
        os.environ['TRANSOPT_DB']=self.folder.name+'/sandbox.db'
        self.client=TestClient(app)
        self.payload={'customer':'Team35 Demo','pickup_zone':'central','drop_zone':'scarborough',
                      'weight_kg':250,'length_cm':100,'width_cm':100,'height_cm':100,
                      'skids':1,'cargo_type':'general','delivery_by':'17:00','requested_vehicle':'T04'}

    def tearDown(self):
        if self.old is None: os.environ.pop('TRANSOPT_DB',None)
        else: os.environ['TRANSOPT_DB']=self.old
        self.folder.cleanup()

    def test_depot_and_service_areas(self):
        response=self.client.get('/api/meta')
        self.assertEqual(response.status_code,200)
        m=response.json()
        self.assertIn('burlington',m['zones'])
        self.assertIn('niagara_falls',m['zones'])
        self.assertIn('vancouver',m['zones'])
        self.assertEqual(m['depot']['address'],'2215 Markham Rd, Scarborough, ON M1B 2W3')
        self.assertEqual(m['version'],'0.8.0')
        lat,lng=to_latlng(*[ZONES['central'][key] for key in ('x','y')])
        self.assertAlmostEqual(lat,DEPOT['lat'])
        self.assertAlmostEqual(lng,DEPOT['lng'])

    def test_manual_create_pin_and_road_map_points(self):
        pre=self.client.post('/api/assignment-preview',json=self.payload)
        self.assertEqual(pre.status_code,200,pre.text)
        self.assertEqual(pre.json()['vehicle'],'T04')
        new=self.client.post('/api/orders',json=self.payload)
        self.assertEqual(new.status_code,201,new.text)
        self.assertEqual(new.json()['requested_vehicle'],'T04')
        planned=self.client.get('/api/plan')
        self.assertEqual(planned.status_code,200,planned.text)
        r=next(r for r in planned.json()['routes'] if 'B001' in r['shipments'])
        self.assertEqual(r['vehicle'],'T04')
        self.assertEqual(r['points'][0]['lat'],DEPOT['lat'])
        self.assertEqual(r['points'][0]['lng'],DEPOT['lng'])
        pickup=next(p for p in r['points'] if p['type']=='drop' and p['shipment']=='B001')
        self.assertAlmostEqual(pickup['lat'],ZONES['scarborough']['lat'],places=4)
        # Assignment is persisted after a second plan request.
        self.assertEqual(next(r for r in self.client.get('/api/plan').json()['routes'] if 'B001' in r['shipments'])['vehicle'],'T04')

    def test_invalid_pinned_vehicle_never_saves(self):
        bad={**self.payload,'skids':25,'requested_vehicle':'T01'}
        response=self.client.post('/api/orders',json=bad)
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(self.client.get('/api/orders').json()['orders'],[])

    def test_existing_order_reassignment_and_auto(self):
        self.assertEqual(self.client.post('/api/orders',json=self.payload).status_code,201)
        changed=self.client.post('/api/orders/1/assign',json={'requested_vehicle':'T02'})
        self.assertEqual(changed.status_code,200,changed.text)
        route=next(r for r in self.client.get('/api/plan').json()['routes'] if 'B001' in r['shipments'])
        self.assertEqual(route['vehicle'],'T02')
        self.assertEqual(self.client.post('/api/orders/1/assign',json={'requested_vehicle':None}).status_code,200)
        self.assertIsNone(self.client.get('/api/orders').json()['orders'][0]['requested_vehicle'])
        self.assertEqual(self.client.post('/api/orders/1/assign',json={'requested_vehicle':'X99'}).status_code,422)

    def test_migrates_previous_order_db(self):
        path=os.environ['TRANSOPT_DB']
        with sqlite3.connect(path) as db:
            db.execute('''CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,customer TEXT NOT NULL,pickup_zone TEXT NOT NULL,
                drop_zone TEXT NOT NULL,weight_kg REAL NOT NULL,volume_m3 REAL NOT NULL,
                cargo_type TEXT NOT NULL,due_min INTEGER NOT NULL,quoted_cad REAL NOT NULL,
                created_at TEXT NOT NULL,skids INTEGER NOT NULL DEFAULT 1,skids_assumed INTEGER NOT NULL DEFAULT 1)''')
            db.execute('''INSERT INTO orders (customer,pickup_zone,drop_zone,weight_kg,volume_m3,cargo_type,due_min,quoted_cad,created_at,skids,skids_assumed)
                VALUES ('Existing Customer','west','east',150,1.5,'general',980,55,'2026-01-01',1,0)''')
        orders=self.client.get('/api/orders')
        self.assertEqual(orders.status_code,200,orders.text)
        self.assertEqual(orders.json()['orders'][0]['pickup_zone'],'west')
        self.assertIsNone(orders.json()['orders'][0]['requested_vehicle'])
        self.assertEqual(self.client.get('/api/plan').status_code,200)


if __name__=='__main__':unittest.main()
