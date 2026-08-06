from __future__ import annotations

import json
from typing import Any

import pytest

from configdirector._bundle import parse_bundle
from configdirector.evaluation import (
    ConditionalRule,
    EnumTypeConstraints,
    NumericTypeConstraints,
    PercentageRule,
)

from helpers import RecordingLogger


def wire_config(**overrides: Any) -> dict[str, Any]:
    config = {
        "id": "00000000-0000-0000-0000-0000000000aa",
        "key": "greeting",
        "type": "string",
        "variations": [],
        "target": {
            "environmentId": "10000000-0000-0000-0000-000000000000",
            "defaultValue": "hello",
            "defaultValueId": "value-id-1",
            "rules": [],
        },
    }
    config.update(overrides)
    return config


def wire_bundle(*configs: dict[str, Any], **overrides: Any) -> str:
    document: dict[str, Any] = {
        "environmentId": "10000000-0000-0000-0000-000000000000",
        "projectId": "20000000-0000-0000-0000-000000000000",
        "kind": "full",
        "configs": {config["key"]: config for config in configs},
    }
    document.update(overrides)
    return json.dumps(document)


@pytest.fixture
def logger() -> RecordingLogger:
    return RecordingLogger()


class TestBundleEnvelope:
    def test_reads_the_envelope_fields(self, logger: RecordingLogger) -> None:
        result = parse_bundle(wire_bundle(timestamp="2024-01-01T00:00:00.000Z"), logger)

        assert result.kind == "full"
        assert result.environment_id == "10000000-0000-0000-0000-000000000000"
        assert result.project_id == "20000000-0000-0000-0000-000000000000"
        assert result.timestamp == "2024-01-01T00:00:00.000Z"

    def test_reads_a_delta_bundle(self, logger: RecordingLogger) -> None:
        assert parse_bundle(wire_bundle(kind="delta"), logger).kind == "delta"

    def test_an_unknown_kind_is_taken_as_full(self, logger: RecordingLogger) -> None:
        assert parse_bundle(wire_bundle(kind="partial"), logger).kind == "full"

    def test_a_missing_timestamp_stays_none(self, logger: RecordingLogger) -> None:
        assert parse_bundle(wire_bundle(), logger).timestamp is None

    def test_rejects_a_payload_that_is_not_an_object(self, logger: RecordingLogger) -> None:
        with pytest.raises(ValueError, match="JSON object"):
            parse_bundle("[]", logger)

    def test_rejects_malformed_json(self, logger: RecordingLogger) -> None:
        with pytest.raises(ValueError, match="Expecting"):
            parse_bundle("{not json", logger)

    def test_a_bundle_without_configs_is_empty(self, logger: RecordingLogger) -> None:
        assert parse_bundle(json.dumps({"kind": "full"}), logger).configs == {}


class TestConfigParsing:
    def test_reads_a_config(self, logger: RecordingLogger) -> None:
        result = parse_bundle(wire_bundle(wire_config()), logger)

        config = result.configs["greeting"]
        assert config.id == "00000000-0000-0000-0000-0000000000aa"
        assert config.key == "greeting"
        assert config.type == "string"
        assert config.target.default_value == "hello"

    def test_a_config_that_cannot_be_read_is_skipped(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(wire_config(), wire_config(key="broken", target=None))

        result = parse_bundle(payload, logger)

        assert set(result.configs) == {"greeting"}
        assert any("Skipping the config 'broken'" in m for m in logger.messages("warning"))

    def test_reads_variations(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(variations=[{"name": "Control", "value": "a"}, {"name": None, "value": 2}])
        )

        variations = parse_bundle(payload, logger).configs["greeting"].variations

        assert [(v.name, v.value) for v in variations] == [("Control", "a"), (None, 2)]

    def test_reads_numeric_type_constraints(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(typeConstraints={"min": {"relation": ">=", "value": 1}, "max": None})
        )

        constraints = parse_bundle(payload, logger).configs["greeting"].type_constraints

        assert isinstance(constraints, NumericTypeConstraints)
        assert constraints.min == {"relation": ">=", "value": 1}

    def test_reads_enum_type_constraints(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(wire_config(typeConstraints={"valueType": "string", "values": ["a", "b"]}))

        constraints = parse_bundle(payload, logger).configs["greeting"].type_constraints

        assert isinstance(constraints, EnumTypeConstraints)
        assert constraints.values == ["a", "b"]

    def test_absent_type_constraints_stay_none(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(wire_config(typeConstraints=None))

        assert parse_bundle(payload, logger).configs["greeting"].type_constraints is None


class TestRuleParsing:
    def test_reads_a_conditional_rule(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(
                target={
                    "defaultValue": "hello",
                    "rules": [
                        {
                            "id": "rule-1",
                            "type": "conditional",
                            "order": 1,
                            "target": "value",
                            "value": "bonjour",
                            "valueId": "value-id-2",
                            "conditions": [
                                {
                                    "id": "condition-1",
                                    "attribute": "name",
                                    "operator": "equals",
                                    "targetType": "text",
                                    "targetValues": ["Ada"],
                                }
                            ],
                        }
                    ],
                }
            )
        )

        rules = parse_bundle(payload, logger).configs["greeting"].target.rules

        assert isinstance(rules[0], ConditionalRule)
        assert rules[0].order == 1
        assert rules[0].value == "bonjour"
        assert rules[0].conditions[0].attribute == "name"
        assert rules[0].conditions[0].target_values == ["Ada"]

    def test_reads_a_percentage_rule(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(
                target={
                    "defaultValue": "hello",
                    "rules": [
                        {
                            "id": "rule-1",
                            "type": "percentage",
                            "order": 0,
                            "target": "percentage",
                            "percentages": [
                                {"id": "p-1", "percentage": 50, "value": "a"},
                                {"id": "p-2", "percentage": 50, "value": "b"},
                            ],
                        }
                    ],
                }
            )
        )

        rules = parse_bundle(payload, logger).configs["greeting"].target.rules

        assert isinstance(rules[0], PercentageRule)
        assert [p.percentage for p in rules[0].percentages] == [50.0, 50.0]

    def test_an_unknown_rule_kind_keeps_its_wire_type(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(
                target={
                    "defaultValue": "hello",
                    "rules": [{"id": "rule-1", "type": "from-the-future", "order": 0}],
                }
            )
        )

        rules = parse_bundle(payload, logger).configs["greeting"].target.rules

        # Carried through rather than dropped, so the evaluator is the one place that decides
        # what to do with a rule kind this version does not know.
        assert rules[0].type == "from-the-future"

    def test_a_rule_without_an_order_evaluates_last(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(
                target={
                    "defaultValue": "hello",
                    "rules": [{"id": "rule-1", "type": "conditional", "value": "x"}],
                }
            )
        )

        assert parse_bundle(payload, logger).configs["greeting"].target.rules[0].order is None

    @pytest.mark.parametrize(
        ("wire_value", "expected"),
        [(True, "true"), (26, "26"), (26.0, "26"), (1.5, "1.5"), ("Ada", "Ada"), (None, "")],
    )
    def test_target_values_render_the_way_every_sdk_renders_them(
        self, logger: RecordingLogger, wire_value: Any, expected: str
    ) -> None:
        payload = wire_bundle(
            wire_config(
                target={
                    "defaultValue": "hello",
                    "rules": [
                        {
                            "id": "rule-1",
                            "type": "conditional",
                            "order": 0,
                            "conditions": [
                                {
                                    "id": "condition-1",
                                    "attribute": "name",
                                    "operator": "equals",
                                    "targetType": "text",
                                    "targetValues": [wire_value],
                                }
                            ],
                        }
                    ],
                }
            )
        )

        rule = parse_bundle(payload, logger).configs["greeting"].target.rules[0]

        assert isinstance(rule, ConditionalRule)
        assert rule.conditions[0].target_values == [expected]

    def test_a_structured_rule_value_is_carried_as_json_text(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(
                target={
                    "defaultValue": "{}",
                    "rules": [{"id": "rule-1", "type": "conditional", "order": 0, "value": {"a": 1}}],
                }
            )
        )

        rule = parse_bundle(payload, logger).configs["greeting"].target.rules[0]

        assert isinstance(rule, ConditionalRule)
        assert rule.value == '{"a":1}'
