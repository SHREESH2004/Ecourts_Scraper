#!/usr/bin/env python3

import sys
import os
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data_service import get_supreme_court_judge_detail

# Create a minimal Flask app for testing
from flask import Flask
app = Flask(__name__)

# Test exactly what the API endpoint does
judge_name = "HON'BLE MR. JUSTICE K. VINOD CHANDRAN"

print(f"Testing API endpoint logic for: {judge_name}")

try:
    with app.app_context():
        detail = get_supreme_court_judge_detail(judge_name)

        if not detail:
            print("ERROR: No detail returned from function")
        else:
            print("SUCCESS: Got detail from function")
            print(f"Detail keys: {list(detail.keys())}")

            # Check if conviction_analysis is in the detail
            if 'conviction_analysis' in detail:
                print("SUCCESS: conviction_analysis FOUND in detail from function")
                print(f"Conviction analysis keys: {list(detail['conviction_analysis'].keys())}")
            else:
                print("ERROR: conviction_analysis MISSING from detail from function")

            # This is exactly what the API endpoint does
            from flask import jsonify
            response = jsonify({"success": True, "data": detail})

            # Get the JSON data from the response
            response_data = json.loads(response.get_data(as_text=True))

            print(f"Response top-level keys: {list(response_data.keys())}")
            print(f"Response data keys: {list(response_data.get('data', {}).keys())}")

            if 'conviction_analysis' in response_data.get('data', {}):
                print("SUCCESS: conviction_analysis FOUND in API response")
            else:
                print("ERROR: conviction_analysis MISSING from API response")
                print(f"Available data keys: {list(response_data.get('data', {}).keys())}")

except Exception as e:
    print(f"ERROR: Exception occurred: {e}")
    import traceback
    traceback.print_exc()