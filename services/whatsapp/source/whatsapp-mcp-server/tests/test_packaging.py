"""Ensure installed wheels contain the modules used by the service entrypoints."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def project_metadata():
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        return tomllib.load(project_file)


def test_all_server_modules_are_listed_for_the_wheel():
    packaged = set(project_metadata()["tool"]["setuptools"]["py-modules"])
    source_modules = {path.stem for path in ROOT.glob("*.py")}
    assert packaged == source_modules


def test_dependency_floors_exclude_known_vulnerable_versions():
    requirements = [Requirement(value) for value in project_metadata()["project"]["dependencies"]]
    specs = {requirement.name.lower(): requirement.specifier for requirement in requirements}
    vulnerable = {
        "certifi": "2025.1.31",
        "cryptography": "48.0.1",
        "mcp": "1.28.1",
        "pygments": "2.19.1",
        "pyjwt": "2.13.0",
        "python-dotenv": "1.1.0",
        "urllib3": "2.7.0",
    }
    for name, old_version in vulnerable.items():
        assert name in specs, f"Missing security floor for {name}"
        assert Version(old_version) not in specs[name], f"Vulnerable {name} {old_version} is allowed"
