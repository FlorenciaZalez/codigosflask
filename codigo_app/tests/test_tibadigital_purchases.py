import importlib
import os
import tempfile
import unittest


TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB.close()
os.environ["LOCAL_DATABASE_URL"] = f"sqlite:///{TEST_DB.name}"
os.environ["USE_LOCAL_DB"] = "1"
os.environ["TIBADIGITAL_API_KEY"] = "test-api-key"
app_module = importlib.import_module("codigo_app.app")


class TibadigitalPurchaseTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        os.unlink(TEST_DB.name)

    def setUp(self):
        self.client = app_module.app.test_client()
        self.headers = {"Authorization": "Bearer test-api-key"}
        with app_module.app.app_context():
            app_module.Historial.query.delete()
            app_module.ReservaCodigo.query.delete()
            app_module.Codigo.query.delete()
            app_module.Usuario.query.filter_by(nombre="Juan").delete()
            app_module.db.session.add_all([
                app_module.Codigo(cuenta="Netflix", codigo="CODE-1"),
                app_module.Codigo(cuenta="Netflix", codigo="CODE-2"),
            ])
            app_module.db.session.commit()

    def reserve(self, allocation_id="allocation-1", user_id="buyer-1", client_code="RV123"):
        return self.client.post(
            "/api/v1/codes/reserve",
            headers=self.headers,
            json={
                "allocation_id": allocation_id,
                "order_id": f"order-{allocation_id}",
                "user_id": user_id,
                "customer_name": "Juan",
                "customer_email": "juan@example.com",
                "client_code": client_code,
                "account": "Netflix",
            },
        )

    def confirm(self, allocation_id="allocation-1", user_id="buyer-1", client_code="RV123"):
        return self.client.post(
            "/api/v1/codes/confirm",
            headers=self.headers,
            json={
                "allocation_id": allocation_id,
                "order_id": f"order-{allocation_id}",
                "user_id": user_id,
                "customer_name": "Juan",
                "customer_email": "juan@example.com",
                "client_code": client_code,
            },
        )

    def test_confirm_registers_purchase_once_in_history(self):
        self.assertEqual(self.reserve().status_code, 201)
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(self.confirm().status_code, 200)

        with app_module.app.app_context():
            purchases = app_module.Historial.query.all()
            self.assertEqual(len(purchases), 1)
            self.assertEqual(purchases[0].usuario, "Juan (TIBADIGITAL)")
            self.assertEqual(purchases[0].cuenta, "Netflix")
            self.assertEqual(purchases[0].codigo, "CODE-1")
            self.assertEqual(purchases[0].external_user_id, "buyer-1")
            self.assertEqual(purchases[0].customer_email, "juan@example.com")
            self.assertEqual(purchases[0].client_code, "RV123")

    def test_restricts_same_buyer_and_account_for_one_day(self):
        self.assertEqual(self.reserve().status_code, 201)
        self.assertEqual(self.confirm().status_code, 200)

        response = self.reserve(allocation_id="allocation-2")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "PURCHASE_RESTRICTED")
        self.assertEqual(response.get_json()["remaining_days"], 1)

    def test_different_buyer_is_not_restricted(self):
        self.assertEqual(self.reserve().status_code, 201)
        self.assertEqual(self.confirm().status_code, 200)

        response = self.reserve(allocation_id="allocation-2", user_id="buyer-2")

        self.assertEqual(response.status_code, 201)

    def test_confirm_rechecks_restriction_for_parallel_reservations(self):
        self.assertEqual(self.reserve().status_code, 201)
        self.assertEqual(self.reserve(allocation_id="allocation-2").status_code, 201)
        self.assertEqual(self.confirm().status_code, 200)

        response = self.confirm(allocation_id="allocation-2")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "PURCHASE_RESTRICTED")

    def test_cf_client_code_uses_seven_day_restriction(self):
        self.assertEqual(self.reserve(client_code="CF123").status_code, 201)
        self.assertEqual(self.confirm(client_code="CF123").status_code, 200)

        response = self.reserve(allocation_id="allocation-2", client_code="CF123")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["remaining_days"], 7)

    def test_manual_request_honors_tibadigital_purchase_for_client_code(self):
        with app_module.app.app_context():
            app_module.db.session.add(app_module.Usuario(
                nombre="Juan",
                contraseña=app_module.generate_password_hash("secret"),
                rol="cliente",
                email="juan@example.com",
                verificado=True,
                activo=True,
                codigo_cliente="RV123",
            ))
            app_module.db.session.add(app_module.Historial(
                usuario="Juan (TIBADIGITAL)",
                cuenta="Netflix",
                codigo="TIBA-CODE",
                origen="TIBADIGITAL",
                external_user_id="buyer-1",
                customer_email="juan@example.com",
                client_code="RV123",
            ))
            app_module.db.session.commit()

        with self.client.session_transaction() as flask_session:
            flask_session["usuario"] = "Juan"
            flask_session["rol"] = "cliente"

        response = self.client.post("/codigo", data={"cuenta": "Netflix"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Debés esperar 1 día(s)", response.get_data(as_text=True))
        with app_module.app.app_context():
            self.assertEqual(app_module.Codigo.query.filter_by(cuenta="Netflix").count(), 2)


if __name__ == "__main__":
    unittest.main()
