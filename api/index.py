from http.server import BaseHTTPRequestHandler
import json
import sys
import os

# Allow importing nse_scanner.py from the parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nse_scanner import run_scan

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Allow Cross-Origin Requests (CORS) so the front-end can fetch this data
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        
        try:
            # Run the scanner logic
            data = run_scan()
            response_json = json.dumps(data)
            self.wfile.write(response_json.encode('utf-8'))
        except Exception as e:
            err_response = json.dumps({"success": False, "error": str(e)})
            self.wfile.write(err_response.encode('utf-8'))
        return
