import { useRef } from 'react';
import { useModel } from './src/generic/model-store';

// Returns a stable getter for feedback enrichment fields (course name, unit title, URL).
// Reads a ref refreshed each render so values stay current without re-initializing the bundle.
export default function useFeedbackEnrichment(courseId, unitId) {
  const course = useModel('courseHomeMeta', courseId);
  const unit = useModel('units', unitId);

  const ref = useRef({});
  ref.current = {
    courseName: course?.title ?? '',
    unitTitle: unit?.title ?? '',
    url: window.location.href,
  };

  const getterRef = useRef(() => ref.current);
  return getterRef.current;
}
