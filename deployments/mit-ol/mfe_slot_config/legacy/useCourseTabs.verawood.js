import { useParams } from 'react-router-dom';

import { useModel } from './src/generic/model-store';

// Course-home tabs (outline, dates, progress, ...) no longer populate
// state.courseHome.courseId now that they're on React Query (frontend-app-learning
// #1997 and siblings) — read the route param directly instead, like those tabs do.
const useCourseTabs = () => {
  const { courseId } = useParams();
  return useModel('courseHomeMeta', courseId)?.tabs;
};

export default useCourseTabs;
