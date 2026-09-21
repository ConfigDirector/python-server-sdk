from __future__ import annotations

from configdirector._evaluation import assign_percentage


class TestAssignPercentage:
    def test_assigns_a_stable_percentage_using_rapidhash(self) -> None:
        assert assign_percentage("00000000-0000-0000-0000-000000000001", "abc") == 61.8
        assert assign_percentage("00000000-0000-0000-0000-0000000003e8", "abc") == 34.0
        assert assign_percentage("00000000-0000-0000-0000-0000000007d0", "378368375") == 13.5
        assert assign_percentage("00000000-0000-0000-0000-0000000003e8", "378368376") == 66.0
