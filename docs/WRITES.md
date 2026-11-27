# Writes

The owner decided on 2026-11-26 that this toolkit gets a write path. It lives in `scripts/meta_mcp.py` and is used only through an MCP host. The CLI adapters stay read-only.

## Tools

A host calls `register(server, prefix="")` for the read tool and `register_writes(server, gate, prefix="", uploads=None)` for the write tools:

- `list_profiles()`: the active profile and each profile's `business_id`, `ad_accounts`, `pages` and `instagram_ids`. No token or secret.
- `plan_changes(account_id, operations, profile=None)`: validates the operations, reads the current state, uploads new media after the gate allows it, sends every operation Meta can check with `execution_options=["validate_only"]`, and returns a diff and a `confirm` token.
- `apply_changes(confirm, profile=None)`: sends a reviewed plan once.

The host must gate writes. `gate(profile)` receives the resolved profile name and returns `None` to allow or an error dict that the tool returns unchanged. It runs before every apply and before a plan uploads media. `register_writes` raises `TypeError` for a gate that cannot take one argument. `credentials_present()` tells the host whether to register the set at all.

## Credentials file

`~/.claude/meta-credentials.json`, written by the owner, never by a tool:

```json
{
  "active": "own",
  "profiles": {
    "own": {
      "access_token": "<system-user token>",
      "app_secret": "<optional>",
      "business_id": "123",
      "ad_accounts": ["act_111"],
      "pages": ["222"],
      "instagram_ids": ["333"]
    }
  }
}
```

A profile is one business. `ad_accounts`, `pages` and `instagram_ids` are allowlists: an `account_id`, `page_id`, `promoted_object.page_id` or `instagram_user_id` outside them is refused before any request. `profile=None` means `active`. The token goes in the `Authorization: Bearer` header, never in a URL or form field. With `app_secret`, every request carries `appsecret_proof`: in the form body of a POST, in the query string of a GET. This file is separate from `meta-ads-credentials.json`, which the CLI adapters read.

## Operations

1 to 50 operations, each with `op` and exactly these fields (`[]` optional). An unknown `op` or field is `invalid_argument` naming the operation index.

| op | Fields | Graph call |
|---|---|---|
| `create_campaign` | `id`, `name`, `objective`, `special_ad_categories` (list, may be empty), [`daily_budget`, `lifetime_budget`, `bid_strategy`, `is_adset_budget_sharing_enabled` (boolean; sent as false when the campaign has no budget of its own)] | `POST /act_<id>/campaigns`, `status=PAUSED` |
| `create_ad_set` | `id`, `campaign_id`, `name`, `optimization_goal`, `billing_event`, `targeting`, [`daily_budget`, `lifetime_budget`, `bid_amount`, `bid_strategy`, `promoted_object`, `start_time`, `end_time`] | `POST /act_<id>/adsets`, `status=PAUSED` |
| `create_creative` | `id`, `name`, `page_id`, [`instagram_user_id`], `image` or `video`, `cover` (with `video` only), `message`, `link`, [`headline`, `description`], `call_to_action`, [`url_tags`] | `POST /act_<id>/adcreatives` with `object_story_spec.link_data` or `video_data` |
| `create_ad` | `id`, `adset_id`, `creative_id`, `name` | `POST /act_<id>/ads`, `status=PAUSED` |
| `update` | `resource` (`campaign`, `ad_set`, `ad`), `object_id`, exactly one of `name`, `daily_budget`, `lifetime_budget`, `bid_amount`, `end_time` | `POST /<object_id>` with that field |
| `set_status` | `resource`, `ids` (1-50), `status` (`PAUSED` only) | `POST /<id>` per id |

- `image` is `{"upload": handle}` or `{"hash": ...}`; `video` is `{"upload": handle}` or `{"video_id": ...}`; `cover` takes the image forms. `call_to_action` is the type string; the link goes into its value.
- Budgets and bids are integers in the account currency's minor units.
- `update` accepts budgets on campaigns and ad sets, `bid_amount` and `end_time` on ad sets, `name` on all three. A campaign end date is `stop_time` in the Graph API and is not offered. `end_time` on an ad set whose current `end_time` has passed is `not_supported`, because a new date would resume delivery; a schedule that has not ended can be shortened or extended.
- Nothing is activated. Every create is PAUSED and `set_status` only pauses; activation happens in Ads Manager.
- `id` matches `[a-z][a-z0-9_]{0,30}` and is unique in the plan. `"$<id>"` in `campaign_id`, `adset_id` and `creative_id` refers to a campaign, ad set or creative created earlier in the same plan; a reference to the wrong type is refused.
- A `create_campaign` whose name already exists in the account, or repeats in the plan, is refused. An `update` or `set_status` target must belong to the planned ad account and be of the declared `resource`: the read asks for a field only that type has (campaign `objective`, ad set `campaign_id` and `optimization_goal`, ad `adset_id`). An existing `campaign_id`, `adset_id` or `creative_id` is read for its `account_id` the same way, and an image `hash` must be in the account's `adimages`. These checks need reads, so they run before any validation request, not before any request. An existing `video_id` is not checked for ownership; Meta refuses a video the account cannot use when the creative is validated.

## What the plan can validate

The plan reads the account `currency` and `account_status`, and for each edited object its `account_id`, `status`, `effective_status`, `updated_time` and the edited field. It then sends campaigns, creatives, updates, status changes, and ad sets and ads whose parents already exist, with `validate_only`. An ad set or ad under a parent created in the same plan cannot be sent before the parent exists; its diff entry says `validated: "at_apply"` and Meta checks it only when it is sent.

The diff has one entry per operation with `op_index`, `op`, `validated`, the operation's fields, the media `sha256` and Meta id, and for edits `from`, `to` and `effective_status`.

The token is single use and lasts 10 minutes. It is bound to the tool, the account, the profile, the operations with each upload replaced by its `sha256`, MIME type and Meta id, and a digest of the state read for the plan.

Each object is read with its own `GET /<id>?fields=...`; v26.0 refuses the `?ids=` multi-get. Meta returns budgets and bids as strings, and the diff shows `from` and `to` for `daily_budget`, `lifetime_budget` and `bid_amount` as integers.

## Uploads

`uploads` is the host's store. `read(handle, profile, account_id)` returns `mime_type` (`IMAGE_PNG`, `IMAGE_JPEG`, `VIDEO_MP4`, `VIDEO_QUICKTIME`), `sha256`, `size_bytes` and `path`, or raises `KeyError` when the handle is unknown, expired or bound to another profile or account. The toolkit reads the file from `path`, checks it against `sha256` and `size_bytes`, and never writes to it. `discard(handles)` is called after an apply that sent anything; a failure there is logged and does not change the result. Without a store, an upload is `invalid_argument`.

Uploading writes to the ad account's media library, so a plan with a file that has no Meta id yet calls the gate first. Images go to `/act_<id>/adimages`, videos to `/act_<id>/advideos` in start, transfer and finish phases. Meta ids are kept in memory per account and SHA-256 for an hour, like upload handles, and at most 1000 of them, so planning the same file again within the hour uploads nothing. Until a video is `ready` the plan returns `media_processing` with the pending handles and no token; a video in `error` or `expired` is `invalid_argument`. File bytes are never stored with the plan.

The image part is named `upload.png` or `upload.jpg` with the matching content type, because Meta takes the file type from the extension and the stored file is named by its handle; this was confirmed live. Video chunks are named `upload.mp4` or `upload.mov` by the same rule, unverified.

## Apply

`apply_changes` checks, in this order: that the token exists and has not expired, the gate (a refusal keeps the token), the token's binding (another profile or changed operations or files is `invalid_argument`), then it reads the state, redeems the token (single use) and compares the state (changed is `conflict`). A failed state read leaves the token usable. Then it sends one request at a time: creatives, campaigns, ad sets, ads, updates, status changes. Writes are never retried, because a retried create can create twice. Each request has a 60-second timeout.

On success:

```json
{"dry_run": false, "account_id": "act_111", "outcome": "applied", "created": {"c": "120..."}, "applied": 4}
```

It stops at the first failure. `outcome` is one of four values: `applied` (everything was sent), `partial` (something was sent before a failure Meta reported), `failed` (the first request failed and nothing was sent successfully), or `unknown` (the stopping operation is `outcome_unknown`, whether or not anything was created before it). A failure comes with `created`, `failed` (`op_index`, `error`, `errors`) and `not_attempted`. For a `set_status` operation `failed` also lists `done_ids`, `failed_id` and `unsent_ids`. Nothing is rolled back and nothing is deleted; created objects are PAUSED, so plan the remaining operations against the created ids. A write that may have reached Meta gives `error: "outcome_unknown"` with a hint: a timeout, a connection error, an HTTP 5xx, a body that is not JSON, or an unexpected error in the toolkit. The object may exist, so read the account before retrying. Validation requests and reads report these as `upstream_error`. An update or status change that Meta answers with `{"success": false}` is a failure of that operation. Upload handles are discarded only when the apply sent a request.

Errors are `{"error", "hint"[, "errors"]}`. Meta's error codes map to `auth_required` (102, 190), `permission_denied` (10, 200-299), `not_found` (100 with subcode 33), `invalid_argument` (100) and `upstream_error` (rate limits and the rest). `errors` holds `op_index`, `code`, `subcode` and `field` only: Meta's messages can echo request text and are dropped.

Each confirmed apply logs one line, `meta write apply_changes act_<id> outcome=<applied|partial|failed|unknown>`.

## Checked against live Meta on 2026-11-27, Graph v26.0

- `validate_only` is honoured on campaigns, ad sets (when the campaign exists) and node updates; a dry-run edit changed nothing.
- Image upload to `/act_<id>/adimages`.
- Campaign and ad set create, PAUSED. A campaign without its own budget needs `is_adset_budget_sharing_enabled`, which the toolkit sends as `false` unless given; an ad set under such a campaign needs a `bid_strategy` or a bid.
- Rename and pause.
- Per-object reads, including the code 100 answer for a field the object's type does not have.

## Not yet checked live

- Creative and ad creation, and `validate_only` on creatives. The test token had no Page permission, so the creative dry run only got as far as Meta's permission refusal (code 10, subcode 3858749, mapped to `permission_denied`) and created nothing.
- Video upload.
- The Instagram fields.
