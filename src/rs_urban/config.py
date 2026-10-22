"""Configuration loading and ProjectContext construction for rs-urban.

Entry point conventions and common parameters:
All five processing scripts share two standard arguments:
  --config <path>    Path to project.toml (defaults to configs/project.toml relative to repo root)
  --env-file <path>  Path to .env (defaults to .env relative to repo root)

Specific script arguments:
  01_preprocess.py: --config, --env-file, --step (boundaries|surface|pansharpen), --year (1992|2021)
  02_samples.py:    --config, --env-file, --year (1992|2021)
  03_classify.py:   --config, --env-file, --year (1992|2021)
  04_evaluate.py:   --config, --env-file, --year (1992|2021)
  05_analyze.py:    --config, --env-file
"""

import argparse
import os
from pathlib import Path
from typing import Any
import tomllib
from dotenv import dotenv_values

from rs_urban.contracts import ProjectContext

# Default values specified in .env.example
DEFAULT_ENV_VARS = {
    "RS_DATA_ROOT": "./data",
    "RS_OUTPUT_ROOT": "./outputs",
    "RS_REPORT_ROOT": "./reports",
    "RS_SCRATCH_ROOT": "./.cache/processing",
    "GDAL_CACHEMAX": "512",
}


def get_repo_root() -> Path:
    """Return the absolute path to the repository root."""
    return Path(__file__).resolve().parents[2]


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add standard --config and --env-file arguments to an ArgumentParser."""
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/project.toml"),
        help="Path to project.toml (relative to repository root or absolute)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to .env file (relative to repository root or absolute)",
    )


def load_context(
    config_path: Path,
    env_file: Path,
    root_dir: Path | None = None,
) -> ProjectContext:
    """Load configuration TOML and environment variables into a ProjectContext.

    Priority resolution for environment variables:
      1. Process environment (os.environ), if already set.
      2. Key-value pair in env_file (.env).
      3. Default value declared in .env.example.

    Relative paths in env vars and config are resolved relative to the repository root,
    ensuring identical resolution regardless of the current working directory.
    """
    root = (Path(root_dir).resolve() if root_dir is not None else get_repo_root())

    # Resolve config_path and env_file relative to root if relative
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = (root / config_path).resolve()
    else:
        config_path = config_path.resolve()

    env_file = Path(env_file)
    if not env_file.is_absolute():
        env_file = (root / env_file).resolve()
    else:
        env_file = env_file.resolve()

    # Read .env file values if present
    file_vars: dict[str, str] = {}
    if env_file.exists():
        parsed = dotenv_values(env_file)
        file_vars = {k: v for k, v in parsed.items() if v is not None}

    # Resolve final string value for each configured key
    resolved_env: dict[str, str] = {}
    for key, default_val in DEFAULT_ENV_VARS.items():
        if key in os.environ and os.environ[key] != "":
            resolved_env[key] = os.environ[key]
        elif key in file_vars and file_vars[key] != "":
            resolved_env[key] = file_vars[key]
        else:
            resolved_env[key] = default_val

    def resolve_path(val: str) -> Path:
        p = Path(val)
        return (root / p).resolve() if not p.is_absolute() else p.resolve()

    data_path = resolve_path(resolved_env["RS_DATA_ROOT"])
    outputs_path = resolve_path(resolved_env["RS_OUTPUT_ROOT"])
    reports_path = resolve_path(resolved_env["RS_REPORT_ROOT"])
    scratch_path = resolve_path(resolved_env["RS_SCRATCH_ROOT"])
    gdal_cachemax = resolved_env["GDAL_CACHEMAX"]

    # Export resolved values to process environment for GDAL and child tools
    os.environ["RS_DATA_ROOT"] = str(data_path)
    os.environ["RS_OUTPUT_ROOT"] = str(outputs_path)
    os.environ["RS_REPORT_ROOT"] = str(reports_path)
    os.environ["RS_SCRATCH_ROOT"] = str(scratch_path)
    os.environ["GDAL_CACHEMAX"] = str(gdal_cachemax)
    os.environ["CPL_TMPDIR"] = str(scratch_path)

    scratch_path.mkdir(parents=True, exist_ok=True)

    # Load scientific configuration from TOML
    with open(config_path, "rb") as f:
        config_data: dict[str, Any] = tomllib.load(f)

    return ProjectContext(
        root=root,
        data=data_path,
        outputs=outputs_path,
        reports=reports_path,
        scratch=scratch_path,
        config=config_data,
    )
