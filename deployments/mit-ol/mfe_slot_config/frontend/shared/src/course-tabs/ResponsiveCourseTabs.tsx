/**
 * TODO: This component cannot be fully migrated until frontend-app-learning is ported
 * to frontend-base as a module library.
 *
 * ResponsiveCourseTabs requires:
 *   - useCourseHomeMeta(courseId, { enabled: false }).data?.tabs from
 *     frontend-app-learning's course-home/data/apiHooks to get the tabs array (the
 *     model store no longer carries courseHomeMeta since openedx/frontend-app-learning#2110)
 *   - tabs keyed by their API `tabId` (#2099), with the Course tab (`courseware`) also
 *     active on the outline page (`outline`), as course-tabs/utils isActiveTab does
 *
 * Both dependencies are internal to frontend-app-learning. When it becomes a module
 * library the slot operation for org.openedx.frontend.learning.course_tab_links.v1
 * should live inside the learning app's own slot definitions.
 *
 * The canonical source is:
 *   deployments/mit-ol/mfe_slot_config/legacy/ResponsiveCourseTabs.jsx
 *
 * The component itself is a pure UI component — a responsive tab bar that overflows
 * extra tabs into a "More..." dropdown. The migration is straightforward once the
 * model store access is available:
 *   - Replace the per-release useCourseTabs hook with whatever the learning module
 *     exports for accessing course tabs.
 *   - Replace useIntl/FormattedMessage import path from @edx/frontend-platform/i18n
 *     to @openedx/frontend-base.
 */

export {};
