import unittest
from engine import calculate_bkt, get_recommendation

class TestEngine(unittest.TestCase):
    def test_bkt_progression(self):
        # Testing with initial p = 0.3
        p1 = calculate_bkt(0.3, True)
        self.assertGreater(p1, 0.3)

        p2 = calculate_bkt(p1, True)
        self.assertGreater(p2, p1)

        p3 = calculate_bkt(p2, False)
        self.assertLess(p3, p2)

        # Test lower clamp
        p_low = calculate_bkt(0.01, False)
        self.assertGreaterEqual(p_low, 0.01)

    def test_recommendations(self):
        rec1, _ = get_recommendation(0.2)
        self.assertIn("basic concepts", rec1)

        rec2, _ = get_recommendation(0.6)
        self.assertIn("practice questions", rec2)

        rec3, _ = get_recommendation(0.9)
        self.assertIn("practical evidence", rec3)

if __name__ == '__main__':
    unittest.main()
