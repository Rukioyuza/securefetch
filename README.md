<h1 align="left">securefetch</h1>

<p align="left">
  <img src="https://img.shields.io/badge/Python-181717?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/TLS-Verified-181717?style=for-the-badge&logo=letsencrypt&logoColor=white" />
  <img src="https://img.shields.io/badge/Dependencies-None-181717?style=for-the-badge" />
</p>

A small HTTPS client built only on the standard library (`urllib`, `http.client` and `ssl`). It wraps the parts I kept rewriting for class projects: a base URL, default headers, cookies, JSON, retries and proper errors.

---

### About

- **Session.** One object holds the base URL, default headers, timeout, cookies and retry policy.
- **JSON helpers.** `get_json` and `post_json` for the common case, `json=` on any request and `response.json()` on any response.
- **Retries.** Exponential backoff on connection errors, timeouts, `429` and `5xx`. A `Retry-After` header from the server is used instead of the backoff when present.
- **Certificates.** Always verified, TLS 1.2 or newer. Pass `ca_bundle=` to trust your own CA. There is no switch to turn checking off.
- **Safe redirects.** Redirects from `https` to `http` or to other schemes are refused, and `Authorization` and `Cookie` headers are dropped when a redirect goes to another host.
- **Typed exceptions.** Everything raised inherits from `SecureFetchError`.

---

### Install

```sh
git clone https://github.com/Rukioyuza/securefetch
cd securefetch
pip install .
```

Requires Python 3.10 or newer.

---

### Usage

```python
from securefetch import ClientError, RetryPolicy, Session

api = Session(
    "https://api.example.com/v1",
    headers={"Authorization": "Bearer my-token"},
    timeout=5,
    retry=RetryPolicy(total=3, backoff_factor=0.5),
)

# GET https://api.example.com/v1/users?page=2
users = api.get_json("users", params={"page": 2})

# POST a JSON body and read the JSON reply
created = api.post_json("users", {"name": "Ada"})

# Lower level: get the Response object
response = api.get("users/42")
print(response.status, response.headers["Content-Type"])
print(response.text)

try:
    api.get("users/does-not-exist")
except ClientError as err:
    print(err.status, err.response.json())
```

Trusting a custom CA, for example an internal server or a self-signed test certificate:

```python
internal = Session("https://intranet.local", ca_bundle="certs/company-ca.pem")
```

Turning off the automatic exception for `4xx` and `5xx` responses:

```python
session = Session(raise_for_status=False)
response = session.get("https://example.com/maybe-missing")
if not response.ok:
    print("got", response.status)
```

---

### Session options

| Option | Default | Purpose |
| --- | --- | --- |
| `base_url` | `None` | Relative URLs are appended to this. Absolute URLs are used as they are |
| `headers` | `{}` | Headers sent with every request. Per request headers override them |
| `timeout` | `10.0` | Seconds to wait for the connection and for each read |
| `retry` | `RetryPolicy()` | When and how long to wait before retrying |
| `ca_bundle` | `None` | PEM file or folder of CA certificates to trust instead of the system store |
| `raise_for_status` | `True` | Raise `ClientError` or `ServerError` for `4xx` and `5xx` responses |
| `trust_env` | `True` | Use proxy settings from the environment |

Request methods: `get`, `head`, `post`, `put`, `patch`, `delete` and `request(method, url)`. Each takes `params=`, `headers=`, `json=`, `data=` (bytes, str or a dict to form encode) and `timeout=`.

---

### Retry policy

| Field | Default | Purpose |
| --- | --- | --- |
| `total` | `3` | Retries after the first attempt. `0` turns retries off |
| `backoff_factor` | `0.5` | First delay in seconds, doubled on each retry |
| `max_backoff` | `30.0` | Upper limit for any delay, including `Retry-After` |
| `statuses` | `429, 500, 502, 503, 504` | Status codes that are retried |
| `methods` | `GET, HEAD, OPTIONS, PUT, DELETE, TRACE` | Methods retried on connection errors and `5xx` |

A `429` is retried for every method, since the server did not handle the request. A `POST` that hits a connection error or a `5xx` is not retried, so it is never sent twice by accident. TLS errors are never retried.

---

### Exceptions

| Exception | Raised when |
| --- | --- |
| `SecureFetchError` | Base class for everything below |
| `InvalidURL` | The URL is not `http` or `https`, or has no host |
| `ConnectionFailed` | The connection could not be made or was dropped |
| `RequestTimeout` | The server did not answer in time (a `ConnectionFailed`) |
| `TLSError` | The TLS handshake failed, usually an untrusted certificate (a `ConnectionFailed`) |
| `RedirectError` | A redirect was refused |
| `HTTPError` | A `4xx` or `5xx` response, with `.status` and `.response` |
| `ClientError` / `ServerError` | `4xx` / `5xx` (both are `HTTPError`) |
| `DecodeError` | `response.json()` got a body that is not JSON |

---

### Running the tests

```sh
pip install -e .
python -m unittest discover -s tests
```

The tests start a local server on `127.0.0.1` in a thread and never touch the network. The certificate and key in `tests/certs` are a self-signed pair for `127.0.0.1`, used only to test HTTPS end to end. Do not use them for anything else.

---

### License

MIT
