from __future__ import annotations

import json
from typing import Any

import pytest

from configdirector import Context
from configdirector._bundle import NotAConfigBundleError, parse_bundle
from configdirector._evaluation import (
    AttributeCondition,
    ConditionalRule,
    ConfigEvaluator,
    EnumTypeConstraints,
    EvaluationContext,
    NumericTypeConstraints,
    PercentageRule,
    Segment,
    SegmentCondition,
)
from tests.helpers import RecordingLogger


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

    def test_a_document_without_configs_is_not_a_config_bundle(self, logger: RecordingLogger) -> None:
        with pytest.raises(NotAConfigBundleError):
            parse_bundle(json.dumps({"kind": "full"}), logger)

    def test_a_document_whose_configs_are_not_an_object_is_not_a_config_bundle(
        self, logger: RecordingLogger
    ) -> None:
        with pytest.raises(NotAConfigBundleError):
            parse_bundle(json.dumps({"kind": "delta", "configs": []}), logger)

    def test_not_a_config_bundle_is_a_value_error(self, logger: RecordingLogger) -> None:
        with pytest.raises(ValueError, match="configs"):
            parse_bundle(json.dumps({"type": "heartbeat"}), logger)

    def test_an_explicitly_empty_configs_object_is_an_empty_bundle(self, logger: RecordingLogger) -> None:
        assert parse_bundle(json.dumps({"kind": "full", "configs": {}}), logger).configs == {}


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
        assert result.unreadable_keys == ["broken"]
        assert any("Skipping the config 'broken'" in m for m in logger.messages("warning"))

    def test_a_bundle_whose_configs_all_read_lists_no_unreadable_keys(self, logger: RecordingLogger) -> None:
        assert parse_bundle(wire_bundle(wire_config()), logger).unreadable_keys == []

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
        condition = rules[0].conditions[0]
        assert isinstance(condition, AttributeCondition)
        assert condition.attribute == "name"
        assert condition.target_values == ["Ada"]

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
        condition = rule.conditions[0]
        assert isinstance(condition, AttributeCondition)
        assert condition.target_values == [expected]

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


class TestValueIds:
    def test_reads_the_targeting_default_value_id(self, logger: RecordingLogger) -> None:
        result = parse_bundle(wire_bundle(wire_config()), logger)

        assert result.configs["greeting"].target.default_value_id == "value-id-1"

    def test_reads_a_conditional_rules_value_id(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(
                target={
                    "defaultValue": "hello",
                    "defaultValueId": "value-id-1",
                    "rules": [
                        {
                            "id": "rule-1",
                            "type": "conditional",
                            "order": 0,
                            "target": "value",
                            "value": "bonjour",
                            "valueId": "value-id-2",
                            "conditions": [],
                        }
                    ],
                }
            )
        )

        rule = parse_bundle(payload, logger).configs["greeting"].target.rules[0]

        assert isinstance(rule, ConditionalRule)
        assert rule.value_id == "value-id-2"

    def test_reads_a_percentage_buckets_value_id(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(
                target={
                    "defaultValue": "hello",
                    "defaultValueId": "value-id-1",
                    "rules": [
                        {
                            "id": "rule-1",
                            "type": "percentage",
                            "order": 0,
                            "target": "percentage",
                            "percentages": [
                                {"id": "p-1", "percentage": 100, "value": "a", "valueId": "value-id-3"}
                            ],
                        }
                    ],
                }
            )
        )

        rule = parse_bundle(payload, logger).configs["greeting"].target.rules[0]

        assert isinstance(rule, PercentageRule)
        assert rule.percentages[0].value_id == "value-id-3"

    def test_a_missing_value_id_stays_none(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(
                target={
                    "defaultValue": "hello",
                    "rules": [
                        {"id": "rule-1", "type": "conditional", "order": 0, "value": "x", "conditions": []}
                    ],
                }
            )
        )

        config = parse_bundle(payload, logger).configs["greeting"]
        rule = config.target.rules[0]

        assert isinstance(rule, ConditionalRule)
        assert rule.value_id is None
        assert config.target.default_value_id is None


class TestPayloadFieldsTheSdkDoesNotRead:
    def set_with_condition_kinds_and_payload_version(self, kind: str) -> str:
        return wire_bundle(
            wire_config(
                target={
                    "defaultValue": "hello",
                    "defaultValueId": "value-id-1",
                    "rules": [
                        {
                            "id": "rule-1",
                            "type": "conditional",
                            "order": 0,
                            "target": "value",
                            "value": "bonjour",
                            "valueId": "value-id-2",
                            "conditions": [
                                {
                                    "id": "condition-1",
                                    "kind": "attribute",
                                    "attribute": "identifier",
                                    "trait": None,
                                    "operator": "=",
                                    "targetType": "text",
                                    "targetValues": ["10"],
                                },
                                {
                                    "id": "condition-2",
                                    "kind": "attribute",
                                    "attribute": "traits",
                                    "trait": "/plan",
                                    "operator": "is one of",
                                    "targetType": "text",
                                    "targetValues": ["pro", "enterprise"],
                                },
                            ],
                        }
                    ],
                }
            ),
            kind=kind,
            payloadVersion=1,
        )

    def test_a_full_set_with_condition_kinds_and_a_payload_version_serves_as_before(
        self, logger: RecordingLogger
    ) -> None:
        bundle = parse_bundle(self.set_with_condition_kinds_and_payload_version("full"), logger)
        evaluator = ConfigEvaluator(logger)

        assert bundle.kind == "full"
        assert bundle.unreadable_keys == []
        config = bundle.configs["greeting"]
        matched = evaluator.evaluate(
            config, EvaluationContext(context=Context(id="10", traits={"plan": "pro"}))
        )
        assert matched.value == "bonjour"
        assert matched.value_id == "value-id-2"
        unmatched = evaluator.evaluate(
            config, EvaluationContext(context=Context(id="10", traits={"plan": "free"}))
        )
        assert unmatched.value == "hello"
        assert unmatched.value_id == "value-id-1"

    def test_a_delta_with_condition_kinds_and_a_payload_version_serves_as_before(
        self, logger: RecordingLogger
    ) -> None:
        bundle = parse_bundle(self.set_with_condition_kinds_and_payload_version("delta"), logger)
        evaluator = ConfigEvaluator(logger)

        assert bundle.kind == "delta"
        assert bundle.unreadable_keys == []
        config = bundle.configs["greeting"]
        matched = evaluator.evaluate(
            config, EvaluationContext(context=Context(id="10", traits={"plan": "pro"}))
        )
        assert matched.value == "bonjour"
        assert matched.value_id == "value-id-2"
        unmatched = evaluator.evaluate(
            config, EvaluationContext(context=Context(id="10", traits={"plan": "free"}))
        )
        assert unmatched.value == "hello"
        assert unmatched.value_id == "value-id-1"


class TestSegments:
    def segment_group(self, domain: str, kind: str | None = "attribute") -> dict[str, Any]:
        condition: dict[str, Any] = {
            "id": "g0c0",
            "attribute": "traits",
            "trait": "/email",
            "operator": "ends with any of",
            "targetType": "text",
            "targetValues": [domain],
        }
        if kind is not None:
            condition["kind"] = kind
        return condition

    def rule_for_members_of(self, segment_id: str) -> dict[str, Any]:
        return {
            "id": "rule-1",
            "type": "conditional",
            "order": 0,
            "target": "value",
            "value": "members",
            "valueId": "value-id-2",
            "conditions": [
                {"id": "condition-1", "kind": "segment", "operator": "in", "segmentId": segment_id}
            ],
        }

    def test_reads_the_segments_section_into_groups_of_attribute_conditions(
        self, logger: RecordingLogger
    ) -> None:
        payload = wire_bundle(
            wire_config(),
            segments={
                "segment-1": {
                    "groups": [[self.segment_group("@acme.com")], [self.segment_group("@beta.com")]]
                }
            },
        )

        bundle = parse_bundle(payload, logger)

        assert bundle.segments == {
            "segment-1": Segment(
                groups=[
                    [
                        AttributeCondition(
                            id="g0c0",
                            attribute="traits",
                            trait="/email",
                            operator="ends with any of",
                            target_type="text",
                            target_values=["@acme.com"],
                        )
                    ],
                    [
                        AttributeCondition(
                            id="g0c0",
                            attribute="traits",
                            trait="/email",
                            operator="ends with any of",
                            target_type="text",
                            target_values=["@beta.com"],
                        )
                    ],
                ]
            )
        }

    def test_a_payload_without_a_segments_section_carries_no_segments(self, logger: RecordingLogger) -> None:
        bundle = parse_bundle(wire_bundle(wire_config()), logger)

        assert bundle.segments == {}

    def test_a_group_condition_without_a_kind_is_an_attribute_condition(
        self, logger: RecordingLogger
    ) -> None:
        payload = wire_bundle(
            wire_config(), segments={"segment-1": {"groups": [[self.segment_group("@acme.com", kind=None)]]}}
        )

        bundle = parse_bundle(payload, logger)

        assert bundle.segments["segment-1"].groups[0][0].attribute == "traits"

    def test_reads_a_segment_condition_in_a_rule(self, logger: RecordingLogger) -> None:
        payload = wire_bundle(
            wire_config(target={"defaultValue": "hello", "rules": [self.rule_for_members_of("segment-1")]})
        )

        bundle = parse_bundle(payload, logger)

        rule = bundle.configs["greeting"].target.rules[0]
        assert isinstance(rule, ConditionalRule)
        assert rule.conditions == [SegmentCondition(id="condition-1", operator="in", segment_id="segment-1")]

    def test_an_unreadable_segment_is_skipped_and_logged_and_the_rest_kept(
        self, logger: RecordingLogger
    ) -> None:
        payload = wire_bundle(
            wire_config(),
            segments={
                "broken": {"groups": [[{"id": "g0c0", "kind": "attribute", "operator": "equals"}]]},
                "segment-1": {"groups": [[self.segment_group("@acme.com")]]},
            },
        )

        bundle = parse_bundle(payload, logger)

        assert list(bundle.segments) == ["segment-1"]
        assert bundle.unreadable_keys == []
        assert any("broken" in message for message in logger.messages("warning"))

    def test_a_segment_condition_inside_a_group_makes_the_segment_unreadable(
        self, logger: RecordingLogger
    ) -> None:
        nested = {"id": "g0c0", "kind": "segment", "operator": "in", "segmentId": "other"}
        payload = wire_bundle(wire_config(), segments={"segment-1": {"groups": [[nested]]}})

        bundle = parse_bundle(payload, logger)

        assert bundle.segments == {}

    def test_a_condition_of_an_unknown_kind_makes_the_config_unreadable(
        self, logger: RecordingLogger
    ) -> None:
        rule = self.rule_for_members_of("segment-1")
        rule["conditions"][0]["kind"] = "made-up"
        payload = wire_bundle(wire_config(target={"defaultValue": "hello", "rules": [rule]}))

        bundle = parse_bundle(payload, logger)

        assert bundle.configs == {}
        assert bundle.unreadable_keys == ["greeting"]
