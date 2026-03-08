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


def _make_ctx2():
    """ssl.SSLContext directo (sem urllib3), forçando http/1.1 via ALPN, sem session tickets"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.set_ciphers('DEFAULT@SECLEVEL=1')
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cafile=certifi.where())
    ctx.set_alpn_protocols(['http/1.1'])
    # desabilita session tickets – evita NewSessionTicket pós-handshake que pode confundir estado TLS
    try:
        ctx.options |= ssl.OP_NO_TICKET
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
            AT_HOST, port=port, timeout=30, context=_make_ctx2())
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


@app.route('/run-test')
def run_test():
    """Faz handshake TLS + SOAP no mesmo ssl socket (tudo num request)"""
    soap = b'<?xml version="1.0" encoding="UTF-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="http://servicos.portaldasfinancas.gov.pt/faturas/"><soap:Body><ns1:obterVersaoServico><ns1:nif>518651746</ns1:nif></ns1:obterVersaoServico></soap:Body></soap:Envelope>'
    lines = []
    try:
        ctx = _make_ctx()
        lines.append('1. _make_ctx OK')
        raw = socket.create_connection((AT_HOST, 700), timeout=10)
        lines.append('2. TCP connect OK')
        ssl_sock = ctx.wrap_socket(raw, server_hostname=AT_HOST, do_handshake_on_connect=False)
        lines.append('3. wrap_socket OK')
        ssl_sock.do_handshake()
        lines.append('4. do_handshake OK')
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
        lines.append('5. sendall OK')
        resp = b''
        while True:
            chunk = ssl_sock.recv(4096)
            if not chunk:
                break
            resp += chunk
        ssl_sock.close()
        lines.append(f'6. recv OK ({len(resp)} bytes)')
        lines.append(resp[:500].decode('utf-8', errors='replace'))
    except Exception as e:
        lines.append(f'FAILED: {type(e).__name__}: {e}')
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}


@app.route('/run-test2')
def run_test2():
    """Usa ssl.SSLContext directo (sem urllib3), lê com makefile()"""
    soap = b'<?xml version="1.0" encoding="UTF-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="http://servicos.portaldasfinancas.gov.pt/faturas/"><soap:Body><ns1:obterVersaoServico><ns1:nif>518651746</ns1:nif></ns1:obterVersaoServico></soap:Body></soap:Envelope>'
    lines = []
    ssl_sock = None
    try:
        ctx = _make_ctx2()
        lines.append('1. _make_ctx2 OK')
        raw = socket.create_connection((AT_HOST, 700), timeout=15)
        raw.settimeout(15)
        lines.append('2. TCP connect OK')
        ssl_sock = ctx.wrap_socket(raw, server_hostname=AT_HOST)
        lines.append(f'3. wrap+handshake OK (TLS {ssl_sock.version()}, ALPN={ssl_sock.selected_alpn_protocol()})')
        req = (
            b'POST /fews/versao HTTP/1.1\r\n'
            b'Host: ' + AT_HOST.encode() + b'\r\n'
            b'Content-Type: text/xml; charset=utf-8\r\n'
            b'SOAPAction: "versao"\r\n'
            b'Content-Length: ' + str(len(soap)).encode() + b'\r\n'
            b'Connection: close\r\n\r\n'
            + soap
        )
        ssl_sock.sendall(req)
        lines.append('4. sendall OK')
        # read via makefile
        f = ssl_sock.makefile('rb')
        resp_bytes = f.read(4096)
        lines.append(f'5. read OK ({len(resp_bytes)} bytes)')
        lines.append(resp_bytes[:500].decode('utf-8', errors='replace'))
    except ssl.SSLError as e:
        lines.append(f'FAILED SSLError lib={getattr(e,"library","?")} reason={getattr(e,"reason","?")} args={e.args}')
    except Exception as e:
        lines.append(f'FAILED: {type(e).__name__}: {e}')
    finally:
        if ssl_sock:
            try: ssl_sock.close()
            except: pass
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}


@app.route('/run-test-selfcert')
def run_test_selfcert():
    """Testa ligação AT com certificado cliente auto-assinado (gerado via openssl subprocess)"""
    import subprocess as _sp, tempfile
    lines = []
    ssl_sock = None
    try:
        with tempfile.TemporaryDirectory() as td:
            cert_path = f'{td}/client.crt'
            key_path  = f'{td}/client.key'
            r = _sp.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-keyout', key_path,
                         '-out', cert_path, '-days', '1', '-nodes',
                         '-subj', '/CN=faturix-proxy'], capture_output=True, timeout=10)
            if r.returncode != 0:
                lines.append(f'openssl req FAILED: {r.stderr.decode(errors="replace")}')
                return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}
            lines.append('1. cert gerado OK')
            ctx = _make_ctx2()
            ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
            lines.append('2. ctx com client cert OK')
            soap = b'<?xml version="1.0" encoding="UTF-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="http://servicos.portaldasfinancas.gov.pt/faturas/"><soap:Body><ns1:obterVersaoServico><ns1:nif>518651746</ns1:nif></ns1:obterVersaoServico></soap:Body></soap:Envelope>'
            raw = socket.create_connection((AT_HOST, 700), timeout=15)
            raw.settimeout(15)
            ssl_sock = ctx.wrap_socket(raw, server_hostname=AT_HOST)
            lines.append(f'3. handshake OK TLS={ssl_sock.version()}')
            req = (b'POST /fews/versao HTTP/1.1\r\nHost: ' + AT_HOST.encode() +
                   b'\r\nContent-Type: text/xml; charset=utf-8\r\nSOAPAction: "versao"\r\nContent-Length: '
                   + str(len(soap)).encode() + b'\r\nConnection: close\r\n\r\n' + soap)
            ssl_sock.sendall(req)
            lines.append('4. sendall OK')
            f = ssl_sock.makefile('rb')
            resp_bytes = f.read(4096)
            lines.append(f'5. read OK ({len(resp_bytes)} bytes)')
            lines.append(resp_bytes[:500].decode('utf-8', errors='replace'))
    except ssl.SSLError as e:
        lines.append(f'FAILED SSLError lib={getattr(e,"library","?")} reason={getattr(e,"reason","?")} args={e.args}')
    except Exception as e:
        lines.append(f'FAILED: {type(e).__name__}: {e}')
    finally:
        if ssl_sock:
            try: ssl_sock.close()
            except: pass
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}


@app.route('/run-test-notkt')
def run_test_notkt():
    """Testa com OP_NO_TICKET + tenta recv antes de enviar (flush NewSessionTicket)"""
    soap = b'<?xml version="1.0" encoding="UTF-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="http://servicos.portaldasfinancas.gov.pt/faturas/"><soap:Body><ns1:obterVersaoServico><ns1:nif>518651746</ns1:nif></ns1:obterVersaoServico></soap:Body></soap:Envelope>'
    lines = []
    ssl_sock = None
    try:
        ctx = _make_ctx2()  # já inclui OP_NO_TICKET
        raw = socket.create_connection((AT_HOST, 700), timeout=15)
        raw.settimeout(3)  # timeout curto para recv antes de enviar
        ssl_sock = ctx.wrap_socket(raw, server_hostname=AT_HOST)
        lines.append(f'1. handshake OK TLS={ssl_sock.version()}')
        # tentar ler dados que o servidor envie imediatamente pós-handshake (NewSessionTicket etc.)
        pre_data = b''
        for _ in range(5):
            try:
                chunk = ssl_sock.recv(4096)
                if chunk:
                    pre_data += chunk
                    lines.append(f'  pre-recv: {len(chunk)} bytes')
                else:
                    break
            except ssl.SSLWantReadError:
                break
            except socket.timeout:
                break
            except Exception as ex:
                lines.append(f'  pre-recv error: {ex}')
                break
        lines.append(f'2. pre-recv done ({len(pre_data)} bytes total)')
        ssl_sock.settimeout(15)
        req = (b'POST /fews/versao HTTP/1.1\r\nHost: ' + AT_HOST.encode() +
               b'\r\nContent-Type: text/xml; charset=utf-8\r\nSOAPAction: "versao"\r\nContent-Length: '
               + str(len(soap)).encode() + b'\r\nConnection: close\r\n\r\n' + soap)
        ssl_sock.sendall(req)
        lines.append('3. sendall OK')
        f = ssl_sock.makefile('rb')
        resp_bytes = f.read(4096)
        lines.append(f'4. read OK ({len(resp_bytes)} bytes)')
        lines.append(resp_bytes[:500].decode('utf-8', errors='replace'))
    except ssl.SSLError as e:
        lines.append(f'FAILED SSLError lib={getattr(e,"library","?")} reason={getattr(e,"reason","?")} args={e.args}')
    except Exception as e:
        lines.append(f'FAILED: {type(e).__name__}: {e}')
    finally:
        if ssl_sock:
            try: ssl_sock.close()
            except: pass
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}


@app.route('/run-test3')
def run_test3():
    """Usa http.client.HTTPSConnection com _make_ctx2"""
    soap = b'<?xml version="1.0" encoding="UTF-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="http://servicos.portaldasfinancas.gov.pt/faturas/"><soap:Body><ns1:obterVersaoServico><ns1:nif>518651746</ns1:nif></ns1:obterVersaoServico></soap:Body></soap:Envelope>'
    lines = []
    try:
        conn = http.client.HTTPSConnection(AT_HOST, port=700, timeout=15, context=_make_ctx2())
        lines.append('1. HTTPSConnection created')
        conn.request('POST', '/fews/versao', body=soap, headers={
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': '"versao"',
            'Host': AT_HOST,
        })
        lines.append('2. request sent')
        resp = conn.getresponse()
        lines.append(f'3. getresponse OK status={resp.status}')
        data = resp.read()
        conn.close()
        lines.append(f'4. read OK ({len(data)} bytes)')
        lines.append(data[:500].decode('utf-8', errors='replace'))
    except ssl.SSLError as e:
        lines.append(f'FAILED SSLError lib={getattr(e,"library","?")} reason={getattr(e,"reason","?")} args={e.args}')
    except Exception as e:
        lines.append(f'FAILED: {type(e).__name__}: {e}')
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}


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


@app.route('/openssl-test')
def openssl_test():
    """Testa ligação AT com openssl s_client (com SOAP)"""
    import subprocess
    soap_str = ('POST /fews/versao HTTP/1.1\r\n'
                f'Host: {AT_HOST}\r\n'
                'Content-Type: text/xml; charset=utf-8\r\n'
                'SOAPAction: "versao"\r\n'
                'Content-Length: 286\r\n'
                'Connection: close\r\n\r\n'
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
                'xmlns:ns1="http://servicos.portaldasfinancas.gov.pt/faturas/">'
                '<soap:Body><ns1:obterVersaoServico><ns1:nif>518651746</ns1:nif>'
                '</ns1:obterVersaoServico></soap:Body></soap:Envelope>')
    try:
        result = subprocess.run(
            ['openssl', 's_client', '-connect', f'{AT_HOST}:700', '-quiet'],
            input=soap_str.encode(), capture_output=True, timeout=20
        )
        out = result.stdout.decode('utf-8', errors='replace')
        err = result.stderr.decode('utf-8', errors='replace')
        return f'RC={result.returncode}\nSTDOUT:\n{out[:1000]}\nSTDERR:\n{err[:500]}', 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        return f'error: {e}', 200, {'Content-Type': 'text/plain'}


@app.route('/curl-test')
def curl_test():
    """Testa ligação AT usando curl como subprocess"""
    import subprocess
    soap = '<?xml version="1.0" encoding="UTF-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="http://servicos.portaldasfinancas.gov.pt/faturas/"><soap:Body><ns1:obterVersaoServico><ns1:nif>518651746</ns1:nif></ns1:obterVersaoServico></soap:Body></soap:Envelope>'
    url = f'https://{AT_HOST}:700/fews/versao'
    try:
        result = subprocess.run(
            ['curl', '-v', '--max-time', '20', '-X', 'POST', url,
             '-H', 'Content-Type: text/xml; charset=utf-8',
             '-H', 'SOAPAction: versao',
             '-d', soap],
            capture_output=True, timeout=25
        )
        out = result.stdout.decode('utf-8', errors='replace')
        err = result.stderr.decode('utf-8', errors='replace')
        return f'RC={result.returncode}\nSTDOUT:\n{out}\n\nSTDERR:\n{err}', 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        return f'subprocess error: {e}', 200, {'Content-Type': 'text/plain'}


@app.route('/version')
def version():
    import sys
    return f'Python {sys.version}\nOpenSSL {ssl.OPENSSL_VERSION}', 200, {'Content-Type': 'text/plain'}


@app.route('/health')
def health():
    return 'OK'


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
