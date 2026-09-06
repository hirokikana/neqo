from dataclasses import dataclass, field
from typing import Any

from neqo.errors import ConfigError
from neqo.result import QueryResult
from neqo.runner import Runner


@dataclass(frozen=True)
class WorkflowStep:
    engine: str
    macro: str
    output: str
    parameters: dict[str, Any] = field(default_factory=dict)


class Workflow:
    """Sequential named queries. Data transfer is deliberately not implicit."""

    def __init__(self, runners: dict[str, Runner]):
        self.runners = runners

    def run(self, steps: list[WorkflowStep]) -> dict[str, QueryResult]:
        outputs: set[str] = set()
        for step in steps:
            if step.engine not in self.runners or step.output in outputs:
                raise ConfigError("Workflow requires known engines and unique output names")
            outputs.add(step.output)
            self.runners[step.engine].render(step.macro, **step.parameters)
        return {
            step.output: self.runners[step.engine].run(step.macro, **step.parameters)
            for step in steps
        }
