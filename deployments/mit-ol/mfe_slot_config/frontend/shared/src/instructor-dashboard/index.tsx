import { instructorDashboardApp } from "@openedx/frontend-app-instructor-dashboard";
import { WidgetOperationTypes } from "@openedx/frontend-base";
import type { App, SlotOperation } from "@openedx/frontend-base";

import { wrapWithAppsPath } from "../utils/apps";

import CanvasIntegrationPage from "./CanvasIntegrationPage";
import RapidResponseReportsPage from "./RapidResponseReportsPage";

// Instructor Dashboard routes slot (from @openedx/frontend-app-instructor-dashboard).
// Only the routes slot is used here — the nav tabs come from the backend filter.
const ROUTES_SLOT_ID = "org.openedx.frontend.slot.instructorDashboard.routes.v1";

// ---------------------------------------------------------------------------
// PlaceholderSlot
//
// The instructor dashboard does not render the widgets registered in its tab and
// route slots directly. Instead it introspects each widget's props to build its
// nav tabs (tabId/title/url/sortOrder) and its routes (tabId/content). This
// placeholder simply carries those props — it never renders anything itself.
// Mirrors the PlaceholderSlot shipped in the instructor dashboard MFE.
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-unused-vars
const PlaceholderSlot = (_props: Record<string, unknown>) => null;

// ---------------------------------------------------------------------------
// MIT OL instructor dashboard app
//
// Returns the upstream instructorDashboardApp extended in place (a single app):
// its routes are nested under /apps (wrapWithAppsPath) and our two route widgets
// are appended to its routes slot. Site configs register this one app instead of
// the upstream app plus a separate customization app.
//
// Adds two extra pages to the instructor dashboard:
//   - Canvas        → Canvas LMS enrollment / grade sync (ol_openedx_canvas_integration)
//   - Rapid Responses → rapid response run report downloads (ol_openedx_rapid_response_reports)
//
// Only the page content (routes slot) is registered here for each. The nav tabs
// are added by the LMS via the InstructorDashboardTabsRequested filter so they
// surface exactly where the backend plugins apply:
//   - Canvas        → only for Canvas-linked courses (canvas_id set)
//   - Rapid Responses → only on deployments where the plugin is installed
// This mirrors the legacy server-side gating and avoids showing tabs whose
// backend APIs aren't present.
// ---------------------------------------------------------------------------

export function createMITOLInstructorDashboardApp(): App {
	const mitolSlots: SlotOperation[] = [
		// Canvas Integration page (route only). The nav tab is NOT registered here:
		// the LMS adds the "Canvas" tab via the InstructorDashboardTabsRequested
		// filter (ol_openedx_canvas_integration) only for courses linked to Canvas
		// (canvas_id set), matching the legacy gating. Registering the route
		// unconditionally is harmless — the page is only reachable when that tab
		// is present, and its tabId matches the url the backend filter emits.
		{
			slotId: ROUTES_SLOT_ID,
			id: "org.openedx.frontend.widget.instructorDashboard.route.canvas_integration",
			op: WidgetOperationTypes.APPEND,
			element: (
				<PlaceholderSlot tabId="canvas_integration" content={<CanvasIntegrationPage />} />
			),
		},
		// Rapid Response Reports page (route only). Like Canvas, the nav tab is
		// added by the LMS via the InstructorDashboardTabsRequested filter
		// (ol_openedx_rapid_response_reports) — so the tab only appears on
		// deployments where that plugin is installed, rather than on every
		// deployment that ships this MFE config.
		{
			slotId: ROUTES_SLOT_ID,
			id: "org.openedx.frontend.widget.instructorDashboard.route.rapid_response",
			op: WidgetOperationTypes.APPEND,
			element: (
				<PlaceholderSlot tabId="rapid_response" content={<RapidResponseReportsPage />} />
			),
		},
	];

	// Nest the upstream routes under /apps, then append our route widgets to the
	// app's routes slot. Slot operations apply globally to their target slot, so
	// merging them here is equivalent to a separate customization app.
	const wrapped = wrapWithAppsPath(instructorDashboardApp);
	return {
		...wrapped,
		slots: [...(wrapped.slots ?? []), ...mitolSlots],
	};
}
