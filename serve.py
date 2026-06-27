"""
Simple local server that mimics Vercel's routing:
  GET /api  → runs nse_scanner.run_scan() and returns JSON
  GET /     → serves index.html
"""
import sys, os, json, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from nse_scanner import run_scan

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    def do_GET(self):
        path = self.path.split('?')[0]

        if path in ('/api', '/api/'):
            try:
                data = run_scan()
                body = json.dumps(data).encode()
            except Exception as e:
                body = json.dumps({"success": False, "error": str(e)}).encode()
                traceback.print_exc()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)

        elif path in ('/', '/index.html'):
            html = (ROOT / 'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(html)

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not found')

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"✅  SmartMoney running at http://localhost:{port}")
    print(f"    Dashboard: http://localhost:{port}/")
    print(f"    API:       http://localhost:{port}/api")
    HTTPServer(('', port), Handler).serve_forever()
