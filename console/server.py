"""Servidor HTTP para o AION Sim Console.

Serve index.html na porta 3000 e faz proxy de /v1/* → AION (porta 8080).
O proxy elimina a necessidade de CORS — o browser nunca vê cross-origin.

Normalmente iniciado pelo start.py — não precisa rodar diretamente.

Uso direto (opcional):
    python console/server.py
    Acesse: http://localhost:3000
"""
import http.server
import socketserver
import os
import urllib.request
import urllib.error
from pathlib import Path

PORT     = int(os.environ.get("CONSOLE_PORT", "3000"))
AION_URL = os.environ.get("AION_URL", "http://localhost:8080")
DIR      = Path(__file__).resolve().parent

# Headers que não devem ser repasados ao fazer proxy
_HOP_BY_HOP = frozenset([
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
])


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIR), **kwargs)

    def log_message(self, *args):
        pass  # silencia logs de acesso

    def do_POST(self):
        if self.path.startswith("/v1/") or self.path.startswith("/health") or self.path.startswith("/ready"):
            self._proxy()
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path.startswith("/v1/") or self.path in ("/health", "/ready", "/metrics"):
            self._proxy()
        else:
            super().do_GET()

    def do_OPTIONS(self):
        """Responde preflight CORS diretamente — sem repassar ao AION."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "3600")
        self.end_headers()

    def _proxy(self):
        """Encaminha request para AION e retorna a resposta ao browser."""
        target = AION_URL + self.path

        # Lê body se houver
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Copia headers relevantes (exclui hop-by-hop)
        fwd_headers = {}
        for k, v in self.headers.items():
            if k.lower() not in _HOP_BY_HOP and k.lower() != "host":
                fwd_headers[k] = v

        try:
            req = urllib.request.Request(
                target,
                data=body,
                headers=fwd_headers,
                method=self.command,
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in _HOP_BY_HOP:
                        self.send_header(k, v)
                # Adiciona CORS para garantia
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in _HOP_BY_HOP:
                    self.send_header(k, v)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(
                f'{{"error":{{"message":"Proxy error: {e}","type":"proxy_error","code":"proxy_error"}}}}'.encode()
            )


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.allow_reuse_address = True
        print(f"Console em: http://localhost:{PORT} (proxy -> {AION_URL})")
        httpd.serve_forever()
