"""Web UI immune test (split-brain/Tor-C follow-up, 2026-05-30).

Auto-runs scripts/ui_lint.py against the live Web UI so a future refactor that
breaks a rarely-opened page (dead `moFetch` helper, stale element id, dead
/api endpoint -- the classes the Web UI v2 extraction left behind) fails the
suite instead of rotting in production. If `test_no_ui_breakage` fails, run
`python scripts/ui_lint.py` for the per-file detail.

The remaining tests prove the lint's detection actually fires -- a linter that
silently passes everything is worse than none.
"""
import importlib.util
import os

_LINT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "ui_lint.py"
)
_spec = importlib.util.spec_from_file_location("ui_lint", _LINT_PATH)
ui_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui_lint)


def test_no_ui_breakage():
    issues = ui_lint.run_lint()
    assert issues == [], "Web UI lint found issues:\n" + "\n".join(
        f"  {n} [{k}] {d}" for n, k, d in issues
    )


def test_lint_detects_dead_helper():
    # moFetch used but not defined -> flagged; defining it (profile.js alias) -> ok
    assert ui_lint._MOFETCH_USE.search("moFetch('/api/x')")
    assert not ui_lint._MOFETCH_DEF.search("moFetch('/api/x')")
    assert ui_lint._MOFETCH_DEF.search("const moFetch = (u, o) => MariaUI.apiFetch(u, o);")


def test_lint_counts_created_ids_to_avoid_false_positive():
    # getElementById ref is detected...
    assert ui_lint._js_id_refs("document.getElementById('ghost')") == {"ghost"}
    # ...but a `.id = 'x'` assignment counts as created (the chat.js typingIndicator case),
    # so a dynamically-built element is not falsely flagged as stale.
    assert "typingIndicator" in ui_lint._js_created_ids("ind.id = 'typingIndicator';")


def test_lint_detects_dead_endpoint():
    assert not ui_lint._url_known("/api/does-not-exist", {"/api/status"})
    assert ui_lint._url_known("/api/status/full", {"/api/status"})


def _blueprint_fixture(tmp_path, monkeypatch, *, app=None, routes=None, url='/api/voice/transcribe'):
    ui = tmp_path / 'maria_ui'
    js = ui / 'static' / 'js'
    templates = ui / 'templates'
    js.mkdir(parents=True)
    templates.mkdir()
    (templates / 'base.html').write_text('')
    (js / 'voice.js').write_text("fetch(" + repr(url) + ")")
    (ui / 'app.py').write_text(app or '''from maria_ui.voice_routes import create_voice_blueprint
raise RuntimeError('lint must never execute this app')
app.register_blueprint(create_voice_blueprint(authenticated))
''')
    path = ui / 'voice_routes.py'
    path.write_text(routes or '''from flask import Blueprint

def create_voice_blueprint(authenticated):
    voice = Blueprint('voice', __name__)
    @voice.post('/api/voice/transcribe')
    def transcribe():
        return 'ok'
    return voice
''')
    monkeypatch.setattr(ui_lint,'JS_DIR',str(js))
    monkeypatch.setattr(ui_lint,'TPL_DIR',str(templates))
    monkeypatch.setattr(ui_lint,'APP_PY',str(ui / 'app.py'))
    return path


def test_lint_accepts_registered_factory_blueprint_without_import(tmp_path,monkeypatch):
    _blueprint_fixture(tmp_path,monkeypatch)
    assert ui_lint.run_lint() == []


def test_lint_rejects_typo_in_blueprint_endpoint(tmp_path,monkeypatch):
    _blueprint_fixture(tmp_path,monkeypatch,url='/api/voice/trancribe')
    assert ui_lint.run_lint() == [('voice.js','C:dead-endpoint','/api/voice/trancribe has no registered route')]


def test_imported_but_unregistered_blueprint_does_not_hide_missing_endpoint(tmp_path,monkeypatch):
    _blueprint_fixture(tmp_path,monkeypatch,app='from maria_ui.voice_routes import create_voice_blueprint\n')
    assert any(kind=='C:dead-endpoint' for _,kind,_ in ui_lint.run_lint())


def test_removing_actual_route_is_discriminating(tmp_path,monkeypatch):
    path = _blueprint_fixture(tmp_path,monkeypatch)
    assert ui_lint.run_lint() == []
    # A real route mutation must fail, not a blanket /api/voice allowlist.
    path.write_text(path.read_text().replace("@voice.post('/api/voice/transcribe')", "@voice.post('/api/voice/removed')"))
    assert ui_lint.run_lint() == [('voice.js','C:dead-endpoint','/api/voice/transcribe has no registered route')]


def test_unregistered_sibling_factory_with_same_variable_name_is_not_counted(tmp_path,monkeypatch):
    routes='''from flask import Blueprint

def create_voice_blueprint(authenticated):
    voice = Blueprint('voice', __name__)
    @voice.get('/api/voice/status')
    def status(): return 'ok'
    return voice

def unused_blueprint():
    voice = Blueprint('unused', __name__)
    @voice.post('/api/voice/transcribe')
    def transcribe(): return 'ok'
    return voice
'''
    _blueprint_fixture(tmp_path,monkeypatch,routes=routes)
    assert any(kind=='C:dead-endpoint' for _,kind,_ in ui_lint.run_lint())


def test_only_returned_blueprint_and_registration_prefix_are_counted(tmp_path,monkeypatch):
    routes='''from flask import Blueprint as BP

def create_voice_blueprint(authenticated):
    voice = BP('voice', __name__, url_prefix='/unused-default')
    ignored = BP('ignored', __name__)
    @voice.route('/transcribe', methods=['POST'])
    def transcribe(): return 'ok'
    @ignored.post('/ghost')
    def ghost(): return 'ok'
    return voice
'''
    app='''from maria_ui.voice_routes import create_voice_blueprint as build
bound = build(authenticated)
app.register_blueprint(bound, url_prefix='/api/voice')
'''
    _blueprint_fixture(tmp_path,monkeypatch,app=app,routes=routes)
    assert ui_lint.run_lint() == []
    (tmp_path/'maria_ui'/'static'/'js'/'voice.js').write_text("fetch('/api/voice/ghost')")
    assert any(kind=='C:dead-endpoint' for _,kind,_ in ui_lint.run_lint())


def test_module_blueprint_instance_is_supported(tmp_path,monkeypatch):
    routes='''import flask as f
voice = f.Blueprint('voice', __name__, url_prefix='/api/voice')
@voice.post('/transcribe')
def transcribe(): return 'ok'
'''
    app='from maria_ui.voice_routes import voice as bp\napp.register_blueprint(bp)\n'
    _blueprint_fixture(tmp_path,monkeypatch,app=app,routes=routes)
    assert ui_lint.run_lint() == []


def test_missing_blueprint_source_reports_lint_failure_not_fake_routes(tmp_path,monkeypatch):
    import pytest
    path=_blueprint_fixture(tmp_path,monkeypatch)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        ui_lint.run_lint()


def test_module_instance_does_not_adopt_shadowing_factory_routes(tmp_path,monkeypatch):
    routes='''from flask import Blueprint
voice = Blueprint('voice', __name__)
@voice.get('/api/voice/status')
def status(): return 'ok'

def unused_factory():
    voice = Blueprint('unused', __name__)
    @voice.post('/api/voice/transcribe')
    def transcribe(): return 'ok'
    return voice
'''
    app='from maria_ui.voice_routes import voice\napp.register_blueprint(voice)\n'
    _blueprint_fixture(tmp_path,monkeypatch,app=app,routes=routes)
    assert any(kind=='C:dead-endpoint' for _,kind,_ in ui_lint.run_lint())
