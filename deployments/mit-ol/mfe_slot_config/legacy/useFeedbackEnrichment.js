import { useRef } from 'react';
import { useParams } from 'react-router-dom';

import { useCourseHomeMeta } from './src/course-home/data/apiHooks';
import { useUnit } from './src/courseware/data/apiHooks';

// Returns a stable getter for feedback enrichment fields (course name, unit title, URL).
// Reads a ref refreshed each render so values stay current without re-initializing the bundle.
//
// frontend-app-learning master no longer mirrors the course-home metadata or the units into
// the model store (openedx/frontend-app-learning#2110, #2128). Both reads are disabled
// observers of queries the courseware page already fetches; the unit comes from the sequence
// named in the route, which is the sequence query CoursewareContainer fetches.
export default function useFeedbackEnrichment(courseId, unitId) {
  const { sequenceId } = useParams();
  const course = useCourseHomeMeta(courseId, { enabled: false }).data;
  const unit = useUnit(sequenceId, unitId).data;

  const valuesRef = useRef({});
  valuesRef.current = {
    courseName: course?.title ?? '',
    unitTitle: unit?.title ?? '',
    url: window.location.href,
  };

  const getterRef = useRef(() => valuesRef.current);
  return getterRef.current;
}
