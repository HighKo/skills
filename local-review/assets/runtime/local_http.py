#!/usr/bin/env python3
"""Loopback-only development gateway and captured-mail inbox. Standard library only."""
import argparse
import datetime
import html
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

ROOT = Path(__file__).resolve().parent
MAIL = ROOT / 'state/mail.jsonl'
LOCK = threading.Lock()
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Do not log tokens, OTPs, or personal request paths.

    def reply(self, code, body, content_type='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def request_body(self, maximum=100 * 1024 * 1024):
        encoding = self.headers.get('Transfer-Encoding', '').lower()
        if not encoding:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= maximum:
                raise ValueError('Invalid body size')
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('Incomplete request')
            return body
        if encoding != 'chunked' or self.headers.get('Content-Length'):
            raise ValueError('Unsupported or ambiguous body encoding')
        # Dart's HTTP client streams requests using chunked transfer encoding.
        body = bytearray()
        while True:
            line = self.rfile.readline(8192)
            if not line.endswith(b'\r\n'):
                raise ValueError('Invalid chunk header')
            size = int(line.split(b';', 1)[0].strip(), 16)
            if size < 0 or len(body) + size > maximum:
                raise ValueError('Invalid body size')
            if size == 0:
                trailer_bytes = 0
                while True:
                    trailer = self.rfile.readline(8192)
                    trailer_bytes += len(trailer)
                    if not trailer or trailer_bytes > 65536:
                        raise ValueError('Invalid trailers')
                    if trailer == b'\r\n':
                        return bytes(body)
            chunk = self.rfile.read(size)
            if len(chunk) != size or self.rfile.read(2) != b'\r\n':
                raise ValueError('Incomplete chunk')
            body.extend(chunk)

    def handle_request(self):
        if self.server.server_port == 8090:
            return self.inbox()
        prefix = self.path.split('?', 1)[0].split('/')[1]
        port = 8081 if prefix in ('auth', 'internal-auth') else 8080
        if prefix not in ('auth', 'internal-auth', 'app', 'portal', 'admin', 'staff', 'internal', 'public'):
            return self.reply(404, b'{"error":"local_route_not_available"}')
        try:
            body = self.request_body()
        except (ValueError, OSError):
            return self.reply(400, b'{"error":"invalid_request_body"}')
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers.update({'X-Real-IP': '127.0.0.1', 'X-Forwarded-For': '127.0.0.1', 'X-Forwarded-Proto': 'http'})
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=60)
        try:
            conn.request(self.command, self.path, body, headers)
            response = conn.getresponse()
            data = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP:
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)
        except (OSError, http.client.HTTPException):
            self.reply(502, b'{"error":"local_upstream_unavailable"}')
        finally:
            conn.close()

    def inbox(self):
        if self.command == 'POST' and self.path == '/send':
            # Prevent cross-origin web pages from injecting messages into this local inbox.
            if self.headers.get('Origin') or self.headers.get_content_type() != 'application/json':
                return self.reply(403, b'{}')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024 * 1024:
                return self.reply(400, b'{}')
            try:
                message = json.loads(self.rfile.read(length))
                if not all(isinstance(message.get(k), str) for k in ('from', 'to', 'subject', 'bodyText')):
                    raise ValueError('Malformed mail')
            except (ValueError, TypeError):
                return self.reply(400, b'{}')
            message['receivedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            with LOCK:
                with MAIL.open('a') as output:
                    output.write(json.dumps(message) + '\n')
                MAIL.chmod(0o600)
            return self.reply(200, b'{}')
        if self.command != 'GET':
            return self.reply(405, b'{}')
        with LOCK:
            messages = [json.loads(line) for line in MAIL.read_text().splitlines()] if MAIL.exists() else []
        if self.path == '/messages':
            return self.reply(200, json.dumps(messages).encode())
        if self.path != '/':
            return self.reply(404, b'{}')
        cards = ''.join('<article><h2>' + html.escape(m['subject']) + '</h2><p>To: ' +
                        html.escape(m['to']) + ' · ' + html.escape(m['receivedAt']) +
                        '</p><pre>' + html.escape(m['bodyText']) + '</pre></article>' for m in reversed(messages))
        page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Booking local inbox</title><style>body{font:16px system-ui;max-width:900px;margin:40px auto;padding:0 20px}article{border-top:1px solid #ccc;padding:16px 0}pre{white-space:pre-wrap}</style><h1>Booking local inbox</h1><p>Local capture only. <a href="/">Refresh messages</a></p>' + (cards or '<p>No messages yet.</p>') + '</html>'
        self.reply(200, page.encode(), 'text/html; charset=utf-8')

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = handle_request


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('port', type=int, choices=[8082, 8090])
    args = parser.parse_args()
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()

