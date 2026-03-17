cmake_minimum_required(VERSION 3.0.2)
project(test)

find_package(catkin REQUIRED)
catkin_package()

catkin_install_python(PROGRAMS
  scripts/audio_oscillogram_capture_node.py
  scripts/oscillogram_plot_node.py
  scripts/mouth_oscillogram_sync_node.py
  scripts/mouth_level_test_publisher_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/launch
  FILES_MATCHING PATTERN "*.launch"
)
