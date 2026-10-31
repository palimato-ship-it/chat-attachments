"""Native user-level scheduler definitions; never installs on another host."""
from datetime import datetime
from pathlib import Path, PureWindowsPath
import getpass
import json
import os
import plistlib
import subprocess
import sys
import xml.etree.ElementTree as ET

from history import AttachmentError
from service import Service, private_dir, private_write, write_json

LABEL = 'peli.chat-attachments.timer'
INTERVAL = 60


def systemd_quote(value):
    if '\n' in value or '\r' in value:
        raise AttachmentError('invalid_path', 'Background executable paths must not contain newlines.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def configuration(platform, home, user_home, python, script, account=None):
    """Return definitions and argument arrays, independently of the host OS."""
    argv = [str(python), str(script), 'run', '--home', str(home)]
    root = Path(home) / 'chat-attachments'
    if platform == 'darwin':
        path = Path(user_home) / 'Library/LaunchAgents' / (LABEL + '.plist')
        domain = 'gui/' + str(os.getuid())
        value = {'Label': LABEL, 'ProgramArguments': argv,
                 'EnvironmentVariables': {'PYTHONDONTWRITEBYTECODE': '1'},
                 'StartInterval': INTERVAL, 'RunAtLoad': True, 'ProcessType': 'Background',
                 'StandardOutPath': str(root / 'timer.stdout.log'),
                 'StandardErrorPath': str(root / 'timer.stderr.log')}
        return {'platform': platform, 'files': {str(path): plistlib.dumps(value)},
                'before_install': [['launchctl', 'bootout', domain + '/' + LABEL]],
                'install': [['launchctl', 'bootstrap', domain, str(path)]],
                'query': ['launchctl', 'print', domain + '/' + LABEL],
                'stop': [['launchctl', 'bootout', domain + '/' + LABEL]]}
    if platform == 'win32':
        path = str(PureWindowsPath(home) / 'chat-attachments' / 'timer-task.xml')
        ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
        ET.register_namespace('', ns)
        def node(parent, name, text=None, **attrs):
            child = ET.SubElement(parent, '{' + ns + '}' + name, attrs)
            child.text = text
            return child
        task = ET.Element('{' + ns + '}Task', {'version': '1.2'})
        registration = node(task, 'RegistrationInfo')
        node(registration, 'Description', 'Local, opt-in chat image previews; full originals preserved.')
        triggers = node(task, 'Triggers')
        trigger = node(triggers, 'TimeTrigger')
        repetition = node(trigger, 'Repetition')
        node(repetition, 'Interval', 'PT1M')
        node(repetition, 'StopAtDurationEnd', 'false')
        node(trigger, 'StartBoundary', datetime.now().replace(microsecond=0).isoformat())
        node(trigger, 'Enabled', 'true')
        principals = node(task, 'Principals')
        principal = node(principals, 'Principal', id='Author')
        node(principal, 'UserId', account or getpass.getuser())
        node(principal, 'LogonType', 'InteractiveToken')
        node(principal, 'RunLevel', 'LeastPrivilege')
        settings = node(task, 'Settings')
        for key, value in (('MultipleInstancesPolicy', 'IgnoreNew'), ('DisallowStartIfOnBatteries', 'false'),
                           ('StopIfGoingOnBatteries', 'false'), ('StartWhenAvailable', 'true'),
                           ('Enabled', 'true'), ('ExecutionTimeLimit', 'PT0S')):
            node(settings, key, value)
        actions = node(task, 'Actions', Context='Author')
        action = node(actions, 'Exec')
        node(action, 'Command', str(python))
        node(action, 'Arguments', subprocess.list2cmdline(argv[1:]))
        return {'platform': platform, 'files': {path: ET.tostring(task, encoding='utf-16', xml_declaration=True)},
                'before_install': [],
                'install': [['schtasks.exe', '/Create', '/TN', LABEL, '/XML', path, '/F'],
                            ['schtasks.exe', '/Run', '/TN', LABEL]],
                'query': ['schtasks.exe', '/Query', '/TN', LABEL, '/XML'],
                'stop': [['schtasks.exe', '/Delete', '/TN', LABEL, '/F']]}
    if platform.startswith('linux'):
        directory = Path(user_home) / '.config/systemd/user'
        service = directory / (LABEL + '.service')
        timer = directory / (LABEL + '.timer')
        text = ('[Unit]\nDescription=Local Chat Attachments conversion\n\n[Service]\nType=oneshot\n'
                'Environment=PYTHONDONTWRITEBYTECODE=1\nExecStart=' + ' '.join(systemd_quote(v) for v in argv) +
                '\nTimeoutStartSec=infinity\nNice=10\n')
        timer_text = ('[Unit]\nDescription=Check opted-in chat images every minute\n\n[Timer]\n'
                      'OnActiveSec=1s\nOnUnitInactiveSec=60s\nAccuracySec=1s\n\n[Install]\nWantedBy=timers.target\n')
        return {'platform': platform, 'files': {str(service): text.encode(), str(timer): timer_text.encode()},
                'before_install': [],
                'install': [['systemctl', '--user', 'daemon-reload'],
                            ['systemctl', '--user', 'enable', '--now', timer.name]],
                'query': ['systemctl', '--user', 'is-active', timer.name],
                'stop': [['systemctl', '--user', 'disable', '--now', timer.name]]}
    raise AttachmentError('unsupported_platform', 'Supported timer platforms are macOS, Windows and Linux with a systemd user session.')


def install_agent(home=None):
    service = Service(home)
    root = service.home / 'chat-attachments'
    private_dir(root)
    executable = Path(sys.executable)
    if sys.platform == 'win32' and executable.with_name('pythonw.exe').is_file():
        executable = executable.with_name('pythonw.exe')
    account = getpass.getuser()
    if sys.platform == 'win32' and os.environ.get('USERDOMAIN'):
        account = os.environ['USERDOMAIN'] + '\\' + account
    config = configuration(sys.platform, service.home, Path.home(), executable,
                           Path(__file__).with_name('scheduler.py'), account)
    for name, data in config['files'].items():
        private_write(Path(name), data)
    if sys.platform == 'darwin':
        for name in ('timer.stdout.log', 'timer.stderr.log'):
            path = root / name
            path.touch(mode=0o600, exist_ok=True)
            os.chmod(path, 0o600)
    for command in config['before_install']:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for command in config['install']:
        subprocess.run(command, check=True, capture_output=True)
    state = {'installed': True, 'platform': sys.platform, 'label': LABEL,
             'files': list(config['files']), 'query': config['query'], 'stop': config['stop'],
             'poll_seconds': INTERVAL, 'installed_at': datetime.now().astimezone().isoformat(),
             'enabled_chats': 'Only explicitly configured chats; installation enables none.'}
    write_json(root / 'background.json', state)
    return state


def stop_agent(home=None):
    service = Service(home)
    path = service.home / 'chat-attachments/background.json'
    if not path.is_file():
        return {'installed': False, 'policies_preserved': True}
    state = json.loads(path.read_text())
    if state['platform'] != sys.platform:
        raise AttachmentError('platform_changed', 'Reinstall the timer on this operating system first.')
    for command in state['stop']:
        subprocess.run(command, check=True, capture_output=True)
    for name in state['files']:
        Path(name).unlink(missing_ok=True)
    if sys.platform.startswith('linux'):
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, capture_output=True)
    write_json(path, {**state, 'installed': False})
    return {'installed': False, 'policies_preserved': True}
