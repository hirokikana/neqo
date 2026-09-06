from dataclasses import dataclass


@dataclass(frozen=True)
class TableInfo:
    name: str
    schema: str = ""
    catalog: str = ""
    kind: str = "table"


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str = ""
    nullable: bool = True


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    signature: str = ""
    kind: str = "function"
