/**
 * MIT OL course tab navigation for the OEP-65 Site Projects.
 *
 * Replaces frontend-base's `CourseTabsNavigation`, which renders a Bootstrap
 * `<Navbar expand="sm">` carrying `class="course-tabs-navigation"` but **no `id`** — so
 * every rule in the `#courseTabsNavigation` block of `styles/mitxonline.scss` is dead
 * code against it. That block documents the link colours and overflow behaviour the
 * legacy learning MFE has and the upstream widget does not.
 *
 * The wrapper chain rendered below is the legacy learning MFE's, captured from a
 * running instance, so that stylesheet applies as written rather than needing a second
 * set of rules aimed at the Bootstrap navbar. The overflow behaviour is ported from
 * `legacy/ResponsiveCourseTabs.jsx`, which remains the canonical implementation.
 *
 * Tabs come from the same react-query cache entry frontend-base's own course bar fills:
 * the package exports only `.`, so the query is re-declared below under the identical
 * key and fetcher, and both share one entry instead of issuing two requests.
 */

import { useLayoutEffect, useRef, useState } from "react";
import type { FC } from "react";
import { matchPath, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Dropdown } from "@openedx/paragon";
import {
	camelCaseObject,
	getAuthenticatedHttpClient,
	getSiteConfig,
	useIntl,
} from "@openedx/frontend-base";

interface CourseTab {
	tabId: string;
	title: string;
	url: string;
}

const moreMessage = {
	id: "learn.course.tabs.navigation.overflow.menu",
	description: "The title of the overflow menu for course tabs",
	defaultMessage: "More...",
};

const navLabelMessage = {
	id: "mitol.course.tabs.navigation.label",
	description: "Accessible label for the course tab navigation bar",
	defaultMessage: "Course Material",
};

// Must stay identical to frontend-base's
// shell/header/course-bar/data/service.ts so the two share a cache entry.
const courseHomeCourseMetadataQueryKey = (courseId: string) => [
	"org.openedx.frontend.app.header.courseMeta",
	courseId,
];

async function getCourseHomeCourseMetadata(
	courseId: string,
): Promise<{ tabs: CourseTab[] }> {
	const { data } = await getAuthenticatedHttpClient().get(
		`${getSiteConfig().lmsBaseUrl}/api/course_home/course_metadata/${courseId}`,
	);
	const { tabs = [] } = camelCaseObject(data) as { tabs?: CourseTab[] };
	return {
		tabs: tabs.map((tab) => ({
			...tab,
			// Upstream renames this one tab id; keep the mapping so a cache entry
			// written by either component is interchangeable.
			tabId: tab.tabId === "courseware" ? "outline" : tab.tabId,
		})),
	};
}

/**
 * The tab whose URL pathname is the longest prefix of `pathname`, or null.
 * Ported from frontend-base's `findActiveTab` so the highlight matches upstream.
 */
function findActiveTabId(tabs: CourseTab[], pathname: string): string | null {
	let bestId: string | null = null;
	let bestLen = -1;
	for (const tab of tabs) {
		const tabPathname = new URL(tab.url).pathname;
		if (
			tabPathname.length > bestLen &&
			matchPath({ path: `${tabPathname}/*`, end: false }, pathname)
		) {
			bestId = tab.tabId;
			bestLen = tabPathname.length;
		}
	}
	return bestId;
}

/** Tab links plus a "More..." dropdown holding whatever did not fit. */
function ResponsiveCourseTabs({
	tabs,
	activeTabId,
}: { tabs: CourseTab[]; activeTabId: string | null }) {
	const intl = useIntl();
	const moreLabel = intl.formatMessage(moreMessage);
	const mirrorsRef = useRef<HTMLDivElement>(null);
	// Starts at "everything visible" so the measuring pass below has real widths.
	const [splitIndex, setSplitIndex] = useState(tabs.length);

	useLayoutEffect(() => {
		const mirrors = mirrorsRef.current;
		const nav = mirrors?.closest("nav");
		if (!mirrors || !nav) {
			return undefined;
		}

		// Mirrors render in order, "More..." last, so widths.pop() is its width. These
		// are only needed to derive the split, so they stay local to the effect.
		const widths = Array.from(
			mirrors.querySelectorAll<HTMLElement>("[data-measure]"),
		).map((el) => Math.ceil(el.getBoundingClientRect().width));
		const moreWidth = widths.pop() ?? 0;

		const split = () => {
			const availableWidth = Math.floor(nav.getBoundingClientRect().width);
			// Everything fits — no "More..." needed, so it costs no width.
			if (widths.reduce((sum, w) => sum + w, 0) <= availableWidth) {
				setSplitIndex(tabs.length);
				return;
			}
			let usedWidth = moreWidth;
			let count = 0;
			for (const width of widths) {
				if (usedWidth + width > availableWidth) {
					break;
				}
				usedWidth += width;
				count++;
			}
			// Always leave at least one real tab visible.
			setSplitIndex(Math.max(count, 1));
		};

		split();
		const observer = new ResizeObserver(() => window.requestAnimationFrame(split));
		observer.observe(nav);
		return () => observer.disconnect();
	}, [tabs]);

	const visibleTabs = tabs.slice(0, splitIndex);
	const overflowTabs = tabs.slice(splitIndex);

	// A fragment, not a wrapper: these stay direct flex children of the <nav> so the
	// stylesheet's `.nav > .nav-item` rules match.
	return (
		<>
			{visibleTabs.map(({ url, title, tabId }) => (
				<a
					key={tabId}
					href={url}
					className={`nav-item flex-shrink-0 nav-link${tabId === activeTabId ? " active" : ""}`}
				>
					{title}
				</a>
			))}

			{overflowTabs.length > 0 && (
				<div className="pgn__tab_more nav-item flex-shrink-0 nav-link responsive-tabs-overflow">
					<Dropdown className="h-100">
						<Dropdown.Toggle
							variant="link"
							className="nav-link h-100"
							id="responsive-tabs-more-menu"
						>
							{moreLabel}
						</Dropdown.Toggle>
						<Dropdown.Menu className="responsive-tabs-dropdown-menu">
							{overflowTabs.map(({ url, title, tabId }) => (
								<Dropdown.Item
									key={tabId}
									href={url}
									className={tabId === activeTabId ? "active" : ""}
								>
									{title}
								</Dropdown.Item>
							))}
						</Dropdown.Menu>
					</Dropdown>
				</div>
			)}

			{/* Hidden mirrors, same classes as the real tabs so widths match. Fixed and
			    off-screen so they add nothing to layout or scroll width. */}
			<div
				ref={mirrorsRef}
				aria-hidden="true"
				style={{
					position: "fixed",
					visibility: "hidden",
					pointerEvents: "none",
					display: "flex",
					flexWrap: "nowrap",
					top: -10000,
					left: -10000,
					zIndex: -1,
				}}
			>
				{tabs.map(({ title, tabId }) => (
					<span
						key={`measure-${tabId}`}
						data-measure
						className="nav-item flex-shrink-0 nav-link"
						style={{ whiteSpace: "nowrap" }}
					>
						{title}
					</span>
				))}
				<span
					data-measure
					className="nav-item flex-shrink-0 nav-link"
					style={{ whiteSpace: "nowrap" }}
				>
					{moreLabel}
				</span>
			</div>
		</>
	);
}

/**
 * Drop-in replacement for `org.openedx.frontend.widget.header.courseNavigationBar.v1`.
 * Renders the legacy learning MFE's wrapper chain so `styles/mitxonline.scss` applies.
 */
export const MITOLCourseNavigationBar: FC = () => {
	const { courseId = "" } = useParams();
	const location = useLocation();
	const intl = useIntl();

	const { data } = useQuery({
		queryKey: courseHomeCourseMetadataQueryKey(courseId),
		queryFn: () => getCourseHomeCourseMetadata(courseId),
		retry: 2,
		enabled: !!courseId,
	});

	const tabs = data?.tabs ?? [];
	// Also covers loading and a missing courseId (which disables the query). Upstream
	// renders a <Skeleton> here; this bar is a thin strip, and a placeholder that then
	// changes height shifts the page under the user.
	if (!tabs.length) {
		return null;
	}

	const activeTabId = findActiveTabId(tabs, location.pathname);

	return (
		<div id="courseTabsNavigation" className="course-tabs-navigation mb-3">
			<div className="container-xl">
				<div className="nav-bar">
					<div className="nav-menu">
						<nav
							aria-label={intl.formatMessage(navLabelMessage)}
							className="nav flex-nowrap nav-underline-tabs"
						>
							<ResponsiveCourseTabs tabs={tabs} activeTabId={activeTabId} />
						</nav>
					</div>
				</div>
			</div>
		</div>
	);
};
