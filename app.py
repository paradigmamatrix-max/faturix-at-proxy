"""
Faturix AT SOAP Proxy
Relay entre backoffice.faturix.pt e os WebServices AT (portas 700/400)
"""
import os
import ssl
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from flask import Flask, request, Response

app = Flask(__name__)

AT_URLS = {
    'teste':    'https://servicos.portaldasfinancas.gov.pt:700/fews',
    'producao': 'https://servicos.portaldasfinancas.gov.pt:400/fews',
}

class LegacySSLAdapter(HTTPAdapter):
    """Permite TLS legacy para servidores AT (governo português usa cifras antigas)"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        except AttributeError:
            pass
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


@app.route('/', methods=['POST'])
def proxy():
    endpoint    = request.headers.get('X-AT-Endpoint', 'series').lstrip('/')
    ambiente    = request.headers.get('X-AT-Ambiente', 'teste')
    soap_action = request.headers.get('X-SOAP-Action', '')

    base_url = AT_URLS.get(ambiente, AT_URLS['teste'])
    at_url   = f"{base_url}/{endpoint}"

    soap_body = request.get_data()

    session = requests.Session()
    session.mount('https://', LegacySSLAdapter())

    try:
        resp = session.post(
            at_url,
            data=soap_body,
            headers={
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction': soap_action,
            },
            timeout=30,
            verify=False,
        )
        return Response(
            resp.content,
            status=resp.status_code,
            headers={'Content-Type': 'text/xml; charset=utf-8'},
        )
    except requests.exceptions.SSLError as e:
        return Response(f'SSL error: {e}', status=502)
    except requests.exceptions.ConnectionError as e:
        return Response(f'Connection error: {e}', status=502)
    except Exception as e:
        return Response(f'Proxy error: {e}', status=502)

@app.route('/health')
def health():
    return 'OK'

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
