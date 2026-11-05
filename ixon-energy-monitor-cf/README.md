# IXON Energy Monitor - Cloud Function

This is the backend of the IXON Energy Monitor app for IXON Cloud. It reads a building's 15-minute metering data retrieved from Meterbeheer, groups it per quarter-hour, day, month or year, and counts the quarter-hours in which the average power was above the building's contracted capacity. The UI Component in [`../ixon-energy-monitor-ui`](../ixon-energy-monitor-ui) calls these functions and draws the charts.

The Meterbeheer API key stays in the Cloud Function. The browser only receives the feed list (id, name, provider, status, meter kind and channel codes) and the grouped series; EANs, addresses and feed URLs are never sent to it.

Meterbeheer sends data relative to the previous day. For this reason, the "Today" view in the IXON Portal may not always display data correctly.

## Functions

Both live in [`functions/ixon_energy_monitor.py`](./functions/ixon_energy_monitor.py) and return `{"success": false, "error": "<message>"}` when something goes wrong.

### `functions.ixon_energy_monitor.get_feeds`

Returns the feeds of the configured Meterbeheer account for the building and channel pickers. Each channel is labelled `consumption`, `production` or `unknown` from its code, so all providers' naming works (`1.8.0`/`2.8.0`, `consumption`/`production`, `kwhCons`/`kwhProd`); consumption channels come first.

### `functions.ixon_energy_monitor.get_consumption_series`

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

### Where are secrets and environment configurations kept?

- **Locally**: they are retrieved from `context_values.yaml` in this folder. Create that file yourself; it is git-ignored because it holds secrets.
- **In IXON Cloud**, the same block of configuration or secrets placed in `context_values.yaml` has to be placed in the same block in the Cloud Function's encrypted configuration **(Admin > Apps > *function* > More options > Settings)** and set its confidentiality to **Secret (Studio > Cloud Functions > *function* > Confidentiality)**.

**Note:**

- **Never** put the key in the Default config, which is **NOT** encrypted.

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

1. Open this folder (`ixon-energy-monitor-cf`) in a different page of your editor and reopen it in the Dev Container (VS Code: **Reopen in Container**).
2. From the integrated terminal:

   ```sh
   make run
   ```

Port `8080` (where `ixoncdkingress` serves) is forwarded automatically.

## Deployment to IXON Cloud

```sh
make deploy
```

This builds a bundle and deploys it to IXON Cloud. It needs a **Company ID**, a **Cloud Function public ID** and an **access token** (see [Deploy and publish](https://developer.ixon.cloud/docs/how-to-register-deploy-and-publish-a-cloud-function#deploy-and-publish)). Provide them through two files in this folder (both git-ignored):

- `.env` must contain the company and template IDs:

  ```make
  IXON_API_COMPANY_ID=1111-2222-3333-4444-5555
  IXON_API_TEMPLATE_ID=a1b2c3d4e5f6
  ```

- `.accesstoken` must contain a valid access token: the easiest way to obtain one is to run `npx cdk login` while simulating `ixon-energy-monitor` from the UI Component Workspace ()

After deploying, set the encrypted configuration as described under [Configuration](#configuration).

## Other commands

- `make py-venv-dev`: set up the virtual environment without starting `ixoncdkingress`.
- `make py-distclean`: remove this project's virtual environment.

## Support

For more information about Cloud Functions, see the [IXON developer website](https://developer.ixon.cloud/).
