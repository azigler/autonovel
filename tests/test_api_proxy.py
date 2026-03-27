"""Tests for AO3 API proxy — all test cases from spec Section 5.

All tests run against mock mode (MOCK_MODE=true). Queue tests use a
temporary publish_queue/ directory via the _clean_queue fixture.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

# =========================================================================
# TC-01: Browse -- list fandom works (happy path)
# =========================================================================


def test_browse_fandom_works(client: TestClient) -> None:
    resp = client.get(
        "/fandoms/Harry%20Potter/works", params={"sort": "kudos", "page": 1}
    )
    assert resp.status_code == 200

    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    work_10001 = next((w for w in data if w["id"] == 10001), None)
    assert work_10001 is not None
    assert work_10001["title"] == "The Stars Between Us"
    assert work_10001["stats"]["kudos"] == 1842

    # Verify sorted by kudos descending
    kudos_values = [w["stats"]["kudos"] for w in data]
    assert kudos_values == sorted(kudos_values, reverse=True)


# =========================================================================
# TC-02: Browse -- list tag works (happy path)
# =========================================================================


def test_browse_tag_works(client: TestClient) -> None:
    resp = client.get("/tags/Slow%20Burn/works", params={"sort": "kudos"})
    assert resp.status_code == 200

    data = resp.json()
    ids = [w["id"] for w in data]
    assert 10001 in ids  # tagged "Slow Burn"
    assert 10002 not in ids  # not tagged "Slow Burn"


# =========================================================================
# TC-03: Browse -- get work detail (happy path)
# =========================================================================


def test_get_work_detail(client: TestClient) -> None:
    resp = client.get("/works/10001")
    assert resp.status_code == 200

    data = resp.json()
    assert data["id"] == 10001
    assert len(data["chapters"]) >= 2
    assert isinstance(data["body"], str)
    assert len(data["body"]) > 0
    assert data["chapter_count"] == 12


# =========================================================================
# TC-04: Browse -- work not found
# =========================================================================


def test_error_work_not_found(client: TestClient) -> None:
    resp = client.get("/works/99999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Work not found"


# =========================================================================
# TC-05: Search -- query match (happy path)
# =========================================================================


def test_search_query_match(client: TestClient) -> None:
    resp = client.get("/search", params={"query": "stars", "sort": "kudos"})
    assert resp.status_code == 200

    data = resp.json()
    ids = [w["id"] for w in data]
    assert 10001 in ids  # "The Stars Between Us" matches "stars"


# =========================================================================
# TC-06: Search -- no results
# =========================================================================


def test_search_no_results(client: TestClient) -> None:
    resp = client.get(
        "/search", params={"query": "xyznonexistent", "fandom": "Nonexistent"}
    )
    assert resp.status_code == 200
    assert resp.json() == []


# =========================================================================
# TC-07: Metrics -- work stats (happy path)
# =========================================================================


def test_work_stats(client: TestClient) -> None:
    resp = client.get("/works/10001/stats")
    assert resp.status_code == 200

    data = resp.json()
    assert data["kudos"] == 1842
    assert data["hits"] == 23400
    assert data["bookmarks"] == 312
    assert data["subscriptions"] == 189
    assert data["comment_count"] == 97


# =========================================================================
# TC-08: Metrics -- user stats (happy path)
# =========================================================================


def test_user_stats(client: TestClient) -> None:
    resp = client.get("/users/nightowl_writes/stats")
    assert resp.status_code == 200

    data = resp.json()
    assert data["username"] == "nightowl_writes"
    assert data["total_works"] == 2
    assert data["total_kudos"] == 2366  # 1842 + 524
    assert data["total_word_count"] == 54520  # 48320 + 6200


# =========================================================================
# TC-09: Metrics -- user not found
# =========================================================================


def test_error_user_not_found(client: TestClient) -> None:
    resp = client.get("/users/nonexistent_user/stats")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "User not found"


# =========================================================================
# TC-10: Comments -- work comments (happy path)
# =========================================================================


def test_work_comments(client: TestClient) -> None:
    resp = client.get("/works/10001/comments")
    assert resp.status_code == 200

    data = resp.json()
    comment_ids = [c["id"] for c in data]
    assert 90001 in comment_ids
    assert 90002 in comment_ids
    assert 90003 in comment_ids

    for comment in data:
        assert "id" in comment
        assert "author" in comment
        assert "body" in comment
        assert "is_reply" in comment
        assert "chapter_id" in comment


# =========================================================================
# TC-11: Comments -- chapter-level filtering
# =========================================================================


def test_chapter_comments(client: TestClient) -> None:
    resp = client.get("/works/10001/chapters/50001/comments")
    assert resp.status_code == 200

    data = resp.json()
    comment_ids = [c["id"] for c in data]
    assert 90001 in comment_ids
    assert 90002 in comment_ids
    assert 90003 not in comment_ids  # on chapter 50002


# =========================================================================
# TC-12: Publish queue -- create, retrieve, confirm lifecycle
# =========================================================================


def test_publish_queue_lifecycle(client: TestClient) -> None:
    # Step 1: create
    create_resp = client.post(
        "/works",
        json={
            "title": "Test Work",
            "fandom": "Test Fandom",
            "body": "Chapter text",
            "rating": "Not Rated",
        },
    )
    assert create_resp.status_code == 201
    item = create_resp.json()
    assert item["status"] == "pending"
    assert item["ao3_work_id"] is None

    queue_id = item["queue_id"]
    # Step 2: queue_id is 12-char hex
    assert re.fullmatch(r"[0-9a-f]{12}", queue_id)

    # Step 3: retrieve
    get_resp = client.get(f"/queue/{queue_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["queue_id"] == queue_id

    # Step 4: confirm published
    patch_resp = client.patch(f"/queue/{queue_id}", json={"ao3_work_id": 12345})
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["status"] == "published"
    assert patched["ao3_work_id"] == 12345
    assert patched["published_at"] is not None


# =========================================================================
# TC-13: Publish queue -- list and delete (reject)
# =========================================================================


def test_publish_queue_list_and_delete(client: TestClient) -> None:
    # Create two items
    resp_a = client.post(
        "/works",
        json={"title": "Work A", "fandom": "F", "body": "text A"},
    )
    assert resp_a.status_code == 201
    id_a = resp_a.json()["queue_id"]

    resp_b = client.post(
        "/works",
        json={"title": "Work B", "fandom": "F", "body": "text B"},
    )
    assert resp_b.status_code == 201
    id_b = resp_b.json()["queue_id"]

    # List -- both present, sorted by created_at descending
    list_resp = client.get("/queue")
    assert list_resp.status_code == 200
    queue_ids = [i["queue_id"] for i in list_resp.json()]
    assert id_a in queue_ids
    assert id_b in queue_ids

    # Verify descending order by created_at
    items = list_resp.json()
    timestamps = [i["created_at"] for i in items]
    assert timestamps == sorted(timestamps, reverse=True)

    # Delete item A
    del_resp = client.delete(f"/queue/{id_a}")
    assert del_resp.status_code == 204

    # List again -- only B remains
    list_resp2 = client.get("/queue")
    queue_ids2 = [i["queue_id"] for i in list_resp2.json()]
    assert id_a not in queue_ids2
    assert id_b in queue_ids2


# =========================================================================
# TC-14: Publish queue -- item not found
# =========================================================================


def test_error_queue_item_not_found(client: TestClient) -> None:
    resp = client.get("/queue/nonexistent123")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Queue item not found"


# =========================================================================
# TC-15: Publish queue -- delete nonexistent item
# =========================================================================


def test_error_queue_delete_nonexistent(client: TestClient) -> None:
    resp = client.delete("/queue/nonexistent123")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Queue item not found"


# =========================================================================
# TC-16: Publish queue -- PATCH nonexistent item
# =========================================================================


def test_error_queue_patch_nonexistent(client: TestClient) -> None:
    resp = client.patch("/queue/nonexistent123", json={"ao3_work_id": 99999})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Queue item not found"


# =========================================================================
# TC-17: Validation -- malformed publish request
# =========================================================================


def test_error_malformed_publish_request(client: TestClient) -> None:
    resp = client.post("/works", json={"title": "Missing body and fandom"})
    assert resp.status_code == 422
    errors = resp.json()["detail"]
    error_fields = [e["loc"][-1] for e in errors]
    assert "fandom" in error_fields
    assert "body" in error_fields


# =========================================================================
# TC-18: Validation -- invalid rating enum
# =========================================================================


def test_error_invalid_rating_enum(client: TestClient) -> None:
    resp = client.post(
        "/works",
        json={
            "title": "Bad Rating",
            "fandom": "Test",
            "body": "text",
            "rating": "Super Explicit",
        },
    )
    assert resp.status_code == 422


# =========================================================================
# TC-19: Mock mode -- consistent data across calls
# =========================================================================


def test_mock_mode_deterministic(client: TestClient) -> None:
    resp1 = client.get("/works/10001")
    resp2 = client.get("/works/10001")
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    data1 = resp1.json()
    data2 = resp2.json()
    assert data1["id"] == data2["id"]
    assert data1["title"] == data2["title"]
    assert data1["authors"] == data2["authors"]
    assert data1["stats"]["kudos"] == data2["stats"]["kudos"]
    assert len(data1["chapters"]) == len(data2["chapters"])


# =========================================================================
# TC-24: User works -- empty list for unknown user
# =========================================================================


def test_user_works_unknown_user(client: TestClient) -> None:
    resp = client.get("/users/nonexistent_user/works")
    assert resp.status_code == 200
    assert resp.json() == []


# =========================================================================
# TC-25: Browse -- pagination
# =========================================================================


def test_edge_browse_pagination_out_of_range(client: TestClient) -> None:
    resp = client.get("/fandoms/Harry%20Potter/works", params={"page": 999})
    assert resp.status_code == 200
    assert resp.json() == []


# =========================================================================
# Additional edge cases
# =========================================================================


def test_edge_comments_nonexistent_work(client: TestClient) -> None:
    """Comments on a nonexistent work return an empty list, not 404."""
    resp = client.get("/works/99999/comments")
    assert resp.status_code == 200
    assert resp.json() == []


def test_browse_fandom_no_match(client: TestClient) -> None:
    """Fandom that matches no seed works returns empty list."""
    resp = client.get("/fandoms/Nonexistent%20Fandom/works")
    assert resp.status_code == 200
    assert resp.json() == []


def test_user_works_known_user(client: TestClient) -> None:
    """User works endpoint returns works for a known author."""
    resp = client.get("/users/nightowl_writes/works")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    ids = [w["id"] for w in data]
    assert 10001 in ids
    assert 10003 in ids


def test_work_detail_fields_complete(client: TestClient) -> None:
    """WorkDetail response includes all expected fields."""
    resp = client.get("/works/10001")
    assert resp.status_code == 200
    data = resp.json()
    for field in (
        "id",
        "title",
        "authors",
        "fandoms",
        "tags",
        "rating",
        "summary",
        "word_count",
        "chapter_count",
        "stats",
        "chapters",
        "body",
    ):
        assert field in data


def test_search_with_fandom_filter(client: TestClient) -> None:
    """Search filtered by fandom returns only matching works."""
    resp = client.get(
        "/search", params={"fandom": "Good Omens", "sort": "kudos"}
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [w["id"] for w in data]
    assert 10003 in ids
    assert 10001 not in ids


def test_work_stats_not_found(client: TestClient) -> None:
    """Stats for a nonexistent work return 404."""
    resp = client.get("/works/99999/stats")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Work not found"
