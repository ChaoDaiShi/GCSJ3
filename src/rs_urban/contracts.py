from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass
class ProjectContext:
    root: Path
    data: Path
    outputs: Path
    reports: Path
    scratch: Path
    config: dict[str, Any]

@dataclass
class PreparedData:
    year: int
    sr: Path
    valid_sr: Path
    grid: Path
    boundaries: Path

@dataclass
class SampleData:
    year: int
    features: Path
    valid_features: Path
    train: Path
    holdout: Path
    split: Path

@dataclass
class ClassificationData:
    year: int
    model: Path
    raw: Path

@dataclass
class EvaluationData:
    year: int
    final: Path
    vectors: Path
    report: Path
    oa_raw: float
    oa_final: float

@dataclass
class ChangeData:
    raster: Path
    vectors: Path
    townships: Path
    district: Path
