"""GET/PUT/DELETE /ci-target. GitHub is stubbed (the `github` fixture); the token never comes back."""
import logging
from datetime import datetime, timezone

import pytest

from src.casebook.models import CiTarget, CiTargetEvent, RunRequest

URL = "/api/v1/projects/1/ci-target"
TOKEN = "github_pat_11AAAAAAA0" + "b" * 30 + "a1b2"
BODY = {"repo": "acme/obt", "workflow": "qeos-run.yml", "ref": "main", "token": TOKEN}
NOT_CONFIGURED = "Running tests from QEOS is not configured on this server"


@pytest.fixture
def owner(project_role, secrets_key):
    project_role("owner")


def put(client, auth, **changes):
    return client.put(URL, json={**BODY, **changes}, headers=auth())


def github_calls(http):
    return [c for c in http.calls if c.request.url.host == "api.github.com"]


def test_save_checks_github_stores_ciphertext_and_shows_last4_only(client, auth, owner, github, db, caplog):
    caplog.set_level(logging.DEBUG)
    github.check()
    r = put(client, auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True and body["configured"] is True
    assert (body["repo"], body["workflow"], body["ref"], body["token_last4"]) == ("acme/obt", "qeos-run.yml", "main", "a1b2")
    assert body["token_expires_at"].startswith("2027-03-12")
    assert body["last_change"]["action"] == "created" and body["last_change"]["user_id"] == 1
    assert TOKEN not in r.text and TOKEN not in client.get(URL, headers=auth()).text
    assert TOKEN not in db.get(CiTarget, 1).token_encrypted
    assert TOKEN not in caplog.text


def test_a_token_without_expiry_stores_null(client, auth, owner, github):
    github.check(expires=None)
    assert put(client, auth).json()["token_expires_at"] is None


@pytest.mark.parametrize("status, message", [
    (401, "token invalid or expired"),
    (403, "token has no Actions access to this repository. Check that the token's resource owner is \"acme\" (the "
          "repository's owner, not your own account unless you own it), that it can reach this repository with "
          "Actions: Read and write, and that \"acme\" has approved it"),
    (404, "repository or workflow not found. The workflow file must exist on the repository's default branch")])
def test_github_refusals_are_422_with_a_specific_message(client, auth, owner, github, db, status, message):
    github.check(status=status)
    r = put(client, auth)
    assert r.status_code == 422 and r.json()["detail"] == message
    assert db.get(CiTarget, 1) is None and db.query(CiTargetEvent).count() == 0


def test_a_rate_limit_is_503_with_retry_after_and_stores_nothing(client, auth, owner, github, db):
    github.check(status=429, headers={"retry-after": "30"})
    r = put(client, auth)
    assert r.status_code == 503 and r.json()["detail"] == "GitHub rate limit, try again in 30 s"
    assert r.headers["retry-after"] == "30" and db.get(CiTarget, 1) is None


@pytest.mark.parametrize("changes", [
    {"repo": "acme"}, {"repo": "acme/obt/x"}, {"repo": "acme/.."}, {"repo": "a b/c"},
    {"workflow": "run.json"}, {"workflow": "../run.yml"},
    {"ref": "-x"}, {"ref": "a..b"}, {"ref": "a\x00b"}, {"ref": "x" * 256},
    {"ref": "a b"}, {"ref": "a\nb"}, {"ref": "a\tb"}, {"ref": "a\x7fb"}, {"ref": "a~b"}, {"ref": "a^b"},
    {"ref": "a:b"}, {"ref": "a?b"}, {"ref": "a*b"}, {"ref": "a[b"}, {"ref": "a\\b"}, {"ref": "a@{b"},
    {"ref": "a//b"}, {"ref": "/a"}, {"ref": "a/"}, {"ref": "a."}, {"ref": "a.lock"}, {"ref": "a/b.lock"}])
def test_bad_names_are_422_before_github_is_asked(client, auth, owner, http, changes):
    assert put(client, auth, **changes).status_code == 422
    assert not github_calls(http)


def test_a_pasted_token_with_whitespace_is_trimmed(client, auth, owner, github):
    workflow_route = github.check()
    r = put(client, auth, token=f"  {TOKEN}\r\n")
    assert r.status_code == 200, r.text
    assert r.json()["token_last4"] == "a1b2"
    assert workflow_route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


def test_a_malformed_token_is_422_and_not_echoed(client, auth, owner, http):
    bad = TOKEN + "!"
    r = put(client, auth, token=bad)
    assert r.status_code == 422
    assert bad not in r.text and TOKEN not in r.text
    assert not github_calls(http)


def test_the_first_save_needs_a_token(client, auth, owner, github):
    github.check()
    r = client.put(URL, json={"repo": "acme/obt"}, headers=auth())
    assert r.status_code == 422 and "token" in r.json()["detail"]


def test_events_for_create_update_token_replacement_and_delete(client, auth, owner, github, db):
    github.check()
    assert put(client, auth).status_code == 200
    updated = client.put(URL, json={"repo": "acme/obt", "ref": "release"}, headers=auth())  # keeps the stored token
    assert updated.status_code == 200 and updated.json()["ref"] == "release" and updated.json()["token_last4"] == "a1b2"
    assert put(client, auth, token="github_pat_" + "c" * 30 + "zzzz").json()["token_last4"] == "zzzz"
    assert client.delete(URL, headers=auth()).status_code == 204
    assert [e.action for e in db.query(CiTargetEvent).order_by(CiTargetEvent.id)] == [
        "created", "updated", "token_replaced", "deleted"]
    after = client.get(URL, headers=auth()).json()
    assert after["configured"] is False and after["repo"] is None and after["last_change"]["action"] == "deleted"


@pytest.mark.parametrize("role", ["member", "viewer", "billing_manager"])
def test_only_owners_and_admins_change_it_but_every_role_reads(client, auth, project_role, secrets_key, github, role):
    project_role(role)
    github.check()
    assert put(client, auth).status_code == 403
    assert client.delete(URL, headers=auth()).status_code == 403
    assert client.get(URL, headers=auth()).status_code == 200


def test_an_admin_may_save_and_disconnect(client, auth, project_role, secrets_key, github):
    project_role("admin")
    github.check()
    assert put(client, auth).status_code == 200
    assert client.delete(URL, headers=auth()).status_code == 204


def test_without_a_secrets_key_get_says_unavailable_and_put_is_503(client, auth, project_role, no_secrets_key, http):
    project_role("owner")
    assert client.get(URL, headers=auth()).json()["available"] is False
    r = put(client, auth)
    assert r.status_code == 503 and r.json()["detail"] == NOT_CONFIGURED
    assert TOKEN not in r.text and not github_calls(http)


def test_delete_without_a_target_is_404(client, auth, owner):
    assert client.delete(URL, headers=auth()).status_code == 404


def test_delete_is_409_while_a_run_is_active(client, auth, owner, github, db):
    github.check()
    put(client, auth)
    db.add(RunRequest(project_id=1, requested_by=1, requested_at=datetime.now(timezone.utc), selection=[], status="running"))
    db.commit()
    github.runs()  # the refresh before the check finds no run yet: still active
    assert client.delete(URL, headers=auth()).status_code == 409
    assert db.get(CiTarget, 1) is not None


def test_a_422_never_echoes_the_body_so_a_valid_token_without_repo_stays_secret(client, auth, owner, http):
    r = client.put(URL, json={"token": TOKEN}, headers=auth())
    assert r.status_code == 422
    assert TOKEN not in r.text and "input" not in r.text
    assert not github_calls(http)


@pytest.mark.parametrize("ref", ["main", "release/1.2", "feature/x_y-z", "v1.0.0", "a@b", "ünï/cødé", "x" * 255])
def test_ordinary_branch_names_are_accepted(client, auth, owner, github, ref):
    github.check()
    r = put(client, auth, ref=ref)
    assert r.status_code == 200, r.text
    assert r.json()["ref"] == ref


def seed_active(db, **fields):
    row = RunRequest(project_id=1, requested_by=1, requested_at=datetime.now(timezone.utc), selection=[],
                     status="running", github_run_id=501, **fields)
    db.add(row)
    db.commit()
    return row


def test_delete_refreshes_a_run_that_ended_on_github_and_then_disconnects(client, auth, owner, github, db):
    github.check()
    put(client, auth)
    row = seed_active(db)
    github.run(github.run_body(501, row.id, status="completed", conclusion="success"))
    assert client.delete(URL, headers=auth()).status_code == 204
    assert db.get(CiTarget, 1) is None
    db.refresh(row)
    assert row.status == "completed"


def test_delete_is_409_when_github_says_the_run_is_still_active(client, auth, owner, github, db):
    github.check()
    put(client, auth)
    row = seed_active(db)
    github.run(github.run_body(501, row.id, status="in_progress"))
    assert client.delete(URL, headers=auth()).status_code == 409
    assert db.get(CiTarget, 1) is not None


# --- Fix wave A6 ---

def test_a_concurrent_first_save_retries_as_an_update(client, auth, owner, github, db, monkeypatch):
    from src.casebook.service import ci_target_service
    github.check()
    assert put(client, auth).status_code == 200  # the other request's row
    real, calls = ci_target_service.get_target, []

    def blind_first_time(session, project_id):
        calls.append(1)
        return None if len(calls) == 1 else real(session, project_id)

    monkeypatch.setattr(ci_target_service, "get_target", blind_first_time)
    r = put(client, auth, ref="release")
    assert r.status_code == 200, r.text
    assert r.json()["ref"] == "release" and db.query(CiTarget).count() == 1
    assert [e.action for e in db.query(CiTargetEvent).order_by(CiTargetEvent.id)] == ["created", "token_replaced"]


def test_an_empty_token_keeps_the_stored_one(client, auth, owner, github, db):
    github.check()
    put(client, auth)
    stored = db.get(CiTarget, 1).token_encrypted
    r = put(client, auth, token="", ref="dev")
    assert r.status_code == 200 and r.json()["token_last4"] == "a1b2" and r.json()["ref"] == "dev"
    db.expire_all()
    assert db.get(CiTarget, 1).token_encrypted == stored
    assert db.query(CiTargetEvent).order_by(CiTargetEvent.id.desc()).first().action == "updated"


@pytest.mark.parametrize("failure", [500, 502])
def test_a_github_5xx_is_502_and_stores_nothing(client, auth, owner, github, db, failure):
    github.check(status=failure)
    r = put(client, auth)
    assert r.status_code == 502
    assert db.get(CiTarget, 1) is None and db.query(CiTargetEvent).count() == 0


def test_an_expiry_header_with_an_offset_is_stored_in_utc(client, auth, owner, github):
    github.check(expires="2027-03-12 02:00:00 +0200")
    assert put(client, auth).json()["token_expires_at"].startswith("2027-03-12T00:00:00")


def test_a_garbage_expiry_header_stores_null(client, auth, owner, github):
    github.check(expires="next tuesday")
    r = put(client, auth)
    assert r.status_code == 200 and r.json()["token_expires_at"] is None


def test_another_endpoints_422_keeps_loc_and_msg_and_drops_the_input(client, auth, owner):
    r = client.put(URL, json={"repo": "acme", "token": TOKEN}, headers=auth())
    assert r.status_code == 422
    error = r.json()["detail"][0]
    assert error["loc"] == ["body", "repo"] and error["msg"]
    assert "input" not in error and "ctx" not in error and TOKEN not in r.text
