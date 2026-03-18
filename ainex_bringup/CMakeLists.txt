cmake_minimum_required(VERSION 3.0.2)
project(ainex_bringup)

find_package(catkin REQUIRED)
catkin_package()

catkin_install_python(PROGRAMS
  scripts/robot_mouth_talk_node.py
  scripts/robot_mouth_talk.py
  scripts/oled_display.py
  scripts/sound_and_mouth_talk.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/launch
  FILES_MATCHING PATTERN "*.launch"
)
