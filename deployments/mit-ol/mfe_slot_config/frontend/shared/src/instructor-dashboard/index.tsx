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
export const PlaceholderSlot = (_props: Record<string, unknown>) => null;

// ---------------------------------------------------------------------------
// MIT OL instructor dashboard customizations
//
// Adds two extra tabs to the instructor dashboard:
//   - Canvas        → Canvas LMS enrollment / grade sync (ol_openedx_canvas_integration)
//   - Rapid Responses → rapid response run report downloads (ol_openedx_rapid_response_reports)
//
// Each tab needs a nav entry (tabs slot) and its page content (routes slot).
// ---------------------------------------------------------------------------

export function createInstructorDashboardCustomApp(): App {
	const slots: SlotOperation[] = [
		// Canvas Integration tab + page.
		{
			slotId: SLOT.tabs,
			id: "org.openedx.frontend.widget.instructorDashboard.tab.canvas_integration",
			op: WidgetOperationTypes.APPEND,
			element: (
				<PlaceholderSlot
					tabId="canvas_integration"
					title="Canvas"
					url="canvas_integration"
					sortOrder={20}
				/>
			),
		},
		{
			slotId: SLOT.routes,
			id: "org.openedx.frontend.widget.instructorDashboard.route.canvas_integration",
			op: WidgetOperationTypes.APPEND,
			element: (
				<PlaceholderSlot tabId="canvas_integration" content={<CanvasIntegrationPage />} />
			),
		},
		// Rapid Response Reports tab + page.
		{
			slotId: SLOT.tabs,
			id: "org.openedx.frontend.widget.instructorDashboard.tab.rapid_response",
			op: WidgetOperationTypes.APPEND,
			element: (
				<PlaceholderSlot
					tabId="rapid_response"
					title="Rapid Responses"
					url="rapid_response"
					sortOrder={21}
				/>
			),
		},
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
