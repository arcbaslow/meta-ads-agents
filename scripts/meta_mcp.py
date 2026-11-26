"""Meta Ads tools for an MCP host: list_profiles, and gated plan_changes / apply_changes."""

import copy
import functools
import hashlib
import hmac
import inspect
import json
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import meta_utils
import requests

log = logging.getLogger(__name__)

CREDENTIALS_PATH = Path.home() / ".claude" / "meta-credentials.json"
_GRAPH = f"https://graph.facebook.com/{meta_utils.API_VERSION}"
_TIMEOUT_SECONDS = 60
CONFIRM_TTL_SECONDS = 600
MAX_PENDING_CONFIRMS = 100
MEDIA_TTL_SECONDS = 3600
MAX_MEDIA = 1000
_MAX_OPERATIONS = 50

_HINTS = {
    "auth_required": "The Meta credentials file is missing, unreadable or has no token for this profile.",
    "permission_denied": "This token cannot make this request. Check the system user's assets and permissions.",
    "invalid_argument": (
        "Meta rejected the request; errors lists the codes and fields. No campaign, ad set, "
        "creative or ad was changed; media uploaded for this plan stays in the account library."),
    "not_found": "An object in the request was not found or is not visible to this profile.",
    "upstream_error": "The Meta API request failed. Retry later.",
    "rate_limited": "Meta rate limited this request. Wait before retrying.",
}
_STALE_CONFIRM = (
    "confirm is unknown, expired, already used, or was issued for another profile or other "
    "operations. Nothing was sent. Run plan_changes again and review it."
)
_CONFLICT_HINT = "The account or the objects changed since the plan. Nothing was sent. Plan again."
_MAY_EXIST = "No answer came back from Meta, so the object may exist. Read the account before retrying."
_PLAN_HINT = (
    "No campaign, ad set, creative or ad was changed; new media in the plan was uploaded to the "
    "account library. Review the diff, then call apply_changes with confirm and the same "
    "profile within 10 minutes; the token works once. Entries validated at_apply are checked by "
    "Meta only when sent."
)
_PARTIAL_HINT = (
    "Nothing is rolled back; what was created is PAUSED. Plan the remaining operations against "
    "the created ids."
)

_FIELDS = {
    "create_campaign": ({"id", "name", "objective", "special_ad_categories"},
                        {"daily_budget", "lifetime_budget", "bid_strategy"}),
    "create_ad_set": ({"id", "campaign_id", "name", "optimization_goal", "billing_event", "targeting"},
                      {"daily_budget", "lifetime_budget", "bid_amount", "promoted_object",
                       "start_time", "end_time"}),
    "create_creative": ({"id", "name", "page_id", "message", "link", "call_to_action"},
                        {"instagram_user_id", "image", "video", "cover", "headline", "description",
                         "url_tags"}),
    "create_ad": ({"id", "adset_id", "creative_id", "name"}, set()),
    "update": ({"resource", "object_id"},
               {"name", "daily_budget", "lifetime_budget", "bid_amount", "end_time"}),
    "set_status": ({"resource", "ids", "status"}, set()),
}
_REFS = {
    ("create_ad_set", "campaign_id"): "create_campaign",
    ("create_ad", "adset_id"): "create_ad_set",
    ("create_ad", "creative_id"): "create_creative",
}
_TYPE_FIELDS = {"campaign": ["objective"], "ad_set": ["campaign_id", "optimization_goal"],
                "ad": ["adset_id"]}
_EDITS = {
    "name": ("campaign", "ad_set", "ad"),
    "daily_budget": ("campaign", "ad_set"),
    "lifetime_budget": ("campaign", "ad_set"),
    "bid_amount": ("ad_set",),
    "end_time": ("ad_set",),
}
_MEDIA_FORMS = {"image": ("upload", "hash"), "video": ("upload", "video_id"), "cover": ("upload", "hash")}
_MIME_TYPES = {"IMAGE_PNG", "IMAGE_JPEG", "VIDEO_MP4", "VIDEO_QUICKTIME"}
_SEND_ORDER = ("create_creative", "create_campaign", "create_ad_set", "create_ad", "update", "set_status")
_ID = re.compile(r"[a-z][a-z0-9_]{0,30}")
_META_ID = re.compile(r"[0-9]{1,30}")
_CONFIRM = re.compile(r"[0-9a-f]{32}")
_FIELD_NAME = re.compile(r"[\w.]{1,100}")

_pending: dict[str, tuple[str, str, float, dict]] = {}
_media: dict[tuple[str, str], tuple[str, float]] = {}
_lock = threading.Lock()


class _Failure(Exception):
    def __init__(self, category, hint, errors=None):
        super().__init__(hint)
        self.category = category
        self.hint = hint
        self.errors = errors


class _Unknown(_Failure):
    pass


def _guarded(fn):
    @functools.wraps(fn)
    def tool(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _Failure as exc:
            out = {"error": exc.category, "hint": exc.hint}
            if exc.errors is not None:
                out["errors"] = exc.errors
            return out
        except Exception as exc:
            log.warning("%s failed: %s", fn.__name__, type(exc).__name__)
            return {"error": "upstream_error", "hint": _HINTS["upstream_error"]}

    return tool


def _http(method, url, headers, params=None, data=None, files=None, timeout=_TIMEOUT_SECONDS):
    response = requests.request(method, url, headers=headers, params=params, data=data,
                                files=files, timeout=timeout)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


def _graph_failure(body):
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return _Failure("upstream_error", _HINTS["upstream_error"])
    code, subcode = error.get("code"), error.get("error_subcode")
    field = None
    data = error.get("error_data")
    try:
        if isinstance(data, str):
            data = json.loads(data)
        spec = data["blame_field_specs"][0]
        field = ".".join(str(part) for part in (spec if isinstance(spec, list) else [spec]))
        if not _FIELD_NAME.fullmatch(field):
            field = None
    except (ValueError, TypeError, KeyError, IndexError):
        pass
    # message and error_user_msg can quote submitted text, so only codes and field names are kept.
    errors = [{"op_index": None, "code": code, "subcode": subcode, "field": field}]
    if code in (102, 190):
        category = "auth_required"
    elif code == 10 or (isinstance(code, int) and 200 <= code < 300):
        category = "permission_denied"
    elif code in meta_utils._RATE_LIMIT_ERROR_CODES:
        return _Failure("upstream_error", _HINTS["rate_limited"], errors)
    elif code == 100 and subcode == 33:
        category = "not_found"
    elif code == 100:
        category = "invalid_argument"
    else:
        category = "upstream_error"
    return _Failure(category, _HINTS[category], errors)


def _form(data):
    return {key: json.dumps(value) if isinstance(value, (dict, list)) else value
            for key, value in data.items()}


def _call(creds, method, path, params=None, data=None, files=None):
    token = creds["access_token"]
    real_write = method == "POST" and "execution_options" not in (data or {})
    params = dict(params or {})
    if creds.get("app_secret"):
        proof = hmac.new(creds["app_secret"].encode(), token.encode(), hashlib.sha256).hexdigest()
        if method == "POST":
            data = {**(data or {}), "appsecret_proof": proof}
        else:
            params["appsecret_proof"] = proof
    try:
        status, body = _http(method, f"{_GRAPH}/{path}", {"Authorization": f"Bearer {token}"},
                             params, _form(data) if data else None, files)
    except requests.exceptions.RequestException:
        if real_write:
            raise _Unknown("upstream_error", _MAY_EXIST) from None
        raise _Failure("upstream_error", _HINTS["upstream_error"]) from None
    if real_write and (status >= 500 or not isinstance(body, dict)):
        raise _Unknown("upstream_error", _MAY_EXIST, _graph_failure(body).errors)
    if status >= 400 or not isinstance(body, dict) or "error" in body:
        raise _graph_failure(body)
    return body


def _load():
    try:
        data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise _Failure("auth_required", _HINTS["auth_required"]) from None
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise _Failure("auth_required", _HINTS["auth_required"])
    return data


def _profile(name):
    data = _load()
    name = data.get("active") if name is None else name
    creds = data["profiles"].get(name) if isinstance(name, str) else None
    if not isinstance(creds, dict):
        raise _Failure("invalid_argument", "Unknown profile. list_profiles shows the profiles.")
    if not creds.get("access_token"):
        raise _Failure("auth_required", _HINTS["auth_required"])
    return name, creds


def credentials_present() -> bool:
    try:
        _load()
    except _Failure:
        return False
    return True


@_guarded
def list_profiles() -> dict:
    """List the Meta credential profiles with their ad account, Page and Instagram allowlists."""
    data = _load()
    return {"active": data.get("active"), "profiles": [
        {"name": name, **{key: creds.get(key) for key in
                          ("business_id", "ad_accounts", "pages", "instagram_ids")}}
        for name, creds in data["profiles"].items()]}


def _account(value, creds):
    try:
        account_id = meta_utils.normalize_account_id(value)
        allowed = {meta_utils.normalize_account_id(a) for a in creds.get("ad_accounts") or []}
    except ValueError:
        raise _Failure("invalid_argument", "account_id must be an ad account ID (act_<digits>).") from None
    if account_id not in allowed:
        raise _Failure("invalid_argument", "This ad account is not in the profile's ad_accounts.")
    return account_id


def _validate(operations, creds, uploads):
    if not isinstance(operations, list) or not 1 <= len(operations) <= _MAX_OPERATIONS:
        raise _Failure("invalid_argument", f"operations must be a list of 1 to {_MAX_OPERATIONS} objects.")
    created = {}
    for i, op in enumerate(operations):
        def bad(text, i=i):
            return _Failure("invalid_argument", f"Operation {i}: {text}")

        if not isinstance(op, dict) or not isinstance(op.get("op"), str) or op["op"] not in _FIELDS:
            raise bad(f"op must be one of {', '.join(_FIELDS)}.")
        kind = op["op"]
        required, optional = _FIELDS[kind]
        keys = set(op) - {"op"}
        if required - keys:
            raise bad(f"missing {', '.join(sorted(required - keys))}.")
        if keys - required - optional:
            raise bad(f"unknown field; {kind} takes {', '.join(sorted(required | optional))}.")
        for key in keys:
            value = op[key]
            if key in ("daily_budget", "lifetime_budget", "bid_amount"):
                ok = isinstance(value, int) and not isinstance(value, bool) and value > 0
            elif key in ("targeting", "promoted_object"):
                ok = isinstance(value, dict)
            elif key == "special_ad_categories":
                ok = isinstance(value, list) and all(isinstance(v, str) and v for v in value)
            elif key == "ids":
                ok = (isinstance(value, list) and 1 <= len(value) <= _MAX_OPERATIONS
                      and all(isinstance(v, str) and _META_ID.fullmatch(v) for v in value)
                      and len(set(value)) == len(value))
            elif key in _MEDIA_FORMS:
                ok = (isinstance(value, dict) and len(value) == 1
                      and next(iter(value)) in _MEDIA_FORMS[key]
                      and isinstance(next(iter(value.values())), str) and next(iter(value.values())))
            else:
                ok = isinstance(value, str) and value != ""
            if not ok:
                raise bad(f"{key} has the wrong type or form.")
        if "id" in op:
            if not _ID.fullmatch(op["id"]) or op["id"] in created:
                raise bad("id must match [a-z][a-z0-9_]{0,30} and be unique in the plan.")
            created[op["id"]] = kind
        for (owner, field), target in _REFS.items():
            if owner != kind:
                continue
            ref = op[field]
            if ref.startswith("$") and created.get(ref[1:]) != target:
                raise bad(f"{field} must be $<id> of a {target} earlier in this plan, or a Meta ID.")
            if not ref.startswith("$") and not _META_ID.fullmatch(ref):
                raise bad(f"{field} must be $<id> of a {target} earlier in this plan, or a Meta ID.")
        if kind == "create_creative":
            if op["page_id"] not in (creds.get("pages") or []):
                raise bad("page_id is not in the profile's pages.")
            if "instagram_user_id" in op and op["instagram_user_id"] not in (creds.get("instagram_ids") or []):
                raise bad("instagram_user_id is not in the profile's instagram_ids.")
            if ("image" in op) == ("video" in op):
                raise bad("give exactly one of image or video.")
            if ("cover" in op) != ("video" in op):
                raise bad("cover is required with video and only with video.")
            if any("upload" in op.get(role, {}) for role in _MEDIA_FORMS) and uploads is None:
                raise bad("this host has no upload store.")
        if (kind == "create_ad_set" and "page_id" in op.get("promoted_object", {})
                and str(op["promoted_object"]["page_id"]) not in (creds.get("pages") or [])):
            raise bad("promoted_object.page_id is not in the profile's pages.")
        if kind in ("update", "set_status") and op["resource"] not in ("campaign", "ad_set", "ad"):
            raise bad("resource must be campaign, ad_set or ad.")
        if kind == "update":
            edits = [field for field in _EDITS if field in op]
            if not _META_ID.fullmatch(op["object_id"]):
                raise bad("object_id must be a Meta ID.")
            if len(edits) != 1 or op["resource"] not in _EDITS[edits[0]]:
                raise bad("give exactly one field this resource accepts: "
                          + ", ".join(f for f, r in _EDITS.items() if op["resource"] in r) + ".")
        if kind == "set_status" and op["status"] != "PAUSED":
            raise bad("status must be PAUSED; activation is done in Ads Manager.")


def _files(operations, name, account_id, uploads):
    files = {}
    for i, op in enumerate(operations):
        for role in _MEDIA_FORMS:
            handle = op.get(role, {}).get("upload")
            if handle is None:
                continue
            if handle not in files:
                try:
                    info = uploads.read(handle, name, account_id)
                except KeyError:
                    raise _Failure("not_found", f"Operation {i}: upload was not found or is unavailable.") from None
                digest, size = hashlib.sha256(), 0
                with open(info["path"], "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        digest.update(chunk)
                        size += len(chunk)
                if (info.get("mime_type") not in _MIME_TYPES or digest.hexdigest() != info.get("sha256")
                        or size != info.get("size_bytes")):
                    raise _Failure("invalid_argument", f"Operation {i}: upload does not match its record.")
                files[handle] = {key: info[key] for key in ("mime_type", "sha256", "size_bytes", "path")}
            if files[handle]["mime_type"].startswith("VIDEO_") != (role == "video"):
                raise _Failure("invalid_argument", f"Operation {i}: {role} upload has the wrong media type.")
    return files


def _ended(value):
    if not value:
        return False
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z") <= datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return True


def _state(creds, account_id, operations):
    account = _call(creds, "GET", account_id, params={"fields": "currency,account_status"})
    state = {"account": [account.get("currency"), account.get("account_status")], "ops": []}
    rows, problems = {}, []
    names = [op["name"] for op in operations if op["op"] == "create_campaign"]
    if len(set(names)) != len(names):
        problems.append(_Failure("invalid_argument", "Two create_campaign operations use the same name."))
    hashes = sorted({op[role]["hash"] for op in operations for role in ("image", "cover")
                     if "hash" in op.get(role, {})})
    if hashes:
        found = _call(creds, "GET", f"{account_id}/adimages",
                      params={"hashes": json.dumps(hashes), "fields": "hash"}).get("data") or []
        state["hashes"] = sorted({row.get("hash") for row in found} & set(hashes))
        if state["hashes"] != hashes:
            problems.append(_Failure("invalid_argument", "An image hash was not found in this ad account."))
    for i, op in enumerate(operations):
        kind = op["op"]
        if kind == "create_campaign":
            found = _call(creds, "GET", f"{account_id}/campaigns", params={
                "fields": "id", "limit": 1,
                "filtering": json.dumps([{"field": "name", "operator": "EQUAL", "value": op["name"]}]),
            }).get("data") or []
            state["ops"].append(sorted(str(row.get("id")) for row in found))
            if found:
                problems.append(_Failure(
                    "invalid_argument", f"Operation {i}: a campaign with this name already exists in the account."))
            continue
        if kind in ("update", "set_status"):
            ids = [op["object_id"]] if kind == "update" else op["ids"]
            fields = ["account_id", "status", "effective_status", "updated_time",
                      *_TYPE_FIELDS[op["resource"]], *[field for field in _EDITS if field in op]]
        else:
            ids = [op[field] for owner, field in _REFS if owner == kind and not op[field].startswith("$")]
            fields = ["account_id"]
        if not ids:
            continue
        try:
            found = _call(creds, "GET", "", params={"ids": ",".join(ids), "fields": ",".join(fields)})
        except _Failure as exc:
            if exc.category != "invalid_argument":
                raise
            raise _Failure("invalid_argument",
                           f"Operation {i}: Meta refused to read an object; check the ids and resource.") from None
        if any(not isinstance(found.get(object_id), dict) for object_id in ids):
            raise _Failure("not_found", f"Operation {i}: an object was not found.")
        rows[i] = {object_id: found[object_id] for object_id in ids}
        state["ops"].append(rows[i])
        if any(f"act_{row.get('account_id')}" != account_id for row in rows[i].values()):
            problems.append(_Failure("invalid_argument", f"Operation {i}: an object is not in this ad account."))
        if kind in ("update", "set_status") and any(
                row.get(field) is None for row in rows[i].values() for field in _TYPE_FIELDS[op["resource"]]):
            problems.append(_Failure("invalid_argument", f"Operation {i}: an object is not a {op['resource']}."))
        if kind == "update" and "end_time" in op and _ended(rows[i][op["object_id"]].get("end_time")):
            problems.append(_Failure(
                "not_supported", f"Operation {i}: this ad set's schedule has ended, so a new end_time would "
                "resume delivery. Change it in Ads Manager."))
    return state, rows, problems[0] if problems else None


def _known_media(key):
    with _lock:
        entry = _media.get(key)
    return entry[0] if entry and time.monotonic() - entry[1] < MEDIA_TTL_SECONDS else None


def _remember_media(key, meta_id):
    with _lock:
        _media.pop(key, None)
        _media[key] = (meta_id, time.monotonic())
        while len(_media) > MAX_MEDIA:
            del _media[next(iter(_media))]


def _upload(creds, account_id, info):
    path, mime = Path(info["path"]), info["mime_type"]
    try:
        if mime.startswith("IMAGE_"):
            with open(path, "rb") as fh:
                body = _call(creds, "POST", f"{account_id}/adimages", files={
                    "filename": (path.name, fh, "image/" + mime[6:].lower())})
            return str(next(iter(body["images"].values()))["hash"])
        start = _call(creds, "POST", f"{account_id}/advideos",
                      data={"upload_phase": "start", "file_size": info["size_bytes"]})
        session, video_id = start["upload_session_id"], str(start["video_id"])
        offset, end = int(start["start_offset"]), int(start["end_offset"])
        with open(path, "rb") as fh:
            while offset < end:
                fh.seek(offset)
                part = _call(creds, "POST", f"{account_id}/advideos", data={
                    "upload_phase": "transfer", "upload_session_id": session, "start_offset": offset,
                }, files={"video_file_chunk": ("chunk", fh.read(end - offset))})
                if int(part["start_offset"]) <= offset:
                    raise _Failure("upstream_error", _HINTS["upstream_error"])
                offset, end = int(part["start_offset"]), int(part["end_offset"])
        _call(creds, "POST", f"{account_id}/advideos",
              data={"upload_phase": "finish", "upload_session_id": session})
        return video_id
    except (KeyError, TypeError, ValueError, StopIteration, AttributeError):
        raise _Failure("upstream_error", _HINTS["upstream_error"]) from None


def _media_id(op, role, media):
    value = op[role]
    return media[value["upload"]] if "upload" in value else next(iter(value.values()))


def _requests(account_id, op, media, created):
    def ref(value):
        return created[value[1:]] if value.startswith("$") else value

    kind = op["op"]
    if kind == "create_campaign":
        data = {key: value for key, value in op.items() if key not in ("op", "id")}
        return [(f"{account_id}/campaigns", {**data, "status": "PAUSED"})]
    if kind == "create_ad_set":
        data = {key: value for key, value in op.items() if key not in ("op", "id")}
        return [(f"{account_id}/adsets", {**data, "campaign_id": ref(op["campaign_id"]), "status": "PAUSED"})]
    if kind == "create_ad":
        return [(f"{account_id}/ads", {"name": op["name"], "adset_id": ref(op["adset_id"]),
                                       "creative": {"creative_id": ref(op["creative_id"])},
                                       "status": "PAUSED"})]
    if kind == "create_creative":
        cta = {"type": op["call_to_action"], "value": {"link": op["link"]}}
        if "image" in op:
            story = {"link_data": {"link": op["link"], "message": op["message"],
                                   "image_hash": _media_id(op, "image", media), "call_to_action": cta,
                                   **{key: op[key] for key in ("description",) if key in op},
                                   **({"name": op["headline"]} if "headline" in op else {})}}
        else:
            story = {"video_data": {"video_id": _media_id(op, "video", media),
                                    "image_hash": _media_id(op, "cover", media),
                                    "message": op["message"], "call_to_action": cta,
                                    **({"title": op["headline"]} if "headline" in op else {}),
                                    **({"link_description": op["description"]} if "description" in op else {})}}
        story["page_id"] = op["page_id"]
        if "instagram_user_id" in op:
            story["instagram_user_id"] = op["instagram_user_id"]
        data = {"name": op["name"], "object_story_spec": story}
        if "url_tags" in op:
            data["url_tags"] = op["url_tags"]
        return [(f"{account_id}/adcreatives", data)]
    if kind == "update":
        field = next(field for field in _EDITS if field in op)
        return [(op["object_id"], {field: op[field]})]
    return [(object_id, {"status": "PAUSED"}) for object_id in op["ids"]]


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _bound(account_id, name, operations, files, media):
    bound = copy.deepcopy(operations)
    for op in bound:
        for role in _MEDIA_FORMS:
            if "upload" in op.get(role, {}):
                info = files[op[role]["upload"]]
                op[role]["upload"] = {"sha256": info["sha256"], "mime_type": info["mime_type"],
                                      "meta_id": media.get(op[role]["upload"])}
    return _digest({"tool": "apply_changes", "account_id": account_id, "profile": name,
                    "operations": bound})


def _order(operations):
    return sorted(range(len(operations)), key=lambda i: _SEND_ORDER.index(operations[i]["op"]))


@_guarded
def plan_changes(account_id: str, operations: list[dict], profile: str | None = None, *,
                 gate, uploads=None) -> dict:
    """Validate 1-50 Meta Ads operations with validate_only and return a diff and a confirm token.

    Each operation has "op" and exactly these fields ([] = optional):
    - create_campaign: id, name, objective, special_ad_categories (list, may be empty),
      [daily_budget, lifetime_budget, bid_strategy]. Created PAUSED.
    - create_ad_set: id, campaign_id (Meta ID or $id), name, optimization_goal, billing_event,
      targeting (object), [daily_budget, lifetime_budget, bid_amount, promoted_object, start_time,
      end_time]. Created PAUSED.
    - create_creative: id, name, page_id, [instagram_user_id], exactly one of image
      ({"upload": handle} or {"hash": ...}) or video ({"upload": handle} or {"video_id": ...}),
      cover (with video only; image forms), message, link, [headline, description],
      call_to_action (type), [url_tags].
    - create_ad: id, adset_id (Meta ID or $id), creative_id (Meta ID or $id), name. Created PAUSED.
    - update: resource campaign | ad_set | ad, object_id, exactly one of name, daily_budget,
      lifetime_budget (campaign, ad_set), bid_amount, end_time (ad_set).
    - set_status: resource, ids (1-50), status PAUSED.
    Budgets and bids are integers in the account currency's minor units. id matches
    [a-z][a-z0-9_]{0,30}; "$<id>" refers to an object created earlier in the plan. Ad sets and
    ads under a parent created in the plan are validated by Meta only at apply. New uploads are
    sent to the ad account's media library during the plan, after the host's write gate.
    """
    name, creds = _profile(profile)
    account_id = _account(account_id, creds)
    _validate(operations, creds, uploads)
    files = _files(operations, name, account_id, uploads)
    state, rows, problem = _state(creds, account_id, operations)
    if problem is not None:
        raise problem
    currency = state["account"][0]
    media = {handle: _known_media((account_id, info["sha256"])) for handle, info in files.items()}
    new = [handle for handle, meta_id in media.items() if meta_id is None]
    if new:
        refusal = gate(name)
        if refusal is not None:
            return refusal
        for handle in new:
            media[handle] = _upload(creds, account_id, files[handle])
            _remember_media((account_id, files[handle]["sha256"]), media[handle])
    pending = []
    for handle, info in files.items():
        if info["mime_type"].startswith("VIDEO_"):
            status = (_call(creds, "GET", media[handle], params={"fields": "status"})
                      .get("status") or {}).get("video_status")
            if status in ("error", "expired"):
                with _lock:
                    _media.pop((account_id, info["sha256"]), None)
                raise _Failure("invalid_argument", "Meta could not process an uploaded video. Upload it again.")
            if status != "ready":
                pending.append(handle)
    if pending:
        return {"error": "media_processing", "pending": pending,
                "hint": "Meta is still processing the video. Run plan_changes again in a few minutes."}

    diff = []
    for i, op in enumerate(operations):
        entry = {"op_index": i, "op": op["op"], "validated": True,
                 **{key: value for key, value in op.items() if key not in ("op", *_MEDIA_FORMS)}}
        for role in _MEDIA_FORMS:
            if role in op:
                upload = op[role].get("upload")
                entry[role] = {"meta_id": _media_id(op, role, media),
                               **({"sha256": files[upload]["sha256"]} if upload else {})}
        if op["op"] == "update":
            field = next(field for field in _EDITS if field in op)
            row = rows[i][op["object_id"]]
            entry.update({"field": field, "from": row.get(field), "to": op[field],
                          "effective_status": row.get("effective_status")})
        if op["op"] == "set_status":
            entry["changes"] = [{"object_id": object_id, "from": row.get("status"), "to": "PAUSED",
                                 "effective_status": row.get("effective_status")}
                                for object_id, row in rows[i].items()]
        diff.append(entry)
    for i in _order(operations):
        op = operations[i]
        if any(op.get(field, "").startswith("$") for owner, field in _REFS if owner == op["op"]):
            diff[i]["validated"] = "at_apply"
            continue
        for path, data in _requests(account_id, op, media, {}):
            try:
                _call(creds, "POST", path, data={**data, "execution_options": ["validate_only"]})
            except _Failure as exc:
                for error in exc.errors or []:
                    error["op_index"] = i
                raise _Failure(exc.category, f"Operation {i}: {exc.hint}", exc.errors) from None

    token = secrets.token_hex(16)
    now = time.monotonic()
    with _lock:
        for old in [t for t, entry in _pending.items() if now - entry[2] > CONFIRM_TTL_SECONDS]:
            del _pending[old]
        _pending[token] = (_bound(account_id, name, operations, files, media), _digest(state), now,
                           {"account_id": account_id, "profile": name,
                            "operations": copy.deepcopy(operations)})
        while len(_pending) > MAX_PENDING_CONFIRMS:
            del _pending[next(iter(_pending))]
    return {"dry_run": True, "account_id": account_id, "currency": currency, "diff": diff,
            "confirm": token, "confirm_expires_in": CONFIRM_TTL_SECONDS, "hint": _PLAN_HINT}


@_guarded
def apply_changes(confirm: str, profile: str | None = None, *, gate, uploads=None) -> dict:
    """Send a reviewed plan_changes plan once, after the host's write gate.

    Takes the token and the same profile. The plan's uploads and the account state are read
    again: changed operations or files, or another profile, are invalid_argument; changed state
    is conflict. Operations are sent one at a time (creatives, campaigns, ad sets, ads, updates,
    status changes) and stop at the first failure. Nothing is rolled back; created objects are
    PAUSED and listed under created.
    """
    if not isinstance(confirm, str) or not _CONFIRM.fullmatch(confirm):
        raise _Failure("invalid_argument", _STALE_CONFIRM)
    with _lock:
        entry = _pending.get(confirm)
    if entry is None or time.monotonic() - entry[2] > CONFIRM_TTL_SECONDS:
        raise _Failure("invalid_argument", _STALE_CONFIRM)
    name, creds = _profile(profile)
    refusal = gate(name)
    if refusal is not None:
        return refusal
    if entry[3]["profile"] != name:
        with _lock:
            _pending.pop(confirm, None)
        raise _Failure("invalid_argument", _STALE_CONFIRM)
    account_id, operations = entry[3]["account_id"], copy.deepcopy(entry[3]["operations"])
    _account(account_id, creds)
    _validate(operations, creds, uploads)
    files = _files(operations, name, account_id, uploads)
    media = {handle: _known_media((account_id, info["sha256"])) for handle, info in files.items()}
    digest = _bound(account_id, name, operations, files, media)
    with _lock:
        entry = _pending.pop(confirm, None)
    if entry is None or entry[0] != digest:
        raise _Failure("invalid_argument", _STALE_CONFIRM)
    state, _, problem = _state(creds, account_id, operations)
    if _digest(state) != entry[1]:
        raise _Failure("conflict", _CONFLICT_HINT)
    if problem is not None:
        raise problem

    order = _order(operations)
    created, attempted, sent, failed = {}, 0, 0, None
    for position, i in enumerate(order):
        op = operations[i]
        done, target = [], None
        try:
            for path, data in _requests(account_id, op, media, created):
                target = path
                attempted += 1
                body = _call(creds, "POST", path, data=data)
                if "id" not in op and body.get("success") is False:
                    raise _Failure("upstream_error", "Meta answered that the change was not applied.")
                sent += 1
                done.append(path)
                if "id" in op:
                    if not body.get("id"):
                        raise _Unknown("upstream_error", _MAY_EXIST)
                    created[op["id"]] = str(body["id"])
        except Exception as exc:
            known = isinstance(exc, _Failure) and not isinstance(exc, _Unknown)
            if not isinstance(exc, _Failure):
                log.warning("apply_changes request failed: %s", type(exc).__name__)
            failed = {"op_index": i, "error": exc.category if known else "outcome_unknown",
                      "errors": [{**error, "op_index": i} for error in getattr(exc, "errors", None) or []]}
            if not known:
                failed["hint"] = _MAY_EXIST
            if op["op"] == "set_status":
                failed.update(done_ids=done, failed_id=target,
                              unsent_ids=op["ids"][len(done) + (target is not None):])
            not_attempted = order[position + 1:]
            break
    if failed is None:
        outcome = "applied"
    elif failed["error"] == "outcome_unknown":
        outcome = "unknown"
    else:
        outcome = "partial" if sent else "failed"
    log.info("meta write apply_changes %s outcome=%s", account_id, outcome)
    if files and attempted:
        try:
            uploads.discard(list(files))
        except Exception as exc:
            log.warning("upload discard failed after apply_changes: %s", type(exc).__name__)
    if failed is None:
        return {"dry_run": False, "account_id": account_id, "outcome": outcome, "created": created,
                "applied": len(operations)}
    return {"dry_run": False, "account_id": account_id, "outcome": outcome, "created": created,
            "failed": failed, "not_attempted": not_attempted, "hint": _PARTIAL_HINT}


_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
              "openWorldHint": True}
_WRITE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False,
          "openWorldHint": True}


def register(server, prefix: str = "") -> int:
    server.add_tool(list_profiles, name=prefix + "list_profiles", title="List Meta profiles",
                    description=inspect.cleandoc(list_profiles.__doc__), annotations=_READ_ONLY)
    return 1


def register_writes(server, gate, prefix: str = "", uploads=None) -> int:
    try:
        inspect.signature(gate).bind(None)
    except (TypeError, ValueError):
        raise TypeError("gate must accept the profile") from None

    def plan(account_id: str, operations: list[dict], profile: str | None = None) -> dict:
        return plan_changes(account_id, operations, profile, gate=gate, uploads=uploads)

    def apply(confirm: str, profile: str | None = None) -> dict:
        return apply_changes(confirm, profile, gate=gate, uploads=uploads)

    for fn, tool, title, doc in ((plan, "plan_changes", "Plan Meta Ads changes", plan_changes.__doc__),
                                 (apply, "apply_changes", "Apply a reviewed Meta Ads plan",
                                  apply_changes.__doc__)):
        server.add_tool(fn, name=prefix + tool, title=title, description=inspect.cleandoc(doc),
                        annotations=_WRITE)
    return 2
