/**
 * MIT OL custom footer component for @openedx/frontend-base.
 *
 * MIGRATION STATUS: Scaffold only — not yet functional.
 *
 * The legacy Footer.jsx at ../legacy/Footer.jsx uses @edx/frontend-platform
 * and @openedx/frontend-plugin-framework APIs that do not exist in frontend-base.
 * This file is a placeholder for the TypeScript rewrite.
 *
 * Migration tasks:
 * - Replace `getConfig()` from @edx/frontend-platform with the frontend-base config API
 * - Replace `PluginSlot` from @openedx/frontend-plugin-framework with the frontend-base
 *   slot API (see @openedx/frontend-base documentation)
 * - Replace `AppContext` from @edx/frontend-platform/react with the frontend-base equivalent
 * - Replace `getLoginRedirectUrl` / `getAuthenticatedHttpClient` with frontend-base auth API
 * - Replace `FormattedMessage` from @edx/frontend-platform/i18n with direct `react-intl`
 * - Review Paragon imports — @openedx/paragon components should be compatible
 *
 * Reference: ../legacy/Footer.jsx
 * See: plans/03-frontend-base-oep65.md § Task 6
 */

import type React from "react";

export function Footer(): React.ReactElement {
	return (
		<footer>
			{/* TODO: port legacy Footer.jsx to frontend-base APIs */}
			<p>MIT OpenLearning</p>
		</footer>
	);
}

export default Footer;
