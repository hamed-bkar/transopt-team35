import os
import tempfile
import unittest

from main import OrderRequest, quote, all_shipments, connection, create_order, delete_order, get_plan

class OrderTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.previous=os.environ.get('TRANSOPT_DB')
        os.environ['TRANSOPT_DB']=os.path.join(self.dir.name,'orders.db')
        self.payload={'customer':'Demo Bakery','pickup_zone':'west','drop_zone':'east','cargo_type':'general','delivery_by':'16:00'}

    def tearDown(self):
        if self.previous is None: os.environ.pop('TRANSOPT_DB',None)
        else: os.environ['TRANSOPT_DB']=self.previous
        self.dir.cleanup()

    def test_provisional_quote_has_no_discount(self):
        estimate=quote(OrderRequest(**self.payload))
        self.assertTrue(estimate['provisional'])
        self.assertEqual(estimate['information_discount_cad'],0)
        self.assertFalse(estimate['eligible_for_submission'])

    def test_complete_quote_order_route_and_delete(self):
        payload={**self.payload,'weight_kg':300,'length_cm':100,'width_cm':100,'height_cm':100,'skids':1}
        estimate=quote(OrderRequest(**payload))
        self.assertFalse(estimate['provisional'])
        self.assertGreater(estimate['information_discount_cad'],0)
        created=create_order(OrderRequest(**payload))
        self.assertEqual(created['shipment_id'],'B001')
        self.assertEqual(len(all_shipments()),13)
        result=get_plan(absent_driver=None)
        self.assertEqual(result['total_shipments'],13)
        found=[r for r in result['routes'] if 'B001' in r['shipments']]
        if found:
            self.assertIn('P:B001',found[0]['stop_sequence'])
            self.assertLess(found[0]['stop_sequence'].index('P:B001'),found[0]['stop_sequence'].index('D:B001'))
        delete_order(1)
        self.assertEqual(len(all_shipments()),12)

if __name__=='__main__':unittest.main()
