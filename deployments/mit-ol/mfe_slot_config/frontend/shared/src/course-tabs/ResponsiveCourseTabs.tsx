/**
 * TODO: This component cannot be fully migrated until frontend-app-learning is ported
 * to frontend-base as a module library.
 *
 * ResponsiveCourseTabs requires:
 *   - useSelector from react-redux reading state.courseHome.courseId / state.courseware.courseId
 *   - useModel('courseHomeMeta', courseId) from frontend-app-learning's model store
 *     to get the tabs array
 *
 * Both dependencies are internal to frontend-app-learning. When it becomes a module
 * library the slot operation for org.openedx.frontend.learning.course_tab_links.v1
 * should live inside the learning app's own slot definitions.
 *
 * The canonical source is:
 *   ol-infrastructure/src/bridge/settings/openedx/mfe/slot_config/ResponsiveCourseTabs.jsx
 *
 * The component itself is a pure UI component — a responsive tab bar that overflows
 * extra tabs into a "More..." dropdown. The migration is straightforward once the
 * model store access is available:
 *   - Replace useSelector + useModel with whatever hook the learning module exports
 *     for accessing course tabs.
 *   - Replace useIntl/FormattedMessage import path from @edx/frontend-platform/i18n
 *     to @openedx/frontend-base.
 */

export {};
