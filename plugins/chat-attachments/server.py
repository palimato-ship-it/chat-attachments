#!/usr/bin/env python3
"""Local-only MCP stdio entry point and matching CLI."""
import argparse
import json
import sys

from history import AttachmentError
from service import Service

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
    return getattr(service, name)(**arguments)


def serve():
    service = Service()
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
                          'serverInfo': {'name': 'chat-attachments', 'version': '0.2.1'},
                          'instructions': 'Manual conversion needs approval. Per-chat automatic policies require explicit user authorization once; the installed background timer then processes eligible old images without repeated prompts. Originals remain local.'}
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
    args = parser.parse_args()
    service = Service()
    try:
        if args.action == 'scan':
            result = service.scan_chat(args.thread_id)
        elif args.action == 'plan':
            result = service.plan_conversion(args.thread_id)
        elif args.action == 'automatic':
            result = service.configure_automatic(args.thread_id, args.period, not args.disable, args.approved)
        elif args.action == 'status':
            result = service.automatic_status(args.thread_id)
        elif args.action == 'original':
            result = service.original_file(args.thread_id, args.media_id)
        else:
            result = service.apply_conversion(args.plan_id, args.approved)
        print(json.dumps(result, ensure_ascii=False))
    except AttachmentError as error:
        print(json.dumps({'error': {'code': error.code, 'message': str(error)}}))
        raise SystemExit(1)


if __name__ == '__main__':
    cli() if len(sys.argv) > 1 else serve()
