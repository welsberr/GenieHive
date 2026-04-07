# GenieHive Reverse Proxy

For external clients, a reverse proxy is cleaner than binding GenieHive directly to every interface.

Recommended pattern:

- keep upstream model servers on `127.0.0.1`
- keep GenieHive node on `127.0.0.1`
- keep GenieHive control on `127.0.0.1`
- expose only the reverse proxy on LAN or ZeroTier

## Caddy Example

Config file:

```caddy
192.168.40.207:8080 {
    reverse_proxy 127.0.0.1:8800
}
```

ZeroTier variant:

```caddy
172.24.50.65:8080 {
    reverse_proxy 127.0.0.1:8800
}
```

Advantages:

- simple config
- easy to move to TLS later
- good default operational behavior

## Nginx Example

Server block:

```nginx
server {
    listen 192.168.40.207:8080;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8800;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

ZeroTier variant:

```nginx
server {
    listen 172.24.50.65:8080;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8800;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Operational Recommendation

For your current host, the cleanest shape is:

1. GenieHive control on `127.0.0.1:8800`
2. reverse proxy on either:
   - `192.168.40.207:8080`
   - `172.24.50.65:8080`
3. clients talk only to the reverse proxy

## Client Example

```bash
python scripts/demo_client_agent.py \
  --base-url http://172.24.50.65:8080 \
  --api-key change-me-client-key \
  --model mentor \
  --task "Describe the preferred and fallback routes on this host."
```

## Security Note

The API key is still required. The reverse proxy improves exposure hygiene, but it is not a substitute for network trust boundaries.
