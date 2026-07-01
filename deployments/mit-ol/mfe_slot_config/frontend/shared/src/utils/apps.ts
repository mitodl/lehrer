import type { App } from "@openedx/frontend-base";

/**
 * Nest an app's routes under `/apps` so React Router matches `/apps/*` without
 * double-prefixing the site basename. Apps with no routes are returned unchanged.
 */
export const wrapWithAppsPath = (app: App): App =>
	app.routes
		? { ...app, routes: [{ path: "apps", children: app.routes }] }
		: app;
