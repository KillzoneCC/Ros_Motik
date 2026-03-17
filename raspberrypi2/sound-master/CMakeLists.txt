cmake_minimum_required(VERSION 3.0.2)
project(sound)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  message_generation
)

add_service_files(
  FILES
  CheckAudioCard.srv
  SoundDuration.srv
  PlaySoundWithOscillogram.srv
)

generate_messages(
  DEPENDENCIES
  std_msgs
)

catkin_package(
  CATKIN_DEPENDS rospy std_msgs message_runtime
)

include_directories(${catkin_INCLUDE_DIRS})

catkin_install_python(PROGRAMS
  scripts/sound_node.py
  scripts/audio_card_check_node.py
  scripts/audio_level_test_sine.py
  scripts/sound_play_osc_node.py
  scripts/audio_card_stream_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/launch
)

