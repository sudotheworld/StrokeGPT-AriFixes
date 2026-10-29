import sqlite3

import pytest
from flask import Flask

from conversation_api import DIMENSIONS, register_conversation_routes


@pytest.fixture
def conversation(tmp_path):
    calls = []
    path = tmp_path / 'conversation.sqlite3'
    def reply(messages):
        calls.append(messages)
        return 'A clear, useful answer.'
    def create():
        app = Flask(__name__)
        app.testing = True
        register_conversation_routes(app, lambda: path, reply)
        return app
    return create, path, calls


def new_reply(client):
    response = client.post('/api/conversation', json={'message': 'Explain this simply.'})
    assert response.status_code == 200
    assert response.json['ok'] is True
    return response.json['response_id']


@pytest.mark.parametrize('score', range(-5, 6))
def test_all_scores_are_tied_to_exact_response_and_recalled(conversation, score):
    create, _, calls = conversation
    client = create().test_client()
    response_id = new_reply(client)
    assert client.post('/api/conversation/feedback', json={
        'response_id': response_id, 'score': score, 'note': 'Less jargon ✓', 'dimension': 'clarity'
    }).json == {'ok': True}
    new_reply(client)
    context = calls[-1]
    assert 'Historical conversational feedback' in context[1]['content']
    assert f'"score": {score}' in context[1]['content']
    assert 'Less jargon ✓' in context[1]['content']
    assert 'A clear, useful answer.' in context[1]['content']
    assert context[-1] == {'role': 'user', 'content': 'Explain this simply.'}
    history = client.get('/api/conversation').json['turns']
    assert history[0]['ratings']['clarity']['score'] == score
    assert history[1]['ratings'] == {}  # Unrated is not zero.


def test_dimensions_independent_and_rerating_replaces_previous_value(conversation):
    create, path, _ = conversation
    client = create().test_client(); rid = new_reply(client)
    for dimension in DIMENSIONS:
        assert client.post('/api/conversation/feedback', json={'response_id': rid, 'dimension': dimension, 'score': 5}).status_code == 200
    client.post('/api/conversation/feedback', json={'response_id': rid, 'dimension': 'tone', 'score': 0})
    ratings = client.get('/api/conversation').json['turns'][0]['ratings']
    assert ratings['tone']['score'] == 0
    assert ratings['clarity']['score'] == 5
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM ratings').fetchone()[0] == 5


def test_history_survives_restart_and_is_private_to_browser(conversation):
    create, _, calls = conversation
    client = create().test_client(); rid = new_reply(client)
    client.post('/api/conversation/feedback', json={'response_id': rid, 'score': -5, 'note': 'private preference'})
    token = client.get_cookie('conversation_owner').value
    restarted = create().test_client(); restarted.set_cookie('conversation_owner', token)
    assert restarted.get('/api/conversation').json['turns'][0]['response_id'] == rid
    other = create().test_client()
    assert other.get('/api/conversation').json['turns'] == []
    assert other.post('/api/conversation/feedback', json={'response_id': rid, 'score': 1}).status_code == 404
    new_reply(other)
    assert all('private preference' not in m['content'] for m in calls[-1])


@pytest.mark.parametrize('patch', [{'score': True}, {'score': 1.2}, {'score': '5'}, {'score': 6},
    {'score': -6}, {'note': None}, {'note': 'x'*301}, {'dimension': 'motion'},
    {'dimension': []}, {'response_id': 'missing'}, {'response_id': None}])
def test_invalid_ratings_do_not_persist(conversation, patch):
    create, _, _ = conversation; client = create().test_client(); rid = new_reply(client)
    response = client.post('/api/conversation/feedback', json={'response_id': rid, 'score': 1, **patch})
    assert response.status_code == 400
    assert client.get('/api/conversation').json['turns'][0]['ratings'] == {}


@pytest.mark.parametrize('payload', [None, [], {}, {'message': ''}, {'message': ' '}, {'message': 5}, {'message': 'x'*4001}])
def test_invalid_chat(conversation, payload):
    create, _, calls = conversation
    response = create().test_client().post('/api/conversation', json=payload)
    assert response.status_code == 400
    assert calls == []


def test_llm_failure_keeps_history_empty(tmp_path):
    app = Flask(__name__)
    def failed(_): raise RuntimeError('private credentials should not leak')
    register_conversation_routes(app, lambda: tmp_path/'chat.db', failed)
    client = app.test_client()
    response = client.post('/api/conversation', json={'message': 'Hello'})
    assert response.status_code == 503
    assert 'private credentials' not in response.get_data(as_text=True)
    assert client.get('/api/conversation').json['turns'] == []


def test_storage_failure_reports_failure(tmp_path):
    app = Flask(__name__)
    register_conversation_routes(app, lambda: tmp_path, lambda _: 'reply')
    client = app.test_client()
    assert client.get('/api/conversation').status_code == 503
    assert client.post('/api/conversation', json={'message': 'Hello'}).status_code == 503
    assert client.post('/api/conversation/feedback', json={'response_id': 'a'*32, 'score': 0}).status_code == 503


def test_text_adapter_has_no_device_schema(monkeypatch):
    import conversation_llm
    calls = []
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'message': {'content': 'Hello'}}
    def post(url, **kwargs): calls.append((url, kwargs)); return Response()
    monkeypatch.setattr(conversation_llm.requests, 'post', post)
    assert conversation_llm.text_reply([{'role': 'user', 'content': 'Hi'}]) == 'Hello'
    payload = calls[0][1]['json']
    assert set(payload) == {'model', 'stream', 'messages'}
    assert 'move' not in str(payload)
