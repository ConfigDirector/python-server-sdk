from __future__ import annotations

from ..types import ConfigType, ConfigValue, Context, EvaluationReason
from .queue import InvalidContextRecording
from .tracked_events import TrackedEventAdmission

__all__ = ["DiscardingTelemetry"]


class DiscardingTelemetry:
    def record_evaluation(
        self,
        *,
        key: str,
        default: ConfigValue,
        value: ConfigValue,
        used_default: bool,
        reason: EvaluationReason,
        context: Context | None = None,
        config_type: ConfigType | None = None,
        value_id: str | None = None,
        variation_id: str | None = None,
        rule_id: str | None = None,
        share_id: str | None = None,
    ) -> None:
        return None

    def record_invalid_context(self, kind_sample: str) -> InvalidContextRecording:
        return "new-kind-sample"

    def record_tracked_event(self, admission: TrackedEventAdmission) -> None:
        return None

    def close(self) -> None:
        return None
