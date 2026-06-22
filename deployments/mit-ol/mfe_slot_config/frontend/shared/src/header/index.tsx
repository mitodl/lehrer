import type { FC } from "react";
import {
	useSiteConfig,
	useAuthenticatedUser,
	WidgetOperationTypes,
	Slot,
} from "@openedx/frontend-base";
import type { App, SlotOperation } from "@openedx/frontend-base";
import { Container, Dropdown, Hyperlink, Image } from "@openedx/paragon";
import { isLearnCourse, isMITxOnlineCourse } from "../utils/courseContext";

// ---------------------------------------------------------------------------
// Shared slot IDs and widget IDs (from @openedx/frontend-base headerApp)
// ---------------------------------------------------------------------------

const SLOT = {
	desktop: "org.openedx.frontend.slot.header.desktop.v1",
	mobile: "org.openedx.frontend.slot.header.mobile.v1",
	desktopLeft: "org.openedx.frontend.slot.header.desktopLeft.v1",
	desktopRight: "org.openedx.frontend.slot.header.desktopRight.v1",
	mobileCenter: "org.openedx.frontend.slot.header.mobileCenter.v1",
	mobileRight: "org.openedx.frontend.slot.header.mobileRight.v1",
	secondaryLinks: "org.openedx.frontend.slot.header.secondaryLinks.v1",
	authenticatedMenu: "org.openedx.frontend.slot.header.authenticatedMenu.v1",
} as const;

const WIDGET = {
	desktopLayout: "org.openedx.frontend.widget.header.desktopLayout.v1",
	mobileLayout: "org.openedx.frontend.widget.header.mobileLayout.v1",
	desktopLogo: "org.openedx.frontend.widget.header.desktopLogo.v1",
	mobileLogo: "org.openedx.frontend.widget.header.mobileLogo.v1",
	desktopPrimaryLinks:
		"org.openedx.frontend.widget.header.desktopPrimaryLinks.v1",
	desktopAuthenticatedMenu:
		"org.openedx.frontend.widget.header.desktopAuthenticatedMenu.v1",
	mobileAuthenticatedMenu:
		"org.openedx.frontend.widget.header.mobileAuthenticatedMenu.v1",
	help: "org.openedx.frontend.widget.header.help.v1",
	menuProfile:
		"org.openedx.frontend.widget.header.desktopAuthenticatedMenuProfile.v1",
	menuAccount:
		"org.openedx.frontend.widget.header.desktopAuthenticatedMenuAccount.v1",
	menuLogout:
		"org.openedx.frontend.widget.header.desktopAuthenticatedMenuLogout.v1",
} as const;

// ---------------------------------------------------------------------------
// Shared config interface (populated via FRONTEND_SITE_CONFIG commonAppConfig)
// ---------------------------------------------------------------------------

export interface MITOLHeaderConfig {
	mitLearnBaseUrl?: string;
	marketingSiteBaseUrl?: string;
}

function useMITOLHeaderConfig(): MITOLHeaderConfig {
	const { commonAppConfig } = useSiteConfig();
	return ((commonAppConfig as Record<string, unknown>)?.mitolHeader ??
		{}) as MITOLHeaderConfig;
}

// ---------------------------------------------------------------------------
// Shared user menu toggle component
// Used by mitxonline to replace the default AvatarButton toggle with an SVG
// person icon + display name. mitx and xpro use the default Paragon toggle.
// ---------------------------------------------------------------------------

const UserMenuToggle: FC = () => {
	const authenticatedUser = useAuthenticatedUser();
	if (!authenticatedUser) return null;
	return (
		<Dropdown.Toggle
			as="div"
			id="user-nav-dropdown-custom"
			className="d-flex align-items-center gap-2 cursor-pointer"
		>
			{/* Person icon */}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="24"
				height="24"
				viewBox="0 0 32 32"
				fill="none"
			>
				<path
					d="M15.9998 2.66797C23.3598 2.66797 29.3332 8.6413 29.3332 16.0013C29.3332 23.3613 23.3598 29.3346 15.9998 29.3346C8.63984 29.3346 2.6665 23.3613 2.6665 16.0013C2.6665 8.6413 8.63984 2.66797 15.9998 2.66797ZM8.03093 20.5564C9.98761 23.4772 12.9267 25.3346 16.2128 25.3346C19.4989 25.3346 22.438 23.4772 24.3946 20.5564C22.2512 18.5576 19.3748 17.3346 16.2128 17.3346C13.0508 17.3346 10.1744 18.5576 8.03093 20.5564ZM15.9998 14.668C18.209 14.668 19.9998 12.8771 19.9998 10.668C19.9998 8.45884 18.209 6.66797 15.9998 6.66797C13.7906 6.66797 11.9998 8.45884 11.9998 10.668C11.9998 12.8771 13.7906 14.668 15.9998 14.668Z"
					fill="white"
				/>
			</svg>
			<span className="user-menu-name">
				{authenticatedUser.name || authenticatedUser.username}
			</span>
			<svg
				viewBox="0 0 24 24"
				xmlns="http://www.w3.org/2000/svg"
				width="24"
				height="24"
				fill="currentColor"
			>
				<path d="M11.9999 13.1714L16.9497 8.22168L18.3639 9.63589L11.9999 15.9999L5.63599 9.63589L7.0502 8.22168L11.9999 13.1714Z" />
			</svg>
		</Dropdown.Toggle>
	);
};

// ---------------------------------------------------------------------------
// Custom authenticated user menu — replaces the default AvatarButton toggle
// with UserMenuToggle (person icon + display name + chevron) while keeping the
// frontend-base authenticatedMenu slot for the dropdown items.
// ---------------------------------------------------------------------------

const MITxOnlineAuthenticatedMenu: FC<{ className?: string }> = ({
	className,
}) => (
	<Dropdown className={className}>
		<UserMenuToggle />
		<Dropdown.Menu className="dropdown-menu-right">
			<Slot id={SLOT.authenticatedMenu} />
		</Dropdown.Menu>
	</Dropdown>
);

// ---------------------------------------------------------------------------
// Always-desktop header layout. The frontend-base shell swaps to a hamburger +
// centered-logo MobileLayout below 768px (via a JS media query). MIT OL keeps
// the desktop-style layout (logo left, course info, user menu right) at every
// width to match the rest of the platform, so we replace the shell's
// DesktopLayout with one that never applies `d-none` and replace MobileLayout
// with nothing. Narrow-width trimming is handled in the deployment SCSS.
// ---------------------------------------------------------------------------

const AlwaysDesktopLayout: FC = () => (
	<Container
		fluid
		className="align-items-center justify-content-between d-flex"
	>
		<div className="d-flex flex-grow-1 align-items-center">
			<Slot id={SLOT.desktopLeft} />
		</div>
		<div className="d-flex align-items-center">
			<Slot id={SLOT.desktopRight} />
		</div>
	</Container>
);

const NoMobileLayout: FC = () => null;

// ---------------------------------------------------------------------------
// MITx Online header — full UAI/Learn course detection, custom logo, user menu
// ---------------------------------------------------------------------------

/** Logo that links to the dashboard appropriate for the current course context. */
const MITxOnlineLogo: FC = () => {
	const { lmsBaseUrl } = useSiteConfig();
	const { mitLearnBaseUrl, marketingSiteBaseUrl } = useMITOLHeaderConfig();
	const destinationUrl = isLearnCourse()
		? `${mitLearnBaseUrl ?? "https://learn.mit.edu"}/dashboard`
		: `${marketingSiteBaseUrl ?? lmsBaseUrl}/dashboard/`;
	const { headerLogoImageUrl } = useSiteConfig();
	return (
		<Hyperlink destination={destinationUrl} className="p-0">
			<Image
				src={headerLogoImageUrl ?? "https://edx-cdn.org/v3/default/logo.svg"}
				style={{ maxHeight: "2rem" }}
			/>
		</Hyperlink>
	);
};

/** Dashboard link rendered in the secondary links slot. */
const MITxOnlineDashboardLink: FC = () => {
	const { lmsBaseUrl } = useSiteConfig();
	const { mitLearnBaseUrl, marketingSiteBaseUrl } = useMITOLHeaderConfig();
	const url = isLearnCourse()
		? `${mitLearnBaseUrl ?? "https://learn.mit.edu"}/dashboard`
		: `${marketingSiteBaseUrl ?? lmsBaseUrl}/dashboard/`;
	return (
		<Hyperlink destination={url} className="dashboard-btn">
			Dashboard
		</Hyperlink>
	);
};

/** Profile menu item — only shown for MITx Online courses (not UAI/Learn, not non-course pages). */
const MITxOnlineProfileMenuItem: FC = () => {
	const { marketingSiteBaseUrl } = useMITOLHeaderConfig();
	if (!isMITxOnlineCourse()) return null;
	return (
		<Dropdown.Item href={`${marketingSiteBaseUrl ?? ""}/profile/`}>
			Profile
		</Dropdown.Item>
	);
};

/** Account settings menu item — only shown for MITx Online courses. */
const MITxOnlineAccountMenuItem: FC = () => {
	const { marketingSiteBaseUrl } = useMITOLHeaderConfig();
	if (!isMITxOnlineCourse()) return null;
	return (
		<Dropdown.Item href={`${marketingSiteBaseUrl ?? ""}/account-settings/`}>
			Settings
		</Dropdown.Item>
	);
};

/** Dashboard menu item with context-aware URL (mobile-only; secondary links covers desktop). */
const MITxOnlineDashboardMenuItem: FC = () => {
	const { lmsBaseUrl } = useSiteConfig();
	const { mitLearnBaseUrl, marketingSiteBaseUrl } = useMITOLHeaderConfig();
	const url = isLearnCourse()
		? `${mitLearnBaseUrl ?? "https://learn.mit.edu"}/dashboard`
		: `${marketingSiteBaseUrl ?? lmsBaseUrl}/dashboard/`;
	return <Dropdown.Item href={url}>Dashboard</Dropdown.Item>;
};

/** Sign-out menu item for mitxonline (always LMS logout). */
const MITxOnlineLogoutMenuItem: FC = () => {
	const { logoutUrl } = useSiteConfig();
	return <Dropdown.Item href={logoutUrl}>Sign out</Dropdown.Item>;
};

export function createMITxOnlineHeaderApp(): App {
	const slots: SlotOperation[] = [
		// Keep the desktop-style header layout at all widths (no mobile hamburger).
		{
			slotId: SLOT.desktop,
			id: "mitol.header.mitxonline.desktopLayout",
			relatedId: WIDGET.desktopLayout,
			op: WidgetOperationTypes.REPLACE,
			component: AlwaysDesktopLayout,
		},
		{
			slotId: SLOT.mobile,
			id: "mitol.header.mitxonline.mobileLayout",
			relatedId: WIDGET.mobileLayout,
			op: WidgetOperationTypes.REPLACE,
			component: NoMobileLayout,
		},
		// Replace desktop and mobile logo widgets with context-aware logo.
		{
			slotId: SLOT.desktopLeft,
			id: "mitol.header.mitxonline.desktopLogo",
			relatedId: WIDGET.desktopLogo,
			op: WidgetOperationTypes.REPLACE,
			component: MITxOnlineLogo,
		},
		{
			slotId: SLOT.mobileCenter,
			id: "mitol.header.mitxonline.mobileLogo",
			relatedId: WIDGET.mobileLogo,
			op: WidgetOperationTypes.REPLACE,
			component: MITxOnlineLogo,
		},
		// Add Dashboard button in secondary links (shows next to nav items on desktop).
		{
			slotId: SLOT.secondaryLinks,
			id: "mitol.header.mitxonline.dashboardLink",
			op: WidgetOperationTypes.PREPEND,
			component: MITxOnlineDashboardLink,
		},
		// Remove the default Help link from the header.
		{
			slotId: SLOT.secondaryLinks,
			op: WidgetOperationTypes.REMOVE,
			relatedId: WIDGET.help,
		},
		// Replace the default avatar-button toggle with the custom MIT OL user menu
		// (person icon + display name + chevron), on both desktop and mobile.
		{
			slotId: SLOT.desktopRight,
			id: "mitol.header.mitxonline.desktopAuthenticatedMenu",
			relatedId: WIDGET.desktopAuthenticatedMenu,
			op: WidgetOperationTypes.REPLACE,
			component: MITxOnlineAuthenticatedMenu,
		},
		{
			slotId: SLOT.mobileRight,
			id: "mitol.header.mitxonline.mobileAuthenticatedMenu",
			relatedId: WIDGET.mobileAuthenticatedMenu,
			op: WidgetOperationTypes.REPLACE,
			component: MITxOnlineAuthenticatedMenu,
		},
		// Replace all three default authenticated menu items with mitxonline-specific ones.
		{
			slotId: SLOT.authenticatedMenu,
			op: WidgetOperationTypes.REMOVE,
			relatedId: WIDGET.menuProfile,
		},
		{
			slotId: SLOT.authenticatedMenu,
			op: WidgetOperationTypes.REMOVE,
			relatedId: WIDGET.menuAccount,
		},
		{
			slotId: SLOT.authenticatedMenu,
			op: WidgetOperationTypes.REMOVE,
			relatedId: WIDGET.menuLogout,
		},
		{
			slotId: SLOT.authenticatedMenu,
			id: "mitol.header.mitxonline.menuDashboard",
			op: WidgetOperationTypes.APPEND,
			component: MITxOnlineDashboardMenuItem,
		},
		{
			slotId: SLOT.authenticatedMenu,
			id: "mitol.header.mitxonline.menuProfile",
			op: WidgetOperationTypes.APPEND,
			component: MITxOnlineProfileMenuItem,
		},
		{
			slotId: SLOT.authenticatedMenu,
			id: "mitol.header.mitxonline.menuAccount",
			op: WidgetOperationTypes.APPEND,
			component: MITxOnlineAccountMenuItem,
		},
		{
			slotId: SLOT.authenticatedMenu,
			id: "mitol.header.mitxonline.menuLogout",
			op: WidgetOperationTypes.APPEND,
			component: MITxOnlineLogoutMenuItem,
		},
		// TODO: Hide primary nav links on dashboard apps (gradebook, learner-dashboard).
		// This requires knowing which route roles those apps register. Add a condition with
		// condition: { active: ['<gradebook-role>'] } once frontend-app-gradebook is a module.
		//
		// TODO: Per-app header_learning_course_info override (UAI course title-only display).
		// In frontend-base the course info is inside CourseTabsNavigation; override it via
		// org.openedx.frontend.slot.header.courseNavigationBar.extraContent.v1 once the
		// course bar slot API is confirmed.
	];

	return { appId: "mitol.header.mitxonline", slots };
}

// ---------------------------------------------------------------------------
// MITx / MITx-Staging header — simple LMS-based user menu, no UAI detection
// ---------------------------------------------------------------------------

/** Dashboard menu item pointing to the LMS. */
const MITxDashboardMenuItem: FC = () => {
	const { lmsBaseUrl } = useSiteConfig();
	return (
		<Dropdown.Item href={`${lmsBaseUrl}/dashboard`}>Dashboard</Dropdown.Item>
	);
};

/** Sign-out menu item pointing to LMS logout. */
const MITxLogoutMenuItem: FC = () => {
	const { logoutUrl } = useSiteConfig();
	return <Dropdown.Item href={logoutUrl}>Sign out</Dropdown.Item>;
};

export function createMITxHeaderApp(): App {
	const slots: SlotOperation[] = [
		// Replace default menu items with LMS-based dashboard + logout.
		{
			slotId: SLOT.authenticatedMenu,
			op: WidgetOperationTypes.REMOVE,
			relatedId: WIDGET.menuProfile,
		},
		{
			slotId: SLOT.authenticatedMenu,
			op: WidgetOperationTypes.REMOVE,
			relatedId: WIDGET.menuAccount,
		},
		{
			slotId: SLOT.authenticatedMenu,
			op: WidgetOperationTypes.REMOVE,
			relatedId: WIDGET.menuLogout,
		},
		{
			slotId: SLOT.authenticatedMenu,
			id: "mitol.header.mitx.menuDashboard",
			op: WidgetOperationTypes.APPEND,
			component: MITxDashboardMenuItem,
		},
		{
			slotId: SLOT.authenticatedMenu,
			id: "mitol.header.mitx.menuLogout",
			op: WidgetOperationTypes.APPEND,
			component: MITxLogoutMenuItem,
		},
		// TODO: Hide "looking for a challenge" sidebar (widget_sidebar_slot on learner-dashboard).
		// Requires frontend-app-learner-dashboard to be a module library.
	];

	return { appId: "mitol.header.mitx", slots };
}

// ---------------------------------------------------------------------------
// xPRO header — marketing-site-based user menu, no UAI detection
// ---------------------------------------------------------------------------

/** Dashboard link for xPRO — uses marketing site URL. */
const XProDashboardMenuItem: FC = () => {
	const { marketingSiteBaseUrl } = useMITOLHeaderConfig();
	return (
		<Dropdown.Item href={`${marketingSiteBaseUrl ?? ""}/dashboard`}>
			Dashboard
		</Dropdown.Item>
	);
};

/** Profile link for xPRO. */
const XProProfileMenuItem: FC = () => {
	const { marketingSiteBaseUrl } = useMITOLHeaderConfig();
	return (
		<Dropdown.Item href={`${marketingSiteBaseUrl ?? ""}/profile/`}>
			Profile
		</Dropdown.Item>
	);
};

/** Account settings link for xPRO. */
const XProAccountMenuItem: FC = () => {
	const { marketingSiteBaseUrl } = useMITOLHeaderConfig();
	return (
		<Dropdown.Item href={`${marketingSiteBaseUrl ?? ""}/account-settings/`}>
			Settings
		</Dropdown.Item>
	);
};

/** Sign-out for xPRO — LMS logout. */
const XProLogoutMenuItem: FC = () => {
	const { logoutUrl } = useSiteConfig();
	return <Dropdown.Item href={logoutUrl}>Sign out</Dropdown.Item>;
};

export function createXProHeaderApp(): App {
	const slots: SlotOperation[] = [
		// Replace all default menu items with xPRO marketing-site links.
		{
			slotId: SLOT.authenticatedMenu,
			op: WidgetOperationTypes.REMOVE,
			relatedId: WIDGET.menuProfile,
		},
		{
			slotId: SLOT.authenticatedMenu,
			op: WidgetOperationTypes.REMOVE,
			relatedId: WIDGET.menuAccount,
		},
		{
			slotId: SLOT.authenticatedMenu,
			op: WidgetOperationTypes.REMOVE,
			relatedId: WIDGET.menuLogout,
		},
		{
			slotId: SLOT.authenticatedMenu,
			id: "mitol.header.xpro.menuDashboard",
			op: WidgetOperationTypes.APPEND,
			component: XProDashboardMenuItem,
		},
		{
			slotId: SLOT.authenticatedMenu,
			id: "mitol.header.xpro.menuProfile",
			op: WidgetOperationTypes.APPEND,
			component: XProProfileMenuItem,
		},
		{
			slotId: SLOT.authenticatedMenu,
			id: "mitol.header.xpro.menuAccount",
			op: WidgetOperationTypes.APPEND,
			component: XProAccountMenuItem,
		},
		{
			slotId: SLOT.authenticatedMenu,
			id: "mitol.header.xpro.menuLogout",
			op: WidgetOperationTypes.APPEND,
			component: XProLogoutMenuItem,
		},
		// TODO: xPRO certificate status override (CustomCertificateStatus) for the
		// learning app. Depends on frontend-app-learning being a module library.
	];

	return { appId: "mitol.header.xpro", slots };
}
