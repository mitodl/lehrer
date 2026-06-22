import { WidgetOperationTypes } from "@openedx/frontend-base";
import type { App, SlotOperation } from "@openedx/frontend-base";

import CanvasIntegrationPage from "./CanvasIntegrationPage";
import RapidResponseReportsPage from "./RapidResponseReportsPage";

// ---------------------------------------------------------------------------
// Instructor Dashboard slot IDs (from @openedx/frontend-app-instructor-dashboard)
// ---------------------------------------------------------------------------

const SLOT = {
	tabs: "org.openedx.frontend.slot.instructorDashboard.tabs.v1",
	routes: "org.openedx.frontend.slot.instructorDashboard.routes.v1",
} as const;

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
// MIT OL instructor dashboard customizations
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

export function createInstructorDashboardCustomApp(): App {
	const slots: SlotOperation[] = [
		// Canvas Integration page (route only). The nav tab is NOT registered here:
		// the LMS adds the "Canvas" tab via the InstructorDashboardTabsRequested
		// filter (ol_openedx_canvas_integration) only for courses linked to Canvas
		// (canvas_id set), matching the legacy gating. Registering the route
		// unconditionally is harmless — the page is only reachable when that tab
		// is present, and its tabId matches the url the backend filter emits.
		{
			slotId: SLOT.routes,
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
			slotId: SLOT.routes,
			id: "org.openedx.frontend.widget.instructorDashboard.route.rapid_response",
			op: WidgetOperationTypes.APPEND,
			element: (
				<PlaceholderSlot tabId="rapid_response" content={<RapidResponseReportsPage />} />
			),
		},
	];

	return { appId: "mitol.instructorDashboard.customizations", slots };
}
