import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.aco_route import aco_route
from app.hho_route import hho_route
from app.lo_dcs import lo_dcs_route
from app.predictor import FillPredictor
from app.route_common import route_length_km


class RouteTests(unittest.TestCase):
    def test_routes_preserve_stops_and_reproduce_seed(self):
        bins = [SimpleNamespace(bin_id=str(i), lat=53.3+i*0.001,
                                lon=-6.2+(i % 3)*0.002) for i in range(8)]
        for algorithm in (aco_route, hho_route, lo_dcs_route):
            with self.subTest(algorithm=algorithm.__name__):
                options = dict(max_iterations=5)
                options['n_ants' if algorithm is aco_route else 'population_size'] = 10
                first = algorithm(bins, 53.3, -6.2, rng=random.Random(42), **options)
                second = algorithm(bins, 53.3, -6.2, rng=random.Random(42), **options)
                self.assertCountEqual([b.bin_id for b in bins], [s.bin_id for s in first])
                self.assertEqual(first, second)
                self.assertGreater(route_length_km(first, 53.3, -6.2), 0)
                self.assertEqual(algorithm([], 53.3, -6.2, **options), [])


class PredictorTests(unittest.TestCase):
    def test_learning_fallback_and_reset(self):
        predictor = FillPredictor()
        self.assertEqual(predictor.predicted_fill_rate_h('a', 4), 4)
        for start, end in ((0, 36000), (40000, 76000)):
            predictor.record_event('EMPTIED', 'a', start)
            predictor.record_event('OVERFLOW', 'a', end)
        self.assertTrue(predictor.has_learned('a'))
        self.assertAlmostEqual(predictor.predicted_fill_rate_h('a', 4), 10)
        self.assertAlmostEqual(predictor.predicted_etf_h('a', 80, 4), 2)
        self.assertEqual(predictor.predicted_etf_h('a', 110, 4), 0)
        predictor.reset()
        self.assertFalse(predictor.has_learned('a'))
        self.assertEqual(predictor.predicted_fill_rate_h('a', 4), 4)


if __name__ == '__main__':
    unittest.main()
