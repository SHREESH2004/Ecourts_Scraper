#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data_service import get_supreme_court_judge_detail

# Test the function directly
judge_name = "HON'BLE MR. JUSTICE K. VINOD CHANDRAN"

print(f"Testing get_supreme_court_judge_detail for: {judge_name}")

try:
    result = get_supreme_court_judge_detail(judge_name)

    if result:
        print("SUCCESS: Got result from function")
        print(f"Keys in result: {list(result.keys())}")

        if 'conviction_analysis' in result:
            print("SUCCESS: conviction_analysis key is present in function result")
            ca = result['conviction_analysis']
            print(f"Conviction analysis keys: {list(ca.keys())}")
        else:
            print("ERROR: conviction_analysis key is MISSING from function result")

        # Show what keys ARE present
        print(f"All keys: {list(result.keys())}")

    else:
        print("ERROR: Got None result from function")

except Exception as e:
    print(f"ERROR: Exception occurred: {e}")
    import traceback
    traceback.print_exc()