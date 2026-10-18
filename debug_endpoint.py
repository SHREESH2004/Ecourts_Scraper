#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Monkey patch the data_service function to add logging
import data_service

original_function = data_service.get_supreme_court_judge_detail

def debug_get_supreme_court_judge_detail(judge_name):
    print(f"[DEBUG] get_supreme_court_judge_detail called with: {judge_name}")
    result = original_function(judge_name)
    print(f"[DEBUG] get_supreme_court_judge_detail returning: {result is not None}")
    if result:
        print(f"[DEBUG] Result keys: {list(result.keys())}")
        if 'conviction_analysis' in result:
            print(f"[DEBUG] conviction_analysis present with keys: {list(result['conviction_analysis'].keys())}")
        else:
            print(f"[DEBUG] conviction_analysis MISSING from result")
    return result

# Replace the function
data_service.get_supreme_court_judge_detail = debug_get_supreme_judge_detail

# Now import and run the Flask app to see what happens
from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    print(f"Starting debug server on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)