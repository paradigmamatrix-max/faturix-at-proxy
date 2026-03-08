"""
Faturix AT SOAP Proxy
Relay entre backoffice.faturix.pt e os WebServices AT (portas 700/400)
"""
import os
import ssl
import socket
import base64
import certifi
import http.client
from urllib3.util.ssl_ import create_urllib3_context
from flask import Flask, request, Response

app = Flask(__name__)

AT_PORTS = {
    'teste':    700,
    'producao': 400,
}
AT_HOST = 'servicos.portaldasfinancas.gov.pt'


def _make_ctx():
    ctx = create_urllib3_context()
    ctx.set_ciphers('DEFAULT@SECLEVEL=1')
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cafile=certifi.where())
    try:
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    except AttributeError:
        pass
    return ctx


class ATHTTPSConn(http.client.HTTPSConnection):
    """Ligação HTTPS com ssl_context personalizado (handshake manual)"""
    def __init__(self, host, port, ssl_ctx):
        super().__init__(host, port=port, timeout=30)
        self._ssl_ctx = ssl_ctx

    def connect(self):
        raw = socket.create_connection((self.host, self.port), timeout=10)
        ssl_sock = self._ssl_ctx.wrap_socket(
            raw,
            server_hostname=self.host,
            do_handshake_on_connect=False,
        )
        ssl_sock.do_handshake()
        self.sock = ssl_sock


@app.route('/', methods=['POST'])
def proxy():
    endpoint    = request.headers.get('X-AT-Endpoint', 'series').lstrip('/')
    ambiente    = request.headers.get('X-AT-Ambiente', 'teste')
    soap_action = request.headers.get('X-SOAP-Action', '')

    port     = AT_PORTS.get(ambiente, AT_PORTS['teste'])
    path     = f'/fews/{endpoint}'
    soap_body = request.get_data()

    try:
        conn = ATHTTPSConn(AT_HOST, port, _make_ctx())
        conn.request(
            'POST', path, body=soap_body,
            headers={
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction':   soap_action,
                'Host':         AT_HOST,
            },
        )
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return Response(
            data,
            status=resp.status,
            headers={'Content-Type': 'text/xml; charset=utf-8'},
        )
    except ssl.SSLError as e:
        return Response(f'SSL error: {e}', status=502)
    except OSError as e:
        return Response(f'Connection error: {e}', status=502)
    except Exception as e:
        return Response(f'Proxy error: {e}', status=502)


@app.route('/get-cert')
def get_cert():
    """Extrai o certificado TLS da AT"""
    ctx2 = _make_ctx()
    lines = []
    try:
        sock = socket.create_connection((AT_HOST, 700), timeout=10)
        ssl_sock = ctx2.wrap_socket(
            sock, server_hostname=AT_HOST, do_handshake_on_connect=False)
        try:
            ssl_sock.do_handshake()
            lines.append('Handshake OK')
        except ssl.SSLCertVerificationError as e:
            lines.append(f'CertVerificationError: {e}')
        except ssl.SSLError as e:
            lines.append(f'SSLError: {e}')
            return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}
        try:
            der = ssl_sock.getpeercert(binary_form=True)
            if der:
                pem = ('-----BEGIN CERTIFICATE-----\n'
                       + base64.b64encode(der).decode() + '\n'
                       + '-----END CERTIFICATE-----')
                lines.append(pem)
            else:
                lines.append('No peer cert')
        except Exception as e2:
            lines.append(f'getpeercert error: {e2}')
    except Exception as e:
        lines.append(f'Connection error: {e}')
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}


@app.route('/health')
def health():
    return 'OK'


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
