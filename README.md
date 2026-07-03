# Fleet API Postman Collection

A Postman collection for the [Fleet REST API](https://fleetdm.com/docs/rest-api/rest-api), generated directly from Fleet's official API documentation.

> **Note:** This collection is a community resource and is **not officially supported by Fleet**. It's generated from Fleet's API docs and may contain errors or lag behind the latest release. For authoritative reference, always use the [official API documentation](https://fleetdm.com/docs/rest-api/rest-api).

**Current version:** see [`VERSION`](VERSION) (the collection file is always `fleet.postman_collection.json`, regardless of Fleet version).

### How it works

Fleet doesn't publish an OpenAPI spec, the source of truth is [`docs/REST API/rest-api.md`](https://github.com/fleetdm/fleet/blob/main/docs/REST%20API/rest-api.md) in the fleetdm/fleet repo, versioned by release tag. [`scripts/generate_collection.py`](scripts/generate_collection.py) parses that markdown and produces the collection, including every documented endpoint, its parameters, request body examples, and a saved default response.

### Setup & usage

Clone this repo, then import **both** files into Postman (drag the folder in, or File → Import):

1. `fleet.postman_collection.json` — the collection
2. `fleet.postman_environment.json` — creates the `Fleet` environment automatically, with:
   * `baseUrl` — your Fleet server, e.g. `https://fleet.example.com`
   * `token` — your API token (Fleet UI → **My account** → **Get API token**), stored as a Postman **secret**

Select the `Fleet` environment, fill in the two values, and you're done. Every request inherits `Bearer {{token}}` auth from the collection — no per-request setup, no email/password login flow.

Query parameters are included on each request but **disabled by default**. Enable the ones you need and replace the placeholder values.

### Recommendations

* Always test requests against a **development environment** before using them in production.
* Review endpoints and parameters carefully before execution to ensure correctness.

### Contributing

If you discover any issues or identify areas for improvement, please open a pull request. Note that `fleet.postman_collection.json` is generated, so improve `scripts/generate_collection.py` instead of editing the collection by hand.

### Documentation

* [Fleet REST API documentation](https://fleetdm.com/docs/rest-api/rest-api)