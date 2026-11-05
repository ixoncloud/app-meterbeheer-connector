# IXON Energy Monitor - UI Component

This is the front end of the IXON Energy Monitor app for IXON Cloud. It shows a building's electricity consumption from the Meterbeheer HUB and marks every quarter-hour in which the average power went above the building's contracted capacity, so users can spot moments that could lead to extra charges or fines.

The data comes from the Cloud Function in [`../ixon-energy-monitor-cf`](../ixon-energy-monitor-cf) (`functions.ixon_energy_monitor.*`). The component itself never talks to Meterbeheer.

## What the component shows

At the top, a **building** dropdown (all feeds of the Meterbeheer account) and, when a feed has several channels, a **channel** picker (consumption is default). The chart follows the page's time range:

| Time range | Expected view |
| --- | --- |
| **up to ~1 day** | **Quarter-hours:** kWh bars (left axis), average-power line in kW (right axis, kW = kWh × 4), dashed contracted-capacity line, red dots on exceeded quarter-hours and a "Limit exceeded!" note on the highest one. |
| **up to ~2 months** | **Days:** kWh per day. |
| **up to ~2 years** | **Months:** kWh per month, with the value above each bar. |
| **longer** | **Years:** kWh per year, with the value above each bar. |

Other characteristics:

- In the day, month and year views a red ▼ marks periods that contain a quarter-hour **above the capacity**. Clicking a bar zooms in (year > month > day > quarter-hours);
- **Back** returns one level.
- **Hovering** shows kWh, peak and average kW, the number of exceedances and whether the period is incomplete.
- **Missing data** is never drawn as 0: a period without data is hatched ("No data"), a period with gaps is drawn lighter ("Incomplete"), and time Meterbeheer has not published yet (it publishes each day's data the following day) stays blank, with "Data available up to …" below the chart. Dates and numbers follow the platform's locale and time zone; colours of text and background follow the IXON design tokens, so dark mode works.

## Settings (component inputs)

| Setting | Description |
| --- | --- |
| **Title** | Optional heading |
| **Contracted capacity per building** | A list with one entry per building: the **building name** (typed exactly as it appears in the building dropdown, or copied from the Meterbeheer HUB; capitals and extra spaces are ignored) and its **contracted capacity (kW)**. Quarter-hours whose average power is above that value count as exceeded (strictly above); 1 kW = 0.25 kWh per quarter-hour. The kW may be left empty. A building without a kW value is shown without the capacity line, with "Contracted capacity not set" in the legend. |
| **Chart colours** | Consumption bars, average-power line, and capacity line/exceedance markers. Defaults follow the specification. |
| **Color rules** | Optional: colour a bar or its value label when its kWh meets a condition. Each rule has an **Applies to** view, because a kWh threshold that suits days rarely suits months or years. Rules only change bars; the line and capacity colours stay. |

The component needs at least 7 × 6 grid cells (10 × 12 by default). Below 7 columns the simulator shows "Invalid component size".

## Running it in the simulator

All commands run from this folder (`ixon-energy-monitor-ui`). Outside it, `npx` cannot find IXON's `cdk` and offers an unrelated public package with the same name.

1. Install the dependencies (first time only):

   ```sh
   npm install
   ```

2. Start the Cloud Function with `make run` in [`../ixon-energy-monitor-cf`](../ixon-energy-monitor-cf).
3. Start the simulator:

   ```sh
   npx cdk simulate ixon-energy-monitor
   ```

4. In the simulator, open **Settings > Component** and select **Local Cloud Function Ingress**, add one or more buildings with their contracted capacity in the right-hand panel, and click **Preview** to interact with the component.

The simulator rebuilds and reloads on every change to the component's source files.

## Files

- [`components/ixon-energy-monitor/ixon-energy-monitor.svelte`](./components/ixon-energy-monitor/ixon-energy-monitor.svelte): the component (Svelte 5)
- [`components/ixon-energy-monitor/manifest.json`](./components/ixon-energy-monitor/manifest.json): settings panel inputs and grid size
- [`cdk.config.json`](./cdk.config.json): workspace configuration (prefix `pct`, so the element is `pct-ixon-energy-monitor`)

## Deployment to IXON Cloud

The deployment needs a **company ID** and a **the ID of the UI Component**; see [Deploying UI Components](https://developer.ixon.cloud/docs/deploying-ui-components) (steps 4 and 5). Log in with your IXON account, then deploy:

```sh
npx cdk login
npx cdk deploy ixon-energy-monitor
```

You are prompted for the company ID and UI Component ID. If all goes well you receive a preview link to test the component in production. Then publish it so it becomes available to all company users:

```sh
npx cdk publish ixon-energy-monitor
```

The component has not been deployed yet, so `manifest.json` stays at `"version": "1"`. Increment it for every later deployment, or the deploy fails with "version: Already exists".

Deploy the Cloud Function as well and set its encrypted Meterbeheer configuration; see the [Cloud Function README](../ixon-energy-monitor-cf/README.md#configuration).

## Updating the workspace

`npm install` installs the versions recorded in `package-lock.json`. Check for newer `@ixon-cdk/` packages with `npm outdated` and keep them on the same version when updating:

```sh
npm update @ixon-cdk/core @ixon-cdk/runner @ixon-cdk/simulator @ixon-cdk/templates
```

Release notes are on the [IXON developer website](https://developer.ixon.cloud/changelog).

## Support

For more information about UI Components, see the [UI Component documentation](https://developer.ixon.cloud/docs/getting-started-ui-components) and the [@ixon-cdk/runner](https://www.npmjs.com/package/@ixon-cdk/runner) command overview.
