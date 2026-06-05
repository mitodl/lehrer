import {
	type App,
	SlotOperation,
	WidgetOperationTypes,
} from "@openedx/frontend-base";

/**
 * Creates a shell-level styling app that registers a slot operation
 * to load the deployment's specific stylesheet into a shell slot.
 *
 * This injects the theme SCSS or CSS overrides built specifically for
 * the target environment into a head-level slot in the Shell.
 *
 * @param stylesheetPath Relative or absolute path to the stylesheet (e.g. "@shared/styles/mitxonline.scss")
 */
export function createStyleOverrideApp(stylesheetPath: string): App {
	return {
		appId: `org.mitol.styleOverride.${stylesheetPath.replace(/[^a-zA-Z0-0]/g, "")}`,
		slots: [
			new SlotOperation({
				targetId: "org.openedx.frontend.slot.shell.head.v1",
				widgetOperations: [
					{
						op: WidgetOperationTypes.APPEND,
						widget: {
							id: `mitol-style-override-${stylesheetPath.replace(/[^a-zA-Z0-0]/g, "")}`,
							component: () => {
								// Dynamic import triggers Webpack/Vite compilation of SCSS/CSS
								// and loads it onto the page when the app mounts.
								if (stylesheetPath === "@shared/styles/mitxonline.scss") {
									import("@shared/styles/mitxonline.scss");
								} else if (stylesheetPath === "@shared/styles/mitx.scss") {
									import("@shared/styles/mitx.scss");
								}
								return null;
							},
						},
					},
				],
			}),
		],
	};
}
