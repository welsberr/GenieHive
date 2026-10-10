import json

import pytest
from fastapi.testclient import TestClient

from geniehive_control.main import create_app
from geniehive_control.models import HostRegistration
from geniehive_control.responses import to_chat, from_chat, events
from geniehive_control.upstream import UpstreamClient


def test_tools_and_history():
    chat, mapping = to_chat({'model': 'local', 'tools': [
        {'type': 'namespace', 'name': 'functions', 'tools': [
            {'type': 'function', 'name': 'shell', 'parameters': {'type': 'object'}},
            {'type': 'custom', 'name': 'apply_patch'}]}], 'input': [
        {'type': 'custom_tool_call', 'call_id': 'c1', 'namespace': 'functions', 'name': 'apply_patch', 'input': 'patch'},
        {'type': 'custom_tool_call_output', 'call_id': 'c1', 'output': 'done'}]})
    assert chat['messages'][0]['tool_calls'][0]['function']['name'] == 'functions__apply_patch'
    assert chat['messages'][1] == {'role': 'tool', 'tool_call_id': 'c1', 'content': 'done'}
    r = from_chat({'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
        {'id': 'c2', 'function': {'name': 'functions__apply_patch', 'arguments': '{"input":"hello"}'}}]}}]}, 'local', mapping)
    assert r['output'][0]['type'] == 'custom_tool_call'
    assert r['output'][0]['input'] == 'hello'
    assert r['output'][0]['namespace'] == 'functions'
    stream = [json.loads(x.decode().split('data: ')[1]) for x in events(r)]
    assert stream[-1]['type'] == 'response.completed'
    assert [e['sequence_number'] for e in stream] == list(range(len(stream)))


@pytest.mark.parametrize('extra', [{'previous_response_id': 'x'}, {'background': True},
    {'tools': [{'type': 'web_search'}]}, {'input': [{'role': 'user', 'content': [{'type': 'input_image'}]}]}])
def test_reject_unsupported(extra):
    with pytest.raises(ValueError):
        to_chat({'model': 'local', 'input': 'hello', **extra})


def test_truncated_tools_rejected():
    with pytest.raises(ValueError, match='truncated'):
        from_chat({'choices': [{'finish_reason': 'length', 'message': {'tool_calls': [{}]}}]}, 'local', {})


def test_endpoint_auth_errors_and_stream(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text(f'auth:\n  client_api_keys: [synthetic-key]\nstorage:\n  sqlite_path: {tmp_path / "state.db"}\n')

    class Reply:
        status_code = 200
        text = ''
        def json(self):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'hello'}}]}

    class Poster:
        calls = []
        async def post(self, url, *, json, headers=None):
            self.calls.append(json)
            return Reply()

    poster = Poster()
    app = create_app(config, upstream_client=UpstreamClient(client=poster))
    app.state.registry.register_host(HostRegistration.model_validate({
        'host_id': 'fixture', 'address': '127.0.0.1', 'services': [{
            'service_id': 'fixture/chat', 'host_id': 'fixture', 'kind': 'chat',
            'endpoint': 'http://127.0.0.1:18420', 'assets': [{'asset_id': 'local', 'loaded': True}],
            'state': {'health': 'healthy', 'load_state': 'loaded', 'accept_requests': True}}]}))
    with TestClient(app) as client:
        assert client.post('/v1/responses', json={'model': 'local', 'input': 'hi'}).status_code == 401
        assert not poster.calls
        headers = {'X-Api-Key': 'synthetic-key'}
        r = client.post('/v1/responses', headers=headers, json={'model': 'local', 'input': 'hi', 'stream': True})
        assert r.status_code == 200
        assert 'event: response.completed' in r.text
        assert poster.calls[0]['stream'] is False
        Reply.status_code = 503
        Reply.text = 'synthetic unavailable'
        r = client.post('/v1/responses', headers=headers, json={'model': 'local', 'input': 'hi', 'stream': True})
        assert r.status_code == 503
        assert 'response.completed' not in r.text
