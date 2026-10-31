"""Local attachment plans, conversion and explicitly enabled per-chat timers."""
from pathlib import Path
import base64
import json
import mimetypes
import os
import sqlite3
import time
import uuid

from history import AttachmentError, existing_index, inventory, offsets, read_history, session, state_path, translated
from media import DATA_URI, IMAGE_MIMES, blobs, decode, digest, dimensions, raw_blob
from timing import assert_idle, eligible
from locking import exclusive
from imaging import jpeg_preview


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise AttachmentError('unsafe_output', 'The attachment storage directory must not be a symbolic link.')
    os.chmod(path, 0o700)


def private_write(path, data):
    private_dir(path.parent)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path, value):
    private_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def attachment_output(project, path):
    root = project / 'attachments'
    if not path.resolve().is_relative_to(root.resolve()):
        raise AttachmentError('unsafe_output', 'Attachment output must remain inside this project’s attachments folder.')
    current = path
    while current != project:
        if current.is_symlink():
            raise AttachmentError('unsafe_output', 'Attachment storage must not traverse symbolic links.')
        current = current.parent
    return path


class Service:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).resolve()
        self.plans = self.home / 'chat-attachments' / 'plans'

    def configure_automatic(self, thread_id, period='2 days', enabled=True, approved=False):
        from scheduler import Scheduler
        return Scheduler(self).configure(thread_id, period, enabled, approved)

    def automatic_status(self, thread_id):
        from scheduler import Scheduler
        return Scheduler(self).status(thread_id)

    def _load(self, thread_id):
        path, raw, lines, records, meta = session(self.home, thread_id)
        project = Path(meta.get('cwd', ''))
        if not project.is_absolute() or not project.is_dir():
            raise AttachmentError('project_unavailable', 'The original project folder is unavailable on this Mac.')
        project = project.resolve()
        attachments = project / 'attachments'
        if attachments.is_symlink() or (attachments.exists() and not attachments.is_dir()):
            raise AttachmentError('unsafe_output', 'The project attachments location is not a regular directory.')
        index = existing_index(project, thread_id)
        return path, raw, lines, records, meta, project, index

    def scan_chat(self, thread_id):
        path, raw, _, records, _, project, index = self._load(thread_id)
        files, refs = inventory(records, index)
        image_files = [v for v in files.values() if v['mime'].startswith('image/')]
        return {
            'thread_id': thread_id, 'project': str(project), 'history_path': str(path),
            'history_bytes': len(raw), 'history_mb': round(len(raw) / 1e6, 4),
            'unique_images': len(image_files),
            'unique_other_embedded_files': len(files) - len(image_files),
            'image_copies': sum(v['copies'] for v in image_files),
            'convertible_images': sum(v['convertible'] for v in files.values()),
            'already_optimized_images': sum(v['status'] == 'already_optimized' for v in image_files),
            'embedded_image_bytes': sum(v['stored_encoded_bytes'] for v in image_files),
            'files': list(files.values()), 'external_files': refs,
            'defaults': {'jpeg_quality': 20, 'dimension_scale': 0.5},
            'read_only': True,
        }

    def plan_conversion(self, thread_id, cutoff=None):
        path, raw, _, records, _, project, index = self._load(thread_id)
        files, _ = inventory(records, index)
        selected = ([v['id'] for v in files.values() if v['convertible']] if cutoff is None
                    else eligible(records, files, cutoff))
        plan_id = uuid.uuid4().hex
        plan = {
            'id': plan_id, 'thread_id': thread_id, 'project': str(project), 'history_path': str(path),
            'prefix_bytes': len(raw), 'prefix_sha256': digest(raw), 'created_at': time.time(),
            'selected': selected, 'jpeg_quality': 20, 'dimension_scale': 0.5,
        }
        write_json(self.plans / (plan_id + '.json'), plan)
        return {'plan_id': plan_id, 'thread_id': thread_id, 'selected_images': len(selected),
                'selected_encoded_bytes': sum(files[key]['stored_encoded_bytes'] for key in selected),
                'jpeg_quality': 20, 'dimension_scale': 0.5, 'approval_required': True,
                'other_file_types': 'inventoried; unchanged by this version'}

    def original_file(self, thread_id, media_id):
        _, _, _, _, _, project, index = self._load(thread_id)
        for original, asset in index['assets'].items():
            if media_id == original or media_id in asset.get('preview_hashes', []):
                path = Path(asset['original'])
                if not path.is_file() or digest(path.read_bytes()) != original:
                    raise AttachmentError('original_unavailable', 'The recorded original is missing or differs from its saved hash.')
                return {'original_id': original, 'path': str(path), 'bytes': path.stat().st_size,
                        'name': asset.get('name', path.name),
                        'instruction': 'Open this file for full detail. Do not re-embed it unless the user requests that.'}
        raise AttachmentError('original_not_indexed', 'This attachment has not been offloaded by the plugin yet.')

    def apply_conversion(self, plan_id, approved=False):
        if approved is not True:
            raise AttachmentError('approval_required', 'Show the conversion plan and obtain the user’s approval first.')
        if not isinstance(plan_id, str) or len(plan_id) != 32 or any(c not in '0123456789abcdef' for c in plan_id):
            raise AttachmentError('invalid_plan', 'Use the plan ID returned by plan_conversion.')
        path = self.plans / (plan_id + '.json')
        if not path.is_file():
            raise AttachmentError('plan_missing', 'Create a conversion plan first.')
        plan = json.loads(path.read_text())
        if time.time() - plan['created_at'] > 3600:
            raise AttachmentError('plan_expired', 'The conversion plan expired; scan and plan again.')
        log, before, lines, records, _, project, index = self._load(plan['thread_id'])
        if str(log) != plan['history_path'] or str(project) != plan['project']:
            raise AttachmentError('plan_changed', 'The selected history or project changed; create a new plan.')
        prefix = before[:plan['prefix_bytes']]
        if digest(prefix) != plan['prefix_sha256']:
            raise AttachmentError('history_changed', 'The approved history prefix changed; scan and plan again.')
        if plan.get('automatic'):
            assert_idle(self.home, plan['thread_id'], log, records)
        if not plan['selected']:
            return {'status': 'no_op', 'converted_images': 0, 'history_bytes': len(before),
                    'reason': 'No unprocessed supported images were selected.'}
        folder = attachment_output(project, project / 'attachments' / '.chat-attachments' / plan['thread_id'])
        private_dir(folder)
        try:
            with (folder / 'conversion.lock').open('a+b') as lock, exclusive(lock, blocking=False):
                return self._convert(plan, log, before, lines, records, project, index, folder)
        except BlockingIOError:
            raise AttachmentError('conversion_busy', 'Another attachment conversion is already running for this chat.') from None

    def _convert(self, plan, log, before, lines, records, project, index, folder):
        selected = set(plan['selected'])
        found = {}
        # Keep only selected originals; other files never enter the conversion map.
        for row in records:
            for mime, data, _, _ in blobs(row.get('payload', {})):
                sha = digest(data)
                if sha in selected:
                    found.setdefault(sha, (mime, data))
        if set(found) != selected:
            raise AttachmentError('attachment_changed', 'A selected attachment is no longer present; create a fresh plan.')
        targets = {}
        for sha, (mime, data) in found.items():
            old = index['assets'].get(sha)
            suffix = {
                'image/png': '.png', 'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/gif': '.gif',
                'image/webp': '.webp', 'image/tiff': '.tiff', 'image/heic': '.heic',
                'image/heif': '.heif', 'image/avif': '.avif', 'image/bmp': '.bmp', 'image/x-icon': '.ico',
            }[mime]
            name = old.get('name') if old else 'attachment-' + sha[:16] + suffix
            name = Path(name).name
            original = attachment_output(project, Path(old['original']) if old else project / 'attachments' / 'originals' / sha[:16] / name)
            if original.is_file():
                if digest(original.read_bytes()) != sha:
                    raise AttachmentError('original_changed', 'A saved original differs; conversion was stopped.')
            else:
                private_write(original, data)
            preview = attachment_output(project, project / 'attachments' / 'previews' / sha[:16] / (Path(name).stem + '-q20-half.jpg'))
            private_dir(preview.parent)
            small, size, preview_size = jpeg_preview(data)
            width, height = preview_size
            private_write(preview, small)
            if dimensions(small) != preview_size:
                raise AttachmentError('preview_invalid', 'A preview has unexpected dimensions; history was not changed.')
            targets[sha] = {'original': str(original), 'name': name, 'preview': str(preview),
                            'preview_hash': digest(small), 'encoded': base64.b64encode(small).decode(),
                            'original_dimensions': list(size), 'preview_dimensions': [width, height],
                            'original_bytes': len(data), 'preview_bytes': len(small)}

        def target_for_path(value):
            if not isinstance(value, str) or not Path(value).is_absolute():
                return None
            file = Path(value)
            if mimetypes.guess_type(file.name)[0] not in IMAGE_MIMES or not file.is_file():
                return None
            return targets.get(digest(file.read_bytes()))

        def encoded_target(value):
            data = decode(value)
            return targets.get(digest(data)) if data else None

        def image_link(target):
            return '[Full-size original: ' + target['name'] + '](<' + target['original'] + '>)'

        def transform(value):
            if isinstance(value, list):
                return [transform(v) for v in value]
            if isinstance(value, str):
                def replace(match):
                    target = encoded_target(match.group(2))
                    return 'data:image/jpeg;base64,' + target['encoded'] if target else match.group(0)
                return DATA_URI.sub(replace, value)
            if not isinstance(value, dict):
                return value
            result = {key: transform(child) for key, child in value.items()}
            blob = raw_blob(value)
            target = encoded_target(blob[1]) if blob else None
            if target:
                result[blob[2]] = target['encoded']
                if value.get('type') == 'image':
                    result['mimeType'] = 'image/jpeg'
                if blob[2] == 'file_data':
                    result['filename'] = Path(target['preview']).name
                if blob[2] == 'result':
                    result['savedPath'] = target['preview']
            if value.get('type') in ('local_image', 'localImage'):
                target = target_for_path(value.get('path'))
                if target:
                    result['path'] = target['preview']
            # Display content links to originals. The per-chat content index also
            # resolves preview IDs to originals after model-context compaction.
            content = value.get('content')
            if isinstance(content, list) and value.get('type') in ('UserMessage', 'userMessage'):
                rebuilt = []
                for child in content:
                    rebuilt.append(transform(child))
                    target = target_for_path(child.get('path')) if isinstance(child, dict) else None
                    if target:
                        rebuilt.append({'type': 'text', 'text': image_link(target), 'text_elements': []})
                result['content'] = rebuilt
            return result

        new_lines, changed = [], []
        for number, (line, record) in enumerate(zip(lines, records)):
            updated = transform(record)
            if updated == record:
                new_lines.append(line)
            else:
                changed.append(number)
                new_lines.append((json.dumps(updated, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
        after = b''.join(new_lines)
        operation = folder / 'backups' / uuid.uuid4().hex
        private_dir(operation)
        private_write(operation / 'history.jsonl', before)
        write_json(operation / 'operation.json', {'status': 'prepared', 'thread_id': plan['thread_id'],
                                                 'changed_records': changed, 'plan_id': plan['id']})
        db = self.home / 'thread_history_1.sqlite'
        con = sqlite3.connect(db, timeout=10) if db.is_file() else None
        wrote_history = False
        try:
            old_items, old_turns, projection = [], [], None
            planned_items, planned_turns = {}, {}
            if con:
                con.row_factory = sqlite3.Row
                con.execute('BEGIN IMMEDIATE')
                required = {
                    'thread_items': {'thread_id', 'turn_id', 'item_id', 'item_json'},
                    'thread_turns': {'thread_id', 'turn_id', 'rollout_ordinal', 'rollout_byte_offset', 'rollout_end_ordinal', 'rollout_end_byte_offset'},
                    'thread_history_projection_state': {'thread_id', 'next_rollout_ordinal', 'next_rollout_byte_offset'},
                }
                for table, columns in required.items():
                    actual = {row[1] for row in con.execute('PRAGMA table_info(' + table + ')')}
                    if not columns <= actual:
                        raise AttachmentError('unsupported_display_schema', 'This Codex display schema is unfamiliar; no history was changed.')
                sid = plan['thread_id']
                old_items = [dict(r) for r in con.execute('SELECT * FROM thread_items WHERE thread_id=?', (sid,))]
                old_turns = [dict(r) for r in con.execute('SELECT * FROM thread_turns WHERE thread_id=?', (sid,))]
                state = con.execute('SELECT * FROM thread_history_projection_state WHERE thread_id=?', (sid,)).fetchone()
                projection = dict(state) if state else None
                for row in old_items:
                    item = json.loads(row['item_json'])
                    updated = transform(item)
                    if updated != item:
                        planned_items[row['item_id']] = json.dumps(updated, ensure_ascii=False, separators=(',', ':'))
            write_json(operation / 'display.json', {'items': [r for r in old_items if r['item_id'] in planned_items],
                                                   'turns': old_turns, 'projection': projection})
            with log.open('r+b') as stream:
                latest = stream.read()
                if not latest.startswith(before):
                    raise AttachmentError('history_changed', 'The chat history changed concurrently; no conversion was applied.')
                if plan.get('automatic'):
                    # Reject even append-only changes during a timed conversion.
                    # No native recorder lock is exposed; remain conservative.
                    if latest != before:
                        raise AttachmentError('chat_active', 'The chat changed during conversion; deferred.')
                    assert_idle(self.home, plan['thread_id'], log, records)
                tail = latest[len(before):]
                if tail and not tail.endswith(b'\n'):
                    raise AttachmentError('history_busy', 'The chat is writing a partial record; try when it is idle.')
                if tail:
                    for line in tail.splitlines():
                        json.loads(line)
                    before = latest
                    after += tail
                    private_write(operation / 'history.jsonl', before)
                old_offsets, new_offsets = offsets(before), offsets(after)
                for row in old_turns:
                    planned_turns[row['turn_id']] = (
                        translated(old_offsets, new_offsets, row['rollout_ordinal'], row['rollout_byte_offset']),
                        translated(old_offsets, new_offsets, row['rollout_end_ordinal'], row['rollout_end_byte_offset']))
                next_offset = translated(old_offsets, new_offsets, projection['next_rollout_ordinal'], projection['next_rollout_byte_offset']) if projection else None
                write_json(operation / 'operation.json', {'status': 'writing', 'thread_id': plan['thread_id'],
                    'before_bytes': len(before), 'after_bytes': len(after), 'plan_id': plan['id']})
                stream.seek(0)
                stream.write(after)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
                wrote_history = True
            if con:
                for row in old_items:
                    if row['item_id'] in planned_items:
                        con.execute('UPDATE thread_items SET item_json=? WHERE thread_id=? AND turn_id=? AND item_id=?',
                                    (planned_items[row['item_id']], plan['thread_id'], row['turn_id'], row['item_id']))
                for row in old_turns:
                    start, end = planned_turns[row['turn_id']]
                    con.execute('UPDATE thread_turns SET rollout_byte_offset=?,rollout_end_byte_offset=? WHERE thread_id=? AND turn_id=?',
                                (start, end, plan['thread_id'], row['turn_id']))
                if projection:
                    con.execute('UPDATE thread_history_projection_state SET next_rollout_byte_offset=? WHERE thread_id=?', (next_offset, plan['thread_id']))
                con.commit()
            for sha, target in targets.items():
                asset = {key: value for key, value in target.items() if key not in ('encoded', 'preview_hash')}
                asset['original_sha256'] = sha
                asset['preview_hashes'] = sorted(set(index['assets'].get(sha, {}).get('preview_hashes', [])) | {target['preview_hash']})
                index['assets'][sha] = asset
            write_json(state_path(project, plan['thread_id']), index)
            result = {'status': 'converted', 'thread_id': plan['thread_id'], 'converted_images': len(targets),
                      'before_bytes': len(before), 'after_bytes': len(after), 'saved_bytes': len(before) - len(after),
                      'changed_history_records': len(changed), 'changed_display_records': len(planned_items),
                      'backup': str(operation), 'originals': [v['original'] for v in targets.values()],
                      'jpeg_quality': 20, 'dimension_scale': 0.5,
                      'refresh': 'Reopen or restart the desktop app if it still displays cached images.'}
            write_json(operation / 'operation.json', {**result, 'status': 'complete'})
            return result
        except Exception:
            if con:
                con.rollback()
            write_json(operation / 'operation.json', {'status': 'needs_recovery' if wrote_history else 'not_applied',
                'thread_id': plan['thread_id'], 'backup': str(operation), 'automatic_restore': False})
            raise
        finally:
            if con:
                con.close()
