"""
Faturix AT SOAP Proxy
Relay entre backoffice.faturix.pt e os WebServices AT (portas 700/400)
"""
import os
import httpx
from flask import Flask, request, Response

app = Flask(__name__)

AT_URLS = {
    'teste':    'https://servicos.portaldasfinancas.gov.pt:700/fews',
    'producao': 'https://servicos.portaldasfinancas.gov.pt:400/fews',
}

_client = httpx.Client(verify=False, timeout=30.0)


@app.route('/', methods=['POST'])
def proxy():
    endpoint    = request.headers.get('X-AT-Endpoint', 'series').lstrip('/')
    ambiente    = request.headers.get('X-AT-Ambiente', 'teste')
    soap_action = request.headers.get('X-SOAP-Action', '')

    base_url = AT_URLS.get(ambiente, AT_URLS['teste'])
    at_url   = f"{base_url}/{endpoint}"

    soap_body = request.get_data()

    try:
        resp = _client.post(
            at_url,
            content=soap_body,
            headers={
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction':   soap_action,
            },
        )
        return Response(
            resp.content,
            status=resp.status_code,
            headers={'Content-Type': 'text/xml; charset=utf-8'},
        )
    except httpx.HTTPError as e:
        return Response(f'HTTP error: {e}', status=502)
    except Exception as e:
        return Response(f'Proxy error: {e}', status=502)


@app.route('/health')
def health():
    return 'OK'


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
