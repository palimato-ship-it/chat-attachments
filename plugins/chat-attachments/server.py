#!/usr/bin/env python3
"""Local-only MCP stdio entry point and matching CLI."""
import argparse
import json
import sys

from history import AttachmentError
from runtime import invoke_worker, setup_runtime, setup_status

TOOLS = [
    {'name': 'scan_chat', 'description': 'Read the selected local Codex chat’s complete history and report embedded files, duplicates, origins, external references and already-processed images. Does not modify history.',
     'inputSchema': {'type': 'object', 'properties': {'thread_id': {'type': 'string'}}, 'required': ['thread_id'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}},
    {'name': 'plan_conversion', 'description': 'Prepare an approval-bound plan for this chat: JPEG quality 20, half original dimensions, full originals kept. Only writes a private plan file, never chat history.',
     'inputSchema': {'type': 'object', 'properties': {'thread_id': {'type': 'string'}}, 'required': ['thread_id'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False, 'openWorldHint': False}},
    {'name': 'apply_conversion', 'description': 'Apply a previously shown conversion plan ONLY after explicit human approval. Updates selected history and its local display index; keeps originals and backups. Never automatically restores over the experiment.',
     'inputSchema': {'type': 'object', 'properties': {'plan_id': {'type': 'string'}, 'approved': {'type': 'boolean'}}, 'required': ['plan_id', 'approved'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': False, 'openWorldHint': False}},
    {'name': 'original_file', 'description': 'Resolve an original or preview content ID to the preserved full-resolution original. Returns a local path, not binary data, to avoid re-embedding large files.',
     'inputSchema': {'type': 'object', 'properties': {'thread_id': {'type': 'string'}, 'media_id': {'type': 'string'}}, 'required': ['thread_id', 'media_id'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}},
    {'name': 'configure_automatic',
     'description': 'On explicit user request, enable/change or disable automatic conversion for ONLY this local chat. Period examples: 2 days, 48 hours, 30 minutes, 1 week. Default 2 days. Enabled policy authorizes future scheduled JPEG-quality-20, half-dimension previews with full originals/backups preserved. Only old images in idle chats are processed. The native background service must be installed on this operating system.',
     'inputSchema': {'type': 'object', 'properties': {'thread_id': {'type': 'string'}, 'period': {'type': 'string'}, 'enabled': {'type': 'boolean'}, 'approved': {'type': 'boolean'}}, 'required': ['thread_id', 'period', 'enabled', 'approved'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': True, 'openWorldHint': False}},
    {'name': 'automatic_status', 'description': 'Report the selected chat’s saved automatic-conversion period, enabled state and last timer result. Does not scan or mutate chat history.',
     'inputSchema': {'type': 'object', 'properties': {'thread_id': {'type': 'string'}}, 'required': ['thread_id'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}},

    {'name': 'setup_runtime', 'description': 'On an explicit setup request, install/repair Pillow in a dedicated local environment and register the native user timer. Downloads dependencies. Preserves existing chat timer policies and enables no chats.',
     'inputSchema': {'type': 'object', 'properties': {'approved': {'type': 'boolean'}}, 'required': ['approved'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': True}},
    {'name': 'setup_status', 'description': 'Report local image runtime/setup readiness, timer registration marker and last safe setup error without requiring Pillow.',
     'inputSchema': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
     'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}},

]


def invoke(service, name, arguments):
    allowed = {tool['name']: tool for tool in TOOLS}
    if name not in allowed:
        raise AttachmentError('unknown_tool', 'Choose one of the Chat Attachments tools.')
    schema = allowed[name]['inputSchema']
    if not isinstance(arguments, dict) or set(arguments) - set(schema['properties']) or set(schema['required']) - set(arguments):
        raise AttachmentError('invalid_arguments', 'The tool arguments do not match its declared inputs.')
    for key, value in arguments.items():
        kind = schema['properties'][key]['type']
        if (kind == 'string' and not isinstance(value, str)) or (kind == 'boolean' and not isinstance(value, bool)):
            raise AttachmentError('invalid_arguments', 'A tool argument has an incorrect type.')
    if name == 'setup_runtime':
        return setup_runtime(**arguments)
    if name == 'setup_status':
        return setup_status()
    return getattr(service, name)(**arguments) if service is not None else invoke_worker(name, arguments)


def serve():
    service = None
    for line in sys.stdin:
        request = {}
        try:
            if len(line) > 1_000_000:
                raise ValueError('request too large')
            request = json.loads(line)
            if 'id' not in request:
                continue
            method, params = request.get('method'), request.get('params', {})
            if method == 'initialize':
                result = {'protocolVersion': params.get('protocolVersion', '2025-06-18'),
                          'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': 'chat-attachments', 'version': '0.3.0'},
                          'instructions': 'Use setup_runtime on an explicit setup request if first-use setup is incomplete; setup tools do not need Pillow. Manual conversion requires approval. Per-chat timers require explicit opt-in. Originals remain local.'}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': TOOLS}
            elif method == 'tools/call':
                try:
                    value = invoke(service, params.get('name'), params.get('arguments', {}))
                    result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}], 'isError': False}
                except AttachmentError as error:
                    result = {'content': [{'type': 'text', 'text': json.dumps({'error': {'code': error.code, 'message': str(error)}})}], 'isError': True}
                except Exception as error:
                    print('Chat Attachments operation failed: ' + type(error).__name__, file=sys.stderr)
                    result = {'content': [{'type': 'text', 'text': json.dumps({'error': {'code': 'operation_failed', 'message': 'The local operation failed. Preserve the operation backup and inspect its status before retrying.'}})}], 'isError': True}
            else:
                print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)
                continue
            print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
        except (ValueError, TypeError):
            print(json.dumps({'jsonrpc': '2.0', 'id': request.get('id'), 'error': {'code': -32700, 'message': 'Invalid request'}}), flush=True)


def cli():
    parser = argparse.ArgumentParser(description='Chat Attachments — local, explicit attachment conversion')
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('scan', 'plan', 'original'):
        child = sub.add_parser(name)
        child.add_argument('--thread-id', required=True)
        if name == 'original':
            child.add_argument('--media-id', required=True)
    child = sub.add_parser('convert')
    child.add_argument('--plan-id', required=True)
    child.add_argument('--approved', action='store_true')
    child = sub.add_parser('automatic')
    child.add_argument('--thread-id', required=True)
    child.add_argument('--period', default='2 days')
    child.add_argument('--disable', action='store_true')
    child.add_argument('--approved', action='store_true')
    child = sub.add_parser('status')
    child.add_argument('--thread-id', required=True)
    child = sub.add_parser('setup')
    child.add_argument('--approved', action='store_true')
    sub.add_parser('setup-status')
    args = parser.parse_args()
    service = None
    try:
        mapping = {
            'scan': ('scan_chat', lambda: {'thread_id': args.thread_id}),
            'plan': ('plan_conversion', lambda: {'thread_id': args.thread_id}),
            'original': ('original_file', lambda: {'thread_id': args.thread_id, 'media_id': args.media_id}),
            'automatic': ('configure_automatic', lambda: {'thread_id': args.thread_id, 'period': args.period, 'enabled': not args.disable, 'approved': args.approved}),
            'status': ('automatic_status', lambda: {'thread_id': args.thread_id}),
            'convert': ('apply_conversion', lambda: {'plan_id': args.plan_id, 'approved': args.approved}),
            'setup': ('setup_runtime', lambda: {'approved': args.approved}),
            'setup-status': ('setup_status', lambda: {}),
        }
        name, arguments = mapping[args.action]
        result = invoke(service, name, arguments())
        print(json.dumps(result, ensure_ascii=False))
    except AttachmentError as error:
        print(json.dumps({'error': {'code': error.code, 'message': str(error)}}))
        raise SystemExit(1)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--invoke':
        try:
            print(json.dumps({'ok': True, 'value': invoke(None, sys.argv[2], json.load(sys.stdin))}))
        except AttachmentError as error:
            print(json.dumps({'ok': False, 'error': {'code': error.code, 'message': str(error)}}))
        except Exception as error:
            print('Chat Attachments worker failed: ' + type(error).__name__, file=sys.stderr)
            print(json.dumps({'ok': False, 'error': {'code': 'operation_failed', 'message': 'The local operation failed. Preserve its backup/status before retrying.'}}))
    else:
        cli() if len(sys.argv) > 1 else serve()
