from conftest import PASSWORD, login


def test_wrong_password_rejected(client):
    r = login(client, "nope")
    assert r.status_code == 401
    assert "whoop_session" not in r.cookies


def test_login_sets_cookie_and_grants_access(client):
    assert client.get("/api/data").status_code == 401
    assert client.get("/", follow_redirects=False).status_code == 303
    r = login(client)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert client.get("/api/data").status_code == 200
    assert 'id="syncBtn"' in client.get("/").text  # dashboard shell renders once logged in


def test_lockout_after_five_failures(client):
    for _ in range(5):
        assert login(client, "bad").status_code == 401
    assert login(client, PASSWORD).status_code == 429  # even the right password is locked out


def test_logout_clears_cookie(client):
    login(client)
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/api/data").status_code == 401


def test_healthz_is_public(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_tampered_cookie_is_ignored(client):
    client.cookies.set("whoop_session", "eyJhdXRoIjp0cnVlfQ.forged.signature")
    assert client.get("/api/data").status_code == 401
