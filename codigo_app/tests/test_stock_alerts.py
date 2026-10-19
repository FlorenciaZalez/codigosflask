"""Run with python -m unittest discover -s codigo_app/tests -p test_stock_alerts.py."""
import importlib
import os
import tempfile
import unittest
from unittest.mock import patch, Mock


class StockAlertTests(unittest.TestCase):
    def test_alerts_for_both_entrypoints(self):
        for module_name in ('codigo_app.app',):
            with self.subTest(module=module_name), tempfile.TemporaryDirectory() as directory:
                with patch.dict(os.environ, {
                    'USE_LOCAL_DB': '1', 'RENDER': 'false',
                    'LOCAL_DATABASE_URL': f'sqlite:///{directory}/test.db',
                    'TIBADIGITAL_API_KEY': 'test-key',
                    'TELEGRAM_BOT_TOKEN': 'test-token', 'TELEGRAM_CHAT_ID': '123',
                }):
                    with patch('werkzeug.security.generate_password_hash', return_value='test-only-hash'):
                        module = importlib.import_module(module_name)
                    with module.app.app_context():
                        module.db.session.add_all([
                            module.Codigo(cuenta='Netflix', codigo=f'code-{i}')
                            for i in range(3)
                        ])
                        module.db.session.commit()
                    response = Mock()
                    response.json.return_value = {'ok': True}
                    with patch.object(module, 'render_template', return_value='OK'), patch.object(module.requests, 'post', return_value=response) as send:
                        client = module.app.test_client()
                        with client.session_transaction() as session:
                            session['usuario'] = 'admin'
                            session['rol'] = 'admin'
                        self.assertEqual(client.post('/codigo', data={'cuenta': 'netflix'}).status_code, 200)
                        send.assert_not_called()
                        self.assertEqual(client.post('/codigo', data={'cuenta': 'NETFLIX'}).status_code, 200)
                        self.assertEqual(send.call_count, 1)
                        self.assertIn('1 código', send.call_args.kwargs['json']['text'])
                        client.post('/codigo', data={'cuenta': 'Netflix'})
                        self.assertEqual(send.call_count, 1)
                    with module.app.app_context():
                        module.db.session.add_all([
                            module.Codigo(cuenta='Disney', codigo=f'disney-{i}')
                            for i in range(2)
                        ])
                        module.db.session.commit()
                    with patch.object(module.requests, 'post', side_effect=RuntimeError('network')) as send:
                        result = client.post('/api/v1/codes/reserve',
                            headers={'Authorization': 'Bearer test-key'},
                            json={'account': 'Disney', 'allocation_id': 'one', 'order_id': 'one', 'user_id': 'one', 'customer_name': 'Test', 'customer_email': 'test@example.com', 'client_code': 'RV123'})
                        self.assertEqual(result.status_code, 201, result.get_json())
                        self.assertEqual(send.call_count, 1)
                        self.assertEqual(client.post('/api/v1/codes/reserve',
                            headers={'Authorization': 'Bearer test-key'},
                            json={'account': 'Disney', 'allocation_id': 'one', 'order_id': 'one', 'user_id': 'one', 'customer_name': 'Test', 'customer_email': 'test@example.com', 'client_code': 'RV123'}).status_code, 200)
                        self.assertEqual(send.call_count, 1)
                    with module.app.app_context(), patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': ''}), patch.object(module.requests, 'post') as send:
                        module.notify_low_stock('Disney')
                        send.assert_not_called()
                    with module.app.app_context():
                        module.db.session.remove()
                        module.db.engine.dispose()
