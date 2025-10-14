import importlib


def test_memory_toggle_updates_context():
    app_module = importlib.import_module('app')

    # Ensure a known starting state
    original_state = app_module.use_long_term_memory
    original_saved_state = app_module.settings.use_long_term_memory

    client = app_module.app.test_client()

    try:
        app_module.use_long_term_memory = True
        app_module.settings.use_long_term_memory = True
        app_module.settings.save()

        response_disable = client.post('/api/memory/toggle', json={'enabled': False})
        assert response_disable.status_code == 200
        data_disable = response_disable.get_json()
        assert data_disable['ok'] is True
        assert data_disable['use_long_term_memory'] is False
        assert app_module.use_long_term_memory is False
        assert app_module.get_current_context()['use_long_term_memory'] is False

        response_enable = client.post('/api/memory/toggle', json={'enabled': True})
        assert response_enable.status_code == 200
        data_enable = response_enable.get_json()
        assert data_enable['ok'] is True
        assert data_enable['use_long_term_memory'] is True
        assert app_module.use_long_term_memory is True
        assert app_module.get_current_context()['use_long_term_memory'] is True
    finally:
        app_module.use_long_term_memory = original_state
        app_module.settings.use_long_term_memory = original_saved_state
        app_module.settings.save()
