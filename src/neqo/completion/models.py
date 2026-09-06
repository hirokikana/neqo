from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    value: str
    kind: str
    signature: str = ""
    start_position: int = 0
