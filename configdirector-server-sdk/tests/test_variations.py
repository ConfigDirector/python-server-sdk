from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from configdirector import (
    ConfigDirectorTypeError,
    ConfigDirectorValidationError,
    ConfigEvaluatedEvent,
    ConfigEvaluation,
    Context,
    Variation,
)
from configdirector._bundle import ConfigBundle, parse_bundle
from configdirector.client import _ConfigDirectorClient
from tests.helpers import ReportingTelemetry, StubHttp, TransportRecorder, create_stubbed_logger

CONTROL_ID = "77777777-7777-4777-8777-777777777777"
TREATMENT_ID = "88888888-8888-4888-8888-888888888888"
UNNAMED_ID = "99999999-9999-4999-8999-999999999999"
EMPTY_NAME_ID = "99999999-9999-4999-8999-99999999999a"
ROLLOUT_RULE_ID = "22222222-2222-4222-8222-222222222222"
TREATMENT_SHARE_ID = "66666666-6666-4666-8666-666666666666"
SECOND_TREATMENT_SHARE_ID = "66666666-6666-4666-8666-666666666667"


def plan_is(plan: str) -> dict[str, Any]:
    return {
        "id": "44444444-4444-4444-8444-444444444444",
        "kind": "attribute",
        "attribute": "traits",
        "trait": "/plan",
        "operator": "is one of",
        "targetType": "text",
        "targetValues": [plan],
    }


def treatment_share(share_id: str, percentage: float) -> dict[str, Any]:
    return {
        "id": share_id,
        "percentage": percentage,
        "value": "Try it free",
        "valueId": "value-id-treatment",
        "variationId": TREATMENT_ID,
    }


def experiment_with_rollout(*shares: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "key": "checkout-cta-copy",
        "type": "string",
        "variations": [
            {"id": CONTROL_ID, "name": "control", "value": "Start free trial"},
            {"id": TREATMENT_ID, "name": "treatment", "value": "Try it free"},
            {"id": UNNAMED_ID, "name": None, "value": "Get started"},
            {"id": EMPTY_NAME_ID, "name": "", "value": "Begin"},
        ],
        "target": {
            "environmentId": "10000000-0000-0000-0000-000000000000",
            "defaultValue": "Start free trial",
            "defaultValueId": "value-id-control",
            "defaultVariationId": CONTROL_ID,
            "rules": [
                {
                    "id": "33333333-3333-4333-8333-333333333333",
                    "order": 0,
                    "type": "conditional",
                    "target": "value",
                    "value": "Get started",
                    "valueId": "value-id-get-started",
                    "variationId": UNNAMED_ID,
                    "conditions": [plan_is("enterprise")],
                },
                {
                    "id": "33333333-3333-4333-8333-333333333334",
                    "order": 1,
                    "type": "conditional",
                    "target": "value",
                    "value": "Begin",
                    "valueId": "value-id-begin",
                    "variationId": EMPTY_NAME_ID,
                    "conditions": [plan_is("team")],
                },
                {
                    "id": ROLLOUT_RULE_ID,
                    "order": 2,
                    "type": "conditional",
                    "target": "percentage",
                    "conditions": [plan_is("pro")],
                    "percentages": list(shares),
                },
            ],
        },
    }


FLAG = {
    "id": "00000000-0000-0000-0000-000000000002",
    "key": "new-checkout",
    "type": "boolean",
    "variations": [],
    "target": {
        "environmentId": "10000000-0000-0000-0000-000000000000",
        "defaultValue": "true",
        "defaultValueId": "value-id-true",
        "rules": [],
    },
}

EXPERIMENT = experiment_with_rollout(treatment_share(TREATMENT_SHARE_ID, 100))

EXPERIMENT_FOR_EVERY_CONTEXT = {
    "id": "00000000-0000-0000-0000-000000000003",
    "key": "pricing-page-copy",
    "type": "string",
    "variations": [
        {"id": CONTROL_ID, "name": "control", "value": "Start free trial"},
        {"id": TREATMENT_ID, "name": "treatment", "value": "Try it free"},
    ],
    "target": {
        "environmentId": "10000000-0000-0000-0000-000000000000",
        "defaultValue": "Start free trial",
        "defaultValueId": "value-id-control",
        "defaultVariationId": CONTROL_ID,
        "rules": [
            {
                "id": ROLLOUT_RULE_ID,
                "order": 0,
                "type": "percentage",
                "target": "percentage",
                "percentages": [treatment_share(TREATMENT_SHARE_ID, 100)],
            }
        ],
    },
}

PRO_USER = Context(id="user-1", traits={"plan": "pro"})
PRO_CONTEXT_WITHOUT_AN_ID = Context(traits={"plan": "pro"})
ENTERPRISE_USER = Context(id="user-1", traits={"plan": "enterprise"})
TEAM_USER = Context(id="user-1", traits={"plan": "team"})
FREE_USER = Context(id="user-1", traits={"plan": "free"})


def payload_with(*configs: dict[str, Any]) -> ConfigBundle:
    return parse_bundle(
        json.dumps(
            {
                "environmentId": "10000000-0000-0000-0000-000000000000",
                "projectId": "20000000-0000-0000-0000-000000000000",
                "kind": "full",
                "configs": {config["key"]: config for config in configs},
            }
        ),
        create_stubbed_logger(),
    )


def client_reporting_to(http: StubHttp, transports: TransportRecorder) -> _ConfigDirectorClient:
    return _ConfigDirectorClient(
        "test-server-sdk-key",
        logger=create_stubbed_logger(),
        transport_factory=transports,
        telemetry_factory=ReportingTelemetry(http),
    )


def evaluation_events_sent_on_close(client: _ConfigDirectorClient, http: StubHttp) -> list[dict[str, Any]]:
    client.close()
    return [entry["event"] for entry in http.payload["aggregatedEvents"]["evaluatedConfig"]]


@pytest.fixture
def http() -> StubHttp:
    return StubHttp()


@pytest.fixture
def client(transports: TransportRecorder, http: StubHttp) -> Iterator[_ConfigDirectorClient]:
    transports.initial_bundle = payload_with(EXPERIMENT, EXPERIMENT_FOR_EVERY_CONTEXT, FLAG)
    client = client_reporting_to(http, transports)
    client.initialize()
    yield client
    client.close()


class TestEvaluate:
    def test_returns_the_variation_of_the_share_a_percentage_rollout_served(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate("checkout-cta-copy", "in-code default", PRO_USER)

        assert evaluation == ConfigEvaluation(
            key="checkout-cta-copy",
            value="Try it free",
            is_default=False,
            reason="found-match",
            value_id="value-id-treatment",
            context=PRO_USER,
            variation=Variation(id=TREATMENT_ID, name="treatment"),
        )

    def test_returns_the_unnamed_variation_of_a_conditional_rules_value_with_its_id_and_no_name(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate("checkout-cta-copy", "in-code default", ENTERPRISE_USER)

        assert evaluation.value == "Get started"
        assert evaluation.variation == Variation(id=UNNAMED_ID, name=None)

    def test_returns_a_variation_whose_name_is_empty_with_its_id_and_no_name(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate("checkout-cta-copy", "in-code default", TEAM_USER)

        assert evaluation.value == "Begin"
        assert evaluation.variation == Variation(id=EMPTY_NAME_ID, name=None)

    def test_returns_the_variation_of_the_default_targeting_rule_value(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate("checkout-cta-copy", "in-code default", FREE_USER)

        assert evaluation.value == "Start free trial"
        assert evaluation.reason == "found-match"
        assert evaluation.is_default is False
        assert evaluation.variation == Variation(id=CONTROL_ID, name="control")

    def test_serves_a_context_without_an_id_that_reaches_a_rollout_the_default_targeting_rule_value(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate("checkout-cta-copy", "in-code default", PRO_CONTEXT_WITHOUT_AN_ID)

        assert evaluation == ConfigEvaluation(
            key="checkout-cta-copy",
            value="Start free trial",
            is_default=False,
            reason="rollout-skipped-no-identifier",
            value_id="value-id-control",
            context=PRO_CONTEXT_WITHOUT_AN_ID,
            variation=Variation(id=CONTROL_ID, name="control"),
        )

    def test_serves_a_context_without_an_id_the_rule_after_a_skipped_rollout(
        self, client: _ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        pro_plans_get_begin = {
            "id": "33333333-3333-4333-8333-333333333335",
            "order": 3,
            "type": "conditional",
            "target": "value",
            "value": "Begin",
            "valueId": "value-id-begin",
            "variationId": EMPTY_NAME_ID,
            "conditions": [plan_is("pro")],
        }
        experiment = experiment_with_rollout(treatment_share(TREATMENT_SHARE_ID, 100))
        experiment["target"]["rules"].append(pro_plans_get_begin)
        transports.last.deliver(payload_with(experiment))

        evaluation = client.evaluate("checkout-cta-copy", "in-code default", PRO_CONTEXT_WITHOUT_AN_ID)

        assert evaluation == ConfigEvaluation(
            key="checkout-cta-copy",
            value="Begin",
            is_default=False,
            reason="found-match",
            value_id="value-id-begin",
            context=PRO_CONTEXT_WITHOUT_AN_ID,
            variation=Variation(id=EMPTY_NAME_ID, name=None),
        )

    def test_serves_a_read_without_a_context_that_reaches_a_rollout_the_default_targeting_rule_value(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate("pricing-page-copy", "in-code default")

        assert evaluation == ConfigEvaluation(
            key="pricing-page-copy",
            value="Start free trial",
            is_default=False,
            reason="rollout-skipped-no-identifier",
            value_id="value-id-control",
            context=None,
            variation=Variation(id=CONTROL_ID, name="control"),
        )

    def test_serves_a_context_ignored_for_an_invalid_kind_at_a_rollout_the_default_targeting_rule_value(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate(
            "pricing-page-copy", "in-code default", Context(id="user-1", kind="Device")
        )

        assert evaluation == ConfigEvaluation(
            key="pricing-page-copy",
            value="Start free trial",
            is_default=False,
            reason="rollout-skipped-no-identifier",
            value_id="value-id-control",
            context=None,
            variation=Variation(id=CONTROL_ID, name="control"),
        )

    def test_returns_no_variation_for_a_flag_whose_config_has_no_variations(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate("new-checkout", False)

        assert evaluation.value is True
        assert evaluation.variation is None

    def test_returns_no_variation_with_the_in_code_default_value_when_the_value_cannot_be_read(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate("checkout-cta-copy", 42, PRO_USER)

        assert evaluation.value == 42
        assert evaluation.is_default is True
        assert evaluation.reason == "invalid-number"
        assert evaluation.variation is None

    def test_keeps_the_reason_of_the_in_code_default_value_for_a_context_without_an_id_at_a_rollout(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate("checkout-cta-copy", 42, PRO_CONTEXT_WITHOUT_AN_ID)

        assert evaluation.value == 42
        assert evaluation.reason == "invalid-number"
        assert evaluation.variation is None

    def test_returns_the_in_code_default_value_for_a_key_that_does_not_exist(
        self, client: _ConfigDirectorClient
    ) -> None:
        evaluation = client.evaluate("no-such-config", "in-code default")

        assert evaluation.value == "in-code default"
        assert evaluation.is_default is True
        assert evaluation.reason == "config-state-missing"
        assert evaluation.variation is None

    def test_returns_the_in_code_default_value_before_the_client_is_ready(
        self, transports: TransportRecorder, http: StubHttp
    ) -> None:
        client = client_reporting_to(http, transports)

        evaluation = client.evaluate("checkout-cta-copy", "in-code default", PRO_USER)
        client.close()

        assert evaluation.value == "in-code default"
        assert evaluation.reason == "client-not-ready"

    def test_returns_the_value_get_value_returns(self, client: _ConfigDirectorClient) -> None:
        evaluated = client.evaluate("new-checkout", False).value

        read = client.get_value("new-checkout", False)

        assert evaluated is True
        assert read is True

    def test_rejects_a_blank_config_key(self, client: _ConfigDirectorClient) -> None:
        with pytest.raises(ConfigDirectorValidationError):
            client.evaluate(" ", "in-code default")

    def test_rejects_an_in_code_default_value_of_none(self, client: _ConfigDirectorClient) -> None:
        with pytest.raises(ConfigDirectorTypeError):
            client.evaluate("checkout-cta-copy", None)  # type: ignore[arg-type]

    def test_emits_the_evaluation_it_returns_on_config_evaluated(self, client: _ConfigDirectorClient) -> None:
        events: list[ConfigEvaluatedEvent] = []
        client.on("config_evaluated", events.append)

        evaluation = client.evaluate("checkout-cta-copy", "in-code default", PRO_USER)

        assert events == [ConfigEvaluatedEvent(evaluation=evaluation)]

    def test_is_counted_as_one_evaluation_in_telemetry(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.evaluate("checkout-cta-copy", "in-code default", PRO_USER)

        client.close()

        assert [entry["count"] for entry in http.payload["aggregatedEvents"]["evaluatedConfig"]] == [1]


class TestConfigEvaluated:
    def test_carries_the_variation_of_the_value_get_value_served(self, client: _ConfigDirectorClient) -> None:
        events: list[ConfigEvaluatedEvent] = []
        client.on("config_evaluated", events.append)

        client.get_value("checkout-cta-copy", "in-code default", PRO_USER)

        assert events[0].evaluation.variation == Variation(id=TREATMENT_ID, name="treatment")

    def test_carries_the_reason_for_a_skipped_rollout(self, client: _ConfigDirectorClient) -> None:
        events: list[ConfigEvaluatedEvent] = []
        client.on("config_evaluated", events.append)

        value = client.get_value("checkout-cta-copy", "in-code default", PRO_CONTEXT_WITHOUT_AN_ID)

        assert value == "Start free trial"
        assert events[0].evaluation.reason == "rollout-skipped-no-identifier"
        assert events[0].evaluation.is_default is False

    def test_carries_the_variation_of_a_value_delivered_to_a_watcher(
        self, client: _ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        values: list[str] = []
        events: list[ConfigEvaluatedEvent] = []
        client.watch("checkout-cta-copy", "in-code default", values.append, PRO_USER)
        client.on("config_evaluated", events.append)

        transports.last.deliver(payload_with(EXPERIMENT))

        assert values == ["Try it free"]
        assert events[0].evaluation.variation == Variation(id=TREATMENT_ID, name="treatment")


class TestWatch:
    def test_a_context_without_an_id_that_reaches_a_rollout_is_given_the_default_targeting_rule_value(
        self, client: _ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        values: list[str] = []
        client.watch("checkout-cta-copy", "in-code default", values.append, PRO_CONTEXT_WITHOUT_AN_ID)

        transports.last.deliver(payload_with(EXPERIMENT))

        assert values == ["Start free trial"]


class TestEvaluationEvents:
    def test_report_the_rule_share_and_variation_of_a_value_a_percentage_rollout_served(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.get_value("checkout-cta-copy", "in-code default", PRO_USER)

        events = evaluation_events_sent_on_close(client, http)

        assert len(events) == 1
        assert events[0]["evaluationReason"] == "found-match"
        assert events[0]["ruleId"] == ROLLOUT_RULE_ID
        assert events[0]["shareId"] == TREATMENT_SHARE_ID
        assert events[0]["variationId"] == TREATMENT_ID

    def test_report_the_variation_and_no_rule_or_share_for_a_conditional_rules_value(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.get_value("checkout-cta-copy", "in-code default", ENTERPRISE_USER)

        events = evaluation_events_sent_on_close(client, http)

        assert events[0]["variationId"] == UNNAMED_ID
        assert "ruleId" not in events[0]
        assert "shareId" not in events[0]

    def test_report_a_skipped_rollout_with_its_reason_and_the_default_targeting_rule_values_variation(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.get_value("checkout-cta-copy", "in-code default", PRO_CONTEXT_WITHOUT_AN_ID)

        events = evaluation_events_sent_on_close(client, http)

        assert events[0]["evaluationReason"] == "rollout-skipped-no-identifier"
        assert events[0]["usedDefault"] is False
        assert events[0]["variationId"] == CONTROL_ID
        assert "ruleId" not in events[0]
        assert "shareId" not in events[0]

    def test_report_no_rule_share_or_variation_for_a_flag_whose_config_has_no_variations(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.get_value("new-checkout", False)

        events = evaluation_events_sent_on_close(client, http)

        assert "variationId" not in events[0]
        assert "ruleId" not in events[0]
        assert "shareId" not in events[0]

    def test_report_no_rule_share_or_variation_when_the_in_code_default_value_is_returned(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.get_value("checkout-cta-copy", 42, PRO_USER)

        events = evaluation_events_sent_on_close(client, http)

        assert events[0]["usedDefault"] is True
        assert "variationId" not in events[0]
        assert "ruleId" not in events[0]
        assert "shareId" not in events[0]

    def test_count_evaluations_of_one_value_served_by_two_shares_separately(
        self, transports: TransportRecorder, http: StubHttp
    ) -> None:
        transports.initial_bundle = payload_with(
            experiment_with_rollout(
                treatment_share(TREATMENT_SHARE_ID, 50),
                treatment_share(SECOND_TREATMENT_SHARE_ID, 50),
            )
        )
        client = client_reporting_to(http, transports)
        client.initialize()

        client.get_value(
            "checkout-cta-copy",
            "in-code default",
            Context(id="user-1", anonymous=True, traits={"plan": "pro"}),
        )
        client.get_value(
            "checkout-cta-copy",
            "in-code default",
            Context(id="user-3", anonymous=True, traits={"plan": "pro"}),
        )
        client.close()

        entries = http.payload["aggregatedEvents"]["evaluatedConfig"]
        assert [(entry["count"], entry["event"]["shareId"]) for entry in entries] == [
            (1, TREATMENT_SHARE_ID),
            (1, SECOND_TREATMENT_SHARE_ID),
        ]


class TestGetAllConfigs:
    def test_returns_the_variation_rule_and_share_of_a_value_a_percentage_rollout_served(
        self, client: _ConfigDirectorClient
    ) -> None:
        state = client.get_all_configs(PRO_USER)["checkout-cta-copy"]

        assert state.value == "Try it free"
        assert state.variation == Variation(id=TREATMENT_ID, name="treatment")
        assert state.rule_id == ROLLOUT_RULE_ID
        assert state.share_id == TREATMENT_SHARE_ID

    def test_returns_the_default_targeting_rule_values_variation_for_a_context_without_an_id(
        self, client: _ConfigDirectorClient
    ) -> None:
        state = client.get_all_configs(PRO_CONTEXT_WITHOUT_AN_ID)["checkout-cta-copy"]

        assert state.value == "Start free trial"
        assert state.variation == Variation(id=CONTROL_ID, name="control")
        assert state.rule_id is None
        assert state.share_id is None

    def test_returns_no_variation_rule_or_share_for_a_flag(self, client: _ConfigDirectorClient) -> None:
        state = client.get_all_configs()["new-checkout"]

        assert state.variation is None
        assert state.rule_id is None
        assert state.share_id is None
