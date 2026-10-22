"""First-chat contract using real Flask/SocketIO/brain and a loopback Ollama stub.

No product import occurs in the pytest process. The child uses copied sources,
an empty HOME, synthetic credentials and no inherited integration configuration.
Run directly with --standalone to check a core-only environment without pytest.
This verifies protocol/dependency closure, not real-model quality or latency.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def _history_digest(messages):
    # Memory and disk entries receive separate timestamps. The persistence
    # contract here is ordered roles and complete text, not clock equality.
    content = [{'role': m['role'], 'content': m['content']} for m in messages]
    return hashlib.sha256(json.dumps(content, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def _child(mode):
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    calls, violations = [], []

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            assert 0 < length <= 256 * 1024
            payload = json.loads(self.rfile.read(length))
            assert self.path == '/api/chat'
            assert payload['model'] == 'quickstart-fixture'
            calls.append(payload)
            body = json.dumps({
                'model': payload['model'], 'done': True,
                'message': {'role': 'assistant',
                            'content': 'Synthetic complete reply ' + str(len(calls))},
            }).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    os.environ['OLLAMA_HOST'] = 'http://127.0.0.1:' + str(server.server_port)
    connect = socket.socket.connect

    def loopback_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', '::1'}:
            violations.append('external_connect')
            raise AssertionError('External network is forbidden in this fixture')
        return connect(sock, address)

    def no_process(*args, **kwargs):
        # Config's optional Tailscale discovery may attempt a subprocess. Never
        # execute it or inherit the machine's identity/network configuration.
        raise FileNotFoundError('External processes disabled in fixture')

    socket.socket.connect = loopback_only
    subprocess.run = no_process
    subprocess.Popen = no_process
    sys.path.insert(0, str(Path.cwd()))
    client = None
    try:
        import maria_ui.app as ui
        import agent_core.llm.kritaqo_work_service as work_service

        def forbidden_work_service(*args, **kwargs):
            violations.append('work_service')
            raise AssertionError('First-chat mode must not initialize work service')

        work_service.get_work_service = forbidden_work_service

        assert ui.chat_only_mode()
        assert ui.OLLAMA_AVAILABLE
        http = ui.app.test_client()
        assert http.get('/api/chat/history').status_code in {302, 401}
        unauthenticated = ui.socketio.test_client(ui.app)
        assert not unauthenticated.is_connected()
        wrong = http.post('/login', data={'pin': 'wrong-fixture-pin'})
        assert wrong.status_code == 200
        assert http.get('/api/chat/history').status_code in {302, 401}
        assert http.post('/login', data={'pin': 'fixture-pin'}).status_code == 302
        page = http.get('/').get_data(as_text=True)
        assert 'Lokalny czat' in page and 'id="chatInput"' in page
        assert all(fragment not in page for fragment in (
            'id="workProject"', 'id="voiceMic"', 'href="/tasks"',
            'js/chat_work.js', 'js/chat_voice.js',
        ))

        def history():
            response = http.get('/api/chat/history')
            assert response.status_code == 200
            return response.get_json()['messages']

        if mode == 'history':
            messages = history()
            assert len(messages) == 6
            assert ui._maria_brain is None
            assert not calls
        else:
            assert history() == []
            client = ui.socketio.test_client(ui.app, flask_test_client=http)
            assert client.is_connected()
            client.get_received()

            def turn(text, nonce):
                client.emit('chat_message', {'message': text, 'request_id': nonce})
                responses = [e['args'][0] for e in client.get_received()
                             if e['name'] == 'chat_response']
                assert len(responses) == 1
                result = responses[0]
                assert result['success'] is True and result.get('fallback') is False
                assert result['request_id'] == nonce
                receipt = http.get('/api/chat/turn/' + nonce)
                assert receipt.status_code == 200
                assert receipt.get_json()['state'] == 'completed'
                return result

            reply = turn('Powiedz krótkie powitanie.', '1' * 32)
            assert 'Synthetic complete reply 1' in json.dumps(reply)
            assert len(calls) == 1
            replay = turn('Powiedz krótkie powitanie.', '1' * 32)
            assert replay['replayed'] is True and len(calls) == 1
            assert ui._maria_brain._chat_backend is None

            before = {str(p): p.read_bytes() for p in Path('meta_data').glob('*goal*')
                      if p.is_file()}
            turn('Uruchom analizę projektu i utwórz zadanie.', '2' * 32)
            after = {str(p): p.read_bytes() for p in Path('meta_data').glob('*goal*')
                     if p.is_file()}
            assert before == after and len(calls) == 1
            assert not list(Path('meta_data').rglob('kritaqo_tools*'))

            poem = turn('Napisz krótki wiersz o lesie.', '3' * 32)
            assert 'Synthetic complete reply 2' in json.dumps(poem)
            assert len(calls) == 2
            messages = history()
            assert len(messages) == 6
            assert any(m['content'] == 'Synthetic complete reply 2' for m in messages)
        assert not violations
        print('QUICKSTART_RESULT ' + json.dumps({
            'messages': len(messages), 'historyDigest': _history_digest(messages),
            'modelCalls': len(calls), 'externalConnections': len(violations),
        }))
    finally:
        if client is not None and client.is_connected():
            client.disconnect()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_core_first_chat_and_restart_without_model_or_work(tmp_path):
    source = Path(__file__).resolve().parents[2]
    isolated = tmp_path / 'source'
    isolated.mkdir()
    # Only source packages; no .env, runtime, venv, Git metadata or test caches.
    for package in ('agent_core', 'maria_core', 'maria_ui', 'models'):
        shutil.copytree(source / package, isolated / package,
                        ignore=shutil.ignore_patterns('tests', '__pycache__',
                                                     'data', '*.pyc'))
    home = tmp_path / 'home'
    home.mkdir()
    environment = {
        'PATH': os.defpath, 'HOME': str(home), 'USERPROFILE': str(home),
        'XDG_CONFIG_HOME': str(home / 'config'),
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(isolated),
        'MARIA_PIN': 'fixture-pin', 'MARIA_SECRET_KEY': 'fixture-session-key',
        'MARIA_API_TOKEN': 'fixture-api-token', 'MARIA_CHAT_ONLY': '1',
        'MARIA_CHAT_BACKEND': 'codex', 'MARIA_CODEX_MODEL': 'must-not-run',
        'MARIA_CHAT_MODEL': 'quickstart-fixture', 'MARIA_CHAT_RATE_LIMIT': '60',
        'MARIA_CORS_ORIGINS': 'http://localhost', 'CHAT_FAST_CONTEXT': '1',
        'MARIA_BACKGROUND_REASONING': '0', 'MARIA_WARMUP': '0',
        'MARIA_TELEGRAM_INTEGRATION': '0', 'MARIA_CONDUCTOR_INTEGRATION': '0',
    }

    def run(mode, timeout):
        completed = subprocess.run(
            [sys.executable, '-B', str(Path(__file__).resolve()),
             '--quickstart-child', mode], cwd=isolated, env=environment,
            capture_output=True, text=True, timeout=timeout,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return json.loads(next(line.removeprefix('QUICKSTART_RESULT ')
                               for line in completed.stdout.splitlines()
                               if line.startswith('QUICKSTART_RESULT ')))

    first = run('chat', 25)
    restored = run('history', 15)
    assert first['modelCalls'] == 2 and restored['modelCalls'] == 0
    assert first['historyDigest'] == restored['historyDigest']


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--quickstart-child':
        _child(sys.argv[2])
    elif sys.argv[1:] == ['--standalone']:
        with tempfile.TemporaryDirectory(prefix='maria-quickstart-') as directory:
            test_core_first_chat_and_restart_without_model_or_work(Path(directory))
        print('PASS: isolated core first chat and persisted restart')
    else:
        raise SystemExit('Use pytest or --standalone')
