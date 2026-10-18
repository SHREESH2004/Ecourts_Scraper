#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data_service import get_supreme_court_judge_detail, _calculate_judge_conviction_analysis

# Test with a judge name
judge_name = "HON'BLE MR. JUSTICE K. VINOD CHANDRAN"

print(f"Testing conviction analysis for: {judge_name}")

try:
    # Get the full judge detail
    result = get_supreme_court_judge_detail(judge_name)

    if result:
        print("SUCCESS: Got judge detail")
        print(f"Keys in result: {list(result.keys())}")

        if 'conviction_analysis' in result:
            print("SUCCESS: conviction_analysis key is present")
            ca = result['conviction_analysis']
            print(f"Conviction analysis keys: {list(ca.keys())}")

            if 'supreme_court_conviction_rate' in ca:
                rate = ca['supreme_court_conviction_rate']
                print(f"Supreme Court conviction rate: {rate.get('rate', 'N/A')}%")
                print(f"  Numerator: {rate.get('numerator', 'N/A')}")
                print(f"  Denominator: {rate.get('denominator', 'N/A')}")

            if 'outcome_distribution' in ca:
                dist = ca['outcome_distribution']
                print(f"Outcome distribution keys: {list(dist.keys())}")
                # Show non-zero counts
                non_zero = {k: v for k, v in dist.items() if v > 0}
                print(f"Non-zero outcome counts: {non_zero}")
        else:
            print("ERROR: conviction_analysis key is MISSING")

        # Also show summary info
        if 'summary' in result:
            summary = result['summary']
            print(f"Judge: {summary.get('judge_name', 'N/A')}")
            print(f"Total cases: {summary.get('total_cases', 'N/A')}")
    else:
        print("ERROR: Got None result from get_supreme_court_judge_detail")

except Exception as e:
    print(f"ERROR: Exception occurred: {e}")
    import traceback
    traceback.print_exc()