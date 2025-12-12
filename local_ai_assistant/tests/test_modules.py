"""Comprehensive test suite for core assistant modules."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import modules to test
from modules import (
    conversation_manager,
    memory_manager,
    window_control,
)


def test_logger(msg: str) -> None:
    """Test logger that prints to console."""
    print(f"[TEST LOG] {msg}")


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def test_conversation_manager() -> dict:
    """Test conversation manager functionality."""
    print_section("Testing Conversation Manager")
    
    results = {}
    
    try:
        # Test 1: Clear context
        print("\n1. Testing clear_context...")
        conversation_manager.clear_context()
        context = conversation_manager.get_recent_context()
        if len(context) == 0:
            print("   ✓ Context cleared successfully")
            results['clear_context'] = 'PASS'
        else:
            print(f"   ✗ Context not empty after clear: {len(context)} items")
            results['clear_context'] = f'FAIL: Context has {len(context)} items'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['clear_context'] = f'FAIL: {e}'
    
    try:
        # Test 2: Add turns
        print("\n2. Testing add_turn...")
        conversation_manager.clear_context()
        conversation_manager.add_turn("user", "Hello assistant")
        conversation_manager.add_turn("assistant", "Hello! How can I help?")
        context = conversation_manager.get_recent_context()
        if len(context) == 2:
            print(f"   ✓ Added 2 turns successfully")
            print(f"      User: {context[0]['text']}")
            print(f"      Assistant: {context[1]['text']}")
            results['add_turn'] = 'PASS'
        else:
            print(f"   ✗ Expected 2 turns, got {len(context)}")
            results['add_turn'] = f'FAIL: Expected 2, got {len(context)}'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['add_turn'] = f'FAIL: {e}'
    
    try:
        # Test 3: Get recent context with limit
        print("\n3. Testing get_recent_context with limit...")
        conversation_manager.clear_context()
        for i in range(10):
            conversation_manager.add_turn("user", f"Message {i}")
            conversation_manager.add_turn("assistant", f"Response {i}")
        
        context = conversation_manager.get_recent_context(max_turns=4)
        if len(context) == 4:
            print(f"   ✓ Retrieved last 4 turns correctly")
            results['get_recent_context'] = 'PASS'
        else:
            print(f"   ✗ Expected 4 turns, got {len(context)}")
            results['get_recent_context'] = f'FAIL: Expected 4, got {len(context)}'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['get_recent_context'] = f'FAIL: {e}'
    
    try:
        # Test 4: Build prompt with context
        print("\n4. Testing build_prompt_with_context...")
        conversation_manager.clear_context()
        conversation_manager.add_turn("user", "What is Python?")
        conversation_manager.add_turn("assistant", "Python is a programming language.")
        
        prompt = conversation_manager.build_prompt_with_context(
            user_input="Tell me more",
            system_preamble="You are a helpful assistant.",
        )
        
        if "Python" in prompt and "Tell me more" in prompt:
            print("   ✓ Prompt built with context")
            results['build_prompt'] = 'PASS'
        else:
            print("   ✗ Prompt missing context or user input")
            results['build_prompt'] = 'FAIL: Missing context'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['build_prompt'] = f'FAIL: {e}'
    
    # Clean up
    conversation_manager.clear_context()
    
    return results


def test_memory_manager() -> dict:
    """Test memory manager functionality."""
    print_section("Testing Memory Manager")
    
    results = {}
    
    # Use a temporary file for testing
    original_path = memory_manager.DATA_PATH
    temp_file = Path(tempfile.gettempdir()) / "test_memory.json"
    memory_manager.DATA_PATH = temp_file
    
    try:
        # Test 1: Load memory
        print("\n1. Testing load_memory...")
        if temp_file.exists():
            temp_file.unlink()
        
        memory = memory_manager.load_memory()
        if "facts" in memory and "history" in memory and "conversation" in memory:
            print("   ✓ Memory loaded with correct structure")
            results['load_memory'] = 'PASS'
        else:
            print("   ✗ Memory structure incorrect")
            results['load_memory'] = 'FAIL: Missing keys'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['load_memory'] = f'FAIL: {e}'
    
    try:
        # Test 2: Set fact
        print("\n2. Testing set_fact...")
        memory_manager.set_fact("user_name", "Alice")
        memory = memory_manager.load_memory()
        
        if memory.get("facts", {}).get("user_name") == "Alice":
            print("   ✓ Fact saved successfully: user_name=Alice")
            results['set_fact'] = 'PASS'
        else:
            print("   ✗ Fact not saved correctly")
            results['set_fact'] = 'FAIL: Fact not found'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['set_fact'] = f'FAIL: {e}'
    
    try:
        # Test 3: Get fact
        print("\n3. Testing get_fact...")
        memory_manager.set_fact("favorite_color", "blue")
        color = memory_manager.get_fact("favorite_color")
        
        if color == "blue":
            print("   ✓ Fact retrieved successfully: favorite_color=blue")
            results['get_fact'] = 'PASS'
        else:
            print(f"   ✗ Expected 'blue', got '{color}'")
            results['get_fact'] = f'FAIL: Expected blue, got {color}'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['get_fact'] = f'FAIL: {e}'
    
    try:
        # Test 4: Clear facts
        print("\n4. Testing clear_memory...")
        memory_manager.set_fact("temp_key", "temp_value")
        memory_manager.clear_memory("facts")
        value = memory_manager.get_fact("temp_key")
        
        if value is None:
            print("   ✓ Facts cleared successfully")
            results['clear_facts'] = 'PASS'
        else:
            print(f"   ✗ Fact still exists: {value}")
            results['clear_facts'] = 'FAIL: Fact not cleared'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['clear_facts'] = f'FAIL: {e}'
    
    try:
        # Test 5: Add history entry
        print("\n5. Testing add_history_entry...")
        memory_manager.add_history_entry("Opened Chrome browser")
        memory = memory_manager.load_memory()
        history = memory.get("history", [])
        
        if "Opened Chrome browser" in history:
            print("   ✓ History entry added successfully")
            results['add_history_entry'] = 'PASS'
        else:
            print("   ✗ History entry not found")
            results['add_history_entry'] = 'FAIL: Entry not found'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['add_history_entry'] = f'FAIL: {e}'
    
    try:
        # Test 6: Get recent history
        print("\n6. Testing get_recent_history...")
        history = memory_manager.get_recent_history()
        
        if isinstance(history, list) and len(history) > 0:
            print(f"   ✓ Retrieved {len(history)} history entries")
            results['get_recent_history'] = 'PASS'
        else:
            print("   ✗ History empty or invalid")
            results['get_recent_history'] = 'FAIL: No history'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['get_recent_history'] = f'FAIL: {e}'
    
    try:
        # Test 7: Add conversation turn
        print("\n7. Testing add_conversation_turn...")
        memory_manager.add_conversation_turn("user", "Test message")
        memory = memory_manager.load_memory()
        conversation = memory.get("conversation", [])
        
        last_turn = conversation[-1] if conversation else None
        if last_turn and last_turn.get("role") == "user" and last_turn.get("text") == "Test message":
            print("   ✓ Conversation turn added successfully")
            results['add_conversation_turn'] = 'PASS'
        else:
            print("   ✗ Conversation turn not found")
            results['add_conversation_turn'] = 'FAIL: Turn not found'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['add_conversation_turn'] = f'FAIL: {e}'
    
    try:
        # Test 8: Get recent turns
        print("\n8. Testing get_recent_turns...")
        turns = memory_manager.get_recent_turns()
        
        if isinstance(turns, list):
            print(f"   ✓ Retrieved {len(turns)} conversation turns")
            results['get_recent_turns'] = 'PASS'
        else:
            print("   ✗ Turns invalid")
            results['get_recent_turns'] = 'FAIL: Invalid turns'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['get_recent_turns'] = f'FAIL: {e}'
    
    # Clean up
    if temp_file.exists():
        temp_file.unlink()
    memory_manager.DATA_PATH = original_path
    
    return results


def test_window_control() -> dict:
    """Test window control functionality (basic validation)."""
    print_section("Testing Window Control")
    
    results = {}
    
    try:
        # Test 1: Check imports
        print("\n1. Checking required imports...")
        has_win32 = window_control.win32gui is not None
        if has_win32:
            print("   ✓ win32gui available")
            results['imports'] = 'PASS'
        else:
            print("   ⚠ win32gui not available (Windows-specific)")
            results['imports'] = 'SKIP: Not on Windows or missing pywin32'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['imports'] = f'FAIL: {e}'
    
    try:
        # Test 2: Check window info dataclass
        print("\n2. Testing WindowInfo dataclass...")
        win_info = window_control.WindowInfo(
            hwnd=12345,
            title="Test Window",
            pid=1000,
            process_name="test.exe",
            exe_path="C:\\test.exe"
        )
        if win_info.hwnd == 12345 and win_info.title == "Test Window":
            print("   ✓ WindowInfo dataclass works")
            results['window_info'] = 'PASS'
        else:
            print("   ✗ WindowInfo dataclass failed")
            results['window_info'] = 'FAIL: Dataclass error'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['window_info'] = f'FAIL: {e}'
    
    try:
        # Test 3: Check constants
        print("\n3. Checking module constants...")
        has_aliases = hasattr(window_control, 'APP_ALIASES') and isinstance(window_control.APP_ALIASES, dict)
        has_actions = hasattr(window_control, 'ACTIONS') and isinstance(window_control.ACTIONS, set)
        
        if has_aliases and has_actions:
            print(f"   ✓ Constants defined: {len(window_control.APP_ALIASES)} aliases, {len(window_control.ACTIONS)} actions")
            results['constants'] = 'PASS'
        else:
            print("   ✗ Constants missing or invalid")
            results['constants'] = 'FAIL: Constants invalid'
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results['constants'] = f'FAIL: {e}'
    
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
                result = result.replace('SKIP: ', '')
            else:
                status = f'✗ FAIL'
                failed += 1
                if result.startswith('FAIL: '):
                    result = result.replace('FAIL: ', '')
            
            print(f"  {status}: {test_name}")
            if status == '✗ FAIL':
                print(f"         {result}")
            elif status == '⚠ SKIP':
                print(f"         {result}")
    
    print(f"\n{'=' * 60}")
    print(f"Total: {total} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
    print(f"Success Rate: {(passed / (total - skipped) * 100) if (total - skipped) > 0 else 0:.1f}%")
    print('=' * 60)


def main() -> None:
    """Run all module tests."""
    print("\n🔍 AI PC Assistant - Module Test Suite")
    print('=' * 60)
    
    all_results = {}
    
    # Run all test suites
    all_results['conversation_manager'] = test_conversation_manager()
    all_results['memory_manager'] = test_memory_manager()
    all_results['window_control'] = test_window_control()
    
    # Print summary
    print_summary(all_results)


if __name__ == "__main__":
    main()
