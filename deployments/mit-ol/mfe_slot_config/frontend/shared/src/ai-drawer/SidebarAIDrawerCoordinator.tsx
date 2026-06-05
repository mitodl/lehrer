/**
 * TODO: This component cannot be fully migrated until frontend-app-learning is ported
 * to frontend-base as a module library.
 *
 * The SidebarAIDrawerCoordinator requires:
 *   - SidebarContext and NewSidebarContext (internal to frontend-app-learning)
 *   - Sidebar and NewSidebar components (internal to frontend-app-learning)
 *   - useModel('courseHomeMeta', courseId) from @src/generic/model-store (internal)
 *
 * When frontend-app-learning is migrated, this component's slot operation should be
 * registered inside the learning app's own slot definitions rather than here, since it
 * depends on learning-internal React contexts that are only present when the learning
 * app is mounted.
 *
 * The AIDrawerManagerSidebar component (same directory) is self-contained and can be
 * imported independently for any deployment that embeds it directly.
 */

export { default as AIDrawerManagerSidebar } from "./AIDrawerManagerSidebar";
