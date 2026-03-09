"""
Faturix AT SOAP Proxy
Relay entre backoffice.faturix.pt e os WebServices AT (portas 700/400)

Requer certificado mTLS da AT configurado em AT_CERT_B64:
  base64 do ficheiro PEM combinado (cert + chave privada, sem password)
  Obter em: Portal das Finanças > e-Fatura > Produtores de Software
  Converter: openssl pkcs12 -in TesteWebservices.pfx -nodes -out cert.pem -passin pass:TESTEwebservice
  Codificar: base64 -w0 cert.pem  (ou openssl base64 -in cert.pem -out cert.b64)
"""
import os
import ssl
import base64
import tempfile
import certifi
import http.client
from flask import Flask, request, Response

app = Flask(__name__)

AT_PORTS  = {'teste': 700, 'producao': 400}
AT_HOST   = 'servicos.portaldasfinancas.gov.pt'
PROXY_SECRET = os.environ.get('AT_PROXY_SECRET', '')

# ─── Contexto SSL com certificado mTLS ────────────────────────────────────────

_at_ctx   = None
_ctx_err  = None


def _init_ctx():
    global _at_ctx, _ctx_err
    cert_b64 = os.environ.get('AT_CERT_B64', '').strip()
    if not cert_b64:
        _ctx_err = (
            'AT_CERT_B64 não configurado. '
            'Defina o certificado AT (PEM base64) nas variáveis de ambiente do Railway.'
        )
        return
    try:
        cert_pem = base64.b64decode(cert_b64)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        # Verificar o certificado do servidor AT (Sectigo)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cafile=certifi.where())
        # Carregar certificado cliente (mTLS) — necessário para AT WebServices
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pem') as f:
            f.write(cert_pem)
            tmp = f.name
        try:
            ctx.load_cert_chain(tmp)
        finally:
            os.unlink(tmp)
        _at_ctx = ctx
    except Exception as e:
        _ctx_err = f'Erro ao carregar certificado AT: {e}'


_init_ctx()


# ─── Rotas ────────────────────────────────────────────────────────────────────

@app.route('/', methods=['POST'])
def proxy():
    # Verificar segredo do proxy
    if PROXY_SECRET and request.headers.get('X-Proxy-Secret') != PROXY_SECRET:
        return Response('Forbidden', status=403)

    if _at_ctx is None:
        return Response(f'Proxy não disponível: {_ctx_err}', status=503,
                        mimetype='text/plain')

    endpoint    = request.headers.get('X-AT-Endpoint', 'series').lstrip('/')
    ambiente    = request.headers.get('X-AT-Ambiente', 'teste')
    soap_action = request.headers.get('X-SOAP-Action', '')

    port      = AT_PORTS.get(ambiente, AT_PORTS['teste'])
    path      = f'/fews/{endpoint}'
    soap_body = request.get_data()

    try:
        conn = http.client.HTTPSConnection(
            AT_HOST, port=port, timeout=30, context=_at_ctx)
        conn.request('POST', path, body=soap_body, headers={
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction':   soap_action,
            'Host':         AT_HOST,
        })
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return Response(data, status=resp.status,
                        headers={'Content-Type': 'text/xml; charset=utf-8'})
    except ssl.SSLError as e:
        return Response(f'SSL error: {e}', status=502, mimetype='text/plain')
    except OSError as e:
        return Response(f'Connection error: {e}', status=502, mimetype='text/plain')
    except Exception as e:
        return Response(f'Proxy error: {e}', status=502, mimetype='text/plain')


@app.route('/health')
def health():
    # Sempre 200 para o Railway poder fazer deploy.
    # O erro de certificado é retornado nas chamadas ao proxy (/).
    status = 'OK' if _at_ctx is not None else f'NO_CERT: {_ctx_err}'
    return Response(status, status=200, mimetype='text/plain')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
