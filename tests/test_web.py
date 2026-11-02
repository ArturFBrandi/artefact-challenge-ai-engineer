import threading

import pytest
from fastapi.testclient import TestClient

from emporio.llm.fake import tool_step
from emporio.web.app import COOKIE, MAX_MESSAGE_LENGTH, create_app


def client_for(service) -> TestClient:
    return TestClient(create_app(service), raise_server_exceptions=False)


@pytest.fixture
def client(make_service):
    service, _ = make_service(["Oi!", "Tudo bem!"])
    return client_for(service)


def test_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Empório da Música" in response.text
    assert "innerHTML" not in response.text


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_message_round_trip(client):
    body = client.post("/api/messages", json={"message": "oi"}).json()
    assert body["reply"] == "Oi!"
    assert body["turn"] == 1
    assert body["debug"]["outcome"] == "answered"


def test_session_cookie_is_http_only(client):
    response = client.post("/api/messages", json={"message": "oi"})
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert COOKIE not in response.text


def test_conversation_continues_and_reloads(client):
    client.post("/api/messages", json={"message": "oi"})
    second = client.post("/api/messages", json={"message": "tudo bem?"}).json()
    assert second["turn"] == 2
    messages = client.get("/api/history").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]


def test_two_browsers_are_isolated(make_service):
    service, _ = make_service(["Da primeira", "Da segunda"])
    first, second = client_for(service), client_for(service)
    first.post("/api/messages", json={"message": "segredo"})
    assert second.get("/api/history").json()["messages"] == []
    assert second.post("/api/messages", json={"message": "oi"}).json()["turn"] == 1


def test_verified_identity_stays_in_its_browser(make_service):
    verify = '{"order_id": 8, "phone": "(67) 99654-7821"}'
    service, _ = make_service(
        [
            tool_step("verify_customer", verify),
            "Ok!",
            tool_step("get_order", '{"order_id": 8}'),
            "?",
        ]
    )
    first, second = client_for(service), client_for(service)
    first.post("/api/messages", json={"message": "pedido 8"})
    body = second.post("/api/messages", json={"message": "pedido 8"}).json()
    assert body["debug"]["tools"][0]["ok"] is False


def test_forged_cookie_gets_a_new_session(make_service):
    service, _ = make_service(["Oi!"])
    client = client_for(service)
    client.cookies.set(COOKIE, "forged")
    assert client.get("/api/history").json()["messages"] == []
    response = client.post("/api/messages", json={"message": "oi"})
    assert "forged" not in response.headers["set-cookie"]


def test_reset_starts_a_new_conversation(client):
    client.post("/api/messages", json={"message": "oi"})
    client.post("/api/reset")
    client.cookies.clear()
    assert client.get("/api/history").json()["messages"] == []


@pytest.mark.parametrize(
    "payload",
    [{"message": ""}, {"message": "   "}, {"message": "x" * (MAX_MESSAGE_LENGTH + 1)}, {}],
)
def test_invalid_messages_share_one_error_shape(client, payload):
    response = client.post("/api/messages", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_message"


def test_unexpected_errors_hide_details(make_service):
    def explode(_messages):
        raise RuntimeError("secret internal detail")

    service, _ = make_service([explode])
    response = client_for(service).post("/api/messages", json={"message": "oi"})
    assert response.status_code == 500
    assert "secret" not in response.text
    assert response.json()["error"]["code"] == "internal_error"


def test_concurrent_turn_on_one_session_is_refused(make_service):
    entered, release = threading.Event(), threading.Event()

    def slow(_messages):
        from emporio.llm.fake import FakeLLMProvider

        entered.set()
        release.wait(5)
        return FakeLLMProvider._final("Pronta")

    service, _ = make_service(["Primeira", slow])
    client = client_for(service)
    client.post("/api/messages", json={"message": "oi"})

    results = []
    worker = threading.Thread(
        target=lambda: results.append(client.post("/api/messages", json={"message": "lenta"}))
    )
    worker.start()
    assert entered.wait(5)
    second = client.post("/api/messages", json={"message": "de novo"})
    release.set()
    worker.join()
    assert second.status_code == 409
    assert results[0].status_code == 200


def test_script_in_a_reply_stays_as_data(make_service):
    service, _ = make_service(["<script>alert(1)</script>"])
    body = client_for(service).post("/api/messages", json={"message": "oi"}).json()
    assert body["reply"] == "<script>alert(1)</script>"
    page = client_for(service).get("/").text
    assert "textContent" in page
