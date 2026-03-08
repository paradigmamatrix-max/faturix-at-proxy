"""
Faturix AT SOAP Proxy
Relay entre backoffice.faturix.pt e os WebServices AT (portas 700/400)
"""
import os
import ssl
import certifi
import urllib3
from flask import Flask, request, Response

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

AT_URLS = {
    'teste':    'https://servicos.portaldasfinancas.gov.pt:700/fews',
    'producao': 'https://servicos.portaldasfinancas.gov.pt:400/fews',
}


def _make_pool():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cafile=certifi.where())
    ctx.set_ciphers('DEFAULT@SECLEVEL=1')
    try:
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    except AttributeError:
        pass
    try:
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    except AttributeError:
        pass
    # Pass ssl_context; also tell urllib3 not to verify hostname/cert
    return urllib3.PoolManager(
        ssl_context=ctx,
        assert_hostname=False,
        cert_reqs='CERT_NONE',
    )


_pool = _make_pool()


@app.route('/', methods=['POST'])
def proxy():
    endpoint    = request.headers.get('X-AT-Endpoint', 'series').lstrip('/')
    ambiente    = request.headers.get('X-AT-Ambiente', 'teste')
    soap_action = request.headers.get('X-SOAP-Action', '')

    base_url = AT_URLS.get(ambiente, AT_URLS['teste'])
    at_url   = f"{base_url}/{endpoint}"

    soap_body = request.get_data()

    try:
        resp = _pool.request(
            'POST',
            at_url,
            body=soap_body,
            headers={
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction':   soap_action,
            },
            timeout=urllib3.Timeout(connect=10, read=30),
        )
        return Response(
            resp.data,
            status=resp.status,
            headers={'Content-Type': 'text/xml; charset=utf-8'},
        )
    except urllib3.exceptions.SSLError as e:
        return Response(f'SSL error: {e}', status=502)
    except urllib3.exceptions.MaxRetryError as e:
        return Response(f'Connection error: {e}', status=502)
    except Exception as e:
        return Response(f'Proxy error: {e}', status=502)


@app.route('/get-cert')
def get_cert():
    """Extrai o certificado TLS da AT para diagnóstico"""
    import socket
    import base64
    ctx2 = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx2.check_hostname = False
    ctx2.verify_mode = ssl.CERT_REQUIRED
    ctx2.load_verify_locations(cafile=certifi.where())
    ctx2.set_ciphers('DEFAULT@SECLEVEL=1')
    try:
        ctx2.maximum_version = ssl.TLSVersion.TLSv1_2
    except AttributeError:
        pass
    lines = []
    try:
        sock = socket.create_connection(
            ('servicos.portaldasfinancas.gov.pt', 700), timeout=10)
        ssl_sock = ctx2.wrap_socket(
            sock,
            server_hostname='servicos.portaldasfinancas.gov.pt',
            do_handshake_on_connect=False,
        )
        try:
            ssl_sock.do_handshake()
            lines.append('Handshake OK (no cert error)')
        except ssl.SSLCertVerificationError as e:
            lines.append(f'CertVerificationError (expected): {e}')
        except ssl.SSLError as e:
            lines.append(f'SSLError: {e}')
            return '\n'.join(lines)
        # Try to get peer cert even after error
        try:
            der = ssl_sock.getpeercert(binary_form=True)
            if der:
                pem = ('-----BEGIN CERTIFICATE-----\n'
                       + base64.b64encode(der).decode() + '\n'
                       + '-----END CERTIFICATE-----')
                lines.append(pem)
            else:
                lines.append('No peer cert available')
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
