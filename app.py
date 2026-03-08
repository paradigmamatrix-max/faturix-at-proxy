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


@app.route('/', methods=['POST'])
def proxy():
    endpoint    = request.headers.get('X-AT-Endpoint', 'series').lstrip('/')
    ambiente    = request.headers.get('X-AT-Ambiente', 'teste')
    soap_action = request.headers.get('X-SOAP-Action', '')

    port      = AT_PORTS.get(ambiente, AT_PORTS['teste'])
    path      = f'/fews/{endpoint}'
    soap_body = request.get_data()

    try:
        # Usa o context= nativo do HTTPSConnection (sem override de connect)
        conn = http.client.HTTPSConnection(
            AT_HOST, port=port, timeout=30, context=_make_ctx())
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


@app.route('/debug-proxy')
def debug_proxy():
    """Testa ligação AT com código idêntico ao /get-cert mas faz SOAP request"""
    ctx = _make_ctx()
    soap = b'<?xml version="1.0"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body><versao xmlns="http://at.gov.pt/"/></soapenv:Body></soapenv:Envelope>'
    try:
        raw = socket.create_connection((AT_HOST, 700), timeout=10)
        ssl_sock = ctx.wrap_socket(raw, server_hostname=AT_HOST, do_handshake_on_connect=False)
        ssl_sock.do_handshake()
        # Envia HTTP request manual
        req = (
            b'POST /fews/versao HTTP/1.1\r\n'
            b'Host: ' + AT_HOST.encode() + b'\r\n'
            b'Content-Type: text/xml; charset=utf-8\r\n'
            b'SOAPAction: versao\r\n'
            b'Content-Length: ' + str(len(soap)).encode() + b'\r\n'
            b'Connection: close\r\n\r\n'
            + soap
        )
        ssl_sock.sendall(req)
        resp = b''
        while True:
            chunk = ssl_sock.recv(4096)
            if not chunk:
                break
            resp += chunk
        ssl_sock.close()
        return resp[:2000], 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        return f'Error: {type(e).__name__}: {e}', 502, {'Content-Type': 'text/plain'}


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
