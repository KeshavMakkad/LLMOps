"""Statistics: bootstrap confidence intervals over requests.

All bootstraps resample *items*, not individual judgments: judgments of the same item are
correlated (same question difficulty), so resampling judgments would give falsely tight CIs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass
class Estimate:
    value: float | None
    lo: float | None
    hi: float | None
    n: int

    def dict(self) -> dict:
        return asdict(self)


def _nan_estimate(n: int = 0) -> Estimate:
    return Estimate(None, None, None, n)


def bootstrap_mean(values: list[float] | np.ndarray, n_boot: int = 2000, alpha: float = 0.05,
                   seed: int = 13) -> Estimate:
    """Percentile bootstrap CI for the mean of per-item values."""
    x = np.asarray([v for v in values if v is not None and not np.isnan(v)], dtype=float)
    if len(x) == 0:
        return _nan_estimate()
    if len(x) == 1:
        return Estimate(float(x[0]), float(x[0]), float(x[0]), 1)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    means = x[idx].mean(axis=1)
    return Estimate(float(x.mean()), float(np.quantile(means, alpha / 2)),
                    float(np.quantile(means, 1 - alpha / 2)), len(x))
