"""Test cases: per-project numbering, steps, labels, filters, archive, and the automation link."""
import pytest

URL = "/api/v1/projects/1/cases"
KEY = "a" * 64
ALL_ROLES = ("owner", "admin", "member", "viewer", "billing_manager")


@pytest.fixture
def member(project_role):
    project_role("member")


def create(client, auth, **body):
    payload = {"title": "Pays with a stored card", **body}
    response = client.post(URL, json=payload, headers=auth())
    assert response.status_code == 201, response.text
    return response.json()


def test_a_case_gets_the_next_number_and_keeps_what_was_sent(client, auth, member):
    first = create(client, auth)
    second = create(client, auth, title="Applies a coupon", description="A logged-in shopper",
                    steps=[{"action": "Open the cart", "expected": "The total shows"}],
                    labels=["Checkout", "smoke"], priority="high")
    assert (first["number"], second["number"]) == (1, 2)
    assert second["key"] == "TC-2"
    assert second["labels"] == ["checkout", "smoke"]              # lower-cased, sorted
    assert second["steps"] == [{"action": "Open the cart", "expected": "The total shows"}]
    assert (second["priority"], second["status"]) == ("high", "draft")
    assert second["created_by"] == 1 and second["updated_at"] is None


def test_numbers_are_per_project_and_never_reused(client, auth, project_role):
    project_role("member", project_id=1)
    project_role("member", project_id=2)
    create(client, auth)
    other = client.post("/api/v1/projects/2/cases", json={"title": "x"}, headers=auth()).json()
    assert other["number"] == 1
    client.patch(f"{URL}/1", json={"status": "archived"}, headers=auth())
    assert create(client, auth)["number"] == 2


@pytest.mark.parametrize("body", [
    {"title": ""},
    {"title": "x" * 201},
    {"title": "x", "labels": ["has space"]},
    {"title": "x", "labels": ["l"] * 21},
    {"title": "x", "steps": [{"action": "a", "expected": "b"}] * 51},
    {"title": "x", "priority": "urgent"},
    {"title": "x", "automated_test_key": "not-hex"},
    {"title": "x", "number": 7},
])
def test_invalid_cases_are_422(client, auth, member, body):
    assert client.post(URL, json=body, headers=auth()).status_code == 422


def test_edit_changes_only_what_is_sent_and_records_who(client, auth, member):
    create(client, auth, labels=["smoke"], priority="low")
    response = client.patch(f"{URL}/1", json={"title": "Pays with a saved card", "status": "ready"}, headers=auth(2))
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["title"], body["status"], body["priority"], body["labels"]) == ("Pays with a saved card", "ready", "low", ["smoke"])
    assert body["updated_by"] == 2 and body["updated_at"] is not None


def test_keeping_one_label_and_adding_another_succeeds(client, auth, member):
    create(client, auth, labels=["a", "b"])
    response = client.patch(f"{URL}/1", json={"labels": ["a", "c"]}, headers=auth())
    assert response.status_code == 200, response.text
    assert response.json()["labels"] == ["a", "c"]
    assert client.get(f"{URL}/1", headers=auth()).json()["labels"] == ["a", "c"]


def test_link_and_unlink_an_automated_test(client, auth, member):
    create(client, auth)
    linked = client.patch(f"{URL}/1", json={"automated_test_key": KEY.upper(), "automated_name": "checkout › Cart › pays"},
                          headers=auth()).json()
    assert (linked["automated_test_key"], linked["automated_name"]) == (KEY, "checkout › Cart › pays")
    unlinked = client.patch(f"{URL}/1", json={"automated_test_key": None}, headers=auth()).json()
    assert (unlinked["automated_test_key"], unlinked["automated_name"]) == (None, None)


def test_list_filters_search_labels_status_and_hides_archived(client, auth, member):
    create(client, auth, title="Pays with card", labels=["checkout", "smoke"], priority="high")
    create(client, auth, title="Pays with voucher", labels=["checkout"])
    create(client, auth, title="Logs in", labels=["auth", "smoke"])
    create(client, auth, title="Old payment flow", labels=["checkout"])
    client.patch(f"{URL}/4", json={"status": "archived"}, headers=auth())

    def numbers(query=""):
        body = client.get(f"{URL}?{query}", headers=auth()).json()
        return body["total"], [c["number"] for c in body["items"]]

    assert numbers() == (3, [1, 2, 3])
    assert numbers("search=PAYS") == (2, [1, 2])
    assert numbers("label=smoke") == (2, [1, 3])
    assert numbers("label=checkout&label=smoke") == (1, [1])
    assert numbers("priority=high") == (1, [1])
    assert numbers("status=archived") == (1, [4])
    assert numbers("include_archived=true") == (4, [1, 2, 3, 4])
    assert numbers("limit=2&offset=1") == (3, [2, 3])


def test_search_treats_wildcards_literally(client, auth, member):
    create(client, auth, title="100% coverage")
    create(client, auth, title="Other")
    assert client.get(f"{URL}?search=%25", headers=auth()).json()["total"] == 1


def test_labels_in_use_with_counts(client, auth, member):
    create(client, auth, labels=["checkout", "smoke"])
    create(client, auth, labels=["smoke"])
    create(client, auth, labels=["gone"])
    client.patch(f"{URL}/3", json={"status": "archived"}, headers=auth())
    body = client.get("/api/v1/projects/1/case-labels", headers=auth()).json()
    assert body == [{"label": "checkout", "count": 1}, {"label": "smoke", "count": 2}]


def test_missing_case_is_404(client, auth, member):
    assert client.get(f"{URL}/99", headers=auth()).status_code == 404
    assert client.patch(f"{URL}/99", json={"title": "x"}, headers=auth()).status_code == 404


@pytest.mark.parametrize("role", ALL_ROLES)
def test_every_role_reads(client, auth, project_role, role):
    project_role(role)
    assert client.get(URL, headers=auth()).status_code == 200


@pytest.mark.parametrize("role", ("viewer", "billing_manager"))
def test_viewers_cannot_write(client, auth, project_role, role):
    project_role(role)
    assert client.post(URL, json={"title": "x"}, headers=auth()).status_code == 403


def test_another_projects_cases_stay_hidden(client, auth, project_role):
    project_role(project_id=3, status_code=404, body={"detail": "Project not found"})
    assert client.get("/api/v1/projects/3/cases", headers=auth()).status_code == 404


def test_no_token_is_401(client):
    assert client.get(URL).status_code == 401


@pytest.mark.parametrize("claims", [{"purpose": "mfa"}, {"token_type": "service"}, {"purpose": "password_reset"}])
def test_non_access_tokens_are_401_on_user_routes(client, http, claims):
    from conftest import make_token
    headers = {"Authorization": f"Bearer {make_token(1, **claims)}"}
    assert client.get(URL, headers=headers).status_code == 401
    assert not http.calls


def test_a_project_pending_deletion_is_404(client, auth, project_role):
    project_role(status_code=410, body={"detail": {"code": "pending_deletion"}})
    assert client.get("/api/v1/projects/1/cases", headers=auth()).status_code == 404
