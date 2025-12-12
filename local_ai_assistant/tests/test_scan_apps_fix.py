"""Quick test to verify 'scan apps' command routing fix."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import commands_toolkit


def test_logger(msg: str) -> None:
    print(f"[LOG] {msg}")


print("Testing 'scan apps' command routing...")
print("=" * 60)

# Test that "scan apps" triggers app scanner, not file indexer
response = commands_toolkit.run_command("scan apps", logger=test_logger)
print(f"\nResponse: {response}")

# Check if response mentions "applications" (good) or "files" (bad)
if "application" in response.lower() or "app" in response.lower():
    print("\n✅ SUCCESS: 'scan apps' correctly triggered the app scanner!")
elif "file" in response.lower():
    print("\n❌ FAIL: 'scan apps' incorrectly triggered the file indexer!")
else:
    print(f"\n⚠️ UNKNOWN: Unexpected response")

print("\n" + "=" * 60)
print("\nTesting 'scan files' command routing...")
print("=" * 60)

# Test that "scan files" still triggers file indexer
response = commands_toolkit.run_command("scan files", logger=test_logger)
print(f"\nResponse: {response}")

if "file" in response.lower():
    print("\n✅ SUCCESS: 'scan files' correctly triggered the file indexer!")
elif "application" in response.lower() or "app" in response.lower():
    print("\n❌ FAIL: 'scan files' incorrectly triggered the app scanner!")
else:
    print(f"\n⚠️ UNKNOWN: Unexpected response")
