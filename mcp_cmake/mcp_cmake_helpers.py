import json
from packaging.version import Version

def get_minimum_cmake_version(preset_file_path):
    with open(preset_file_path, "r") as f:
        presets = json.load(f)
    min_req = presets.get("cmakeMinimumRequired", {})
    major = min_req.get("major", 0)
    minor = min_req.get("minor", 0)
    patch = min_req.get("patch", 0)
    return Version(f"{major}.{minor}.{patch}")