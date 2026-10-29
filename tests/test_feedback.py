import json

import pytest
from flask import Flask

from feedback_api import register_feedback_routes


@pytest.fixture
def feedback(tmp_path):
    app = Flask(__name__)
    app.testing = True
    path = tmp_path / 'feedback.jsonl'
    register_feedback_routes(app, lambda: path)
    return app.test_client(), path


@pytest.mark.parametrize('score', [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5])
def test_ui_payload_is_persisted(feedback, score):
    client, path = feedback
    response = client.post('/api/feedback', json={'score': score, 'note': 'Useful ✓'})
    assert response.status_code == 200
    assert response.json == {'ok': True}
    record = json.loads(path.read_text())
    assert record['score'] == score
    assert record['note'] == 'Useful ✓'
    assert isinstance(record['ts'], float)


def test_optional_note_and_append(feedback):
    client, path = feedback
    for score in [1, -1]:
        assert client.post('/api/feedback', json={'score': score}).json == {'ok': True}
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r['score'] for r in records] == [1, -1]
    assert all(r['note'] == '' for r in records)


@pytest.mark.parametrize('payload', [None, [], [1], 'text', True, {},
    {'score': 0}, {'score': 6}, {'score': -6}, {'score': 1.5},
    {'score': '5'}, {'score': True}, {'score': None},
    {'score': 1, 'note': None}, {'score': 1, 'note': {}},
    {'score': 1, 'note': 'x' * 301}])
def test_invalid_payload_does_not_write(feedback, payload):
    client, path = feedback
    response = client.post('/api/feedback', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 400
    assert response.json['ok'] is False
    assert not path.exists()


@pytest.mark.parametrize('content_type,body', [('application/json', '{'), ('text/plain', '{}')])
def test_invalid_request(feedback, content_type, body):
    client, path = feedback
    assert client.post('/api/feedback', data=body, content_type=content_type).status_code == 400
    assert not path.exists()


def test_note_boundary(feedback):
    client, path = feedback
    assert client.post('/api/feedback', json={'score': 5, 'note': 'x' * 300}).status_code == 200
    assert len(json.loads(path.read_text())['note']) == 300


def test_storage_failure_is_reported(feedback):
    client, path = feedback
    path.mkdir()  # Deterministic write failure, even under root.
    response = client.post('/api/feedback', json={'score': 5})
    assert response.status_code == 500
    assert response.json == {'ok': False, 'error': 'Could not save feedback'}
