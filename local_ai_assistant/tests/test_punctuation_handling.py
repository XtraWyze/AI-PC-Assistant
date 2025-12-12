"""Test command handling with punctuation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import commands_toolkit


def test_logger(msg: str) -> None:
    print(f"[LOG] {msg}")


test_cases = [
    ("scan apps", "Should scan applications"),
    ("Scan apps.", "Should scan applications (with period)"),
    ("scan files", "Should scan files"),
    ("list apps!", "Should list apps (with exclamation)"),
]

print("Testing command handling with punctuation:")
print("=" * 60)

for cmd, description in test_cases:
    print(f"\n{description}")
    print(f"Command: '{cmd}'")
    is_cmd = commands_toolkit.is_command(cmd)
    print(f"Recognized as command: {is_cmd}")
    
    if is_cmd:
        # Don't actually run full scan, just check the first few words of response
        try:
            response = commands_toolkit.handle_command(cmd, logger=test_logger)
            # Just show first 80 chars to avoid long output
            print(f"Response: {response[:80]}...")
        except Exception as e:
            print(f"Error: {e}")
    print("-" * 60)
