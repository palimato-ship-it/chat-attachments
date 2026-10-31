"""Opt-in per-chat policies and portable, one-shot timer runs."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import sys
import time

from history import AttachmentError
from service import Service, private_dir, write_json
from timing import assert_idle, period_seconds
from locking import exclusive

LABEL = 'peli.chat-attachments.timer'
INTERVAL = 60


class Scheduler:
    def __init__(self, service=None):
        self.service = service or Service()
        self.root = self.service.home / 'chat-attachments'
        self.policies = self.root / 'schedules'

    def policy_path(self, thread_id):
        # Reuse the exact UUID validation without reading any unselected chat.
        import re
        if not isinstance(thread_id, str) or not re.fullmatch(r'[0-9a-fA-F-]{36}', thread_id):
            raise AttachmentError('invalid_thread', 'Use the exact selected Codex chat ID.')
        return self.policies / (thread_id + '.json')

    @contextmanager
    def lock(self, thread_id):
        path = self.policy_path(thread_id)
        private_dir(self.policies)
        with path.with_suffix('.lock').open('a+b') as stream:
            os.chmod(path.with_suffix('.lock'), 0o600)
            with exclusive(stream):
                yield path

    def configure(self, thread_id, period='2 days', enabled=True, approved=False):
        if approved is not True:
            raise AttachmentError('approval_required', 'Enable or change this chat’s automatic conversion only on the user’s explicit request.')
        seconds = period_seconds(period)
        _, _, _, _, _, project, _ = self.service._load(thread_id)
        with self.lock(thread_id) as path:
            previous = json.loads(path.read_text()) if path.is_file() else {}
            policy = {'version': 1, 'thread_id': thread_id, 'project': str(project),
                      'enabled': bool(enabled), 'period': period.strip(), 'age_seconds': seconds,
                      'jpeg_quality': 20, 'dimension_scale': 0.5,
                      'authorized_at': time.time(), 'updated_at': time.time()}
            if previous.get('last_run'):
                policy['last_run'] = previous['last_run']
            write_json(path, policy)
        return self.status(thread_id)

    def status(self, thread_id):
        path = self.policy_path(thread_id)
        if not path.is_file():
            return {'thread_id': thread_id, 'enabled': False, 'period': '2 days',
                    'age_seconds': 172800, 'configured': False, 'poll_seconds': INTERVAL}
        policy = json.loads(path.read_text())
        return {**policy, 'configured': True, 'poll_seconds': INTERVAL,
                'idle_requirement': 'No unfinished turns and at least two minutes without a history write.',
                'background_service': str(self.root / 'background.json')}

    def run_once(self, now=None):
        now = time.time() if now is None else now
        private_dir(self.root)
        # launchd coalesces runs; this also prevents CLI/MCP overlap.
        with (self.root / 'timer.lock').open('a+b') as guard:
            os.chmod(self.root / 'timer.lock', 0o600)
            try:
                with exclusive(guard, blocking=False):
                    return self._run_policies(now)
            except BlockingIOError:
                return {'status': 'busy', 'chats': []}

    def _run_policies(self, now):
        outcomes = []
        for path in sorted(self.policies.glob('*.json')) if self.policies.is_dir() else []:
            thread_id = path.stem
            try:
                with self.lock(thread_id) as locked:
                    policy = json.loads(locked.read_text())
                    if not policy.get('enabled'):
                        continue
                    if policy.get('thread_id') != thread_id or policy.get('age_seconds') != period_seconds(policy.get('period')):
                        raise AttachmentError('invalid_policy', 'The saved timer policy needs to be set again.')
                    try:
                        log, _, _, records, _, project, _ = self.service._load(thread_id)
                        if str(project) != policy['project']:
                            raise AttachmentError('project_changed', 'The chat moved to another project; set its timer again.')
                        backups = project / 'attachments' / '.chat-attachments' / thread_id / 'backups'
                        for operation in backups.glob('*/operation.json') if backups.is_dir() else []:
                            if json.loads(operation.read_text()).get('status') in ('prepared', 'writing', 'needs_recovery'):
                                raise AttachmentError('recovery_required', 'A previous conversion needs inspection; the timer was paused.')
                        assert_idle(self.service.home, thread_id, log, records, now)
                        prepared = self.service.plan_conversion(thread_id, cutoff=now - policy['age_seconds'])
                        if not prepared['selected_images']:
                            outcome = {'status': 'no_op', 'converted_images': 0}
                            (self.service.plans / (prepared['plan_id'] + '.json')).unlink()
                        else:
                            plan_path = self.service.plans / (prepared['plan_id'] + '.json')
                            plan = json.loads(plan_path.read_text())
                            plan['automatic'] = True
                            write_json(plan_path, plan)
                            outcome = self.service.apply_conversion(prepared['plan_id'], approved=True)
                            plan_path.unlink()
                    except AttachmentError as error:
                        deferred = error.code in ('chat_active', 'activity_unknown', 'conversion_busy', 'history_busy', 'history_changed')
                        outcome = {'status': 'deferred' if deferred else 'paused_error', 'code': error.code}
                        if not deferred:
                            policy['enabled'] = False
                    except Exception as error:
                        # An interrupted write may need recovery. Never retry it automatically.
                        outcome = {'status': 'paused_error', 'code': 'operation_failed', 'exception_type': type(error).__name__}
                        policy['enabled'] = False
                    policy['last_run'] = {'checked_at': now, **outcome}
                    write_json(locked, policy)
                    outcomes.append({'thread_id': thread_id, **outcome})
            except (AttachmentError, OSError, ValueError) as error:
                outcomes.append({'thread_id': thread_id, 'status': 'policy_error',
                                 'code': error.code if isinstance(error, AttachmentError) else 'policy_unreadable'})
        result = {'status': 'complete', 'checked_at': now, 'chats': outcomes}
        write_json(self.root / 'last-run.json', result)
        return result


from background import install_agent, stop_agent


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('run', 'install', 'stop'))
    parser.add_argument('--home')
    args = parser.parse_args()
    action = args.action
    try:
        result = Scheduler(Service(args.home)).run_once() if action == 'run' else install_agent(args.home) if action == 'install' else stop_agent(args.home)
        # LaunchAgent runs retain a bounded last-run.json, not growing transcript logs.
        if action != 'run':
            print(json.dumps(result))
    except Exception as error:
        print('Chat Attachments timer failed: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
