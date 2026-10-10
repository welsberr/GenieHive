"""Stateless text/tool Responses compatibility over the governed chat route.

Upstream generation is buffered before emitting ordered Responses SSE events.
No conversation store, hosted tools, multimodal inputs or remote compaction.
Unsupported semantic features fail explicitly instead of being silently dropped.
"""
from __future__ import annotations

import json
import time
import uuid


def text_content(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise ValueError('Expected text or a list of text content parts')
    parts = []
    for part in value:
        if part.get('type') not in ('input_text', 'output_text', 'text'):
            raise ValueError('Only text content is supported')
        parts.append(part['text'])
    return '\n'.join(parts)


def to_chat(body):
    if not isinstance(body, dict) or not isinstance(body.get('model'), str):
        raise ValueError('model is required')
    for key in ('previous_response_id', 'conversation', 'background'):
        if body.get(key):
            raise ValueError(f'{key} is unsupported; send complete input history')
    fmt = body.get('text', {}).get('format', {})
    if fmt and fmt.get('type', 'text') != 'text':
        raise ValueError('Structured final output is not supported by this adapter')
    definitions, mapping = [], {}

    def add_tool(tool, namespace=None):
        kind = tool.get('type')
        if kind == 'namespace':
            for child in tool.get('tools', []):
                add_tool(child, tool['name'])
            return
        if kind not in ('function', 'custom'):
            raise ValueError(f'Unsupported tool type: {kind}')
        name = tool['name']
        alias = f'{namespace}__{name}' if namespace else name
        if alias in mapping:
            raise ValueError('Duplicate tool name')
        mapping[alias] = (kind, name, namespace)
        schema = tool.get('parameters', {'type': 'object', 'properties': {}})
        description = tool.get('description', '')
        if kind == 'custom':
            schema = {'type': 'object', 'properties': {'input': {'type': 'string'}},
                      'required': ['input'], 'additionalProperties': False}
            description += '\nSupply the exact raw tool input in the input string.'
        definitions.append({'type': 'function', 'function': {
            'name': alias, 'description': description, 'parameters': schema}})

    for tool in body.get('tools', []):
        add_tool(tool)
    messages = []
    if body.get('instructions'):
        messages.append({'role': 'system', 'content': body['instructions']})
    items = body.get('input', [])
    if isinstance(items, str):
        items = [{'role': 'user', 'content': items}]
    if not isinstance(items, list):
        raise ValueError('input must be text or a list')
    for item in items:
        kind = item.get('type', 'message')
        if kind == 'message':
            role = item['role']
            if role not in ('system', 'developer', 'user', 'assistant'):
                raise ValueError('Unsupported message role')
            messages.append({'role': 'system' if role == 'developer' else role,
                             'content': text_content(item.get('content', ''))})
        elif kind in ('function_call', 'custom_tool_call'):
            namespace = item.get('namespace')
            name = f"{namespace}__{item['name']}" if namespace else item['name']
            arguments = item.get('arguments', '{}') if kind == 'function_call' else json.dumps({'input': item['input']})
            call = {'id': item['call_id'], 'type': 'function', 'function': {'name': name, 'arguments': arguments}}
            if messages and messages[-1].get('tool_calls'):
                messages[-1]['tool_calls'].append(call)
            else:
                messages.append({'role': 'assistant', 'content': None, 'tool_calls': [call]})
        elif kind in ('function_call_output', 'custom_tool_call_output'):
            messages.append({'role': 'tool', 'tool_call_id': item['call_id'],
                             'content': text_content(item['output'])})
        elif kind == 'reasoning':
            # Reasoning is model-specific and is not evidence or tool output.
            continue
        else:
            raise ValueError(f'Unsupported input item: {kind}')
    chat = {'model': body['model'], 'messages': messages, 'stream': False,
            'temperature': body.get('temperature', 0), 'max_tokens': body.get('max_output_tokens', 2048)}
    if definitions:
        chat['tools'] = definitions
    choice = body.get('tool_choice', 'auto')
    if choice not in ('auto', 'none', 'required'):
        raise ValueError('Named tool_choice is not supported')
    if definitions:
        chat['tool_choice'] = choice
    return chat, mapping


def from_chat(chat, model, mapping):
    choice = chat['choices'][0]
    finish = choice.get('finish_reason')
    if finish not in ('stop', 'tool_calls', 'length'):
        raise ValueError(f'Unsupported upstream finish reason: {finish}')
    msg = choice['message']
    output = []
    # Never execute tool calls that may have been truncated.
    if finish == 'length' and msg.get('tool_calls'):
        raise ValueError('Upstream truncated a tool call')
    if msg.get('content'):
        output.append({'id': 'msg_' + uuid.uuid4().hex, 'type': 'message', 'role': 'assistant',
                       'status': 'completed', 'content': [{'type': 'output_text', 'text': msg['content'], 'annotations': []}]})
    for call in msg.get('tool_calls') or []:
        fun = call['function']
        if fun['name'] not in mapping:
            raise ValueError('Upstream returned an unknown tool')
        kind, name, namespace = mapping[fun['name']]
        arguments = json.loads(fun['arguments'])
        if not isinstance(arguments, dict):
            raise ValueError('Tool arguments must be an object')
        item = {'id': 'fc_' + uuid.uuid4().hex, 'type': 'function_call' if kind == 'function' else 'custom_tool_call',
                'call_id': call['id'], 'name': name, 'status': 'completed'}
        if namespace:
            item['namespace'] = namespace
        if kind == 'custom':
            if set(arguments) != {'input'} or not isinstance(arguments['input'], str):
                raise ValueError('Custom tool requires exactly one input string')
            item['input'] = arguments['input']
        else:
            item['arguments'] = fun['arguments']
        output.append(item)
    usage = chat.get('usage') or {}
    return {'id': 'resp_' + uuid.uuid4().hex, 'object': 'response', 'created_at': int(time.time()),
            'model': model, 'status': 'incomplete' if finish == 'length' else 'completed',
            'error': None, 'incomplete_details': {'reason': 'max_output_tokens'} if finish == 'length' else None,
            'output': output, 'usage': {'input_tokens': usage.get('prompt_tokens', 0),
                'output_tokens': usage.get('completion_tokens', 0), 'total_tokens': usage.get('total_tokens', 0),
                'input_tokens_details': {'cached_tokens': (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0)},
                'output_tokens_details': {'reasoning_tokens': 0}}}


def events(response):
    """Emit complete ordered SSE events; called only after successful conversion."""
    sequence = 0

    def emit(kind, **payload):
        nonlocal sequence
        event = {'type': kind, 'sequence_number': sequence, **payload}
        sequence += 1
        return ('event: ' + kind + '\ndata: ' + json.dumps(event) + '\n\n').encode()

    initial = {**response, 'status': 'in_progress', 'output': [], 'usage': None}
    yield emit('response.created', response=initial)
    yield emit('response.in_progress', response=initial)
    for index, item in enumerate(response['output']):
        pending = {**item, 'status': 'in_progress'}
        key = 'arguments' if item['type'] == 'function_call' else 'input'
        if item['type'] == 'message':
            pending['content'] = []
        else:
            pending[key] = ''
        yield emit('response.output_item.added', output_index=index, item=pending)
        common = {'item_id': item['id'], 'output_index': index}
        if item['type'] == 'message':
            part = item['content'][0]
            yield emit('response.content_part.added', **common, content_index=0, part={**part, 'text': ''})
            yield emit('response.output_text.delta', **common, content_index=0, delta=part['text'])
            yield emit('response.output_text.done', **common, content_index=0, text=part['text'])
            yield emit('response.content_part.done', **common, content_index=0, part=part)
        else:
            prefix = 'response.function_call_arguments' if key == 'arguments' else 'response.custom_tool_call_input'
            yield emit(prefix + '.delta', **common, delta=item[key])
            yield emit(prefix + '.done', **common, **{key: item[key]})
        yield emit('response.output_item.done', output_index=index, item=item)
    yield emit('response.' + response['status'], response=response)
