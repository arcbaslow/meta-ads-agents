import hashlib
import hmac
import inspect
import json
import logging
import threading

import meta_mcp
import meta_utils
import pytest
import requests

TOKEN = "EAAtesttoken123abc"
SECRET = "appsecret456xyz"
OTHER_TOKEN = "EAAothertoken789"


COMMON_FIELDS = {"id", "account_id", "status", "effective_status", "updated_time", "name"}
TYPE_FIELDS = {
    "campaign": COMMON_FIELDS | {"objective", "daily_budget", "lifetime_budget"},
    "ad_set": COMMON_FIELDS | {"campaign_id", "optimization_goal", "daily_budget", "lifetime_budget",
                               "bid_amount", "end_time"},
    "ad": COMMON_FIELDS | {"adset_id"},
}


class FakeGraph:
    def __init__(self):
        self.calls = []
        self.names = {"Existing"}
        live = {"status": "ACTIVE", "effective_status": "ACTIVE", "updated_time": "t1"}
        self.objects = {
            "901": {"type": "campaign", "account_id": "111", **live, "objective": "OUTCOME_SALES",
                    "daily_budget": "1000", "name": "Old"},
            "902": {"type": "ad", "account_id": "111", **live, "adset_id": "1"},
            "903": {"type": "ad", "account_id": "111", **live, "adset_id": "1"},
            "904": {"type": "ad", "account_id": "111", **live, "adset_id": "1"},
            "990": {"type": "ad", "account_id": "999", **live, "adset_id": "1"},
            "123": {"type": "campaign", "account_id": "111", **live, "objective": "OUTCOME_SALES"},
            "124": {"type": "campaign", "account_id": "999", **live, "objective": "OUTCOME_SALES"},
            "801": {"type": "ad_set", "account_id": "111", **live, "campaign_id": "123",
                    "optimization_goal": "REACH", "end_time": "2020-01-01T00:00:00+0000"},
            "802": {"type": "ad_set", "account_id": "111", **live, "campaign_id": "123",
                    "optimization_goal": "REACH", "end_time": "2099-01-01T00:00:00+0000"},
        }
        self.hashes = {"abc", "h", "h1"}
        self.fail = {}
        self.video_status = "ready"
        self.dry_run_error = None
        self.next_id = 5000

    def __call__(self, method, url, headers, params=None, data=None, files=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "params": params or {},
                           "data": data or {}, "files": files, "timeout": timeout})
        path = url.split(f"/{meta_utils.API_VERSION}/", 1)[1]
        params, data = params or {}, data or {}
        if method == "GET":
            if path == "act_111":
                return 200, {"id": "act_111", "currency": "USD", "account_status": 1}
            if path == "act_111/campaigns":
                name = json.loads(params["filtering"])[0]["value"]
                return 200, {"data": [{"id": "1"}] if name in self.names else []}
            assert "ids" not in params
            if path in self.objects:
                obj, fields = self.objects[path], set(params["fields"].split(","))
                if not fields <= TYPE_FIELDS[obj["type"]]:
                    return 400, {"error": {"code": 100, "message": "Tried accessing nonexisting field"}}
                return 200, {"id": path, **{k: v for k, v in obj.items() if k in fields}}
            if path.isdigit() and params["fields"] != "status":
                return 400, {"error": {"code": 100, "error_subcode": 33}}
            if path == "act_111/adimages":
                return 200, {"data": [{"hash": h} for h in json.loads(params["hashes"])
                                      if h in self.hashes]}
            return 200, {"id": path, "status": {"video_status": self.video_status}}
        if path == "act_111/adimages":
            return 200, {"images": {"a.png": {"hash": "imghash1"}}}
        if path == "act_111/advideos":
            if data["upload_phase"] == "start":
                self.size = int(data["file_size"])
                return 200, {"upload_session_id": "s1", "video_id": "777", "start_offset": "0",
                             "end_offset": str(self.size)}
            if data["upload_phase"] == "transfer":
                return 200, {"start_offset": str(self.size), "end_offset": str(self.size)}
            return 200, {"success": True}
        if "execution_options" in data:
            if isinstance(self.dry_run_error, tuple):
                return self.dry_run_error
            if self.dry_run_error:
                return 400, self.dry_run_error
            return 200, {"success": True}
        failure = self.fail.get(path.split("/")[-1])
        if isinstance(failure, Exception):
            raise failure
        if isinstance(failure, tuple):
            return failure
        if failure:
            return 400, failure
        if path.startswith("act_"):
            self.next_id += 1
            return 200, {"id": str(self.next_id)}
        return 200, {"success": True}

    def posts(self, dry_run=None):
        posts = [c for c in self.calls if c["method"] == "POST"
                 and not c["url"].endswith(("adimages", "advideos"))]
        if dry_run is None:
            return posts
        return [c for c in posts if ("execution_options" in c["data"]) == dry_run]


class Store:
    def __init__(self, root):
        self.root = root
        self.files = {}
        self.discarded = []

    def add(self, handle, content, mime, profile="own"):
        path = self.root / f"{handle}.bin"
        path.write_bytes(content)
        self.files[handle] = {"profile": profile, "account": "act_111", "path": path,
                              "mime_type": mime, "sha256": hashlib.sha256(content).hexdigest(),
                              "size_bytes": len(content)}

    def read(self, handle, profile, account_id):
        record = self.files[handle]
        if record["profile"] != profile or record["account"] != account_id:
            raise KeyError(handle)
        return {key: record[key] for key in ("mime_type", "sha256", "size_bytes", "path")}

    def discard(self, handles):
        self.discarded.extend(handles)


@pytest.fixture
def graph(monkeypatch, tmp_path):
    creds = tmp_path / "meta-credentials.json"
    creds.write_text(json.dumps({"active": "own", "profiles": {
        "own": {"access_token": TOKEN, "app_secret": SECRET, "business_id": "123",
                "ad_accounts": ["act_111"], "pages": ["222"], "instagram_ids": ["333"]},
        "other": {"access_token": OTHER_TOKEN, "business_id": "456",
                  "ad_accounts": ["act_111"], "pages": ["222"], "instagram_ids": []},
    }}))
    monkeypatch.setattr(meta_mcp, "CREDENTIALS_PATH", creds)
    monkeypatch.setattr(meta_mcp, "_pending", {})
    monkeypatch.setattr(meta_mcp, "_media", {})
    fake = FakeGraph()
    monkeypatch.setattr(meta_mcp, "_http", fake)
    return fake


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def allow(profile):
    return None


def refuse(profile):
    return {"error": "writes_disabled", "hint": "Open the write window."}


CAMPAIGN = {"op": "create_campaign", "id": "c", "name": "New", "objective": "OUTCOME_SALES",
            "special_ad_categories": [], "daily_budget": 5000}
AD_SET = {"op": "create_ad_set", "id": "s", "campaign_id": "$c", "name": "Set",
          "optimization_goal": "OFFSITE_CONVERSIONS", "billing_event": "IMPRESSIONS",
          "targeting": {"geo_locations": {"countries": ["KZ"]}}}
CREATIVE = {"op": "create_creative", "id": "cr", "name": "Creative", "page_id": "222",
            "image": {"hash": "abc"}, "message": "Hi", "link": "https://example.com",
            "call_to_action": "LEARN_MORE"}
AD = {"op": "create_ad", "id": "a", "adset_id": "$s", "creative_id": "$cr", "name": "Ad"}
UPDATE = {"op": "update", "resource": "campaign", "object_id": "901", "daily_budget": 2000}
PAUSE = {"op": "set_status", "resource": "ad", "ids": ["902"], "status": "PAUSED"}
FULL = [PAUSE, CAMPAIGN, UPDATE, AD_SET, CREATIVE, AD]


def plan(ops, **kwargs):
    kwargs.setdefault("gate", allow)
    return meta_mcp.plan_changes("act_111", ops, **kwargs)


def test_full_plan_and_apply(graph, caplog):
    result = plan(FULL)
    assert result["dry_run"] is True and result["currency"] == "USD"
    assert result["confirm_expires_in"] == 600
    assert [e["validated"] for e in result["diff"]] == [True, True, True, "at_apply", True, "at_apply"]
    update = result["diff"][2]
    assert (update["from"], update["to"], update["effective_status"]) == (1000, 2000, "ACTIVE")
    assert result["diff"][0]["changes"] == [
        {"object_id": "902", "from": "ACTIVE", "to": "PAUSED", "effective_status": "ACTIVE"}]
    dry = graph.posts(dry_run=True)
    assert len(dry) == len(graph.posts()) == 4
    assert all(c["data"]["execution_options"] == '["validate_only"]' for c in dry)

    graph.calls.clear()
    with caplog.at_level(logging.INFO, logger="meta_mcp"):
        applied = meta_mcp.apply_changes(result["confirm"], gate=allow)
    assert applied == {"dry_run": False, "account_id": "act_111", "outcome": "applied",
                       "created": {"cr": "5001", "c": "5002", "s": "5003", "a": "5004"}, "applied": 6}
    posts = graph.posts()
    assert graph.posts(dry_run=True) == []
    assert [c["url"].rsplit("/", 1)[1] for c in posts] == [
        "adcreatives", "campaigns", "adsets", "ads", "901", "902"]
    for call in posts[1:4]:
        assert call["data"]["status"] == "PAUSED"
    assert posts[2]["data"]["campaign_id"] == "5002"
    assert json.loads(posts[3]["data"]["creative"]) == {"creative_id": "5001"}
    assert posts[3]["data"]["adset_id"] == "5003"
    assert set(posts[4]["data"]) == {"daily_budget", "appsecret_proof"}
    assert "meta write apply_changes act_111 outcome=applied" in caplog.text


def test_creative_story_spec(graph):
    video = {**CREATIVE, "video": {"video_id": "55"}, "cover": {"hash": "h1"},
             "headline": "Title", "instagram_user_id": "333", "url_tags": "utm_source=meta"}
    del video["image"]
    plan([video])
    data = graph.posts()[0]["data"]
    assert data["url_tags"] == "utm_source=meta"
    assert json.loads(data["object_story_spec"]) == {
        "page_id": "222", "instagram_user_id": "333",
        "video_data": {"video_id": "55", "image_hash": "h1", "message": "Hi", "title": "Title",
                       "call_to_action": {"type": "LEARN_MORE", "value": {"link": "https://example.com"}}}}


@pytest.mark.parametrize("ops,account", [
    ([{"op": "delete_campaign", "id": "x"}], "act_111"),
    ([{**CAMPAIGN, "status": "ACTIVE"}], "act_111"),
    ([{**AD_SET, "campaign_id": "$nope"}], "act_111"),
    ([CREATIVE, {**AD_SET, "campaign_id": "$cr"}], "act_111"),
    ([AD_SET, CAMPAIGN], "act_111"),
    ([CAMPAIGN], "act_222"),
    ([{**CREATIVE, "page_id": "999"}], "act_111"),
    ([{**CREATIVE, "instagram_user_id": "999"}], "act_111"),
    ([{**PAUSE, "status": "ACTIVE"}], "act_111"),
    ([{**UPDATE, "name": "x"}], "act_111"),
    ([{**UPDATE, "resource": "ad"}], "act_111"),
    ([{**CAMPAIGN, "daily_budget": 10.5}], "act_111"),
    ([CAMPAIGN, {**CAMPAIGN, "name": "Other"}], "act_111"),
    ([{**CREATIVE, "video": {"video_id": "1"}}], "act_111"),
    ([{**CREATIVE, "image": {"upload": "h"}}], "act_111"),
    ([], "act_111"),
    ([PAUSE] * 51, "act_111"),
    ([{**PAUSE, "ids": [{"a": 1}]}], "act_111"),
    ([{**PAUSE, "ids": [["902"]]}], "act_111"),
    ([{**AD_SET, "campaign_id": "123", "promoted_object": {"page_id": "999"}}], "act_111"),
    ([{"op": ["x"]}], "act_111"),
    ([{"op": {"a": 1}}], "act_111"),
])
def test_refused_before_any_request(graph, ops, account):
    result = meta_mcp.plan_changes(account, ops, gate=allow)
    assert result["error"] == "invalid_argument"
    assert graph.calls == []


def test_target_in_another_account_refused(graph):
    result = plan([{**PAUSE, "ids": ["902", "990"]}])
    assert result["error"] == "invalid_argument"
    assert graph.posts() == []


def test_duplicate_campaign_name_refused(graph):
    result = plan([{**CAMPAIGN, "name": "Existing"}])
    assert result["error"] == "invalid_argument"
    assert graph.posts() == []


def test_token_single_use(graph):
    token = plan([UPDATE])["confirm"]
    assert meta_mcp.apply_changes(token, gate=allow)["outcome"] == "applied"
    graph.calls.clear()
    assert meta_mcp.apply_changes(token, gate=allow)["error"] == "invalid_argument"
    assert meta_mcp.apply_changes("not-a-token", gate=allow)["error"] == "invalid_argument"
    assert graph.calls == []


def test_token_bound_to_tool(graph):
    token = plan([UPDATE])["confirm"]
    digest, state, at, stored = meta_mcp._pending[token]
    other = meta_mcp._digest({"tool": "plan_changes", "account_id": "act_111", "profile": "own",
                              "operations": stored["operations"]})
    meta_mcp._pending[token] = (other, state, at, stored)
    assert meta_mcp.apply_changes(token, gate=allow)["error"] == "invalid_argument"
    assert graph.posts(dry_run=False) == []


def test_token_bound_to_profile(graph):
    token = plan([UPDATE])["confirm"]
    result = meta_mcp.apply_changes(token, profile="other", gate=allow)
    assert result["error"] == "invalid_argument"
    assert graph.posts(dry_run=False) == []


def test_changed_file_under_same_handle_refused(graph, store):
    store.add("h1", b"png-one", "IMAGE_PNG")
    token = plan([{**CREATIVE, "image": {"upload": "h1"}}], uploads=store)["confirm"]
    store.add("h1", b"png-two", "IMAGE_PNG")
    result = meta_mcp.apply_changes(token, gate=allow, uploads=store)
    assert result["error"] == "invalid_argument"
    assert graph.posts(dry_run=False) == []


def test_file_not_matching_record_refused(graph, store):
    store.add("h1", b"png-one", "IMAGE_PNG")
    store.files["h1"]["path"].write_bytes(b"tampered")
    result = plan([{**CREATIVE, "image": {"upload": "h1"}}], uploads=store)
    assert result["error"] == "invalid_argument"
    assert graph.calls == []


def test_changed_state_is_conflict(graph):
    token = plan([UPDATE])["confirm"]
    graph.objects["901"]["updated_time"] = "t2"
    assert meta_mcp.apply_changes(token, gate=allow)["error"] == "conflict"
    assert graph.posts(dry_run=False) == []


def test_new_duplicate_name_at_apply_is_conflict(graph):
    token = plan([CAMPAIGN])["confirm"]
    graph.names.add("New")
    assert meta_mcp.apply_changes(token, gate=allow)["error"] == "conflict"
    assert graph.posts(dry_run=False) == []


def test_gate_refusal_at_apply_keeps_token(graph):
    token = plan([UPDATE])["confirm"]
    graph.calls.clear()
    assert meta_mcp.apply_changes(token, gate=refuse) == refuse("own")
    assert graph.calls == []
    assert meta_mcp.apply_changes(token, gate=allow)["outcome"] == "applied"


def test_gate_receives_resolved_profile(graph):
    seen = []
    token = plan([UPDATE])["confirm"]
    meta_mcp.apply_changes(token, gate=lambda p: seen.append(p))
    assert seen == ["own"]


def test_new_upload_with_refusing_gate_sends_nothing(graph, store):
    store.add("h1", b"png-one", "IMAGE_PNG")
    result = plan([{**CREATIVE, "image": {"upload": "h1"}}], uploads=store, gate=refuse)
    assert result == refuse("own")
    assert [c for c in graph.calls if c["method"] == "POST"] == []


def test_no_upload_store(graph):
    result = plan([{**CREATIVE, "image": {"upload": "h1"}}])
    assert result["error"] == "invalid_argument" and "upload store" in result["hint"]


def test_repeated_plan_uploads_once(graph, store):
    store.add("h1", b"png-one", "IMAGE_PNG")
    op = {**CREATIVE, "image": {"upload": "h1"}}
    first = plan([op], uploads=store)
    second = plan([op], uploads=store)
    uploads = [c for c in graph.calls if c["url"].endswith("adimages")]
    assert len(uploads) == 1
    assert uploads[0]["files"]["filename"][2] == "image/png"
    assert first["diff"][0]["image"] == {"meta_id": "imghash1",
                                         "sha256": hashlib.sha256(b"png-one").hexdigest()}
    assert json.loads(graph.posts()[-1]["data"]["object_story_spec"])["link_data"]["image_hash"] == "imghash1"
    applied = meta_mcp.apply_changes(second["confirm"], gate=allow, uploads=store)
    assert applied["outcome"] == "applied"
    assert store.discarded == ["h1"]
    assert len([c for c in graph.calls if c["url"].endswith("adimages")]) == 1


def test_video_processing_returns_no_token(graph, store):
    store.add("v1", b"video-bytes", "VIDEO_MP4")
    store.add("c1", b"cover", "IMAGE_JPEG")
    op = {**CREATIVE, "video": {"upload": "v1"}, "cover": {"upload": "c1"}}
    del op["image"]
    graph.video_status = "processing"
    result = plan([op], uploads=store)
    assert result["error"] == "media_processing" and result["pending"] == ["v1"]
    assert "confirm" not in result and meta_mcp._pending == {}
    phases = [c["data"]["upload_phase"] for c in graph.calls if c["url"].endswith("advideos")]
    assert phases == ["start", "transfer", "finish"]
    chunk = next(c["files"]["video_file_chunk"] for c in graph.calls if c["files"] and "video_file_chunk" in c["files"])
    assert (chunk[0], chunk[2]) == ("upload.mp4", "video/mp4")
    cover = next(c["files"]["filename"] for c in graph.calls if c["url"].endswith("adimages") and c["method"] == "POST")
    assert (cover[0], cover[2]) == ("upload.jpg", "image/jpeg")
    graph.video_status = "ready"
    result = plan([op], uploads=store)
    assert "confirm" in result
    assert len([c for c in graph.calls if c["url"].endswith("advideos")]) == 3


def test_video_error_is_invalid_argument(graph, store):
    store.add("v1", b"video-bytes", "VIDEO_MP4")
    op = {**CREATIVE, "video": {"upload": "v1"}, "cover": {"hash": "h"}}
    del op["image"]
    graph.video_status = "error"
    assert plan([op], uploads=store)["error"] == "invalid_argument"


def test_image_upload_in_video_slot_refused(graph, store):
    store.add("h1", b"png", "IMAGE_PNG")
    op = {**CREATIVE, "video": {"upload": "h1"}, "cover": {"hash": "h"}}
    del op["image"]
    assert plan([op], uploads=store)["error"] == "invalid_argument"
    assert graph.calls == []


CHAIN = [CREATIVE, CAMPAIGN, AD_SET, AD]


@pytest.mark.parametrize("position,path", [(0, "adcreatives"), (1, "campaigns"), (2, "adsets"), (3, "ads")])
def test_failure_at_each_position(graph, position, path):
    token = plan(CHAIN)["confirm"]
    graph.fail[path] = {"error": {"code": 100, "error_subcode": 1885183, "message": "New is bad",
                                  "error_user_msg": "New is bad",
                                  "error_data": {"blame_field_specs": [["name"]]}}}
    result = meta_mcp.apply_changes(token, gate=allow)
    ids = ["cr", "c", "s", "a"]
    assert result["outcome"] == ("failed" if position == 0 else "partial")
    assert list(result["created"]) == ids[:position]
    assert result["failed"] == {"op_index": position, "error": "invalid_argument", "errors": [
        {"op_index": position, "code": 100, "subcode": 1885183, "field": "name"}]}
    assert result["not_attempted"] == list(range(position + 1, 4))
    assert "Nothing is rolled back" in result["hint"]
    assert "New is bad" not in json.dumps(result)


def test_timeout_is_outcome_unknown(graph, caplog):
    token = plan([CAMPAIGN, UPDATE])["confirm"]
    graph.fail["901"] = requests.exceptions.ReadTimeout("timed out")
    with caplog.at_level(logging.INFO, logger="meta_mcp"):
        result = meta_mcp.apply_changes(token, gate=allow)
    assert result["outcome"] == "unknown"
    assert result["failed"]["error"] == "outcome_unknown"
    assert result["created"] == {"c": "5001"}
    assert "meta write apply_changes act_111 outcome=unknown" in caplog.text


def test_dry_run_error_reports_codes_only(graph):
    graph.dry_run_error = {"error": {"code": 100, "error_subcode": 1487, "message": "secret text",
                                     "error_data": json.dumps({"blame_field_specs": [["targeting", "geo"]]})}}
    result = plan([CAMPAIGN])
    assert result["error"] == "invalid_argument"
    assert result["errors"] == [{"op_index": 0, "code": 100, "subcode": 1487, "field": "targeting.geo"}]
    result = plan([CREATIVE, AD_SET | {"campaign_id": "123"}])
    assert result["errors"][0]["op_index"] == 0
    assert "secret text" not in json.dumps(result)


@pytest.mark.parametrize("error,category", [
    ({"code": 190, "type": "OAuthException"}, "auth_required"),
    ({"code": 200}, "permission_denied"),
    ({"code": 10}, "permission_denied"),
    ({"code": 100, "error_subcode": 33}, "not_found"),
    ({"code": 17}, "upstream_error"),
    ({"code": 2}, "upstream_error"),
])
def test_error_mapping(graph, error, category):
    graph.dry_run_error = {"error": error}
    assert plan([CAMPAIGN])["error"] == category


def test_no_secret_in_urls_logs_or_results(graph, store, caplog):
    store.add("h1", b"png-one", "IMAGE_PNG")
    ops = [{**CREATIVE, "image": {"upload": "h1"}}, CAMPAIGN, UPDATE]
    with caplog.at_level(logging.DEBUG):
        result = plan(ops, uploads=store)
        graph.fail["campaigns"] = requests.exceptions.ConnectTimeout(f"access_token={TOKEN}")
        applied = meta_mcp.apply_changes(result["confirm"], gate=allow, uploads=store)
    proof = hmac.new(SECRET.encode(), TOKEN.encode(), hashlib.sha256).hexdigest()
    for call in graph.calls:
        assert call["headers"] == {"Authorization": f"Bearer {TOKEN}"}
        carrier, other = ("data", "params") if call["method"] == "POST" else ("params", "data")
        assert call[carrier]["appsecret_proof"] == proof
        assert "appsecret_proof" not in call[other]
        exposed = call["url"] + json.dumps(call["params"]) + json.dumps(call["data"], default=str)
        assert TOKEN not in exposed and SECRET not in exposed
    exposed = caplog.text + json.dumps(result) + json.dumps(applied)
    assert TOKEN not in exposed and SECRET not in exposed
    listed = meta_mcp.list_profiles()
    assert TOKEN not in json.dumps(listed) and SECRET not in json.dumps(listed)


def test_list_profiles_and_credentials_present(graph, tmp_path, monkeypatch):
    assert meta_mcp.credentials_present() is True
    assert meta_mcp.list_profiles() == {"active": "own", "profiles": [
        {"name": "own", "business_id": "123", "ad_accounts": ["act_111"], "pages": ["222"],
         "instagram_ids": ["333"]},
        {"name": "other", "business_id": "456", "ad_accounts": ["act_111"], "pages": ["222"],
         "instagram_ids": []}]}
    monkeypatch.setattr(meta_mcp, "CREDENTIALS_PATH", tmp_path / "missing.json")
    assert meta_mcp.credentials_present() is False
    assert meta_mcp.list_profiles()["error"] == "auth_required"
    assert plan([CAMPAIGN])["error"] == "auth_required"
    assert plan([CAMPAIGN], profile="nobody")["error"] == "auth_required"


def test_unknown_profile(graph):
    assert plan([CAMPAIGN], profile="nobody")["error"] == "invalid_argument"


@pytest.mark.parametrize("ops", [
    [{**PAUSE, "resource": "campaign"}],
    [{"op": "update", "resource": "ad_set", "object_id": "901", "name": "x"}],
    [{**AD_SET, "campaign_id": "124"}],
    [{**CREATIVE, "image": {"hash": "zzz"}}],
])
def test_refused_after_reading_state(graph, ops):
    result = plan(ops)
    assert result["error"] == "invalid_argument"
    assert graph.posts() == [] and meta_mcp._pending == {}


def test_existing_parents_are_read_for_their_account(graph):
    result = plan([{**AD_SET, "campaign_id": "123"}, {**AD, "adset_id": "802", "creative_id": "904"}])
    assert result["dry_run"] is True
    reads = [c["url"].rsplit("/", 1)[1] for c in graph.calls
             if c["method"] == "GET" and c["url"].rsplit("/", 1)[1].isdigit()]
    assert reads == ["123", "802", "904"]


def test_new_ad_set_with_end_time_under_existing_campaign(graph):
    result = plan([{**AD_SET, "campaign_id": "123", "end_time": "2099-01-01T00:00:00+0000"}])
    assert result["dry_run"] is True and result["diff"][0]["validated"] is True


def test_unknown_on_first_request_is_unknown(graph, caplog):
    token = plan([UPDATE])["confirm"]
    graph.fail["901"] = (503, None)
    with caplog.at_level(logging.INFO, logger="meta_mcp"):
        result = meta_mcp.apply_changes(token, gate=allow)
    assert result["outcome"] == "unknown" and result["created"] == {}
    assert "meta write apply_changes act_111 outcome=unknown" in caplog.text


def test_success_false_is_a_failure(graph):
    token = plan([UPDATE])["confirm"]
    graph.fail["901"] = (200, {"success": False})
    result = meta_mcp.apply_changes(token, gate=allow)
    assert result["outcome"] == "failed" and result["failed"]["error"] == "upstream_error"


def test_end_time_on_ended_ad_set_is_not_supported(graph):
    ended = {"op": "update", "resource": "ad_set", "object_id": "801",
             "end_time": "2099-02-01T00:00:00+0000"}
    result = plan([ended])
    assert result["error"] == "not_supported" and "resume delivery" in result["hint"]
    assert graph.posts() == []
    assert plan([{**ended, "object_id": "802"}])["dry_run"] is True


@pytest.mark.parametrize("failure", [
    (502, {"error": {"code": 2, "message": "New"}}),
    (200, None),
    requests.exceptions.ConnectionError("connection reset"),
    RuntimeError("unexpected"),
])
def test_ambiguous_write_mid_apply_is_outcome_unknown(graph, failure):
    token = plan(CHAIN)["confirm"]
    graph.fail["adsets"] = failure
    result = meta_mcp.apply_changes(token, gate=allow)
    assert result["outcome"] == "unknown"
    assert result["created"] == {"cr": "5001", "c": "5002"}
    assert result["failed"]["op_index"] == 2 and result["failed"]["error"] == "outcome_unknown"
    assert "Read the account" in result["failed"]["hint"]
    assert result["not_attempted"] == [3]
    assert "New" not in json.dumps(result)


def test_dry_run_and_reads_keep_upstream_error(graph, monkeypatch):
    graph.dry_run_error = (502, None)
    result = plan([CAMPAIGN])
    assert result["error"] == "upstream_error" and "may exist" not in result["hint"]

    def unreachable(*args, **kwargs):
        raise requests.exceptions.ConnectionError("reset")

    monkeypatch.setattr(meta_mcp, "_http", unreachable)
    result = plan([CAMPAIGN])
    assert result == {"error": "upstream_error", "hint": meta_mcp._HINTS["upstream_error"]}


@pytest.mark.parametrize("failure,error,outcome", [
    ({"error": {"code": 100}}, "invalid_argument", "partial"),
    ((200, {"success": False}), "upstream_error", "partial"),
    (requests.exceptions.ReadTimeout("slow"), "outcome_unknown", "unknown"),
])
def test_multi_id_pause_fails_on_second_id(graph, failure, error, outcome):
    token = plan([{**PAUSE, "ids": ["902", "903", "904"]}, CAMPAIGN])["confirm"]
    graph.fail["903"] = failure
    result = meta_mcp.apply_changes(token, gate=allow)
    assert result["outcome"] == outcome
    assert result["created"] == {"c": "5001"}
    assert {k: result["failed"][k] for k in ("op_index", "error", "done_ids", "failed_id", "unsent_ids")} == {
        "op_index": 0, "error": error, "done_ids": ["902"], "failed_id": "903", "unsent_ids": ["904"]}
    assert result["not_attempted"] == []
    assert [c["url"].rsplit("/", 1)[1] for c in graph.posts(dry_run=False)] == ["campaigns", "902", "903"]


def test_discard_only_after_a_request_was_sent(graph, store, monkeypatch):
    store.add("h1", b"png-one", "IMAGE_PNG")
    token = plan([{**CREATIVE, "image": {"upload": "h1"}}], uploads=store)["confirm"]

    def broken(*args):
        raise RuntimeError("bug")

    monkeypatch.setattr(meta_mcp, "_requests", broken)
    result = meta_mcp.apply_changes(token, gate=allow, uploads=store)
    assert result["outcome"] == "unknown" and result["failed"]["error"] == "outcome_unknown"
    assert store.discarded == []


@pytest.mark.parametrize("ids,error", [
    (["902", "777777"], "not_found"),
    (["902", "901"], "invalid_argument"),
])
def test_one_unreadable_object_among_several(graph, ids, error):
    result = plan([CAMPAIGN, {**PAUSE, "ids": ids}])
    assert result["error"] == error and result["hint"].startswith("Operation 1:")
    assert graph.posts() == [] and meta_mcp._pending == {}


def test_image_part_named_by_type(graph, store):
    store.add("j1", b"jpeg-bytes", "IMAGE_JPEG")
    plan([{**CREATIVE, "image": {"upload": "j1"}}], uploads=store)
    part = next(c["files"]["filename"] for c in graph.calls if c["url"].endswith("adimages") and c["method"] == "POST")
    assert (part[0], part[2]) == ("upload.jpg", "image/jpeg")


@pytest.mark.parametrize("extra,sent", [
    ({}, "false"),
    ({"is_adset_budget_sharing_enabled": True}, "true"),
    ({"daily_budget": 5000}, None),
])
def test_budget_sharing_flag(graph, extra, sent):
    campaign = {key: value for key, value in CAMPAIGN.items() if key != "daily_budget"}
    result = plan([{**campaign, **extra}])
    assert graph.posts()[0]["data"].get("is_adset_budget_sharing_enabled") == sent
    assert result["diff"][0].get("is_adset_budget_sharing_enabled") == {"false": False, "true": True}.get(sent)


def test_budget_sharing_flag_must_be_boolean(graph):
    assert plan([{**CAMPAIGN, "is_adset_budget_sharing_enabled": "no"}])["error"] == "invalid_argument"
    assert graph.calls == []


def test_ad_set_bid_strategy_passed_through(graph):
    plan([{**AD_SET, "campaign_id": "123", "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}])
    assert graph.posts()[0]["data"]["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
    graph.calls.clear()
    assert plan([{**AD_SET, "campaign_id": "123", "bid_strategy": ""}])["error"] == "invalid_argument"
    assert graph.calls == []


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_token_expires(graph, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(meta_mcp.time, "monotonic", clock)
    token = plan([UPDATE])["confirm"]
    clock.now += 601
    assert meta_mcp.apply_changes(token, gate=allow)["error"] == "invalid_argument"
    assert graph.posts(dry_run=False) == []


def test_pending_token_cap(graph, monkeypatch):
    monkeypatch.setattr(meta_mcp, "MAX_PENDING_CONFIRMS", 2)
    tokens = [plan([UPDATE])["confirm"] for _ in range(3)]
    assert list(meta_mcp._pending) == tokens[1:]
    assert meta_mcp.apply_changes(tokens[0], gate=allow)["error"] == "invalid_argument"
    assert meta_mcp.apply_changes(tokens[2], gate=allow)["outcome"] == "applied"


def test_failed_state_read_at_apply_keeps_token(graph, monkeypatch):
    token = plan([UPDATE])["confirm"]
    graph.calls.clear()

    def flaky(method, url, *args, **kwargs):
        if method == "GET" and url.endswith("/901"):
            monkeypatch.setattr(meta_mcp, "_http", graph)
            raise requests.exceptions.ConnectionError("reset")
        return graph(method, url, *args, **kwargs)

    monkeypatch.setattr(meta_mcp, "_http", flaky)
    assert meta_mcp.apply_changes(token, gate=allow)["error"] == "upstream_error"
    assert graph.posts() == []
    assert meta_mcp.apply_changes(token, gate=allow)["outcome"] == "applied"
    assert len(graph.posts(dry_run=False)) == 1


def test_concurrent_redeem_sends_once(graph):
    token = plan([UPDATE])["confirm"]
    barrier = threading.Barrier(2)
    results = []

    def gate(profile):
        barrier.wait(timeout=5)

    threads = [threading.Thread(target=lambda: results.append(meta_mcp.apply_changes(token, gate=gate)))
               for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(r.get("outcome", r.get("error")) for r in results) == ["applied", "invalid_argument"]
    assert len(graph.posts(dry_run=False)) == 1


def test_media_ids_expire_and_are_bounded(graph, store, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(meta_mcp.time, "monotonic", clock)
    store.add("h1", b"png-one", "IMAGE_PNG")
    store.add("h2", b"png-two", "IMAGE_PNG")
    op = {**CREATIVE, "image": {"upload": "h1"}}
    plan([op], uploads=store)
    clock.now += 3601
    plan([op], uploads=store)
    assert len([c for c in graph.calls if c["url"].endswith("adimages") and c["method"] == "POST"]) == 2
    monkeypatch.setattr(meta_mcp, "MAX_MEDIA", 1)
    plan([{**CREATIVE, "image": {"upload": "h2"}}], uploads=store)
    assert list(meta_mcp._media) == [("act_111", hashlib.sha256(b"png-two").hexdigest())]


class Server:
    def __init__(self):
        self.tools = {}

    def add_tool(self, fn, **kwargs):
        self.tools[kwargs["name"]] = (fn, kwargs)


def test_register_writes_refuses_zero_argument_gate():
    with pytest.raises(TypeError, match="gate must accept the profile"):
        meta_mcp.register_writes(Server(), lambda: None)


def test_registered_tools_bind_gate_and_uploads(graph, store):
    server = Server()
    assert meta_mcp.register(server, "meta_") == 1
    assert meta_mcp.register_writes(server, refuse, "meta_", uploads=store) == 2
    assert set(server.tools) == {"meta_list_profiles", "meta_plan_changes", "meta_apply_changes"}
    plan_tool = server.tools["meta_plan_changes"][0]
    assert list(inspect.signature(plan_tool).parameters) == ["account_id", "operations", "profile"]
    assert list(inspect.signature(server.tools["meta_apply_changes"][0]).parameters) == [
        "confirm", "profile"]
    store.add("h1", b"png-one", "IMAGE_PNG")
    assert plan_tool("act_111", [{**CREATIVE, "image": {"upload": "h1"}}]) == refuse("own")


def test_registers_on_fastmcp():
    fastmcp = pytest.importorskip("mcp.server.fastmcp")
    server = fastmcp.FastMCP("test")
    meta_mcp.register(server, "meta_")
    meta_mcp.register_writes(server, allow, "meta_")
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    assert tools["meta_apply_changes"].annotations.destructiveHint is True
    assert set(tools["meta_plan_changes"].parameters["properties"]) == {
        "account_id", "operations", "profile"}
