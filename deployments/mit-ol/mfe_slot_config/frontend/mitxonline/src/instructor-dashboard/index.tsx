import {
  enrollmentActionsSlotId,
  enrollmentActionsWidgetId,
} from '@openedx/frontend-app-instructor-dashboard';
import { WidgetOperationTypes } from '@openedx/frontend-base';
import type { App } from '@openedx/frontend-base';

import { createMITOLInstructorDashboardApp } from '@shared/instructor-dashboard';

import EnrollmentActions from './EnrollmentActions';

// ---------------------------------------------------------------------------
// MITx Online instructor dashboard app
//
// Extends the shared MIT OL instructor dashboard app with a mitxonline-only
// override of the enrollment actions slot: it REPLACEs the MFE's default
// (ungated) Enroll Learners / Add Beta Testers buttons with permission-gated
// ones — Enroll Learners → platform staff (permissions.admin), Add Beta Testers
// → course Admin (permissions.instructor) — matching the legacy MITx Online
// dashboard. Scoped here (not in @shared) so xpro / mitx keep the shared
// factory's ungated default.
// ---------------------------------------------------------------------------

export function createMitxOnlineInstructorDashboardApp(): App {
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
    ],
  };
}
