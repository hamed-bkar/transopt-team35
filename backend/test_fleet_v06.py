"""Version 0.6 regression tests: reported fleet, skid turnover, 13h cap, recovery."""
import os
import tempfile
import unittest
from dataclasses import replace
from fastapi.testclient import TestClient
from planner import (
    VEHICLES, Shipment, WORKDAY_START_MIN, PROJECT_MAX_WORK_MIN,
    LB_PER_KG, plan, route_metrics,
)
from operations import recovery_options
from main import app, connection


class FleetRulesTests(unittest.TestCase):
    def test_reported_capacity_table_and_estimated_trailer_skids(self):
        self.assertEqual([(v.skid_limit, v.weight_limit_lb) for v in VEHICLES[:3]],
                         [(12,15000),(26,44000),(26,64000)])
        self.assertFalse(VEHICLES[2].skid_capacity_estimated)
        self.assertFalse(VEHICLES[0].skid_capacity_estimated)
        self.assertEqual(VEHICLES[0].max_weight_kg * LB_PER_KG, 15000)

    def test_rejects_13_skids_on_12_skid_vehicle(self):
        shipment=Shipment('OVER_SKIDS',100,1,3,3,1150,skids=13)
        truck=VEHICLES[0]
        self.assertTrue(route_metrics([('drop',shipment)],truck)['capacity_violation'])
        self.assertEqual(plan([shipment],[truck])['assigned_count'],0)
        self.assertEqual(plan([shipment],[VEHICLES[1]])['assigned_count'],1)

    def test_skids_reclaimed_after_drop_before_new_pickup(self):
        a=Shipment('A',500,3,3,0,1140,skids=12)
        b=Shipment('B',500,3,7,0,1200,pickup_x=4,pickup_y=0,
                   pickup_at_depot=False,skids=12)
        route=plan([a,b],[VEHICLES[0]])['routes'][0]
        self.assertCountEqual(route['shipments'],['A','B'])
        self.assertLessEqual(route['peak_skids'],12)
        self.assertEqual(route['events'][-1]['onboard_skids'],0)
        self.assertEqual(route['events'][-1]['skid_space_left'],12)

    def test_weight_limit_in_pounds_blocks(self):
        s=Shipment('WEIGHT',6900,2,2,2,1150,skids=1)
        self.assertGreater(s.weight_kg*LB_PER_KG,15000)
        self.assertEqual(plan([s],[VEHICLES[0]])['assigned_count'],0)
        self.assertEqual(plan([s],[VEHICLES[1]])['assigned_count'],1)

    def test_work_limit_rejects_long_service_shift(self):
        # 10h + 4h services plus driving and return > 13h project cap.
        a=Shipment('LONG1',100,1,1,1,2000,service_min=600)
        b=Shipment('LONG2',100,1,2,2,2000,service_min=240)
        metric=route_metrics([('drop',a),('drop',b)],VEHICLES[1])
        self.assertGreater(metric['driver_hours']['scheduled_on_duty_min'],PROJECT_MAX_WORK_MIN)
        self.assertTrue(metric['work_violation'])
        self.assertTrue(metric['shift_violation'])

    def test_recovery_wait_pickups_only_after_preexisting_stops(self):
        outcome=recovery_options()
        option=next(o for o in outcome['options'] if o['id']=='wait')
        self.assertEqual(option['priority'],3)
        baseline={r['vehicle']:r for r in outcome['baseline']['routes']}
        displaced=set(outcome['scenario']['displaced_shipments'])
        for route in option['plan']['routes']:
            existing=baseline[route['vehicle']]['stop_sequence']
            extra=[k for k in route['stop_sequence'] if k.split(':')[1] in displaced]
            if extra:
                self.assertEqual(route['stop_sequence'][:len(existing)],existing)
                self.assertTrue(all(e.startswith(('P:','D:')) for e in extra))
                self.assertTrue(all(route['stop_sequence'].index('P:'+id)<route['stop_sequence'].index('D:'+id)
                                    for id in displaced if 'D:'+id in route['stop_sequence']))
        self.assertEqual(option['plan']['assigned_count']+len(option['plan']['unassigned']),
                         option['plan']['total_shipments'])

class FleetApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=os.getenv('TRANSOPT_DB')
        os.environ['TRANSOPT_DB']=os.path.join(self.temp.name,'orders.db')
        self.client=TestClient(app)

    def tearDown(self):
        if self.old is None: os.environ.pop('TRANSOPT_DB',None)
        else: os.environ['TRANSOPT_DB']=self.old
        self.temp.cleanup()

    def test_incomplete_skids_quote_provisional(self):
        sample=dict(customer='Demo Shop',pickup_zone='west',drop_zone='east',weight_kg=300,
                    length_cm=100,width_cm=100,height_cm=100)
        q=self.client.post('/api/quote',json=sample)
        self.assertEqual(q.status_code,200)
        self.assertTrue(q.json()['provisional'])
        self.assertFalse(q.json()['eligible_for_submission'])
        self.assertEqual(self.client.post('/api/orders',json=sample).status_code,422)
        sample['skids']=2
        quote=self.client.post('/api/quote',json=sample).json()
        self.assertFalse(quote['provisional'])
        create=self.client.post('/api/orders',json=sample)
        self.assertEqual(create.status_code,201)
        self.assertEqual(self.client.get('/api/orders').json()['orders'][0]['skids'],2)

    def test_unverified_legacy_order_cannot_be_assigned(self):
        with connection() as db:
            db.execute("""INSERT INTO orders
                (customer,pickup_zone,drop_zone,weight_kg,volume_m3,cargo_type,due_min,quoted_cad,created_at,skids,skids_assumed)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",(
                'Legacy','west','north',300,2,'general',1020,50,'2026-10-01T09:00:00Z',1,1))
        plan_result=self.client.get('/api/plan').json()
        self.assertEqual(plan_result['total_shipments'],13)
        self.assertIn('B001',[item['shipment'] for item in plan_result['unassigned']])
        self.assertIn('declared skid count',plan_result['unassigned'][-1]['reason'])

    def test_recovery_api_has_four_options_and_hours(self):
        result=self.client.get('/api/recovery?failure_type=truck')
        self.assertEqual(result.status_code,200)
        options=result.json()['options']
        self.assertEqual([o['id'] for o in options],['standby','preserve','wait','reopt'])
        self.assertEqual(len(result.json()['waiting_drivers']),1)
        for option in options:
            for r in option['plan']['routes']:
                self.assertLessEqual(r['driver_hours']['scheduled_on_duty_min'],780)
                self.assertLessEqual(r['driver_hours']['estimated_drive_min'],780)
                self.assertLessEqual(r['peak_skids'],r['skid_limit'])
                self.assertLessEqual(r['peak_weight_lb'],r['weight_limit_lb'])

if __name__=='__main__':unittest.main()
