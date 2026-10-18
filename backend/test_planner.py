import unittest
from planner import plan, SHIPMENTS, VEHICLES, Shipment, route_metrics, insertions

class PlannerTests(unittest.TestCase):
    def test_no_duplicates_or_overcapacity(self):
        result=plan()
        seen=[]
        for route in result['routes']:
            seen.extend(route['shipments'])
            self.assertLessEqual(route['peak_weight_kg'],route['weight_limit_kg'])
            self.assertLessEqual(route['peak_skids'],route['skid_limit'])
            self.assertLessEqual(route['peak_volume_m3'],route['volume_limit_m3'])
            self.assertFalse(route['late_shipments'])
            self.assertFalse(route['shift_violation'])
            self.assertFalse(route['capacity_violation'])
            self.assertFalse(route['ordering_violation'])
        self.assertEqual(len(seen),len(set(seen)))
        self.assertEqual(len(seen)+len(result['unassigned']),len(SHIPMENTS))

    def test_driver_absence(self):
        result=plan(absent_driver='D01')
        self.assertNotIn('D01',[r['driver'] for r in result['routes']])
        self.assertEqual(result['assigned_count']+len(result['unassigned']),len(SHIPMENTS))

    def test_pickup_before_drop_and_capacity(self):
        custom=Shipment('B001',1000,4,8,4,960,pickup_x=5,pickup_y=3,pickup_at_depot=False)
        result=plan(shipments=[custom],vehicles=[VEHICLES[0]])
        route=result['routes'][0]
        self.assertEqual(route['stop_sequence'],['P:B001','D:B001'])
        self.assertEqual(route['peak_weight_kg'],1000)
        self.assertEqual(route['events'][-1]['onboard_weight_kg'],0)

    def test_pickup_can_be_rejected_by_capacity(self):
        s=Shipment('B999',40000,150,8,4,960,pickup_x=5,pickup_y=3,pickup_at_depot=False)
        result=plan(shipments=[s])
        self.assertEqual(result['assigned_count'],0)
        self.assertEqual(len(result['unassigned']),1)

    def test_refrigerated_order_is_rejected(self):
        s=Shipment('B888',250,2,4,4,960,equipment='reefer')
        result=plan(shipments=[s])
        self.assertEqual(result['assigned_count'],0)
        self.assertIn('reefer',result['unassigned'][0]['reason'])

    def test_weight_freed_after_delivery(self):
        a=Shipment('A',4000,20,3,0,960)
        b=Shipment('B',4000,20,6,0,1020,pickup_x=4,pickup_y=0,pickup_at_depot=False)
        # after dropping A at x3, truck can pick B at x4 despite 8t cumulative
        result=plan(shipments=[a,b],vehicles=[VEHICLES[0]])
        self.assertEqual(result['assigned_count'],2)
        route=result['routes'][0]
        self.assertLessEqual(route['peak_weight_kg'],VEHICLES[0].max_weight_kg)

if __name__=='__main__': unittest.main()
