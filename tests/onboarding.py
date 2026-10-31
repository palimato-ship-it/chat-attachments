"""Three approved integration cases; each named case is executed once."""
from pathlib import Path
import argparse
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'plugins/chat-attachments'
RESULTS = ROOT / 'test-results/onboarding'
SID = '11111111-2222-4333-8444-555555555555'
OTHER = '99999999-2222-4333-8444-555555555555'
sys.path.insert(0, str(PACKAGE))


def mcp(python, home, calls):
    requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'onboarding-fixture', 'version': '1'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, *calls]
    process = subprocess.run([str(python), str(PACKAGE / 'server.py')],
        input=''.join(json.dumps(r)+'\n' for r in requests), text=True, capture_output=True,
        env={**os.environ, 'CODEX_HOME': str(home), 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=60, check=True)
    return [json.loads(line) for line in process.stdout.splitlines()]


def menu():
    root = Path(tempfile.mkdtemp(prefix='chat-attachments-menu-'))
    manifest = json.loads((PACKAGE / '.codex-plugin/plugin.json').read_text())
    hooks = json.loads((PACKAGE / manifest['hooks']).read_text())
    handler = hooks['hooks']['SessionStart'][0]['hooks'][0]
    command = shlex.split(handler['command'].replace('${PLUGIN_ROOT}', str(PACKAGE)))
    # Use the configured hook command with auto-setup explicitly opted out, so
    # this menu-only scenario cannot install a service or access real chat data.
    result = subprocess.run(command, input=json.dumps({'hook_event_name': 'SessionStart', 'source': 'startup', 'session_id': SID}),
        text=True, capture_output=True, env={**os.environ, 'CODEX_HOME': str(root), 'CHAT_ATTACHMENTS_AUTO_SETUP': '0'}, check=True, timeout=20)
    output = json.loads(result.stdout)['hookSpecificOutput']
    assert output['hookEventName'] == 'SessionStart'
    context = output['additionalContext']
    assert 'first' in context and 'user-visible response' in context
    assert '1. Scan this chat' in context and '8. Set up Chat Attachments' in context
    assert 'Set up Chat Attachments' in manifest['interface']['defaultPrompt']
    assert not (root / 'chat-attachments/setup.json').exists()
    return {'menu_and_setup_supplied': True, 'manifest_hook_wired': True,
            'history_untouched': True, 'actual_desktop_rendering_tested': False}


def native_stub(original, calls):
    def run(command, *args, **kwargs):
        if len(command) > 2 and str(command[1]) == str(PACKAGE / 'scheduler.py') and command[2] == 'install':
            calls.append(list(map(str, command)))
            return subprocess.CompletedProcess(command, 0, stdout=b'{"installed":true}', stderr=b'')
        return original(command, *args, **kwargs)
    return run


def clean_worker(root):
    import runtime
    from server import invoke
    home = root / 'home'; home.mkdir()
    os.environ['CODEX_HOME'] = str(home)
    assert importlib.util.find_spec('PIL') is None, 'The base fixture must not contain Pillow.'
    before = mcp(sys.executable, home, [{'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}])
    names = {t['name'] for t in next(r for r in before if r.get('id') == 2)['result']['tools']}
    assert {'setup_runtime', 'setup_status'} <= names
    calls = []; original = subprocess.run
    with patch('runtime.subprocess.run', side_effect=native_stub(original, calls)):
        setup = invoke(None, 'setup_runtime', {'approved': True})
    assert setup['ready'] and len(calls) == 1
    after = mcp(sys.executable, home, [{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{
        'name':'automatic_status','arguments':{'thread_id':SID}}}])
    reply = next(r for r in after if r.get('id') == 2)['result']
    assert not reply.get('isError'), reply
    value = json.loads(reply['content'][0]['text'])
    assert value['enabled'] is False and value['thread_id'] == SID
    # Runtime can import the actual installed Pillow, independently of the base.
    loaded = original([str(runtime.interpreter()), '-c', 'from PIL import Image; print(Image.__name__)'],
                      capture_output=True, text=True, check=True)
    assert loaded.stdout.strip() == 'PIL.Image'
    return {'clean_base_without_pillow': True, 'pillow_installed': True,
            'mcp_setup_and_timer_tools_work': True, 'native_timer_registration': 'stubbed; requested once'}


def firstuse():
    root = Path(tempfile.mkdtemp(prefix='chat-attachments-firstuse-'))
    base = root / 'base'
    subprocess.run([sys.executable, '-m', 'venv', str(base)], capture_output=True, check=True)
    python = base / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    process = subprocess.run([str(python), str(Path(__file__).resolve()), '_clean_worker', str(root)],
                             capture_output=True, text=True, check=True, timeout=300)
    result = json.loads(process.stdout)
    (RESULTS / 'fixture.json').write_text(json.dumps({'root': str(root), 'base_python': str(python)}))
    return result


def repeat():
    fixture = json.loads((RESULTS / 'fixture.json').read_text())
    process = subprocess.run([fixture['base_python'], str(Path(__file__).resolve()), '_repeat_worker', fixture['root']],
                             capture_output=True, text=True, check=True, timeout=180)
    return json.loads(process.stdout)


def repeat_worker(root):
    import runtime
    from server import invoke
    from startup import on_start
    home = root / 'home'; os.environ['CODEX_HOME'] = str(home)
    policies = home / 'chat-attachments/schedules'; policies.mkdir()
    originals = {}
    for thread, enabled, period, age in ((SID, True, '5 minutes', 300), (OTHER, False, '7 days', 604800)):
        path = policies / (thread + '.json')
        path.write_text(json.dumps({'thread_id':thread,'enabled':enabled,'period':period,'age_seconds':age}))
        originals[path] = path.read_bytes()
    calls = []; original = subprocess.run
    with patch('runtime.subprocess.run', side_effect=native_stub(original, calls)):
        result = invoke(None, 'setup_runtime', {'approved':True})
        assert result['ready'] and len(calls) == 1
        # A later new chat reuses setup rather than reinstalling/re-registering.
        context = on_start({'source':'startup','session_id':OTHER})['hookSpecificOutput']['additionalContext']
        assert '1. Scan this chat' in context and len(calls) == 1
        assert on_start({'source':'resume','session_id':OTHER}) == {}
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    return {'existing_enabled_and_disabled_policies_preserved': True,
            'custom_periods_preserved': True, 'later_chat_reused_setup': True, 'resume_menu_not_repeated': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('case', choices=('menu','firstuse','repeat','_clean_worker','_repeat_worker'))
    parser.add_argument('root', nargs='?')
    args = parser.parse_args()
    if args.case.startswith('_'):
        result = clean_worker(Path(args.root)) if args.case == '_clean_worker' else repeat_worker(Path(args.root))
        print(json.dumps(result))
    else:
        RESULTS.mkdir(parents=True, exist_ok=True)
        result = {'case':args.case,'passed':True, **globals()[args.case]()}
        (RESULTS / (args.case + '.json')).write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
