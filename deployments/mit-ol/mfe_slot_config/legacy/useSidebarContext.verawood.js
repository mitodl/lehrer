import { useContext } from 'react';

import SidebarContext from './src/courseware/course/sidebar/SidebarContext';

const useSidebarContext = () => useContext(SidebarContext);

export default useSidebarContext;
