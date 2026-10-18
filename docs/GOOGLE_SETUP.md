# Google setup

Meeting Desk needs one Google OAuth client. It is used for two things:

1. **Sign-in.** Everyone who uses the app signs in with Google (OpenID Connect).
2. **Admin connections.** An admin connects one or more Google accounts on the **Admin** page. The
   app reads Calendar, Drive, Docs, Gmail and Sheets *as those accounts*, and writes to Sheets as
   them. Their refresh tokens are encrypted at rest with `MEETING_DESK_TOKEN_KEY`.

You do **not** need any of this to try the app: the demo (`docker compose -f
docker-compose.demo.yml up`, or `make run`) uses a built-in fake Google.

## Before you start: Workspace or personal account?

| | Google Workspace (your company domain) | Personal Gmail account |
| --- | --- | --- |
| OAuth consent screen | **Internal**: only your domain can use it, no Google review, refresh tokens do not expire on a timer. Recommended. | **External**, left in *Testing* with yourself added as a test user. |
| Token lifetime | Until revoked | Google expires refresh tokens of apps in *Testing* after **7 days**, so you reconnect on the Admin page weekly. Publishing the app needs Google's verification for the Gmail and Drive scopes. |
| Directory lookups (owner names to emails) | Work, through the People API's directory search | Not available (the scope may not be granted); owners still resolve against the meeting's attendees. |
| `GOOGLE_HOSTED_DOMAIN` | Your domain, e.g. `example.com` | Leave empty |

## 1. Create a Google Cloud project

In the [Google Cloud console](https://console.cloud.google.com/), create a project (any name). If
you will use Gemini on Vertex AI for extraction, this is also the project that goes in
`VERTEX_PROJECT`.

## 2. Enable the APIs

Under **APIs & Services → Library**, enable:

- Google Calendar API
- Google Drive API
- Google Docs API
- Gmail API
- Google Sheets API
- People API
- Vertex AI API (only if `EXTRACTION_PROVIDER=vertex`)

## 3. Configure the OAuth consent screen

**APIs & Services → OAuth consent screen**: choose **Internal** (Workspace) or **External**
(personal account, see the table above). Fill in the app name, support email and developer contact,
then add these scopes:

```
openid
https://www.googleapis.com/auth/userinfo.email
https://www.googleapis.com/auth/userinfo.profile
https://www.googleapis.com/auth/calendar.readonly
https://www.googleapis.com/auth/drive.readonly
https://www.googleapis.com/auth/documents.readonly
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/spreadsheets
https://www.googleapis.com/auth/directory.readonly
```

The list lives in `api/app/google/oauth.py` (`CONNECTION_SCOPES`). Sign-in itself only asks for
`openid`, `email` and `profile`; the rest are requested when an admin connects an account, and the
Admin page shows which ones each connection granted.

What each scope is used for:

| Scope | Used for |
| --- | --- |
| `calendar.readonly` | The meeting list: recent and upcoming events of every connected account |
| `drive.readonly`, `documents.readonly` | Finding and reading the "Notes by Gemini" doc of a meeting |
| `gmail.readonly` | Finding the Gemini recap email of a meeting |
| `spreadsheets` | Reading the roadmap tabs and writing the rows |
| `directory.readonly` | Turning an owner's name into their work email (Workspace only) |

## 4. Create the OAuth client

**APIs & Services → Credentials → Create credentials → OAuth client ID → Web application.**

Authorised redirect URIs (both, for every host you serve the app on):

| URI | Setting |
| --- | --- |
| `http://localhost:8000/auth/callback` | `GOOGLE_OIDC_REDIRECT_URI` |
| `http://localhost:8000/admin/connections/callback` | `GOOGLE_CONNECT_REDIRECT_URI` |
| `https://meeting-desk.example.com/auth/callback` | the same, on your deployment |
| `https://meeting-desk.example.com/admin/connections/callback` | |

Authorised JavaScript origins: the URL you open the app on, e.g. `http://localhost:8000`.

Copy the client ID and secret into `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

## 5. Run it with your account

On your own machine, with Docker:

```bash
cp .env.live.example .env
# fill in BOOTSTRAP_ADMINS (your email), GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET,
# and GOOGLE_HOSTED_DOMAIN if you use Workspace
scripts/live.sh              # or: make live
```

`scripts/live.sh` generates the session secret and the token key, builds the image, starts
Postgres and the app on http://localhost:8000, and waits until it is healthy. Then:

1. Sign in with the account in `BOOTSTRAP_ADMINS`.
2. On **Admin → Connect an account**, connect the Google account whose calendar and notes you want
   to use. Connect a second one if you can: reads fall back across connections.
3. Add teammates to the allow-list on the same page.
4. On **Sheets**, paste the URL of the spreadsheet you want rows written to.

`scripts/live.sh logs` follows the log, `scripts/live.sh down` stops it (the database volume stays).

For a server deployment see [DEPLOY.md](DEPLOY.md).
