# MeterBeheer Connector - UI Component

This is the front end of the MeterBeheer Connector app for IXON Cloud. It shows a building's electricity consumption from the Meterbeheer HUB and marks every quarter-hour in which the average power went above the building's contracted capacity, so users can spot moments that could lead to extra charges or fines.

The data comes from the Cloud Function in [`../meterbeheer-connector-cf`](../meterbeheer-connector-cf) (`functions.meterbeheer_connector.*`). The component itself never talks to Meterbeheer.

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

All commands run from this folder (`meterbeheer-connector-ui`). Outside it, `npx` cannot find IXON's `cdk` and offers an unrelated public package with the same name.

1. Install the dependencies (first time only):

   ```sh
   npm install
   ```

2. Start the Cloud Function with `make run` in [`../meterbeheer-connector-cf`](../meterbeheer-connector-cf).
3. Start the simulator:

   ```sh
   npx cdk simulate meterbeheer-connector
   ```

4. In the simulator, open **Settings > Component** and select **Local Cloud Function Ingress**, add one or more buildings with their contracted capacity in the right-hand panel, and click **Preview** to interact with the component.

The simulator rebuilds and reloads on every change to the component's source files.

## Files

- [`components/meterbeheer-connector/meterbeheer-connector.svelte`](./components/meterbeheer-connector/meterbeheer-connector.svelte): the component (Svelte 5)
- [`components/meterbeheer-connector/manifest.json`](./components/meterbeheer-connector/manifest.json): settings panel inputs and grid size
- [`cdk.config.json`](./cdk.config.json): workspace configuration (prefix `pct`, so the element is `pct-meterbeheer-connector`)

## Deployment to IXON Cloud

Deploy the [Cloud Function](../meterbeheer-connector-cf/README.md#deployment-to-ixon-cloud) first, then follow these steps.

### What you need

- An IXON Cloud account with the **Develop apps** permission. `npx cdk login` needs your IXON credentials; SSO logins are not supported.
- Your company's **Public ID**. You can find it in the IXON Portal when clicking on your avatar while connected to a company.

### 1. Register the UI Component

1. Open [Studio > UI Components](https://portal.ixon.cloud/studio/ui-components).
2. Click **Add new UI Component**.
3. Enter a name that end users will recognise (for example, MeterBeheer Connector) and click **Add**.
4. Copy the **Public ID** that is displayed. This is the UI Component ID.

### 2. Check the icon

[`components/meterbeheer-connector/icon.svg`](./components/meterbeheer-connector/icon.svg) is shown in the component picker when someone adds the component to a page. If you replace it, keep the file name `icon.svg`, use a vector-based image and give it a transparent background.

### 3. Log in

From this folder:

```sh
npx cdk login
```

This asks for your IXON Cloud credentials and creates a git-ignored `.accesstoken` file. You can reuse that token for the Cloud Function deployment.

### 4. Deploy

```sh
npx cdk deploy meterbeheer-connector
```

The first time, you are asked for the **company ID** and the **UI Component ID** from step 1. They are saved in [`cdk.config.json`](./cdk.config.json). When the deployment finishes, you receive a preview link to test the component in your company.

The `version` in [`manifest.json`](./components/meterbeheer-connector/manifest.json) must be increased for every new deployment. Otherwise the deployment fails with "version: Already exists".

### 5. Publish

```sh
npx cdk publish meterbeheer-connector
```

You are asked which version to publish. Once it is published, all users in your company can use the component. Users stay on the published version until you publish a new one.

### 6. Link the UI Component to the Cloud Function

1. Open [Studio > UI Components](https://portal.ixon.cloud/studio/ui-components) and select your UI Component.
2. In the **General** section, click **Edit** next to **Cloud Function**.
3. Select the Cloud Function you deployed.

You can also do this the other way around, by linking the Cloud Function to the UI Component in Studio > Cloud Functions. Make sure the app is enabled under [Admin > Apps](https://portal.ixon.cloud/admin/apps) and that the Meterbeheer configuration has been entered (see [step 5 of the Cloud Function deployment](../meterbeheer-connector-cf/README.md#5-enter-the-meterbeheer-configuration-in-ixon-cloud)).

### 7. Add the component to a page

Open a page in Studio, click **Add a Component** and choose **MeterBeheer Connector**. Then add your buildings and their contracted capacity in the component settings (see [Settings](#settings-component-inputs)).

## Updating the workspace

`npm install` installs the versions recorded in `package-lock.json`. Check for newer `@ixon-cdk/` packages with `npm outdated` and keep them on the same version when updating:

```sh
npm update @ixon-cdk/core @ixon-cdk/runner @ixon-cdk/simulator @ixon-cdk/templates
```

Release notes are on the [IXON developer website](https://developer.ixon.cloud/changelog).

## Support

For more information about UI Components, see the [UI Component documentation](https://developer.ixon.cloud/docs/getting-started-ui-components) and the [@ixon-cdk/runner](https://www.npmjs.com/package/@ixon-cdk/runner) command overview.
