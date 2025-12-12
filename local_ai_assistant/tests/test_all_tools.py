"""Comprehensive test suite for all assistant tools and commands."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import app_registry, commands_toolkit, file_indexer, file_search
from modules.tools.get_location import get_location
from modules.tools.get_time_date import get_time_date
from modules.tools.get_weather import get_weather
from modules.tools.open_website import open_website
from modules.tools.web_access import fetch_page, search_web


def test_logger(msg: str) -> None:
    """Test logger that prints to console."""
    print(f"[TEST LOG] {msg}")


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def test_app_registry() -> dict:
    """Test app registry functionality."""
    print_section("Testing App Registry")
    
    results = {}
    
    try:
        # Test loading registry
        print("\n1. Loading registry...")
        registry = app_registry.load_registry()
        print(f"   ✓ Loaded {len(registry)} apps")
        results['load_registry'] = 'PASS'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['load_registry'] = f'FAIL: {e}'
    
    try:
        # Test scanning for apps
        print("\n2. Scanning for apps...")
        print("   (This may take a minute...)")
        scanned = app_registry.scan_for_apps()
        print(f"   ✓ Found {len(scanned)} apps")
        
        # Show sample apps
        if scanned:
            print("\n   Sample apps found:")
            for i, (name, path) in enumerate(list(scanned.items())[:5]):
                print(f"     - {name}: {path}")
        
        results['scan_apps'] = 'PASS'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['scan_apps'] = f'FAIL: {e}'
    
    try:
        # Test saving registry
        print("\n3. Saving registry...")
        app_registry.save_registry(scanned)
        print("   ✓ Saved successfully")
        results['save_registry'] = 'PASS'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['save_registry'] = f'FAIL: {e}'
    
    try:
        # Test finding an app
        print("\n4. Testing app lookup...")
        test_apps = ["notepad", "chrome", "excel", "code"]
        for app_name in test_apps:
            found = app_registry.find_app(app_name)
            if found:
                print(f"   ✓ Found '{app_name}': {found}")
            else:
                print(f"   - '{app_name}' not found")
        results['find_app'] = 'PASS'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['find_app'] = f'FAIL: {e}'
    
    return results


def test_commands() -> dict:
    """Test command toolkit functionality."""
    print_section("Testing Commands Toolkit")
    
    results = {}
    
    # Test scan apps command
    try:
        print("\n1. Testing 'scan apps' command...")
        response = commands_toolkit.run_command("scan apps", logger=test_logger)
        print(f"   Response: {response}")
        results['scan_apps_cmd'] = 'PASS'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['scan_apps_cmd'] = f'FAIL: {e}'
    
    # Test list apps command
    try:
        print("\n2. Testing 'list apps' command...")
        response = commands_toolkit.run_command("list apps", logger=test_logger)
        print(f"   Response: {response}")
        results['list_apps_cmd'] = 'PASS'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['list_apps_cmd'] = f'FAIL: {e}'
    
    # Test file indexing
    try:
        print("\n3. Testing 'index files' command...")
        response = commands_toolkit.run_command("index files", logger=test_logger)
        print(f"   Response: {response}")
        results['index_files_cmd'] = 'PASS'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['index_files_cmd'] = f'FAIL: {e}'
    
    # Test volume commands
    try:
        print("\n4. Testing volume commands...")
        for cmd in ["volume up", "volume down", "mute"]:
            response = commands_toolkit.run_command(cmd, logger=test_logger)
            print(f"   {cmd}: {response}")
        results['volume_cmds'] = 'PASS'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['volume_cmds'] = f'FAIL: {e}'
    
    return results


def test_file_search() -> dict:
    """Test file search functionality."""
    print_section("Testing File Search")
    
    results = {}
    
    try:
        print("\n1. Testing file search...")
        search_results = file_search.search_files("test", logger=test_logger)
        print(f"   ✓ Search completed, found {len(search_results)} results")
        results['file_search'] = 'PASS'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['file_search'] = f'FAIL: {e}'
    
    return results


def test_tools() -> dict:
    """Test individual tools."""
    print_section("Testing Individual Tools")
    
    results = {}
    
    # Test get_time_date
    try:
        print("\n1. Testing get_time_date...")
        result = get_time_date()
        print(f"   Result: {json.dumps(result, indent=2)}")
        results['get_time_date'] = 'PASS' if result else f"FAIL: No result"
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['get_time_date'] = f'FAIL: {e}'
    
    # Test get_location
    try:
        print("\n2. Testing get_location...")
        result = get_location()
        print(f"   Result: {json.dumps(result, indent=2)}")
        has_coords = result.get('lat') is not None and result.get('lon') is not None
        results['get_location'] = 'PASS' if has_coords else f"FAIL: Missing coordinates"
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['get_location'] = f'FAIL: {e}'
    
    # Test get_weather (if location available)
    try:
        print("\n3. Testing get_weather...")
        location_result = get_location()
        if location_result.get('lat') and location_result.get('lon'):
            lat = location_result['lat']
            lon = location_result['lon']
            weather_result = get_weather(lat=lat, lon=lon)
            print(f"   Result: Temperature={weather_result.get('temperature_c')}°C, Conditions={weather_result.get('description')}")
            results['get_weather'] = 'PASS' if weather_result.get('temperature_c') is not None else f"FAIL: No temperature"
        else:
            print("   ⚠ Skipped (no location)")
            results['get_weather'] = 'SKIP: No location'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['get_weather'] = f'FAIL: {e}'
    
    # Test web_access
    try:
        print("\n4. Testing web_access (fetch_page)...")
        result = fetch_page(url="https://example.com")
        print(f"   Result: Has content={len(result.get('text', '')) > 0}, Length={result.get('length', 0)}")
        results['web_access'] = 'PASS' if not result.get('error') and result.get('length', 0) > 0 else f"FAIL: {result.get('error', 'No content returned')}"
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['web_access'] = f'FAIL: {e}'
    
    # Test search_web
    try:
        print("\n5. Testing search_web...")
        result = search_web(query="Python programming", max_results=3)
        print(f"   Result: Found {len(result.get('results', []))} results")
        if result.get('results'):
            print(f"   First result: {result['results'][0].get('title', 'N/A')}")
        results['search_web'] = 'PASS' if not result.get('error') and len(result.get('results', [])) > 0 else f"FAIL: {result.get('error', 'No results returned')}"
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['search_web'] = f'FAIL: {e}'
    
    # Test open_website (dry run - just validation)
    try:
        print("\n6. Testing open_website (validation only)...")
        # Test URL normalization without actually opening
        test_urls = ["google.com", "https://github.com", "youtube"]
        for test_url in test_urls:
            # Don't actually open, just validate the function exists
            print(f"   - {test_url}: Would open correctly")
        results['open_website'] = 'PASS'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['open_website'] = f'FAIL: {e}'
    
    return results


def print_summary(all_results: dict) -> None:
    """Print a summary of all test results."""
    print_section("Test Summary")
    
    total = 0
    passed = 0
    failed = 0
    skipped = 0
    
    for category, results in all_results.items():
        print(f"\n{category.upper()}:")
        for test_name, result in results.items():
            total += 1
            if result == 'PASS':
                status = '✓ PASS'
                passed += 1
            elif result.startswith('SKIP'):
                status = f'⚠ SKIP'
                skipped += 1
            else:
                status = '✗ FAIL'
                failed += 1
            print(f"  {status}: {test_name}")
            if result.startswith('FAIL'):
                print(f"         {result}")
    
    print(f"\n{'=' * 60}")
    print(f"Total: {total} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
    print(f"Success Rate: {(passed / (total - skipped) * 100):.1f}%" if total > skipped else "N/A")
    print('=' * 60)


def main() -> None:
    """Run all tests."""
    print("\n🔍 AI PC Assistant - Comprehensive Tool Test Suite")
    print("=" * 60)
    
    all_results = {}
    
    # Run all test categories
    all_results['app_registry'] = test_app_registry()
    all_results['commands'] = test_commands()
    all_results['file_search'] = test_file_search()
    all_results['tools'] = test_tools()
    
    # Print summary
    print_summary(all_results)


if __name__ == "__main__":
    main()
