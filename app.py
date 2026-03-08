"""
Faturix AT SOAP Proxy
Relay entre backoffice.faturix.pt e os WebServices AT (portas 700/400)
"""
import os
import requests
from flask import Flask, request, Response

app = Flask(__name__)

AT_URLS = {
    'teste':    'https://servicos.portaldasfinancas.gov.pt:700/fews',
    'producao': 'https://servicos.portaldasfinancas.gov.pt:400/fews',
}

@app.route('/', methods=['POST'])
def proxy():
    # Autenticação — lido no momento do request para garantir env var actualizada
    PROXY_SECRET = os.environ.get('PROXY_SECRET', '').strip()
    secret = request.headers.get('X-Proxy-Secret', '').strip()
    if not PROXY_SECRET or secret != PROXY_SECRET:
        return Response('Unauthorized', status=401)

    endpoint   = request.headers.get('X-AT-Endpoint', 'series').lstrip('/')
    ambiente   = request.headers.get('X-AT-Ambiente', 'teste')
    soap_action = request.headers.get('X-SOAP-Action', '')

    base_url = AT_URLS.get(ambiente, AT_URLS['teste'])
    at_url   = f"{base_url}/{endpoint}"

    soap_body = request.get_data()

    try:
        resp = requests.post(
            at_url,
            data=soap_body,
            headers={
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction': soap_action,
            },
            timeout=30,
            verify=True,
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
