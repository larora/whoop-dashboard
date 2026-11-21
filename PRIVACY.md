# Privacy policy

This software is a self-hosted, single-user dashboard for your own WHOOP data. There is no company behind it and no central service; each person who runs it operates their own private copy.

**What data it accesses.** With your permission, granted through WHOOP's own sign-in page, it reads your recovery, sleep, cycle (strain), workout and body-measurement records from the official WHOOP API.

**Where the data goes.** Into a SQLite database file on the computer or server where you run the app, at the location you configure. Nothing is sent to the author of this software or to any third party. The only external service the app communicates with is `api.prod.whoop.com`.

**Who can see it.** Whoever has your dashboard password, and, if you enable the optional MCP endpoint, whoever has that token. You control both. The dashboard runs behind a login; nothing is public.

**How long it's kept.** Until you delete the database file. Deleting it removes everything, including the WHOOP access tokens.

**Revoking access.** You can revoke the app's access at any time in your WHOOP account settings or by deleting the app in the WHOOP developer dashboard. Deleting the local database file also removes the stored tokens.

**Cookies.** One signed session cookie to keep you logged in to your own dashboard. No analytics, no tracking.

**Changes.** This document lives in the repository alongside the code; any change to how the app handles data will be reflected here.
