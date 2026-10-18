"""Fleet statuses, dispatch manifest locking and emergency reserve behavior."""
import os
import tempfile
import unittest
from fastapi.testclient import TestClient
from main import app

class DispatchLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.old=os.environ.get('TRANSOPT_DB')
        os.environ['TRANSOPT_DB']=self.dir.name+'/fleet.db'
        self.client=TestClient(app)
        self.payload={
            'customer':'Dispatch Demo','pickup_zone':'central','drop_zone':'scarborough',
            'weight_kg':200,'length_cm':100,'width_cm':100,'height_cm':100,
            'skids':1,'cargo_type':'general','delivery_by':'17:00','requested_vehicle':'T04'
        }
    def tearDown(self):
        if self.old is None: os.environ.pop('TRANSOPT_DB',None)
        else: os.environ['TRANSOPT_DB']=self.old
        self.dir.cleanup()
    def routes(self):
        return {r['vehicle']:r for r in self.client.get('/api/plan').json()['routes']}

    def test_ten_trucks_have_distinct_states(self):
        p=self.client.get('/api/plan').json()
        self.assertEqual(len(p['routes']),10)
        self.assertEqual(p['fleet_summary'],{'delivering':2,'available':6,'standby':2})
        self.assertTrue(self.routes()['T01']['shipments'])
        self.assertTrue(self.routes()['T03']['shipments'])
        self.assertEqual(self.routes()['T08']['shipments'],[])
        self.assertTrue(self.routes()['T01']['dispatch_locked'])

    def test_cannot_start_empty_or_reserved_truck(self):
        self.assertEqual(self.client.post('/api/fleet/T04/start').status_code,409)
        self.assertEqual(self.client.post('/api/fleet/T08/start').status_code,409)
        release=self.client.post('/api/fleet/T08/release')
        self.assertEqual(release.status_code,200,release.text)
        self.assertEqual(self.routes()['T08']['dispatch_status'],'available')
        self.assertEqual(self.client.post('/api/fleet/T08/release').status_code,409)

    def test_loaded_truck_can_start_and_manifest_is_frozen(self):
        placed=self.client.post('/api/orders',json=self.payload)
        self.assertEqual(placed.status_code,201,placed.text)
        before=self.routes()['T04']
        self.assertIn('B001',before['shipments'])
        started=self.client.post('/api/fleet/T04/start')
        self.assertEqual(started.status_code,200,started.text)
        self.assertEqual(started.json()['manifest'],before['stop_sequence'])
        after=self.routes()['T04']
        self.assertEqual(after['dispatch_status'],'delivering')
        self.assertEqual(after['stop_sequence'],before['stop_sequence'])
        self.assertEqual(self.client.post('/api/fleet/T04/start').status_code,409)
        self.assertEqual(self.client.delete('/api/orders/1').status_code,409)
        self.assertEqual(self.client.post('/api/orders/1/assign',json={'requested_vehicle':'T05'}).status_code,409)
        self.assertEqual(self.client.post('/api/assignment-preview',json=self.payload).status_code,409)
        self.assertEqual(self.routes()['T04']['stop_sequence'],before['stop_sequence'])

    def test_active_route_is_not_replanned_when_new_order_added(self):
        original=self.routes()['T01']['stop_sequence']
        new={**self.payload,'requested_vehicle':None}
        self.assertEqual(self.client.post('/api/orders',json=new).status_code,201)
        after=self.routes()
        self.assertEqual(after['T01']['stop_sequence'],original)
        self.assertFalse(any('B001' in x for x in after['T01']['stop_sequence']))

if __name__=='__main__':unittest.main()
