import { useEffect, useState, type FC } from "react";
import {
	camelCaseObject,
	getAuthenticatedHttpClient,
	getSiteConfig,
	useSiteConfig,
	useAuthenticatedUser,
	WidgetOperationTypes,
	Slot,
} from "@openedx/frontend-base";
import type { App, SlotOperation } from "@openedx/frontend-base";
import { Dropdown, Hyperlink, Image } from "@openedx/paragon";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
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
	primaryLinks: "org.openedx.frontend.slot.header.primaryLinks.v1",
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
// Widget IDs owned by module libraries (not frontend-base) that we override.
// ---------------------------------------------------------------------------

/**
 * The course info lockup (org + number over the course title) that
 * @openedx/frontend-app-instructor-dashboard appends to the header's
 * primaryLinks slot. `slotShowcase.headerLink` is the id the package actually
 * registers — an upstream copy-paste artifact from frontend-base's slot
 * showcase, not a name we chose — and it is the only handle we have on that
 * widget. Keep it in step with `slots.ts` in that package when bumping it.
 */
const INSTRUCTOR_DASHBOARD_COURSE_INFO_WIDGET =
	"org.openedx.frontend.widget.slotShowcase.headerLink";

/** App ID the instructor dashboard registers, used for its react-query cache keys. */
const INSTRUCTOR_DASHBOARD_APP_ID =
	"org.openedx.frontend.app.instructorDashboard";

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
// Narrow-viewport detection
//
// 991px is the width at which the mitxonline SCSS hides the standalone
// Dashboard button (`@media (max-width: 991px)`), so anything keyed off this
// hook flips over exactly when that button disappears. It is the same
// breakpoint the legacy header's isMobile() used (MOBILE_BREAKPOINT = 991).
// ---------------------------------------------------------------------------

const MOBILE_MEDIA_QUERY = "(max-width: 991px)";

function useIsNarrowViewport(): boolean {
	const [isNarrow, setIsNarrow] = useState(
		() =>
			typeof window !== "undefined" &&
			window.matchMedia(MOBILE_MEDIA_QUERY).matches,
	);
	useEffect(() => {
		if (typeof window === "undefined") return undefined;
		const mediaQueryList = window.matchMedia(MOBILE_MEDIA_QUERY);
		// Re-sync on mount: the initial state was computed before this effect ran,
		// and the width can change between the two (hydration, orientation change).
		setIsNarrow(mediaQueryList.matches);
		const handleChange = (event: MediaQueryListEvent) =>
			setIsNarrow(event.matches);
		mediaQueryList.addEventListener("change", handleChange);
		return () => mediaQueryList.removeEventListener("change", handleChange);
	}, []);
	return isNarrow;
}

// ---------------------------------------------------------------------------
// Shared user menu toggle component
// Used by mitxonline to replace the default AvatarButton toggle with an SVG
// person icon + display name. mitx and xpro use the default Paragon toggle.
// ---------------------------------------------------------------------------

const UserMenuToggle: FC = () => {
	const authenticatedUser = useAuthenticatedUser();
	if (!authenticatedUser) return null;
	const displayName = authenticatedUser.name || authenticatedUser.username;
	return (
		<Dropdown.Toggle
			// Render a native <button> (not a div) so the toggle is focusable and
			// keyboard-activatable. aria-label gives it an accessible name in the
			// icon-only state (the username is hidden below 992px — see the
			// mitxonline.scss media query).
			as="button"
			type="button"
			aria-label={displayName}
			id="user-nav-dropdown-custom"
			className="d-flex align-items-center gap-2 cursor-pointer bg-transparent"
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
			<span className="user-menu-name">{displayName}</span>
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
	// Match the legacy header container exactly: a plain `.container-xl py-2` flex
	// row. Paragon's <Container> can't emit `.container-xl` (its `fluid` prop is
	// boolean-only, and `size="xl"` produces the wider `.container-mw-xl`), so we
	// use a plain div — the same element the legacy header uses. `.container-xl`
	// also lines up with the instructor-dashboard body (`#main-content.container-xl`).
	<div className="container-xl py-2 align-items-center justify-content-between d-flex">
		<div className="d-flex flex-grow-1 align-items-center">
			<Slot id={SLOT.desktopLeft} />
		</div>
		<div className="d-flex align-items-center">
			<Slot id={SLOT.desktopRight} />
		</div>
	</div>
);

const NoMobileLayout: FC = () => null;

// ---------------------------------------------------------------------------
// Instructor dashboard course info
// ---------------------------------------------------------------------------

interface InstructorDashboardCourseInfo {
	org?: string;
	courseNumber?: string;
	displayName?: string;
}

/**
 * Course org / number / title for the header, from the LMS instructor API.
 *
 * The instructor dashboard's own `useCourseInfo` is internal to the package
 * (only `.` is exported), so this re-declares the query — but under the same
 * cache key that hook uses, so the two share one cache entry and the header
 * does not issue a second request alongside the Course Info page.
 */
function useInstructorDashboardCourseInfo(courseId: string) {
	return useQuery<InstructorDashboardCourseInfo>({
		queryKey: [INSTRUCTOR_DASHBOARD_APP_ID, "courseInfo", courseId],
		queryFn: async () => {
			const { data } = await getAuthenticatedHttpClient().get(
				`${getSiteConfig().lmsBaseUrl}/api/instructor/v2/courses/${courseId}`,
			);
			return camelCaseObject(data) as InstructorDashboardCourseInfo;
		},
		enabled: !!courseId,
		refetchOnWindowFocus: false,
		refetchOnMount: false,
		retry: false,
	});
}

// ---------------------------------------------------------------------------
// MITx Online header — full UAI/Learn course detection, custom logo, user menu
// ---------------------------------------------------------------------------

/**
 * Course info lockup for the instructor dashboard header, replacing the one
 * @openedx/frontend-app-instructor-dashboard registers.
 *
 * UAI / MIT Learn courses show the course title on its own; every other course
 * keeps the two-line org + number over title lockup. This mirrors the learning
 * header (addLearningCourseInfoSlotOverride in
 * legacy/mitxonline/common-mfe-config.env.jsx), which hides the default widget
 * and inserts a title-only one for those courses.
 *
 * Why they hide it is not recorded: that override and the slot table in
 * legacy/Readme.md both state the behaviour and not the reason, and it arrived
 * in a bulk slot-config import (7eb5519). Note it is not missing data -- the
 * values exist (course-v1:UAI_SOURCE+UAI111+UAI_11 reports org UAI_SOURCE,
 * number UAI111) -- so treat it as a product decision and check with the team
 * before extending the rule to other courses.
 *
 * Everything except the org/number line matches the upstream widget, so the
 * non-UAI header is unchanged.
 */
const MITxOnlineCourseInfo: FC = () => {
	const { courseId = "" } = useParams();
	const { data } = useInstructorDashboardCourseInfo(courseId);
	if (!data) return null;
	const { org = "", courseNumber = "", displayName = "" } = data;
	const showCourseNumber = isMITxOnlineCourse();
	return (
		// Same element as legacy's LearningHeaderCourseInfo: a plain `min-width: 0`
		// div. The lockup wrapper around it (margin, font-size, line-height) is
		// MITxOnlinePrimaryLinks, mirroring how LearningHeader wraps the slot.
		//
		// The 7px top padding in the title-only case is legacy's too: its UAI
		// override adds it so the single line lands where the two-line lockup's
		// title does, rather than centred in the row. Without it the UAI title
		// sits 3px above the learning header's.
		<div style={{ minWidth: 0, paddingTop: showCourseNumber ? undefined : "7px" }}>
			{showCourseNumber && (
				<span className="d-block small m-0">
					{org} {courseNumber}
				</span>
			)}
			{/* No `font-weight-bold`, unlike the upstream widget and legacy's markup.
			    Legacy carries the class but renders at 400 anyway: mitxonline-styles
			    neutralises it with `.learning-header .font-weight-bold { font-weight:
			    400 !important }`, which outranks Bootstrap's utility on specificity.
			    frontend-base puts Paragon in a cascade layer, so that override no
			    longer wins and the title came out bold — 700 against the learning
			    header's 400. Omitting the class reaches the same computed weight
			    without depending on a cascade fight we cannot win. */}
			<span className="d-block m-0 course-title">{displayName}</span>
		</div>
	);
};

/**
 * Course-info lockup wrapper, replacing frontend-base's PrimaryNavLinks.
 *
 * PrimaryNavLinks wraps the primaryLinks slot in `<Nav className="... ml-3">`,
 * putting a 16px gap between the logo and the course title. The learning header
 * wraps the same content in `<div class="flex-grow-1 course-title-lockup d-flex"
 * style="line-height: 1">` and mitxonline-styles gives that a 10px margin and a
 * 14px font size, so the two headers sat 6px apart. Rendering the legacy element
 * here picks up those existing rules instead of trying to cancel `ml-3` from the
 * site stylesheet — `ml-3` is an `!important` utility that a layered site rule
 * cannot outrank.
 *
 * Dropping the `Nav` wrapper also matches legacy, whose learning header has no
 * nav element around the course info. A future primaryLinks widget that needs
 * `Nav`/`Nav.Link` styling would have to bring its own wrapper.
 */
const MITxOnlinePrimaryLinks: FC = () => (
	<div
		className="flex-grow-1 course-title-lockup d-flex"
		style={{ lineHeight: 1 }}
	>
		<Slot id={SLOT.primaryLinks} />
	</div>
);

/** Logo that links to the dashboard appropriate for the current course context. */
const MITxOnlineLogo: FC = () => {
	const { lmsBaseUrl } = useSiteConfig();
	const { mitLearnBaseUrl, marketingSiteBaseUrl } = useMITOLHeaderConfig();
	const destinationUrl = isLearnCourse()
		? `${mitLearnBaseUrl ?? "https://learn.mit.edu"}/dashboard`
		: `${marketingSiteBaseUrl ?? lmsBaseUrl}/dashboard/`;
	const { headerLogoImageUrl } = useSiteConfig();
	return (
		// `logo` class mirrors the legacy learning-header logo anchor so the
		// mitxonline.scss `.logo img { height: 24px }` rule applies (matching the
		// legacy 24px logo instead of the frontend-base default 2rem/32px).
		<Hyperlink destination={destinationUrl} className="logo p-0">
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

/**
 * Dashboard menu item with context-aware URL.
 *
 * Narrow viewports only. Above 991px the standalone Dashboard button in the
 * secondary links slot is what the user clicks, and duplicating it inside the
 * user menu is what this fixes; at or below 991px the SCSS hides that button
 * (`.dashboard-btn { display: none }`), so the menu becomes the only route to
 * the dashboard. Same rule as the legacy learning MFE, which passed
 * `includeDashboard: isMobile()` when building the user menu.
 */
const MITxOnlineDashboardMenuItem: FC = () => {
	const { lmsBaseUrl } = useSiteConfig();
	const { mitLearnBaseUrl, marketingSiteBaseUrl } = useMITOLHeaderConfig();
	const isNarrowViewport = useIsNarrowViewport();
	const url = isLearnCourse()
		? `${mitLearnBaseUrl ?? "https://learn.mit.edu"}/dashboard`
		: `${marketingSiteBaseUrl ?? lmsBaseUrl}/dashboard/`;
	if (!isNarrowViewport) return null;
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
		// Drop the org + course number from the course info lockup on UAI / MIT
		// Learn courses, matching the learning header. The widget being replaced
		// belongs to @openedx/frontend-app-instructor-dashboard, which appends it
		// to the header's primaryLinks slot; REPLACE is a no-op on sites/pages
		// where that widget is absent.
		{
			slotId: SLOT.primaryLinks,
			id: "mitol.header.mitxonline.courseInfo",
			relatedId: INSTRUCTOR_DASHBOARD_COURSE_INFO_WIDGET,
			op: WidgetOperationTypes.REPLACE,
			component: MITxOnlineCourseInfo,
		},
		// Wrap the primaryLinks slot in the legacy learning-header lockup element
		// instead of frontend-base's `Nav.ml-3`, so the logo-to-title gap and the
		// lockup font size match the learning MFE.
		{
			slotId: SLOT.desktopLeft,
			id: "mitol.header.mitxonline.primaryLinks",
			relatedId: WIDGET.desktopPrimaryLinks,
			op: WidgetOperationTypes.REPLACE,
			component: MITxOnlinePrimaryLinks,
		},
		// TODO: Hide primary nav links on dashboard apps (gradebook, learner-dashboard).
		// This requires knowing which route roles those apps register. Add a condition with
		// condition: { active: ['<gradebook-role>'] } once frontend-app-gradebook is a module.
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
		// Keep the desktop-style header layout at all widths (no mobile hamburger),
		// matching the legacy MITx header. Narrow-width trimming is in mitx.scss.
		{
			slotId: SLOT.desktop,
			id: "mitol.header.mitx.desktopLayout",
			relatedId: WIDGET.desktopLayout,
			op: WidgetOperationTypes.REPLACE,
			component: AlwaysDesktopLayout,
		},
		{
			slotId: SLOT.mobile,
			id: "mitol.header.mitx.mobileLayout",
			relatedId: WIDGET.mobileLayout,
			op: WidgetOperationTypes.REPLACE,
			component: NoMobileLayout,
		},
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
		// Keep the desktop-style header layout at all widths (no mobile hamburger),
		// matching the legacy xPRO header. Narrow-width trimming is in mitx.scss.
		{
			slotId: SLOT.desktop,
			id: "mitol.header.xpro.desktopLayout",
			relatedId: WIDGET.desktopLayout,
			op: WidgetOperationTypes.REPLACE,
			component: AlwaysDesktopLayout,
		},
		{
			slotId: SLOT.mobile,
			id: "mitol.header.xpro.mobileLayout",
			relatedId: WIDGET.mobileLayout,
			op: WidgetOperationTypes.REPLACE,
			component: NoMobileLayout,
		},
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
