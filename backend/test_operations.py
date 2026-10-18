import os
import tempfile
import unittest
from fastapi.testclient import TestClient
from main import app, OrderRequest, quote, create_order, all_shipments
from operations import recovery_options
from planner import route_metrics, VEHICLES

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.before=os.getenv('TRANSOPT_DB')
        os.environ['TRANSOPT_DB']=os.path.join(self.folder.name,'orders.db')
        self.client=TestClient(app)
    def tearDown(self):
        if self.before is None:os.environ.pop('TRANSOPT_DB',None)
        else:os.environ['TRANSOPT_DB']=self.before
        self.folder.cleanup()
    def test_simulated_routes_are_drawable(self):
        plan=self.client.get('/api/plan').json()
        for r in plan['routes']:
            self.assertEqual(len(r['points']),len(r['events'])+ (2 if r['events'] else 1))
            self.assertEqual(r['points'][0]['type'],'depot')
            for e in r['events']:
                self.assertTrue(0<=e['onboard_weight_kg']<=r['weight_limit_kg'])
                self.assertTrue(0<=e['onboard_volume_m3']<=r['volume_limit_m3'])
                self.assertIn('onboard_shipments', e)
                self.assertTrue(e['due_min'] is None or e['eta_min']<=e['due_min'])
            self.assertFalse(r['driver_hours']['actual_hos_verified'])
    def test_recovery_returns_conditional_options_and_wait_candidates(self):
        for kind in ['driver','truck']:
            data=self.client.get('/api/recovery',params={'failure_type':kind}).json()
            self.assertEqual(len(data['options']),4)
            self.assertGreater(len(data['waiting_drivers']),0)
            for choice in data['options']:
                self.assertEqual(choice['status'],'conditional')
                self.assertGreaterEqual(choice['plan']['assigned_count'],0)
                self.assertEqual(choice['plan']['total_shipments'],12)
                self.assertEqual(len(choice['plan']['unassigned'])+choice['plan']['assigned_count'],12)
                self.assertTrue(all('points' in r for r in choice['plan']['routes']))
    def test_new_pickup_changes_routes_and_recovery(self):
        order=OrderRequest(customer='Lab Pickup',pickup_zone='west',drop_zone='north',weight_kg=300,length_cm=100,width_cm=100,height_cm=100,delivery_by='17:00',skids=1)
        created=create_order(order)
        self.assertEqual(created['shipment_id'],'B001')
        response=self.client.get('/api/plan').json()
        self.assertEqual(response['total_shipments'],13)
        assigned=[r for r in response['routes'] if 'B001' in r['shipments']]
        self.assertEqual(len(assigned),1)
        events=assigned[0]['events']
        self.assertLess(next(i for i,e in enumerate(events) if e['shipment']=='B001' and e['type']=='pickup'),next(i for i,e in enumerate(events) if e['shipment']=='B001' and e['type']=='drop'))
        recovery=self.client.get('/api/recovery?failure_type=driver').json()
        self.assertTrue(all(opt['plan']['total_shipments']==13 for opt in recovery['options']))
    def test_weight_early_discount_and_provisional(self):
        p={'customer':'Sample','pickup_zone':'west','drop_zone':'east','delivery_by':'16:00'}
        unknown=quote(OrderRequest(**p))
        weighed=quote(OrderRequest(**p,weight_kg=700))
        complete=quote(OrderRequest(**p,weight_kg=700,length_cm=100,width_cm=100,height_cm=100))
        self.assertEqual(unknown['information_discount_rate'],0)
        self.assertEqual(weighed['information_discount_rate'],.02)
        self.assertTrue(weighed['provisional'])
        self.assertFalse(weighed['eligible_for_submission'])
        self.assertEqual(complete['information_discount_rate'],.05)

if __name__=='__main__':unittest.main()
