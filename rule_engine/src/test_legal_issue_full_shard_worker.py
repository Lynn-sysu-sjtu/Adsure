import unittest

from legal_issue_full_shard_worker import partition_records


class FullShardWorkerTests(unittest.TestCase):
    def test_partitions_cover_all_records_without_overlap(self):
        records = [{"id": index} for index in range(17)]
        shards = [partition_records(records, index, 4) for index in range(4)]
        flattened = [item["id"] for shard in shards for item in shard]
        self.assertEqual(list(range(17)), sorted(flattened))
        self.assertEqual(17, len(set(flattened)))

    def test_rejects_invalid_shard_arguments(self):
        with self.assertRaises(ValueError):
            partition_records([], 4, 4)


if __name__ == "__main__":
    unittest.main()
