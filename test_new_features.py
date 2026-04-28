#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script for new ASA 2.3 features
验证新功能：三重验证、字段纠错、错误压缩
"""

import sys
sys.path.insert(0, '.')

def test_validate_coder_result():
    """Test triple validation mechanism"""
    print("\n" + "="*60)
    print("Testing: Triple Validation Mechanism")
    print("="*60)
    
    from multi_agent import validate_coder_result
    
    test_cases = [
        ("[DATA]: {'price': 100}", True, "Valid data"),
        ("[RESULT]: 42", True, "Valid result"),
        ("No tag here", False, "Missing tag"),
        ("[DATA]: {}", False, "Empty data"),
        ("[DATA]: null", False, "Null data"),
        ("[ERROR]: KeyError", False, "Error state"),
        ("[PARTIAL]: timeout", True, "Partial result"),
    ]
    
    for result, expected, desc in test_cases:
        is_valid, reason, check = validate_coder_result(result)
        status = "✅" if is_valid == expected else "❌"
        print(f"{status} {desc}: valid={is_valid}, check={check}")
    
    print("\nTriple validation test completed!")


def test_format_execution_result():
    """Test output protocol enforcement"""
    print("\n" + "="*60)
    print("Testing: Output Protocol Enforcement")
    print("="*60)
    
    from lib import _format_execution_result
    
    test_cases = [
        ("{'price': 100}", "df = pro.daily()", "[DATA]:"),
        ("42", "sum(values)", "[RESULT]:"),
        ("Traceback... KeyError", "code", "[ERROR]:"),
        ("[DATA]: already tagged", "code", "[DATA]:"),  # Should not duplicate
    ]
    
    for raw_result, code, expected_tag in test_cases:
        formatted = _format_execution_result(raw_result, code)
        status = "✅" if expected_tag in formatted else "❌"
        print(f"{status} Input: {raw_result[:30]}... -> Output: {formatted[:50]}...")
    
    print("\nOutput protocol test completed!")


def test_field_correction():
    """Test field error extraction"""
    print("\n" + "="*60)
    print("Testing: Field Correction Mechanism")
    print("="*60)
    
    from error_handlers import extract_field_error, generate_field_correction_feedback
    
    # Test extraction
    error_msgs = [
        "KeyError: 'pb_ttm'",
        "KeyError: \"dv_yeild\"",
        "'pe_ratio' not in index",
        "Some other error",
    ]
    
    for msg in error_msgs:
        result = extract_field_error(msg)
        if result:
            print(f"✅ Extracted field: {result['field']} from '{msg[:40]}...'")
            feedback = generate_field_correction_feedback(result['field'], None, "daily_basic")
            print(f"   Feedback preview: {feedback[:80]}...")
        else:
            print(f"⚠️ No field found in: {msg[:40]}...")
    
    print("\nField correction test completed!")


def test_error_compression():
    """Test error traceback compression"""
    print("\n" + "="*60)
    print("Testing: Error Traceback Compression")
    print("="*60)
    
    from error_handlers import compress_error_traceback
    
    # Simulate long traceback
    lines = ["Traceback (most recent call last):"]
    lines.extend([f'  File "script.py", line {i}, in <module>' for i in range(1, 21)])
    lines.append("KeyError: 'pb_ttm'")
    long_error = "\n".join(lines)
    
    print(f"Original length: {len(long_error)} characters, {len(long_error.split(chr(10)))} lines")
    
    compressed = compress_error_traceback(long_error, max_lines=5)
    print(f"Compressed length: {len(compressed)} characters, {len(compressed.split(chr(10)))} lines")
    print(f"\nCompressed output:\n{compressed}")
    
    print("\nError compression test completed!")


def test_thread_safe_kernel_manager():
    """Test ThreadSafeKernelManager initialization"""
    print("\n" + "="*60)
    print("Testing: ThreadSafeKernelManager")
    print("="*60)
    
    from lib import kernel_manager
    
    print(f"✅ KernelManager initialized: {type(kernel_manager).__name__}")
    
    # Check if it has the new methods
    if hasattr(kernel_manager, '_locks'):
        print("✅ Per-user lock mechanism available")
    if hasattr(kernel_manager, 'execute'):
        print("✅ Execute method with tag enforcement available")
    
    stats = kernel_manager.get_stats()
    print(f"Stats: {stats}")
    
    print("\nThreadSafeKernelManager test completed!")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("ASA 2.3 New Features Test Suite")
    print("="*70)
    
    try:
        test_validate_coder_result()
    except Exception as e:
        print(f"❌ Triple validation test failed: {e}")
    
    try:
        test_format_execution_result()
    except Exception as e:
        print(f"❌ Output protocol test failed: {e}")
    
    try:
        test_field_correction()
    except Exception as e:
        print(f"❌ Field correction test failed: {e}")
    
    try:
        test_error_compression()
    except Exception as e:
        print(f"❌ Error compression test failed: {e}")
    
    try:
        test_thread_safe_kernel_manager()
    except Exception as e:
        print(f"❌ Kernel manager test failed: {e}")
    
    print("\n" + "="*70)
    print("All tests completed!")
    print("="*70)
