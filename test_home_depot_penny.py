import json
import tempfile
import unittest
from pathlib import Path
from collect_home_depot_penny import classify, run

class PennyRadarTests(unittest.TestCase):
    def test_deep_clearance_is_high_probability(self):
        status, score, _ = classify({"price":20,"regularPrice":100})
        self.assertEqual(status, "HIGH PROBABILITY")
        self.assertGreaterEqual(score, 55)

    def test_unconfirmed_penny_is_candidate(self):
        status, _, _ = classify({"price":0.01,"regularPrice":100})
        self.assertEqual(status, "PENNY CANDIDATE")

    def test_receipt_confirms_penny(self):
        status, score, _ = classify({"price":0.01,"regularPrice":100,"confirmationMethod":"receipt"})
        self.assertEqual((status, score), ("CONFIRMED", 100))

    def test_incomplete_capture_never_creates_disappearance(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d); obs=d/"obs.json"; hist=d/"hist.json"; out=d/"out.json"
            hist.write_text(json.dumps({"products":{"123|ABC":{"latest":{"storeId":"123","sku":"ABC","price":20,"regularPrice":100},"history":[]}}}))
            obs.write_text(json.dumps({"captureComplete":False,"items":[]}))
            result=run(obs,hist,out)
            self.assertEqual(result["items"], [])

    def test_complete_capture_marks_missing_clearance_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d); obs=d/"obs.json"; hist=d/"hist.json"; out=d/"out.json"
            hist.write_text(json.dumps({"products":{"123|ABC":{"latest":{"storeId":"123","sku":"ABC","price":20,"regularPrice":100},"history":[]}}}))
            obs.write_text(json.dumps({"captureComplete":True,"capturedStoreIds":["123"],"items":[]}))
            result=run(obs,hist,out)
            self.assertEqual(result["items"][0]["signalStatus"], "PENNY CANDIDATE")
            self.assertTrue(result["items"][0]["requiresPhysicalConfirmation"])

if __name__ == "__main__":
    unittest.main()
