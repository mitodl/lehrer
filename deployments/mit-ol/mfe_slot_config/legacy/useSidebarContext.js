// frontend-app-learning master made SidebarContext module-private (openedx/frontend-app-learning#2116).
// The right sidebar slot renders inside SidebarProvider, so useSidebar() is always in scope.
export { useSidebar as default } from './src/courseware/course/sidebar/SidebarContext';
