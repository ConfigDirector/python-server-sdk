from __future__ import annotations

from .condition_evaluator import evaluate_condition
from .types import EvaluationContext, Segment, SegmentCondition, Segments

__all__ = ["evaluate_segment_condition"]


def evaluate_segment_condition(
    condition: SegmentCondition, segments: Segments | None, context: EvaluationContext | None
) -> bool:
    segment = (segments or {}).get(condition.segment_id)
    if segment is None:
        return False
    member = _in_segment(segment, context)
    match condition.operator.lower():
        case "in":
            return member
        case "not in":
            return not member
        case _:
            return False


def _in_segment(segment: Segment, context: EvaluationContext | None) -> bool:
    return any(all(evaluate_condition(condition, context) for condition in group) for group in segment.groups)
