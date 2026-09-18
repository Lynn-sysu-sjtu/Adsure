# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jsonbase_correction_migration import inventory_rules, load_manifest


MANIFEST_PATH = PROJECT_ROOT / "assets" / "jsonbase_correction_manifest_20260917.json"
JSONBASE_DIR = PROJECT_ROOT / "jsonbase"

CONFIRMED_UIDS = {
    "RUID-70e2080dbd695f1f", "RUID-f1af67c8b42cb914", "RUID-074787e4ab4196cf",
    "RUID-1180515ca066cdf0", "RUID-79f64e76cbb89c19", "RUID-b90569db453b71fa",
    "RUID-852f55127f56f04a", "RUID-6df547a796e6aaa8", "RUID-7c25254bccd48252",
    "RUID-0e71dab0d661b022", "RUID-4f1b9d757dc9177c", "RUID-6aaf675cf32e4e3d",
    "RUID-a0a3175230952dcd", "RUID-ead6e10661afdcc1", "RUID-ebab4818abe63984",
    "RUID-6439163a7e2b34c8", "RUID-68862f7e3afd4c37", "RUID-c89cdee611365fc3",
    "RUID-28e7a7d2d25ae606", "RUID-e9129bbc59cd80cd", "RUID-c40c5cc7f19f3c4c",
    "RUID-1694a44a93daa824", "RUID-6c252218419f6fb3", "RUID-19607e3f248cc2f5",
    "RUID-467174683e3b6ab3", "RUID-8f6f0be42218913f", "RUID-d6defab474166af4",
    "RUID-444e62477f0779b1", "RUID-8a7b2709bed97422", "RUID-d2ef21544495915e",
    "RUID-f95c371e0e68eee3", "RUID-eb5568dc49e51df9", "RUID-bef8cd9663741f54",
    "RUID-a0fe79ec4fa4a790", "RUID-b288979a746ecc79", "RUID-fba2b7c4e349d1ee",
    "RUID-ec56d205b19873b0", "RUID-60197dfa6e387977", "RUID-ba33920c2d3dd6a9",
    "RUID-97c034528fab40c3", "RUID-c8d9714e6134eb2e", "RUID-5918828973a76530",
    "RUID-11072b7051c09786", "RUID-5aa5c8f2aa831518", "RUID-6003a44f5ad562ab",
    "RUID-abcddf44be8c7b73", "RUID-4a6d2c4fc4cc871e", "RUID-8a102844838a7107",
    "RUID-7d0cafae98e5c7f3", "RUID-e255eaff8d3be92b", "RUID-0aa92e46809d6596",
    "RUID-fe1de6c6adfa8d2f", "RUID-2d6b54805a05b56a",
}

SOURCE_REPAIR_UIDS = {
    "RUID-6c252218419f6fb3", "RUID-19607e3f248cc2f5", "RUID-467174683e3b6ab3",
    "RUID-8f6f0be42218913f", "RUID-d6defab474166af4", "RUID-444e62477f0779b1",
    "RUID-8a7b2709bed97422", "RUID-d2ef21544495915e", "RUID-f95c371e0e68eee3",
}

SIDE_PATH_UIDS = {
    "RUID-70e2080dbd695f1f", "RUID-f1af67c8b42cb914", "RUID-074787e4ab4196cf",
    "RUID-1180515ca066cdf0", "RUID-79f64e76cbb89c19", "RUID-b90569db453b71fa",
    "RUID-852f55127f56f04a", "RUID-6df547a796e6aaa8", "RUID-7c25254bccd48252",
    "RUID-0e71dab0d661b022", "RUID-4f1b9d757dc9177c", "RUID-6aaf675cf32e4e3d",
    "RUID-a0a3175230952dcd", "RUID-ead6e10661afdcc1", "RUID-ebab4818abe63984",
    "RUID-6439163a7e2b34c8", "RUID-68862f7e3afd4c37", "RUID-c89cdee611365fc3",
    "RUID-28e7a7d2d25ae606", "RUID-e9129bbc59cd80cd", "RUID-c40c5cc7f19f3c4c",
    "RUID-1694a44a93daa824",
}


class JsonbaseCorrectionManifestTests(unittest.TestCase):
    def test_manifest_covers_exactly_confirmed_53_uids(self):
        manifest = load_manifest(MANIFEST_PATH)
        entries = manifest["rules"]
        self.assertEqual("2026-09-17.v1", manifest["manifest_version"])
        self.assertEqual(53, len(entries))
        self.assertEqual(CONFIRMED_UIDS, {item["rule_uid"] for item in entries})
        self.assertTrue(all(item.get("action") for item in entries))

    def test_manifest_has_exact_source_repair_and_side_path_sets(self):
        entries = load_manifest(MANIFEST_PATH)["rules"]
        by_action = {}
        for entry in entries:
            by_action.setdefault(entry["action"], set()).add(entry["rule_uid"])
        self.assertEqual(SOURCE_REPAIR_UIDS, by_action.get("source_repair", set()))
        self.assertEqual(SIDE_PATH_UIDS, by_action.get("side_path", set()))

    def test_every_manifest_uid_resolves_to_one_jsonbase_record(self):
        inventory = inventory_rules(JSONBASE_DIR)
        for uid in CONFIRMED_UIDS:
            self.assertIn(uid, inventory)
            self.assertEqual(1, len(inventory[uid]), uid)


if __name__ == "__main__":
    unittest.main()
