import {
  enrollmentActionsSlotId,
  enrollmentActionsWidgetId,
} from '@openedx/frontend-app-instructor-dashboard';
import { WidgetOperationTypes } from '@openedx/frontend-base';
import type { App } from '@openedx/frontend-base';

import {
  createMITOLInstructorDashboardApp,
  PlaceholderSlot,
  ROUTES_SLOT_ID,
} from '@shared/instructor-dashboard';

import CourseSyncPage from './CourseSyncPage';
import EnrollmentActions from './EnrollmentActions';

// ---------------------------------------------------------------------------
// MITx Online instructor dashboard app
//
// Extends the shared MIT OL instructor dashboard app with mitxonline-only
// customizations:
//
//   - Enrollment actions: REPLACEs the MFE's default (ungated) Enroll Learners /
//     Add Beta Testers buttons with permission-gated ones — Enroll Learners →
//     platform staff (permissions.admin), Add Beta Testers → course Admin
//     (permissions.instructor) — matching the legacy MITx Online dashboard.
//   - Course Sync: adds the problem reset/rescore page (route only). Like the
//     shared Canvas / Rapid Responses pages, the nav tab comes from the LMS via
//     the InstructorDashboardTabsRequested filter (ol_openedx_course_sync), so it
//     only surfaces for staff on courses that are an active sync source.
//
// Both are scoped here (not in @shared) so xpro / mitx keep the shared factory's
// defaults — ol_openedx_course_sync is only installed on mitxonline.
// ---------------------------------------------------------------------------

export function createMITxOnlineInstructorDashboardApp(): App {
  const app = createMITOLInstructorDashboardApp();
  return {
    ...app,
    slots: [
      ...(app.slots ?? []),
      {
        slotId: enrollmentActionsSlotId,
        id: 'org.openedx.frontend.widget.instructorDashboard.enrollmentActions.mitxonline',
        op: WidgetOperationTypes.REPLACE,
        relatedId: enrollmentActionsWidgetId,
        component: EnrollmentActions,
      },
      {
        slotId: ROUTES_SLOT_ID,
        id: 'org.openedx.frontend.widget.instructorDashboard.route.course_sync',
        op: WidgetOperationTypes.APPEND,
        element: <PlaceholderSlot tabId="course_sync" content={<CourseSyncPage />} />,
      },
    ],
  };
}
