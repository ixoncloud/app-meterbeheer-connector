# MeterBeheer Connector

An example IXON Cloud App that shows a building's electricity consumption from the [Meterbeheer HUB](https://hub.meterbeheer.nl) and flags every quarter-hour in which the average power went above the building's contracted capacity. Going over the contracted capacity can lead to extra charges or fines from the grid operator, so the app makes those moments easy to spot.

It also serves as a reference for building an app on IXON Cloud from two parts:

- a **UI Component** that runs in the IXON Portal and draws the charts
- a **Cloud Function** that talks to an external API, keeps its API key secret, and prepares the data for the component

## DISCLAIMER: Workshop App

This project is provided as a **reference** for building a similar custom application within the IXON environment. It is not updated on a regular schedule. Use it as a starting point and adapt it to your own needs. It is provided "as is".

## How it works

```
IXON Portal page
  └─ UI Component (meterbeheer-connector-ui)
       │  functions.meterbeheer_connector.get_feeds
       │  functions.meterbeheer_connector.get_consumption_series
       ▼
     Cloud Function (meterbeheer-connector-cf)
       │  Meterbeheer API key (function configuration)
       ▼
     Meterbeheer HUB API (15-minute metering data)
```

1. The component asks the Cloud Function for the list of buildings (Meterbeheer feeds) and shows them in a dropdown.
2. When a user picks a building, the component asks for its consumption over the page's time range.
3. The Cloud Function fetches the 15-minute data from Meterbeheer, groups it per quarter-hour, day, month or year, and counts the quarter-hours above the contracted capacity.
4. The component draws the result.

The browser never sees the Meterbeheer API key, EANs, addresses or feed URLs.

## What users see

The view follows the page's time range:

| Time range | View |
| --- | --- |
| **up to ~1 day** | **Quarter-hours:** kWh bars, average power line (kW), dashed contracted-capacity line, red dots on exceeded quarter-hours and a "Limit exceeded!" note on the highest peak |
| **up to ~2 months** | **Days:** kWh per day |
| **up to ~2 years** | **Months:** kWh per month |
| **longer** | **Years:** kWh per year |

In the day, month and year views a red ▼ marks periods that contain an exceeded quarter-hour. Clicking a bar zooms in, and **Back** zooms out. Missing data is shown as "No data", never as 0.

The [`images`](./images) folder contains the reference designs for the four views from the original specification.

## Contracted capacity per building

Buildings on the same Meterbeheer account can have different contracts. In the component settings, the admin adds one entry per building with its **name** (as shown in the building dropdown or in the Meterbeheer HUB) and its **contracted capacity in kW**. The kW can be left empty until it is known; the chart is then shown without the capacity line, with "Contracted capacity not set" in the legend.

## Folder structure

| Folder / file | Contents |
| --- | --- |
| [`meterbeheer-connector-ui`](./meterbeheer-connector-ui) | UI Component (Svelte), settings, simulator and deployment instructions |
| [`meterbeheer-connector-cf`](./meterbeheer-connector-cf) | Cloud Function (Python), configuration, unit tests and deployment instructions |
| [`images`](./images) | Reference designs of the four views |
| [`CHANGELOG.md`](./CHANGELOG.md) | Changes per release |

## Getting started

1. **Cloud Function:** See the [Cloud Function README](./meterbeheer-connector-cf/README.md).
2. **UI Component:** See the [UI Component README](./meterbeheer-connector-ui/README.md).

**Notes**:

- Make sure to run the Cloud Function and UI Component in **separate terminals**.
- It is advised to open the project folders in **two different editor workspaces** for ease of development.

### Deploy and publish your own version

Read these two sections and follow them **in this order**:

1. **Cloud Function:** [Deployment to IXON Cloud](./meterbeheer-connector-cf/README.md#deployment-to-ixon-cloud). Register, deploy and configure the Cloud Function.
2. **UI Component:** [Deployment to IXON Cloud](./meterbeheer-connector-ui/README.md#deployment-to-ixon-cloud). Register, deploy and publish the UI Component, and link it to the Cloud Function.
