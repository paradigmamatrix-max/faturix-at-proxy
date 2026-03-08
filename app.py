"""
Faturix AT SOAP Proxy
Relay entre backoffice.faturix.pt e os WebServices AT (portas 700/400)
"""
import os
import ssl
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
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers('DEFAULT@SECLEVEL=1')
    try:
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    except AttributeError:
        pass
    return urllib3.PoolManager(ssl_context=ctx)


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


@app.route('/health')
def health():
    return 'OK'


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
