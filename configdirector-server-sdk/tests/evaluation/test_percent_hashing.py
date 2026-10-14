from __future__ import annotations

from configdirector._evaluation import assign_percentage

CONFIG_ID = "11111111-1111-4111-8111-111111111111"


class TestAssignPercentage:
    def test_assigns_a_stable_percentage_using_rapidhash(self) -> None:
        assert assign_percentage("00000000-0000-0000-0000-000000000001", "abc", "user") == 61.8
        assert assign_percentage("00000000-0000-0000-0000-0000000003e8", "abc", "user") == 34.0
        assert assign_percentage("00000000-0000-0000-0000-0000000007d0", "378368375", "user") == 13.5
        assert assign_percentage("00000000-0000-0000-0000-0000000003e8", "378368376", "user") == 66.0

    def test_a_user_hashes_its_identifier_and_the_config_id(self) -> None:
        assert assign_percentage(CONFIG_ID, "user-1", "user") == 7.8

    def test_another_kind_also_hashes_its_kind(self) -> None:
        assert assign_percentage(CONFIG_ID, "user-1", "device") == 59.0
        assert assign_percentage(CONFIG_ID, "user-1", "tenant") == 8.5
        assert assign_percentage(CONFIG_ID, "abc", "device") == 75.0
