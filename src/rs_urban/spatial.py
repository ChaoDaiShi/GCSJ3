"""Module C: exact-area transitions, LEI, landscape shape and factor overlays."""

from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.features import geometry_mask, shapes
from scipy import ndimage
from shapely.geometry import GeometryCollection, Polygon, box, shape
from shapely.geometry.polygon import orient

from rs_urban.analyze import calculate_change_statistics
from rs_urban.contracts import ProjectContext
from rs_urban.detector import detect
from rs_urban.enhance import check_grid, digest, write_json


def metric_crs(crs):
    if crs is None or not crs.is_projected or crs.linear_units_factor[1] != 1:
        raise ValueError("Analysis requires a projected CRS with metre units.")


def polygons(array, mask, transform, crs, field="value", connectivity=4):
    records = [
        {field: int(value), "geometry": shape(geom)}
        for geom, value in shapes(
            np.asarray(array, dtype=np.int32), mask=mask,
            transform=transform, connectivity=connectivity,
        )
    ]
    return gpd.GeoDataFrame(records, columns=[field, "geometry"], crs=crs)


def connected_patches(mask, transform, crs, connectivity=4):
    structure = ndimage.generate_binary_structure(2, 1 if connectivity == 4 else 2)
    labels, _ = ndimage.label(mask, structure)
    # Polygonize component labels with four-neighbour edges so diagonal joins
    # remain valid MultiPolygons rather than self-touching polygon rings.
    frame = polygons(labels, mask, transform, crs)
    if frame.empty:
        return frame
    return frame.dissolve(by="value", as_index=False)


def transition_polygons(first, second, common, transform, crs, study):
    encoded = first.astype(np.int32) * 100 + second
    frame = polygons(encoded, common, transform, crs, "transition")
    frame.geometry = frame.geometry.intersection(study)
    frame = frame[~frame.is_empty & (frame.area > 0)].copy()
    frame["from_class"] = frame.transition // 100
    frame["to_class"] = frame.transition % 100
    frame["area_km2"] = frame.area / 1e6
    frame["change_id"] = np.select(
        [
            (frame.from_class == 1) & (frame.to_class == 1),
            (frame.from_class != 1) & (frame.to_class == 1),
            (frame.from_class == 1) & (frame.to_class != 1),
        ], [1, 2, 3], default=4,
    )
    return frame


def lei_index(patch, old_built, observed, buffer_m=100.0):
    if buffer_m <= 0:
        raise ValueError("LEI buffer must be positive.")
    ring = patch.buffer(buffer_m).difference(patch).intersection(observed)
    if ring.area == 0:
        return {"lei": None, "type": "unobservable", "ring_m2": 0.0, "old_m2": 0.0}
    area = ring.intersection(old_built).area
    lei = float(np.clip(100 * area / ring.area, 0, 100))
    # GEOS area arithmetic can put a mathematically exact half above 50.
    for boundary in (0.0, 50.0, 100.0):
        if abs(lei - boundary) < 1e-9:
            lei = boundary
    return {
        "lei": lei, "type": "infilling" if lei > 50 else ("edge" if lei > 0 else "outlying"),
        "ring_m2": ring.area, "old_m2": area,
    }


def area_ellipse(geometry):
    """Area-weighted second moments, including polygon holes (not polygon vertices)."""
    if geometry.is_empty or geometry.area == 0:
        return None
    cx, cy = geometry.centroid.coords[0]
    xx = yy = xy = area = 0.0
    parts = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
    for part in parts:
        if part.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        if part.geom_type == "MultiPolygon":
            raise ValueError("Union polygon input before ellipse calculation.")
        part = orient(part, sign=1)
        for ring in [part.exterior, *part.interiors]:
            points = np.asarray(ring.coords, dtype=float) - [cx, cy]
            x, y = points[:-1, 0], points[:-1, 1]
            u, v = points[1:, 0], points[1:, 1]
            cross = x * v - u * y
            area += cross.sum() / 2
            xx += np.sum((x * x + x * u + u * u) * cross) / 12
            yy += np.sum((y * y + y * v + v * v) * cross) / 12
            xy += np.sum((2 * x * y + x * v + u * y + 2 * u * v) * cross) / 24
    covariance = np.array([[xx, xy], [xy, yy]]) / area
    eigenvalues, vectors = np.linalg.eigh(covariance)
    order = eigenvalues.argsort()[::-1]
    eigenvalues, vectors = eigenvalues[order], vectors[:, order]
    axes = np.sqrt(2 * np.maximum(eigenvalues, 0))
    angle = math.degrees(math.atan2(vectors[1, 0], vectors[0, 0])) % 180
    return {
        "x": float(cx), "y": float(cy), "area_km2": geometry.area / 1e6,
        "semi_major_m": float(axes[0]), "semi_minor_m": float(axes[1]),
        "angle_degrees_ccw_from_east": angle,
        "convention": "Uniform polygon area weights; semiaxes sqrt(2 * covariance eigenvalues).",
    }


def landscape_metrics(built, observed, resolution_m=30.0, connectivity=4):
    built = np.asarray(built, dtype=bool) & observed
    structure = ndimage.generate_binary_structure(2, 1 if connectivity == 4 else 2)
    labeled, count = ndimage.label(built, structure)
    n = int(built.sum())
    landscape_area = int(observed.sum()) * resolution_m ** 2
    if not n or not landscape_area:
        return {"patch_count": count, "pd_per_100ha": 0.0 if landscape_area else None,
                "lpi_pct": 0.0 if landscape_area else None, "ai_pct": None, "frac_am": None}
    sizes = np.bincount(labeled.ravel())[1:]
    adjacency = int((built[:, 1:] & built[:, :-1]).sum() + (built[1:, :] & built[:-1, :]).sum())
    max_adjacency = 2 * n - math.ceil(2 * math.sqrt(n))
    perimeters = np.zeros(count + 1, dtype=float)
    padded = np.pad(labeled, 1)
    for shifted in [padded[:-2, 1:-1], padded[2:, 1:-1], padded[1:-1, :-2], padded[1:-1, 2:]]:
        edges = (labeled > 0) & (labeled != shifted)
        perimeters += np.bincount(labeled[edges], minlength=count + 1) * resolution_m
    areas = sizes * resolution_m ** 2
    denom = np.log(areas)
    frac = np.divide(
        2 * np.log(0.25 * perimeters[1:]), denom,
        out=np.full(len(areas), np.nan), where=denom != 0,
    )
    return {
        "patch_count": count, "pd_per_100ha": count * 1e6 / landscape_area,
        "lpi_pct": float(areas.max() / landscape_area * 100),
        "ai_pct": 100 * adjacency / max_adjacency if max_adjacency else None,
        "frac_am": float(np.average(frac, weights=areas)) if np.isfinite(frac).all() else None,
        "built_cells": n, "observed_cells": int(observed.sum()),
        "patch_connectivity": connectivity, "adjacency": "4-neighbour single count",
        "scope": "Common observed pixel-centre grid; area-clipped transition areas are separate.",
    }


def source_maps(ctx, source):
    if source == "baseline":
        return [ctx.outputs / "rasters" / f"lulc_{year}_final_30m.tif" for year in ctx.config["years"]]
    return [ctx.outputs / "bcd" / "classification" / str(year) / source / "lulc.tif"
            for year in ctx.config["years"]]


def make_grid(study, observed, transitions, size_m, years, minimum_coverage, crs):
    if size_m <= 0 or not 0 <= minimum_coverage <= 1:
        raise ValueError("Invalid grid size or coverage.")
    xmin, ymin, xmax, ymax = study.bounds
    records = []
    start_x, start_y = math.floor(xmin / size_m) * size_m, math.floor(ymin / size_m) * size_m
    index = transitions.sindex
    for row, y in enumerate(np.arange(start_y, ymax, size_m)):
        for col, x in enumerate(np.arange(start_x, xmax, size_m)):
            geom = box(x, y, x + size_m, y + size_m).intersection(study)
            if geom.area <= 0:
                continue
            common_area = geom.intersection(observed).area
            added = lost = 0.0
            for pos in index.query(geom, predicate="intersects"):
                part = transitions.iloc[pos]
                if part.change_id == 2:
                    added += geom.intersection(part.geometry).area
                elif part.change_id == 3:
                    lost += geom.intersection(part.geometry).area
            records.append({
                "grid_id": f"{row}_{col}", "geometry": geom,
                "area_m2": geom.area, "common_m2": common_area,
                "coverage": common_area / geom.area,
                "ueii": (added - lost) / (years * geom.area) * 100,
            })
    frame = gpd.GeoDataFrame(records, crs=crs)
    return frame[(frame.coverage >= minimum_coverage) & (frame.common_m2 > 0)].copy()


def factor_arrays(ctx, settings, profile, common, transitions, target):
    """Read real drivers; compute exact vector distance and polygon exposure."""
    from rs_urban.preprocess import _compute_terrain_arrays
    arrays, states, overlays = {}, [], []
    height, width = common.shape
    rows, cols = np.nonzero(common)
    transform = profile["transform"]
    x = transform.c + (cols + 0.5) * transform.a
    y = transform.f + (rows + 0.5) * transform.e
    points = shapely.points(x, y)
    observed = transitions.geometry.union_all()
    added = transitions.loc[transitions.change_id == 2].geometry.union_all()
    old = transitions.loc[transitions.from_class == 1].geometry.union_all()
    new = transitions.loc[transitions.to_class == 1].geometry.union_all()
    dem_cfg = ctx.config["feature_stack"]
    dem = ctx.data / dem_cfg["dem_path"]
    if dem.exists():
        elevation, slope, twi, valid = _compute_terrain_arrays(
            dem, profile["transform"], profile["crs"], height, width,
            ctx.config["float_nodata"], dem_cfg["dem_smooth_window"], dem_cfg["twi_buffer_cells"],
        )
        for name, data in [("elevation", elevation), ("slope", slope), ("twi", twi)]:
            arrays[name] = np.where(
                valid & common & np.isfinite(data) & (data != ctx.config["float_nodata"]), data, np.nan
            )
        states.append({"name": "terrain", "status": "computed", "path": str(dem), "sha256": digest(dem)})
    else:
        states.append({"name": "terrain", "status": "pending", "path": str(dem)})
    for factor in settings.get("factors", []):
        name, kind, path = factor["name"], factor["kind"], ctx.data / factor["path"]
        if name in arrays:
            raise ValueError(f"Duplicate factor name: {name}")
        if not path.exists():
            states.append({"name": name, "status": "pending", "path": str(path)})
            continue
        if kind == "raster":
            with rasterio.open(path) as src:
                if (src.crs, src.transform, src.shape) != (profile["crs"], profile["transform"], common.shape):
                    raise ValueError(f"Factor grid mismatch: {path}")
                data = src.read(factor.get("band", 1), masked=True).astype(float).filled(np.nan)
            arrays[name] = np.where(common, data, np.nan)
        elif kind in ("zone", "distance"):
            frame = gpd.read_file(path, layer=factor["layer"]).to_crs(profile["crs"])
            if frame.empty or frame.geometry.isna().any() or not frame.geometry.is_valid.all():
                raise ValueError(f"Empty or invalid factor geometry: {path}")
            geom = frame.geometry.union_all()
            data = np.full(common.shape, np.nan)
            if kind == "distance":
                data[common] = shapely.distance(points, geom)
                distances = factor["breaks"]
                zones = [(f"within_{distance:g}m", geom.buffer(distance)) for distance in distances]
            else:
                data[common] = shapely.intersects(points, geom).astype(float)
                zones = [("inside", geom)]
            arrays[name] = np.where(common, data, np.nan)
            for zone, geometry in zones:
                area = geometry.intersection(observed)
                overlays.append({
                    "factor": name, "zone": zone, "observed_km2": area.area / 1e6,
                    "built_first_km2": area.intersection(old).area / 1e6,
                    "built_last_km2": area.intersection(new).area / 1e6,
                    "added_km2": area.intersection(added).area / 1e6,
                    "scope": "Exposure / spatial association; vector vintage must be checked before interpretation.",
                })
        else:
            raise ValueError(f"Unknown factor kind: {kind}")
        states.append({"name": name, "status": "computed", "path": str(path), "sha256": digest(path)})
    for name, data in arrays.items():
        output = profile | {"count": 1, "dtype": "float32", "nodata": -9999.0, "compress": "deflate"}
        with rasterio.open(target / f"factor_{name}.tif", "w", **output) as dst:
            dst.write(np.where(np.isfinite(data), data, -9999.0).astype(np.float32), 1)
    return arrays, states, overlays


def zonal_factors(grid, arrays, transform, common, minimum_coverage=0.8):
    """Grid factor means use observed pixel centres; response uses exact geometry."""
    from rasterio.features import rasterize
    if grid.empty:
        return grid.assign(**{name: pd.Series(dtype=float) for name in arrays})
    ids = rasterize(
        [(geom, i + 1) for i, geom in enumerate(grid.geometry)],
        out_shape=common.shape, transform=transform, fill=0, dtype="int32",
    )
    labels = ids[common]
    counts = np.bincount(labels, minlength=len(grid) + 1)[1:]
    for name, data in arrays.items():
        finite = common & np.isfinite(data)
        valid_counts = np.bincount(ids[finite], minlength=len(grid) + 1)[1:]
        sums = np.bincount(ids[finite], weights=data[finite], minlength=len(grid) + 1)[1:]
        coverage = np.divide(valid_counts, counts, out=np.zeros(len(grid)), where=counts > 0)
        grid[name] = np.divide(
            sums, valid_counts, out=np.full(len(grid), np.nan),
            where=(valid_counts > 0) & (coverage >= minimum_coverage),
        )
    return grid


def analyze_advanced(ctx: ProjectContext, settings: dict):
    options = settings["analysis"]
    first_year, last_year = ctx.config["years"]
    elapsed = last_year - first_year
    if elapsed <= 0:
        raise ValueError("Analysis needs two ordered dates.")
    first_path, last_path = source_maps(ctx, options["source"])
    boundary = ctx.data / "processed" / "boundaries" / "xindu_2021.gpkg"
    with rasterio.open(first_path) as a, rasterio.open(last_path) as b:
        check_grid(a, b)
        metric_crs(a.crs)
        if a.transform.b != 0 or a.transform.d != 0 or not np.isclose(abs(a.transform.a), abs(a.transform.e)):
            raise ValueError("Landscape metrics require the square, north-up A grid.")
        first, last = a.read(1), b.read(1)
        profile = a.profile.copy()
        raster_valid = (a.read_masks(1) > 0) & (b.read_masks(1) > 0)
    study_frame = gpd.read_file(boundary, layer="study_area").to_crs(profile["crs"])
    towns = gpd.read_file(boundary, layer="townships").to_crs(profile["crs"])
    study = study_frame.geometry.union_all()
    codes = [item["code"] for item in ctx.config["classes"]]
    inside = geometry_mask([study], first.shape, profile["transform"], invert=True)
    common = inside & raster_valid & np.isin(first, codes) & np.isin(last, codes)
    if not common.any():
        raise ValueError("The selected maps have no common observations.")
    transitions = transition_polygons(first, last, common, profile["transform"], profile["crs"], study)
    target = ctx.outputs / "bcd" / "analysis" / options["source"]
    target.mkdir(parents=True, exist_ok=True)
    transitions.to_file(target / "spatial.gpkg", layer="transitions", driver="GPKG")
    matrix = transitions.groupby(["from_class", "to_class"]).area_km2.sum().unstack(fill_value=0)
    matrix = matrix.reindex(index=codes, columns=codes, fill_value=0)
    matrix.to_csv(target / "transition_km2.csv", index_label="from_class")
    old = transitions.loc[transitions.from_class == 1].geometry.union_all()
    new = transitions.loc[transitions.to_class == 1].geometry.union_all()
    observed = transitions.geometry.union_all()
    added_mask = common & (first != 1) & (last == 1)
    patches = connected_patches(added_mask, profile["transform"], profile["crs"],
                                connectivity=options["connectivity"])
    patches.geometry = patches.geometry.intersection(study)
    patches = patches[(~patches.is_empty) & (patches.area > 0)].copy()
    rows = [lei_index(patch, old, observed, options["lei_buffer_m"]) for patch in patches.geometry]
    for column in ["lei", "type", "ring_m2", "old_m2"]:
        patches[column] = [row[column] for row in rows]
    patches["patch_id"] = np.arange(1, len(patches) + 1)
    patches["area_km2"] = patches.area / 1e6
    if len(patches):
        patches.to_file(target / "spatial.gpkg", layer="lei_patches", driver="GPKG")
    patches.drop(columns=["geometry", "value"]).to_csv(target / "lei.csv", index=False)
    change = transitions[["change_id", "geometry"]].copy()
    change["change_name"] = change.change_id.map({1: "persistent", 2: "added", 3: "lost", 4: "nonbuilt"})
    township, district, balance = calculate_change_statistics(
        change, study_frame, towns, elapsed, ctx.config["boundary_reference_year"]
    )
    if not balance["area_balance_check"]["is_balanced"]:
        raise ValueError("Township areas do not balance with the district.")
    for table in [township, district]:
        base = pd.to_numeric(table.built_1992_km2, errors="coerce")
        net = pd.to_numeric(table.net_km2, errors="coerce")
        table["dynamic_degree_pct"] = np.where(base > 0, net / base / elapsed * 100, np.nan)
    township.to_csv(target / "township.csv", index=False)
    district.to_csv(target / "district.csv", index=False)
    moments = {str(first_year): area_ellipse(old), str(last_year): area_ellipse(new)}
    migration = None
    if all(moments.values()):
        dx, dy = moments[str(last_year)]["x"] - moments[str(first_year)]["x"], moments[str(last_year)]["y"] - moments[str(first_year)]["y"]
        migration = {"dx_m": dx, "dy_m": dy, "distance_m": math.hypot(dx, dy),
                     "bearing_degrees_clockwise_from_north": math.degrees(math.atan2(dx, dy)) % 360}
    landscapes = {
        str(year): landscape_metrics(
            data == 1, common, abs(profile["transform"].a), options["connectivity"]
        ) for year, data in [(first_year, first), (last_year, last)]
    }
    arrays, factor_states, overlays = factor_arrays(ctx, settings, profile, common, transitions, target)
    if overlays:
        pd.DataFrame(overlays).to_csv(target / "factor_exposure.csv", index=False)
    gradient_rows = []
    for name, data in arrays.items():
        valid = common & np.isfinite(data)
        if not valid.any():
            continue
        # Explicit breakpoints for distance factors, fixed quantiles for terrain.
        factor_cfg = next((item for item in settings.get("factors", []) if item["name"] == name), {})
        boundaries = factor_cfg.get("breaks", np.unique(np.quantile(data[valid], [0.2, 0.4, 0.6, 0.8])).tolist())
        bins = np.searchsorted(boundaries, data, side="right")
        for index in np.unique(bins[valid]):
            mask = valid & (bins == index)
            # Raster-cell gradient area is explicitly distinct from vector exposure.
            pixel_area = abs(profile["transform"].a * profile["transform"].e)
            gradient_rows.append({
                "factor": name, "bin": int(index), "lower": boundaries[index - 1] if index else None,
                "upper": boundaries[index] if index < len(boundaries) else None,
                "observed_km2": mask.sum() * pixel_area / 1e6,
                "added_km2": (mask & added_mask).sum() * pixel_area / 1e6,
                "built_first_km2": (mask & (first == 1)).sum() * pixel_area / 1e6,
                "built_last_km2": (mask & (last == 1)).sum() * pixel_area / 1e6,
            })
    if gradient_rows:
        pd.DataFrame(gradient_rows).to_csv(target / "gradients.csv", index=False)
    grid = make_grid(study, observed, transitions, options["grid_size_m"], elapsed,
                     options["minimum_grid_coverage"], profile["crs"])
    grid = zonal_factors(grid, arrays, profile["transform"], common, options["minimum_grid_coverage"])
    if len(grid):
        grid.to_file(target / "spatial.gpkg", layer="driver_grid", driver="GPKG")
        grid.drop(columns="geometry").to_csv(target / "driver_grid.csv", index=False)
    detector = detect(
        grid, list(arrays), bins=options["factor_bins"], permutations=options["permutations"],
        seed=ctx.config["random_seed"],
    )
    write_json(target / "geodetector.json", detector)
    summary = {
        "status": "computed", "source": options["source"], "years": [first_year, last_year],
        "inputs": [{"path": str(path), "sha256": digest(path)} for path in [first_path, last_path, boundary]],
        "common_area_km2": observed.area / 1e6, "transition_sum_km2": float(matrix.to_numpy().sum()),
        "ellipses": moments, "migration": migration, "landscape": landscapes,
        "lei_buffer_m": options["lei_buffer_m"], "new_patch_count": len(patches),
        "lei_area_km2": patches.groupby("type").area_km2.sum().to_dict(),
        "area_balance": balance["area_balance_check"], "factors": factor_states,
        "limitations": [
            "Two dates support interval-average change, not policy breakpoint or causal inference.",
            "1992 cropland versus forest/grass confusion affects four-class transitions.",
            "Road/metro/planning input dates must be verified; later networks are retrospective association.",
            "LEI uses the observable external buffer ring; nodata is excluded, not treated as vacant.",
            "Raster landscape and factor gradients use pixel-centre areas; transitions and vector exposure are clipped exactly.",
            "Ellipses describe built-up polygon area, not settlement population.",
        ],
    }
    write_json(target / "summary.json", summary)
    return summary
