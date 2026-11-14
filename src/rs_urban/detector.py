"""GeoDetector on common complete-case grids, with fixed factor discretization."""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


def discretize(values, bins=5):
    """Quantile classes; duplicate boundaries collapse, constant factors stay one class."""
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Discretization requires complete observations.")
    edges = np.unique(np.quantile(values, np.linspace(0, 1, bins + 1)))
    if len(edges) <= 1:
        return np.zeros(len(values), dtype=int), edges.tolist()
    return np.searchsorted(edges[1:-1], values, side="right"), edges.tolist()


def q_statistic(y, strata):
    y, strata = np.asarray(y, dtype=float), np.asarray(strata)
    if len(y) < 2 or len(y) != len(strata) or not np.isfinite(y).all():
        raise ValueError("q requires >=2 finite observations and matching strata.")
    total = float(np.sum((y - y.mean()) ** 2))
    if total == 0:
        return None
    within = 0.0
    for label in np.unique(strata):
        subset = y[strata == label]
        within += float(np.sum((subset - subset.mean()) ** 2))
    return float(np.clip(1 - within / total, 0, 1))


def interaction_type(q1, q2, joint, tolerance=1e-10):
    low, high, total = min(q1, q2), max(q1, q2), q1 + q2
    if joint < low - tolerance:
        return "nonlinear_weaken"
    if joint < high - tolerance:
        return "univariate_weaken"
    if abs(joint - total) <= tolerance:
        return "independent"
    if joint > total + tolerance:
        return "nonlinear_enhance"
    if joint > high + tolerance:
        return "bivariate_enhance"
    return "no_enhancement"


def detect(table: pd.DataFrame, factors: list[str], bins=5, permutations=199, seed=42):
    if not factors:
        return {"status": "pending", "reason": "No real factor inputs available."}
    clean = table.dropna(subset=["ueii", *factors]).copy()
    clean = clean[np.isfinite(clean[["ueii", *factors]].to_numpy(dtype=float)).all(axis=1)]
    if len(clean) < 2:
        return {"status": "undefined", "reason": "Fewer than two complete grids.", "n": len(clean)}
    y = clean.ueii.to_numpy(dtype=float)
    if np.ptp(y) == 0:
        return {"status": "undefined", "reason": "Expansion response has zero variance.", "n": len(y)}
    strata, factor_results = {}, []
    rng = np.random.default_rng(seed)
    # Use the same permutations for all factors on the same complete-case set.
    shuffled = [rng.permutation(y) for _ in range(permutations)]
    for name in factors:
        labels, edges = discretize(clean[name], bins)
        strata[name] = labels
        q = q_statistic(y, labels)
        null = [q_statistic(values, labels) for values in shuffled]
        p = float((1 + sum(value >= q - 1e-12 for value in null)) / (permutations + 1)) if permutations else None
        counts = np.bincount(labels)
        factor_results.append({
            "factor": name, "q": q, "p_permutation": p,
            "edges": edges, "strata_n": len(np.unique(labels)),
            "minimum_stratum_n": int(counts[counts > 0].min()),
            "singleton_strata": int((counts == 1).sum()),
        })
    by_name = {row["factor"]: row["q"] for row in factor_results}
    interactions = []
    for a, b in combinations(factors, 2):
        _, labels = np.unique(np.column_stack((strata[a], strata[b])), axis=0, return_inverse=True)
        q = q_statistic(y, labels)
        counts = np.bincount(labels)
        interactions.append({
            "first": a, "second": b, "q": q,
            "type": interaction_type(by_name[a], by_name[b], q),
            "strata_n": len(counts), "singleton_strata": int((counts == 1).sum()),
        })
    return {
        "status": "computed", "n": len(clean), "dropped_grids": len(table) - len(clean),
        "grid_ids": clean.grid_id.astype(str).tolist(),
        "factors": sorted(factor_results, key=lambda row: -row["q"]),
        "interactions": interactions, "permutations": permutations, "seed": seed,
        "interpretation": (
            "Spatial association only. Unrestricted permutation p values assume exchangeability "
            "and do not correct spatial autocorrelation. Sparse joint strata can inflate q. "
            "No factor ranking or discretization was selected using these results."
        ),
    }
