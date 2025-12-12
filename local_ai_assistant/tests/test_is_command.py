"""Debug test for is_command() function."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import commands_toolkit


test_cases = [
    "scan apps",
    "Scan apps",
    "Scan apps.",
    "SCAN APPS",
    "scan files",
    "index files",
    "list apps",
]

print("Testing is_command() recognition:")
print("=" * 60)

for test in test_cases:
    result = commands_toolkit.is_command(test)
    status = "✅ RECOGNIZED" if result else "❌ NOT RECOGNIZED"
    print(f"{status}: '{test}'")

print("\n" + "=" * 60)
