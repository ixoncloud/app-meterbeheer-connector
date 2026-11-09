# MeterBeheer Connector - Cloud Function

This is the backend of the MeterBeheer Connector app for IXON Cloud. It reads a building's 15-minute metering data retrieved from Meterbeheer, groups it per quarter-hour, day, month or year, and counts the quarter-hours in which the average power was above the building's contracted capacity. The UI Component in [`../meterbeheer-connector-ui`](../meterbeheer-connector-ui) calls these functions and draws the charts.

The Meterbeheer API key stays in the Cloud Function. The browser only receives the feed list (id, name, provider, status, meter kind and channel codes) and the grouped series; EANs, addresses and feed URLs are never sent to it.

### Why do I not see any data for the "Today" view?

Meterbeheer sends data relative to the previous day. For this reason, the "Today" view in the IXON Portal may not always display data correctly.

## Functions

Both functions live in [`functions/meterbeheer_connector.py`](./functions/meterbeheer_connector.py) and return `{"success": false, "error": "<message>"}` when something goes wrong.

### `functions.meterbeheer_connector.get_feeds`

Returns the feeds of the configured Meterbeheer account for the building and channel pickers. Each channel is labelled `consumption`, `production` or `unknown` from its code, so all providers' naming works (`1.8.0`/`2.8.0`, `consumption`/`production`, `kwhCons`/`kwhProd`); consumption channels come first.

### `functions.meterbeheer_connector.get_consumption_series`

| Argument | Description |
| --- | --- |
| `feed_id` | Feed id from `get_feeds` |
| `channel_code` | Channel code from `get_feeds`, e.g. `kwhCons` |
| `from_ms`, `to_ms` | Time window in epoch milliseconds; the end is capped at "now" |
| `interval` | `quarter`, `day`, `month`, `year` or `auto` (default) |
| `tz` | IANA time zone for grouping, default `Europe/Amsterdam` |
| `capacity_kw` | Contracted capacity in kW; leave empty to skip the exceedance count |

With `interval: auto` the view follows the length of the window:

| Window | View |
| --- | --- |
| **up to ~1 day** | quarter-hours |
| **up to ~2 months** | days |
| **up to ~2 years** | months |
| **longer** | years |

Each point holds:
- The total kWh
- The average kW
- The peak quarter-hour kW (and when)
- The number of quarter-hours above the capacity
- How many quarter-hours were received versus expected

A missing period comes back empty (`kwh: null`), never as 0. Time after the newest available quarter does not count as missing, because Meterbeheer publishes each day's data the following day. The response also carries `stats` (totals and `dataUntil`), the unit, Meterbeheer's `errors` list and `master_data`.

Behind the scenes, longer windows are fetched in parallel requests of at most 366 days (Meterbeheer's limit), with one extra day on each side so viewers outside the Dutch time zone don't lose hours at the edges. Daylight-saving days are handled (92 or 100 quarter-hours). Meters that don't report in kWh (gas) get no kW figures or capacity check.

## Configuration

The function reads one block of configuration. Below you can see how it is structured for this project:

```yaml
meterbeheer:
  apiKey: <your Meterbeheer API key>
  baseUrl: https://hub.meterbeheer.nl/api/v1
```

### Where is the configuration kept?

| Where the function runs | Where the configuration comes from |
| --- | --- |
| Locally (`make run`) | `context_values.yaml` in this folder. If not present, create it yourself; it is git-ignored because it holds secrets. It is only used for local development and is **not** part of the deployed bundle. |
| Deployed in IXON Cloud | The function's encrypted configuration in the Portal. See [step 5 of the deployment](#5-enter-the-meterbeheer-configuration-in-ixon-cloud). |

Use the same structure in both places.

**Never** put the key in the Default config, which is **not** encrypted.

## Tests

The unit tests replace Meterbeheer with a stand-in, so they need no network access and no API key. From this folder:

```sh
python -m unittest discover -s tests -v
```

They cover channel detection for all providers, what is and isn't sent to the browser, the 366-day request chunks, daylight-saving days, exceedance counts (including "exactly at the limit is not over"), missing days, the daily publication delay, gas meters, and invalid input.

## Requirements

Running the function locally (`make run`) needs [Docker](https://www.docker.com/) and one of:

- **[Dev Container](#dev-container-recommended) (recommended).** Provides the correct Python version, `make` and `zip` with no local installs. Needs an editor with Dev Container support, such as [VS Code](https://code.visualstudio.com/) with the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers).
- **[Local setup](#local-setup).** Runs the `make` commands directly; on Windows use [WSL](https://learn.microsoft.com/en-us/windows/wsl/). Needs [Python](https://www.python.org/downloads/) matching `ixoncdkingress` (see table) and [zip](https://infozip.sourceforge.net/Zip.html).

| ixoncdkingress | Python |
| -------------- | ------ |
| 1.x.x          | 3.12.x |

`ixoncdkingress` 1.0.0 requires `requests~=2.31.0`, which is why [`requirements.txt`](./requirements.txt) pins `requests==2.31.0`.

### Quick Dev Container Setup (recommended)

Keep the project on a real local disk; Docker cannot bind-mount from cloud-synced drives (Google Drive, OneDrive).

1. Open this folder (`meterbeheer-connector-cf`) in a different page of your editor and reopen it in the Dev Container (VS Code: **Reopen in Container**).
2. From the integrated terminal:

   ```sh
   make run
   ```

Port `8080` (where `ixoncdkingress` serves) is forwarded automatically.

## Deployment to IXON Cloud

Deploy the Cloud Function **before** the UI Component. The [UI Component README](../meterbeheer-connector-ui/README.md#deployment-to-ixon-cloud) continues from here.

### What you need

- An IXON Cloud account with the **Develop apps** permission.
- Your company's **Public ID**. You can find it in the IXON Portal when clicking on your avatar while connected to a company.
- Your Meterbeheer API key.
- `make`, `zip` and Python, **OR** the Dev Container (see [Requirements](#requirements)).

### 1. Register the Cloud Function

1. Open [Studio > Cloud Functions](https://portal.ixon.cloud/studio/cloud-functions).
2. Click **Add new Cloud Function**.
3. Enter a name that end users will recognise (for example, MeterBeheer Connector) and click **Add**.
4. Copy the **Public ID** that is displayed. This is your `IXON_API_TEMPLATE_ID` (also called `publicId` of a Cloud Function).

### 2. Create the `.env` file

Copy `.env.example` to `.env` in this folder and fill in:

```make
IXON_API_COMPANY_ID=1111-2222-3333-4444-5555
IXON_API_TEMPLATE_ID=a1b2c3d4e5f6
```

`IXON_API_COMPANY_ID` is your company's Public ID. `IXON_API_TEMPLATE_ID` is the Public ID of the Cloud Function from step 1. The API base URL, API version and application ID have defaults in the [`Makefile`](./Makefile), so they do not need to be changed.

### 3. Get an access token

`make deploy` reads an access token from a file called `.accesstoken` in this folder.

- **Easiest:** in the UI Component folder, run `npx cdk login` (see the [UI Component README](../meterbeheer-connector-ui/README.md#3-log-in)). It creates an `.accesstoken` file there. Copy its contents into `.accesstoken` in this folder. SSO logins are not supported by this command.
- **Alternative:** create a **User Access Token** by using the **AccessTokenList** endpoint. To learn more, follow [How to create a user access token](https://developer.ixon.cloud/docs/user-access-tokens#how-to-create-a-user-access-token).

Paste only the token, without `Bearer `, on a single line. Tokens expire, so get a new one if the deployment is rejected.

### 4. Deploy

```sh
make deploy
```

This zips `requirements.txt` and the Python files in `functions/` (not the tests and not `context_values.yaml`) into `bundle.zip`, uploads it as a new version and publishes it. The new version appears under **Studio > Cloud Functions > your function > Versions**. The "Last published" label can take a minute or two to show up.

### 5. Enter the Meterbeheer configuration in IXON Cloud

The deployed function does not read `context_values.yaml`. Enter the configuration in the Portal instead:

1. Open [Admin > Apps](https://portal.ixon.cloud/admin/apps) and enable the app if you have not done so yet.
2. Go to **your function > More options > Settings** and enter the same block as in [Configuration](#configuration): your `apiKey` and the `baseUrl`.
3. Set the confidentiality of the configuration to **Secret** under **Studio > Cloud Functions > your function > Confidentiality > Edit**.

### 6. Continue with the UI Component

Follow [Deployment to IXON Cloud](../meterbeheer-connector-ui/README.md#deployment-to-ixon-cloud) in the UI Component README. It also explains how to link the component to this Cloud Function.

### If the deployment fails

An error on the very first request (before anything is uploaded) usually points to the access token, the company ID or your permissions. Check that the token is current and on a single line without `Bearer `, that the company ID in `.env` is complete, and that your account has the **Develop apps** permission.

## Other commands

- `make py-venv-dev`: set up the virtual environment without starting `ixoncdkingress`.
- `make py-distclean`: remove this project's virtual environment.

## Support

For more information about Cloud Functions, see the [IXON developer website](https://developer.ixon.cloud/).
