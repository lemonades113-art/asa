#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Core features test (no heavy dependencies)
核心功能测试（无需重量级依赖）
"""

import sys
import re
from difflib import get_close_matches


def test_validate_coder_result():
    """Test triple validation mechanism"""
    print("\n" + "="*60)
    print("Testing: Triple Validation Mechanism")
    print("="*60)
    
    # Inline implementation for testing
    def validate_coder_result(result: str):
        has_data_tag = "[DATA]:" in result
        has_result_tag = "[RESULT]:" in result
        has_partial_tag = "[PARTIAL]:" in result or "[PARTIAL RESULT]" in result
        
        if not has_data_tag and not has_result_tag and not has_partial_tag:
            return False, "缺少输出标记 [DATA]: / [RESULT]: / [PARTIAL]:", 1
        
        if ":" in result:
            content = result.split(":", 1)[1].strip()
        else:
            content = result.strip()
        
        empty_indicators = ["", "{}", "[]", "null", "None", "''", '""']
        if content in empty_indicators:
            return False, "输出内容为空", 2
        
        if has_data_tag and len(content) < 5:
            return False, "数据标记存在但内容过少", 2
        
        if "[ERROR]:" in result:
            return False, "执行报错", 3
        
        if "[PARTIAL]:" in result or "[PARTIAL RESULT]" in result:
            return True, "部分结果（超时）", 0
        
        return True, "验证通过", 0
    
    test_cases = [
        ("[DATA]: {'price': 100}", True, "Valid data"),
        ("[RESULT]: 42", True, "Valid result"),
        ("No tag here", False, "Missing tag"),
        ("[DATA]: {}", False, "Empty data"),
        ("[DATA]: null", False, "Null data"),
        ("[ERROR]: KeyError", False, "Error state"),
        ("[PARTIAL]: timeout", True, "Partial result"),
    ]
    
    all_passed = True
    for result, expected, desc in test_cases:
        is_valid, reason, check = validate_coder_result(result)
        status = "✅" if is_valid == expected else "❌"
        if is_valid != expected:
            all_passed = False
        print(f"{status} {desc}: valid={is_valid}, check={check}")
    
    return all_passed


def test_format_execution_result():
    """Test output protocol enforcement"""
    print("\n" + "="*60)
    print("Testing: Output Protocol Enforcement")
    print("="*60)
    
    def _format_execution_result(raw_result: str, code: str) -> str:
        if any(tag in raw_result for tag in ["[DATA]:", "[ERROR]:", "[RESULT]:", "[PARTIAL]:"]):
            return raw_result
        
        if "Traceback" in raw_result or "Error:" in raw_result:
            return f"[ERROR]: {raw_result}"
        
        if "[PARTIAL]" in raw_result or "执行超时" in raw_result:
            return f"[PARTIAL]: {raw_result}"
        
        result_stripped = raw_result.strip()
        is_structured_data = (
            result_stripped.startswith(("{", "[")) or
            "DataFrame" in result_stripped or
            "Data type:" in result_stripped or
            any(indicator in code for indicator in ["pro.", "query", "df", "get_data"])
        )
        
        if is_structured_data:
            return f"[DATA]: {raw_result}"
        
        is_computation = any(op in code for op in ["sum(", "mean(", "count(", "max(", "min(", "calculate"])
        if is_computation:
            return f"[RESULT]: {raw_result}"
        
        return f"[RESULT]: {raw_result}"
    
    test_cases = [
        ("{'price': 100}", "df = pro.daily()", "[DATA]:", True),
        ("42", "sum(values)", "[RESULT]:", True),
        ("Traceback... KeyError", "code", "[ERROR]:", True),
        ("[DATA]: already tagged", "code", "[DATA]:", True),
        ("[ERROR]: existing", "code", "[ERROR]:", True),
    ]
    
    all_passed = True
    for raw_result, code, expected_tag, should_contain in test_cases:
        formatted = _format_execution_result(raw_result, code)
        contains = expected_tag in formatted
        status = "✅" if contains == should_contain else "❌"
        if contains != should_contain:
            all_passed = False
        print(f"{status} Input: {raw_result[:30]:<30} -> {formatted[:40]}...")
    
    return all_passed


def test_field_correction():
    """Test field error extraction"""
    print("\n" + "="*60)
    print("Testing: Field Correction Mechanism")
    print("="*60)
    
    def extract_field_error(error_message: str):
        match = re.search(r"KeyError:\s*['\"](\w+)['\"]", error_message)
        if match:
            return {"field": match.group(1)}
        
        match = re.search(r"'(\w+)'\s+not\s+in\s+index", error_message, re.IGNORECASE)
        if match:
            return {"field": match.group(1)}
        
        return None
    
    def suggest_field_correction(wrong_field: str, available_fields: list, cutoff: float = 0.6):
        matches = get_close_matches(wrong_field, available_fields, n=1, cutoff=cutoff)
        return matches[0] if matches else None
    
    test_cases = [
        ("KeyError: 'pb_ttm'", "pb_ttm", True),
        ("KeyError: \"dv_yeild\"", "dv_yeild", True),
        ("'pe_ratio' not in index", "pe_ratio", True),
        ("Some other error", None, False),
    ]
    
    all_passed = True
    for msg, expected_field, should_find in test_cases:
        result = extract_field_error(msg)
        found = result is not None
        status = "✅" if found == should_find else "❌"
        if found != should_find:
            all_passed = False
        
        if result:
            print(f"{status} Extracted: {result['field']:<15} from '{msg[:40]}...'")
        else:
            print(f"{status} No field found in: {msg[:40]}...")
    
    # Test fuzzy matching
    print("\nFuzzy matching test:")
    available = ["pb_ttm", "pe_ttm", "dv_yield", "close", "open", "high", "low"]
    suggestions = [
        ("pb_tm", "pb_ttm"),  # typo
        ("dv_yeild", "dv_yield"),  # typo
        ("pe_ration", "pe_ttm"),  # similar
    ]
    
    for wrong, expected in suggestions:
        suggested = suggest_field_correction(wrong, available, cutoff=0.5)
        status = "✅" if suggested == expected else "⚠️"
        print(f"{status} '{wrong}' -> '{suggested}' (expected: '{expected}')")
    
    return all_passed


def test_error_compression():
    """Test error traceback compression"""
    print("\n" + "="*60)
    print("Testing: Error Traceback Compression")
    print("="*60)
    
    def compress_error_traceback(error_message: str, max_lines: int = 5) -> str:
        lines = error_message.split('\n')
        
        if len(lines) <= max_lines:
            return error_message
        
        first_lines = lines[:2]
        last_lines = lines[-(max_lines-2):]
        omitted_count = len(lines) - len(first_lines) - len(last_lines)
        
        compressed = '\n'.join(first_lines)
        compressed += f"\n... ({omitted_count} lines omitted) ..."
        compressed += '\n' + '\n'.join(last_lines)
        
        return compressed
    
    # Simulate long traceback
    lines = ["Traceback (most recent call last):"]
    lines.extend([f'  File "script.py", line {i}, in <module>' for i in range(1, 21)])
    lines.append("KeyError: 'pb_ttm'")
    long_error = "\n".join(lines)
    
    print(f"Original: {len(long_error)} chars, {len(long_error.split(chr(10)))} lines")
    
    compressed = compress_error_traceback(long_error, max_lines=5)
    print(f"Compressed: {len(compressed)} chars, {len(compressed.split(chr(10)))} lines")
    print(f"\nOutput preview:\n{compressed[:200]}...")
    
    # Verify compression worked
    passed = len(compressed) < len(long_error) and "omitted" in compressed
    print(f"\n{'✅' if passed else '❌'} Compression {'successful' if passed else 'failed'}")
    
    return passed


if __name__ == "__main__":
    print("\n" + "="*70)
    print("ASA 2.3 Core Features Test Suite")
    print("="*70)
    
    results = []
    
    try:
        results.append(("Triple Validation", test_validate_coder_result()))
    except Exception as e:
        print(f"❌ Triple validation test failed: {e}")
        results.append(("Triple Validation", False))
    
    try:
        results.append(("Output Protocol", test_format_execution_result()))
    except Exception as e:
        print(f"❌ Output protocol test failed: {e}")
        results.append(("Output Protocol", False))
    
    try:
        results.append(("Field Correction", test_field_correction()))
    except Exception as e:
        print(f"❌ Field correction test failed: {e}")
        results.append(("Field Correction", False))
    
    try:
        results.append(("Error Compression", test_error_compression()))
    except Exception as e:
        print(f"❌ Error compression test failed: {e}")
        results.append(("Error Compression", False))
    
    print("\n" + "="*70)
    print("Test Summary:")
    print("="*70)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(passed for _, passed in results)
    print("="*70)
    print(f"Overall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    print("="*70)
