# Quack_wiki

## Local development

```bash
python run.py
```

For a new local database, create a local `.env` file from `.env.example` and
set `INITIAL_ADMIN_PASSWORD` before the first run if you want the app to create
an admin account automatically.

## Production WSGI command

Use this on a Python web host that supports long-running WSGI processes:

```bash
pip install -r requirements.txt
gunicorn --bind 0.0.0.0:$PORT main:app
```

If the platform does not provide `PORT`, use:

```bash
gunicorn --bind 0.0.0.0:5000 main:app
```

Required production environment variables:

```bash
SECRET_KEY=use-a-long-random-secret
DATABASE_URL=sqlite:///pages.db
INITIAL_ADMIN_USERNAME=MainAdmin
INITIAL_ADMIN_EMAIL=admin@example.com
INITIAL_ADMIN_PASSWORD=use-a-strong-temporary-password
```

After the first successful admin login, change the admin password and remove
`INITIAL_ADMIN_PASSWORD` from the host environment.

## Cloudflare note

Cloudflare Pages deploys static output from a build command. This Flask app is
dynamic: it needs a long-running Python server, SQLite database writes, sessions,
and uploaded files. Do not use `python run.py` as a Cloudflare Pages build
command, because Pages expects the build command to finish successfully.

To use Cloudflare with this app, host the Flask server on a Python web host
such as Render, Railway, Fly.io, or a VPS, then put Cloudflare DNS/proxy in
front of that host.

## GitHub safety checklist

Before pushing this repository:

```bash
git rm --cached -r instance/pages.db static/img/upload static/img/profile static/img/site
git add .
git commit -m "Harden deployment configuration"
git push
```

In GitHub, open the repository settings and enable:

- Settings > Code security and analysis > Secret scanning
- Settings > Code security and analysis > Push protection
- Settings > Code security and analysis > Dependabot alerts
- Settings > Code security and analysis > Dependabot security updates
- Settings > Branches > Add branch protection rule for `main`

For branch protection, require pull requests, require status checks, disable
force pushes, and disable branch deletion.

## Cloudflare DNS setup

Use Cloudflare as DNS/proxy in front of the Python host:

1. Deploy the Flask app to a Python host using `requirements.txt` and the
   production WSGI command above.
2. Add your domain to Cloudflare and change your domain registrar nameservers
   to the two Cloudflare nameservers.
3. In Cloudflare DNS, create a `CNAME` record for `www` pointing to the host
   domain given by your Python host, for example `your-app.onrender.com`.
4. If your host supports apex domains, create the DNS record it asks for at
   `@`. If it only supports subdomains, redirect the apex domain to `www`.
5. Turn on the orange cloud proxy for public web records.
6. In Cloudflare SSL/TLS, use `Full` or `Full (strict)` once the origin host has
   HTTPS enabled.
