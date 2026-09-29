import { useParams } from 'react-router-dom';

import { useCourseHomeMeta } from './src/course-home/data/apiHooks';

// frontend-app-learning master reads the course-home metadata from React Query and no longer
// mirrors it into the model store (openedx/frontend-app-learning#2110). This is a disabled
// observer: every page that renders the tab bar already fetches the query.
const useCourseTabs = () => {
  const { courseId } = useParams();
  return useCourseHomeMeta(courseId, { enabled: false }).data?.tabs;
};

export default useCourseTabs;
