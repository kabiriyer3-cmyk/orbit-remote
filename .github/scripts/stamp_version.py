"""Write the release version into the host package and the Windows file metadata."""

import re
import sys
from pathlib import Path

version = sys.argv[1].lstrip("v")
nums = [int(x) for x in re.findall(r"\d+", version.split("-")[0])[:3]] + [0, 0, 0]
host = Path(__file__).resolve().parents[2] / "host"

init = host / "orbit_host" / "__init__.py"
init.write_text(re.sub(r'__version__ = "[^"]*"', f'__version__ = "{version}"', init.read_text("utf-8")), "utf-8")

info = host / "version_info.txt"
text = info.read_text("utf-8")
tup = f"({nums[0]}, {nums[1]}, {nums[2]}, 0)"
text = re.sub(r"filevers=\([^)]*\)", f"filevers={tup}", text)
text = re.sub(r"prodvers=\([^)]*\)", f"prodvers={tup}", text)
text = re.sub(r"StringStruct\('(FileVersion|ProductVersion)', '[^']*'\)", lambda m: f"StringStruct('{m.group(1)}', '{version}')", text)
info.write_text(text, "utf-8")
print(f"Stamped version {version}")
